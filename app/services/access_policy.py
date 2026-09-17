from app.core.auth import get_profile
from app.services.uam_reference_service import (
    CLIENT_MEMBER_ALLOWED_ROLES,
    CLIENT_MEMBER_GROUP_ACCESS_ROLES,
    CLIENT_MEMBER_ROLE_CLIENT_ADMIN,
    _normalize_client_member_role,
)


def _chunks(values, size=200):
    values = list(values or [])
    for index in range(0, len(values), size):
        yield values[index:index + size]


def _unique(values):
    out = []
    seen = set()
    for value in values or []:
        if value is None:
            continue
        key = str(value)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


def is_platform_admin(role):
    return str(role or '').strip().lower() in ('admin', 'superadmin')


def get_client_memberships(sb, user_id, client_ids=None):
    try:
        q = (
            sb.table('client_members')
            .select('id, client_id, user_id, member_role')
            .eq('user_id', str(user_id))
        )
        scoped_client_ids = [str(cid) for cid in _unique(client_ids or [])]
        if scoped_client_ids:
            q = q.in_('client_id', scoped_client_ids)
        rows = q.execute().data or []
    except Exception:
        rows = []
    out = []
    for row in rows:
        role = _normalize_client_member_role(row.get('member_role'))
        if role not in CLIENT_MEMBER_ALLOWED_ROLES:
            continue
        out.append({
            'id': row.get('id'),
            'client_id': str(row.get('client_id') or ''),
            'user_id': str(row.get('user_id') or ''),
            'member_role': role,
        })
    return [row for row in out if row.get('id') and row.get('client_id') and row.get('user_id')]


def get_admin_visible_clients(sb, user_id, role):
    if not is_platform_admin(role):
        return []
    try:
        q = sb.table('clients').select('id, name, org_id').order('name')
        if str(role or '').strip().lower() != 'superadmin':
            profile = get_profile(sb, user_id) or {}
            org_id = profile.get('org_id')
            if not org_id:
                return []
            q = q.eq('org_id', org_id)
        rows = q.execute().data or []
    except Exception:
        rows = []
    return [
        {
            'id': str(row.get('id') or ''),
            'name': str(row.get('name') or '').strip() or str(row.get('id') or ''),
            'org_id': str(row.get('org_id') or '') if row.get('org_id') else '',
            'member_role': 'admin',
        }
        for row in rows
        if row.get('id')
    ]


def get_visible_client_options(sb, user_id, role):
    if is_platform_admin(role):
        return get_admin_visible_clients(sb, user_id, role)

    memberships = get_client_memberships(sb, user_id)
    client_ids = _unique([m.get('client_id') for m in memberships])
    if not client_ids:
        return []
    names = {}
    try:
        for chunk in _chunks(client_ids):
            rows = sb.table('clients').select('id, name').in_('id', chunk).execute().data or []
            for row in rows:
                names[str(row.get('id'))] = str(row.get('name') or '').strip()
    except Exception:
        names = {}

    best_role = {}
    role_rank = {
        CLIENT_MEMBER_ROLE_CLIENT_ADMIN: 1,
        'client_user': 2,
        'broker': 3,
    }
    for row in memberships:
        cid = row.get('client_id')
        role_key = row.get('member_role')
        if cid not in best_role or role_rank.get(role_key, 99) < role_rank.get(best_role[cid], 99):
            best_role[cid] = role_key

    return [
        {
            'id': str(cid),
            'name': names.get(str(cid)) or str(cid),
            'member_role': best_role.get(str(cid)) or '',
        }
        for cid in client_ids
    ]


def _client_name_map(sb, client_ids):
    ids = [str(v) for v in _unique(client_ids)]
    if not ids:
        return {}
    out = {}
    try:
        for chunk in _chunks(ids):
            rows = sb.table('clients').select('id, name').in_('id', chunk).execute().data or []
            for row in rows:
                cid = str(row.get('id') or '')
                if cid:
                    out[cid] = str(row.get('name') or '').strip() or cid
    except Exception:
        pass
    return out


