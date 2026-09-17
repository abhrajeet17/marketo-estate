"""
Panorama: access, list, get by id, can_edit_plots, can_delete_panorama.
Used by controllers and other services.
"""
from app.core.database import get_supabase
from app.core.auth import get_profile

_PANORAMA_FIELDS_BASE = 'id, user_id, name, filename, original_filename, width, height, is_360, created_at, updated_at'
_PANORAMA_FIELDS_WITH_WORKSPACE = _PANORAMA_FIELDS_BASE + ', workspace_id'
_MOBILE_PANORAMA_FIELDS_BASE = 'id, user_id, org_id, workspace_id, panorama_parent_id, name, filename, original_filename, width, height, is_360, use_animated_icons, start_view, created_at, updated_at'


def _access_rank(access_type):
    at = str(access_type or 'viewer').lower()
    if at == 'owner':
        return 4
    if at == 'client':
        return 3
    if at == 'broker':
        return 2
    return 1


def _normalize_access_type(access_type):
    at = str(access_type or 'viewer').lower().strip()
    return at if at in ('owner', 'client', 'broker', 'viewer') else 'viewer'


def _select_panorama_rows(sb, selector, values):
    if not values:
        return []

    def _run(fields):
        return sb.table('panoramas').select(fields).in_(selector, values).execute()

    try:
        r = _run(_PANORAMA_FIELDS_WITH_WORKSPACE)
    except Exception as e:
        if 'workspace_id' in str(e).lower():
            r = _run(_PANORAMA_FIELDS_BASE)
        else:
            raise
    return r.data or []


def _count_plots(sb, panorama_id):
    try:
        r = sb.table('plots').select('id', count='exact').eq('panorama_id', panorama_id).execute()
        return r.count or 0
    except Exception:
        return 0


def _plot_counts_for_panoramas(sb, panorama_ids):
    ids = []
    seen = set()
    for pid in (panorama_ids or []):
        if pid is None or pid in seen:
            continue
        seen.add(pid)
        ids.append(pid)
    if not ids:
        return {}
    counts = {pid: 0 for pid in ids}
    chunk_size = 150
    try:
        for i in range(0, len(ids), chunk_size):
            chunk = ids[i:i + chunk_size]
            r = sb.table('plots').select('panorama_id').in_('panorama_id', chunk).limit(50000).execute()
            for row in (r.data or []):
                pid = row.get('panorama_id')
                key = int(pid) if pid is not None and pid not in counts else pid
                if key in counts:
                    counts[key] = int(counts.get(key, 0)) + 1
    except Exception:
        for pid in ids:
            counts[pid] = _count_plots(sb, pid)
    return counts


