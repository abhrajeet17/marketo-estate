"""
Panorama: access, list, get by id, can_edit_plots, can_delete_panorama.
Used by controllers and other services.
"""
from app.core.database import get_supabase
from app.core.auth import get_profile

_PANORAMA_LIST_FIELDS = 'id, user_id, workspace_id, name, filename, original_filename, width, height, is_360, created_at, updated_at'
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


def _chunks(values, size=150):
    values = list(values)
    for i in range(0, len(values), size):
        yield values[i:i + size]


def _select_panorama_rows(sb, column, values):
    rows = []
    for chunk in _chunks(values):
        rows.extend(sb.table('panoramas').select(_PANORAMA_LIST_FIELDS).in_(column, chunk).execute().data or [])
    return rows


def _plot_counts_for_panoramas(sb, panorama_ids):
    counts = {pid: 0 for pid in panorama_ids if pid is not None}
    for chunk in _chunks(counts):
        rows = sb.table('plots').select('panorama_id').in_('panorama_id', chunk).limit(50000).execute().data or []
        for row in rows:
            pid = _normalize_panorama_id(row.get('panorama_id'))
            if pid in counts:
                counts[pid] += 1
    return counts


def _normalize_panorama_id(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return value


def _strongest_access(rows, key):
    """Map rows[key] -> highest-ranked access_type among the rows."""
    out = {}
    for row in rows or []:
        rid = row.get(key)
        if rid is None:
            continue
        rid = _normalize_panorama_id(rid) if key == 'panorama_id' else str(rid)
        at = _normalize_access_type(row.get('access_type'))
        if rid not in out or _access_rank(at) > _access_rank(out[rid]):
            out[rid] = at
    return out


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


def _embedded_plot_count(row):
    """Pop the `plots(count)` embed off a panorama row and return the count."""
    embed = row.pop('plots', None)
    if isinstance(embed, list) and embed:
        return int(embed[0].get('count') or 0)
    return 0


def list_panoramas_for_user(sb, user_id):
    """Return the panoramas the user can see, each with access_type and plot_count."""
    from app.core.concurrency import run_parallel
    # One parallel round-trip: shared panoramas are embedded in their access rows (via the
    # panorama_access / workspace_access foreign keys) and plot counts in each panorama row.
    pano_fields = f'{_PANORAMA_LIST_FIELDS}, plots(count)'
    try:
        owned, shared_rows, workspace_rows = run_parallel(
            lambda: sb.table('panoramas').select(pano_fields).eq('user_id', user_id).execute().data or [],
            lambda: sb.table('panorama_access').select(f'panorama_id, access_type, panoramas({pano_fields})').eq('user_id', user_id).execute().data or [],
            lambda: sb.table('workspace_access').select(
                f'workspace_id, access_type, workspaces(panoramas!panoramas_workspace_id_fkey({pano_fields}))'
            ).eq('user_id', user_id).execute().data or [],
        )
        if owned is None:
            return []
        shared_access = _strongest_access(shared_rows, 'panorama_id')
        workspace_access = _strongest_access(workspace_rows, 'workspace_id')

        shared_panos, seen = [], set()
        for acc in shared_rows or []:
            row = acc.get('panoramas')
            if row and row.get('id') not in seen:
                seen.add(row.get('id'))
                shared_panos.append(row)
        workspace_panos, seen = [], set()
        for acc in workspace_rows or []:
            for row in ((acc.get('workspaces') or {}).get('panoramas') or []):
                if row.get('id') not in seen:
                    seen.add(row.get('id'))
                    workspace_panos.append(row)

        by_id, access_by_id, plot_counts = {}, {}, {}

        def add(row, access_type):
            row = dict(row)
            count = _embedded_plot_count(row)
            pid = _normalize_panorama_id(row.get('id'))
            if pid is None or not access_type:
                return
            by_id.setdefault(pid, row)
            plot_counts.setdefault(pid, count)
            current = access_by_id.get(pid)
            if current is None or _access_rank(access_type) > _access_rank(current):
                access_by_id[pid] = access_type

        for row in owned:
            add(row, 'owner')
        for row in shared_panos:
            add(row, shared_access.get(_normalize_panorama_id(row.get('id')), 'viewer'))
        for row in workspace_panos:
            add(row, workspace_access.get(str(row.get('workspace_id') or '')))

        result = []
        for pid, row in by_id.items():
            row['access_type'] = access_by_id[pid]
            row['plot_count'] = plot_counts.get(pid, 0)
            # Client access only surfaces panoramas that already have plots marked.
            if row['access_type'] == 'client' and row['plot_count'] == 0:
                continue
            result.append(row)
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