def get_resource_client_scope(sb, workspace_ids=None, panorama_ids=None):
    workspace_ids = [str(v) for v in _unique(workspace_ids)]
    panorama_ids_int = []
    for value in _unique(panorama_ids):
        try:
            panorama_ids_int.append(int(value))
        except Exception:
            continue

    member_ids = set()
    ws_member_rows = {}
    pano_member_rows = {}
    try:
        for chunk in _chunks(workspace_ids):
            rows = sb.table('workspace_access').select('workspace_id, client_member_id').in_('workspace_id', chunk).execute().data or []
            for row in rows:
                mid = row.get('client_member_id')
                wsid = str(row.get('workspace_id') or '')
                if mid and wsid:
                    member_ids.add(mid)
                    ws_member_rows.setdefault(wsid, set()).add(mid)
    except Exception:
        pass
    try:
        for chunk in _chunks(panorama_ids_int):
            rows = sb.table('panorama_access').select('panorama_id, client_member_id').in_('panorama_id', chunk).execute().data or []
            for row in rows:
                mid = row.get('client_member_id')
                try:
                    pid = str(int(row.get('panorama_id')))
                except Exception:
                    pid = ''
                if mid and pid:
                    member_ids.add(mid)
                    pano_member_rows.setdefault(pid, set()).add(mid)
    except Exception:
        pass
    if not member_ids:
        return {'workspaces': {}, 'panoramas': {}, 'clients': {}}

    member_to_client = {}
    try:
        for chunk in _chunks(member_ids):
            rows = sb.table('client_members').select('id, client_id').in_('id', chunk).execute().data or []
            for row in rows:
                mid = row.get('id')
                cid = str(row.get('client_id') or '')
                if mid and cid:
                    member_to_client[mid] = cid
    except Exception:
        member_to_client = {}

    client_ids = set(member_to_client.values())
    client_names = _client_name_map(sb, client_ids)

    def build_scope(rows_by_resource):
        scoped = {}
        for rid, mids in rows_by_resource.items():
            cids = sorted({member_to_client.get(mid) for mid in mids if member_to_client.get(mid)})
            scoped[str(rid)] = {
                'client_ids': cids,
                'client_names': [client_names.get(cid, cid) for cid in cids],
            }
        return scoped

    return {
        'workspaces': build_scope(ws_member_rows),
        'panoramas': build_scope(pano_member_rows),
        'clients': {
            str(cid): {'id': str(cid), 'name': client_names.get(str(cid), str(cid))}
            for cid in client_ids
        },
    }


def annotate_resource_rows_with_client_scope(sb, rows, resource_type):
    rows = list(rows or [])
    if not rows:
        return rows
    if resource_type == 'workspace':
        scope = get_resource_client_scope(sb, workspace_ids=[row.get('id') for row in rows]).get('workspaces', {})
        for row in rows:
            rid = str(row.get('id') or '')
            meta = scope.get(rid) or {'client_ids': [], 'client_names': []}
            row['client_ids'] = meta.get('client_ids') or []
            row['client_names'] = meta.get('client_names') or []
        return rows
    else:
        combined = get_resource_client_scope(
            sb,
            workspace_ids=[row.get('workspace_id') for row in rows if row.get('workspace_id')],
            panorama_ids=[row.get('id') for row in rows],
        )
        panorama_scope = combined.get('panoramas', {})
        workspace_scope = combined.get('workspaces', {})
    for row in rows:
        rid = str(row.get('id') or '')
        wsid = str(row.get('workspace_id') or '')
        pano_meta = panorama_scope.get(rid) or {'client_ids': [], 'client_names': []}
        ws_meta = workspace_scope.get(wsid) or {'client_ids': [], 'client_names': []}
        clients = {}
        for cid, name in zip(ws_meta.get('client_ids') or [], ws_meta.get('client_names') or []):
            clients[str(cid)] = name
        for cid, name in zip(pano_meta.get('client_ids') or [], pano_meta.get('client_names') or []):
            clients[str(cid)] = name
        row['client_ids'] = sorted(clients.keys())
        row['client_names'] = [clients[cid] for cid in row['client_ids']]
    return rows


def client_admin_group_member_ids(sb, user_id):
    rows = (
        sb.table('client_members')
        .select('client_id')
        .eq('user_id', str(user_id))
        .eq('member_role', CLIENT_MEMBER_ROLE_CLIENT_ADMIN)
        .execute()
    )
    client_ids = [str(r.get('client_id')) for r in (rows.data or []) if r.get('client_id')]
    if not client_ids:
        return []
    group_rows = (
        sb.table('client_members')
        .select('id, member_role')
        .in_('client_id', client_ids)
        .execute()
    )
    allowed = set(CLIENT_MEMBER_GROUP_ACCESS_ROLES or [])
    member_ids = []
    for row in (group_rows.data or []):
        rid = row.get('id')
        role = _normalize_client_member_role(row.get('member_role'))
        if rid and role in allowed:
            member_ids.append(rid)
    return member_ids


def client_group_resource_ids_for_admin(sb, user_id):
    member_ids = client_admin_group_member_ids(sb, user_id)
    if not member_ids:
        return set(), set()
    workspace_ids = set()
    panorama_ids = set()
    for chunk in _chunks(member_ids):
        wa = sb.table('workspace_access').select('workspace_id').in_('client_member_id', chunk).execute()
        for row in (wa.data or []):
            wsid = row.get('workspace_id')
            if wsid:
                workspace_ids.add(str(wsid))
        pa = sb.table('panorama_access').select('panorama_id').in_('client_member_id', chunk).execute()
        for row in (pa.data or []):
            pid = row.get('panorama_id')
            try:
                if pid is not None:
                    panorama_ids.add(int(pid))
            except Exception:
                continue
    # A project assignment grants access to every panorama/plot inside that
    # workspace, even when no separate panorama_access row was created.
    for chunk in _chunks(workspace_ids):
        try:
            rows = sb.table('panoramas').select('id').in_('workspace_id', chunk).execute()
        except Exception:
            continue
        for row in (rows.data or []):
            try:
                if row.get('id') is not None:
                    panorama_ids.add(int(row.get('id')))
            except Exception:
                continue
    return workspace_ids, panorama_ids