def get_panorama_with_access(sb, panorama_id, user_id):
    """
    Return (panorama_dict, access_type) or (None, None).
    access_type: 'owner' | 'client' | 'broker' | 'viewer'
    """
    try:
        r = sb.table('panoramas').select('*').eq('id', panorama_id).limit(1).execute()
        if r.data and len(r.data) > 0:
            p = dict(r.data[0])
            p['source_table'] = 'panoramas'
            if str(p.get('user_id')) == str(user_id):
                return p, 'owner'
            acc = sb.table('panorama_access').select('access_type').eq('panorama_id', panorama_id).eq('user_id', user_id).limit(1).execute()
            if acc.data and len(acc.data) > 0:
                return p, (acc.data[0].get('access_type') or 'viewer')
            ws_id = p.get('workspace_id')
            if ws_id:
                try:
                    wacc = sb.table('workspace_access').select('access_type').eq('workspace_id', ws_id).eq('user_id', user_id).limit(1).execute()
                    if wacc.data and len(wacc.data) > 0:
                        return p, (wacc.data[0].get('access_type') or 'viewer')
                except Exception:
                    pass
            return None, None
    except Exception:
        return None, None
    try:
        mr = sb.table('mobile_panoramas').select('*').eq('id', panorama_id).limit(1).execute()
        if not mr.data or len(mr.data) == 0:
            return None, None
        mp = dict(mr.data[0])
        parent_id = mp.get('panorama_parent_id')
        if not parent_id:
            return None, None
        pr = sb.table('panoramas').select('*').eq('id', parent_id).limit(1).execute()
        if not pr.data or len(pr.data) == 0:
            return None, None
        parent = dict(pr.data[0])
        mp['workspace_id'] = parent.get('workspace_id')
        mp['org_id'] = parent.get('org_id')
        mp['source_table'] = 'mobile_panoramas'
        if str(parent.get('user_id')) == str(user_id):
            return mp, 'owner'
        acc = sb.table('panorama_access').select('access_type').eq('panorama_id', parent_id).eq('user_id', user_id).limit(1).execute()
        if acc.data and len(acc.data) > 0:
            return mp, (acc.data[0].get('access_type') or 'viewer')
        ws_id = parent.get('workspace_id')
        if ws_id:
            try:
                wacc = sb.table('workspace_access').select('access_type').eq('workspace_id', ws_id).eq('user_id', user_id).limit(1).execute()
                if wacc.data and len(wacc.data) > 0:
                    return mp, (wacc.data[0].get('access_type') or 'viewer')
            except Exception:
                pass
    except Exception:
        return None, None
    return None, None


def list_panoramas_for_user(sb, user_id):
    """Return list of panoramas the user can see, each with access_type and plot_count."""
    try:
        def _normalize_panorama_id(value):
            try:
                return int(value)
            except Exception:
                return value

        try:
            owned = sb.table('panoramas').select(_PANORAMA_FIELDS_WITH_WORKSPACE).eq('user_id', user_id).order('updated_at', desc=True).execute()
        except Exception as e:
            if 'workspace_id' in str(e).lower():
                owned = sb.table('panoramas').select(_PANORAMA_FIELDS_BASE).eq('user_id', user_id).order('updated_at', desc=True).execute()
            else:
                raise

        shared = sb.table('panorama_access').select('panorama_id, access_type').eq('user_id', user_id).execute()
        shared_access = {}
        for row in (shared.data or []):
            pid = _normalize_panorama_id(row.get('panorama_id'))
            if pid is None:
                continue
            at = _normalize_access_type(row.get('access_type'))
            current = shared_access.get(pid)
            if current is None or _access_rank(at) > _access_rank(current):
                shared_access[pid] = at

        try:
            workspace_access = sb.table('workspace_access').select('workspace_id, access_type').eq('user_id', user_id).execute()
            workspace_access_rows = workspace_access.data or []
        except Exception:
            workspace_access_rows = []

        workspace_to_access = {}
        for row in workspace_access_rows:
            wsid = row.get('workspace_id')
            if not wsid:
                continue
            key = str(wsid)
            at = _normalize_access_type(row.get('access_type'))
            current = workspace_to_access.get(key)
            if current is None or _access_rank(at) > _access_rank(current):
                workspace_to_access[key] = at

        shared_ids = list(shared_access.keys())
        workspace_ids = list(workspace_to_access.keys())

        shared_panos = _select_panorama_rows(sb, 'id', shared_ids) if shared_ids else []
        workspace_panos = _select_panorama_rows(sb, 'workspace_id', workspace_ids) if workspace_ids else []

        by_id = {}
        access_by_id = {}

        def _upsert(row, access_type):
            pid = _normalize_panorama_id(row.get('id')) if isinstance(row, dict) else None
            if pid is None:
                return
            new_access = _normalize_access_type(access_type)
            existing_access = access_by_id.get(pid)
            if existing_access is None or _access_rank(new_access) > _access_rank(existing_access):
                access_by_id[pid] = new_access
            if pid not in by_id:
                by_id[pid] = dict(row)

        for row in (owned.data or []):
            _upsert(row, 'owner')
        for row in (shared_panos or []):
            pid = row.get('id') if isinstance(row, dict) else None
            _upsert(row, shared_access.get(pid, 'viewer'))
        for row in (workspace_panos or []):
            wsid = row.get('workspace_id') if isinstance(row, dict) else None
            access_type = workspace_to_access.get(str(wsid)) if wsid else None
            if not access_type:
                continue
            _upsert(row, access_type)

        panorama_ids = list(by_id.keys())
        plot_counts = _plot_counts_for_panoramas(sb, panorama_ids)

        result = []
        for pid, row in by_id.items():
            out = dict(row)
            out['access_type'] = access_by_id.get(pid, 'viewer')
            out['plot_count'] = int(plot_counts.get(pid, 0))
            # For client access, only show panoramas that have plots marked
            if out['access_type'] == 'client' and out['plot_count'] == 0:
                continue
            result.append(out)
        result.sort(key=lambda x: x.get('updated_at') or '', reverse=True)
        return result
    except Exception:
        return []


def get_panorama_by_id(sb, panorama_id):
    """Fetch panorama by id (no access check). Excludes image_data blob."""
    try:
        cols = 'id, user_id, name, filename, original_filename, width, height, is_360, created_at, updated_at'
        try:
            r = sb.table('panoramas').select(cols + ', workspace_id, use_animated_icons, start_view, audio_filename').eq('id', panorama_id).limit(1).execute()
        except Exception:
            try:
                r = sb.table('panoramas').select(cols + ', workspace_id, use_animated_icons, start_view').eq('id', panorama_id).limit(1).execute()
            except Exception:
                try:
                    r = sb.table('panoramas').select(cols + ', workspace_id, start_view').eq('id', panorama_id).limit(1).execute()
                except Exception:
                    r = sb.table('panoramas').select(cols).eq('id', panorama_id).limit(1).execute()
        if r.data and len(r.data) > 0:
            row = dict(r.data[0])
            if 'use_animated_icons' not in row:
                row['use_animated_icons'] = False
            if 'start_view' not in row:
                row['start_view'] = None
            row['source_table'] = 'panoramas'
            return row
    except Exception:
        pass
    try:
        cols = _MOBILE_PANORAMA_FIELDS_BASE
        r = sb.table('mobile_panoramas').select(cols).eq('id', panorama_id).limit(1).execute()
        if r.data and len(r.data) > 0:
            row = dict(r.data[0])
            if 'use_animated_icons' not in row:
                row['use_animated_icons'] = False
            if 'start_view' not in row:
                row['start_view'] = None
            row['source_table'] = 'mobile_panoramas'
            parent_id = row.get('panorama_parent_id')
            if parent_id:
                try:
                    pr = sb.table('panoramas').select('workspace_id, org_id').eq('id', parent_id).limit(1).execute()
                    if pr.data and len(pr.data) > 0:
                        if not row.get('workspace_id'):
                            row['workspace_id'] = pr.data[0].get('workspace_id')
                        if not row.get('org_id'):
                            row['org_id'] = pr.data[0].get('org_id')
                except Exception:
                    pass
            return row
    except Exception:
        pass
    return None


def get_mobile_panorama_by_parent_id(sb, panorama_parent_id):
    try:
        if not panorama_parent_id:
            return None
        cols = _MOBILE_PANORAMA_FIELDS_BASE
        r = sb.table('mobile_panoramas').select(cols).eq('panorama_parent_id', panorama_parent_id).order('id').limit(1).execute()
        if not r.data or len(r.data) == 0:
            return None
        row = dict(r.data[0])
        if 'use_animated_icons' not in row:
            row['use_animated_icons'] = False
        if 'start_view' not in row:
            row['start_view'] = None
        row['source_table'] = 'mobile_panoramas'
        return row
    except Exception:
        return None


def can_edit_plots(access_type):
    return access_type in ('owner', 'client')


def can_delete_panorama(access_type):
    return access_type == 'owner'
