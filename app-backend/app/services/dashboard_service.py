"""
Builder dashboard data: the panoramas a user can see and the projects (workspaces)
that hold them, resolved in one pass with independent reads run concurrently.
"""
from app.core.concurrency import run_parallel
from app.services.access_policy import _chunks, client_group_resource_ids_for_admin, get_client_memberships
from app.services.panorama_service import _PANORAMA_LIST_FIELDS, _plot_counts_for_panoramas, list_panoramas_for_user
from app.services.storage_service import get_s3_client, get_signed_get_url, panorama_thumb_object_key

PROJECT_FIELDS = 'id, user_id, name, main_panorama_id, updated_at'
PLATFORM_ADMIN_ROLES = ('admin', 'superadmin')


def _serialize_panorama(row, sign_thumbs):
    out = dict(row)
    for key in ('user_id', 'workspace_id', 'created_at', 'updated_at'):
        if out.get(key) is not None:
            out[key] = str(out[key])
    # Direct storage URL for the thumbnail: signing is local (no HEAD round-trip), so the browser
    # skips the /uploads redirect hop. The UI falls back to /uploads/<file>?size=thumb, which
    # generates a missing thumbnail on demand, if this URL fails.
    out['thumb_url'] = get_signed_get_url(panorama_thumb_object_key(out.get('filename')), verify=False) if sign_thumbs else None
    return out


def _serialize_project(row, access_type):
    main_id = row.get('main_panorama_id')
    return {
        'id': str(row['id']),
        'user_id': str(row.get('user_id') or ''),
        'name': row.get('name') or 'Project',
        'main_panorama_id': int(main_id) if main_id is not None else None,
        'updated_at': str(row.get('updated_at') or ''),
        'access_type': access_type,
    }


def client_member_workspace_access(sb, user_id):
    """workspace_id -> access_type granted through the user's client-team memberships."""
    member_ids = [row['id'] for row in get_client_memberships(sb, user_id) if row.get('id')]
    out = {}
    for chunk in _chunks(member_ids):
        rows = (
            sb.table('workspace_access').select('workspace_id, access_type')
            .in_('client_member_id', chunk).execute().data or []
        )
        for row in rows:
            if row.get('workspace_id'):
                out[str(row['workspace_id'])] = str(row.get('access_type') or 'viewer')
    return out


def list_visible_panoramas(sb, user_id, client_group_panorama_ids=None, visible=None):
    """Panoramas the user can open: direct/shared access plus client-admin group scope.

    `visible` may carry an already-fetched list_panoramas_for_user() result.
    """
    if visible is not None:
        client_group_panorama_ids = client_group_panorama_ids or set()
    elif client_group_panorama_ids is None:
        client_group, visible = run_parallel(
            lambda: client_group_resource_ids_for_admin(sb, user_id),
            lambda: list_panoramas_for_user(sb, user_id),
        )
        client_group_panorama_ids = client_group[1] if client_group else set()
    elif visible is None:
        visible = list_panoramas_for_user(sb, user_id)
    by_id = {str(p['id']): p for p in visible or [] if p.get('id') is not None}
    missing = [pid for pid in client_group_panorama_ids if str(pid) not in by_id]
    extra = []
    for chunk in _chunks(missing):
        extra.extend(sb.table('panoramas').select(_PANORAMA_LIST_FIELDS).in_('id', chunk).execute().data or [])
    if extra:
        counts = _plot_counts_for_panoramas(sb, [row['id'] for row in extra])
        for row in extra:
            by_id[str(row['id'])] = dict(row, access_type='client', plot_count=counts.get(row['id'], 0))
    sign_thumbs = get_s3_client() is not None
    return [_serialize_panorama(p, sign_thumbs) for p in by_id.values()]


def dashboard_snapshot(sb, user_id, role):
    owned, direct_access, member_access, client_group, visible = run_parallel(
        lambda: sb.table('workspaces').select(PROJECT_FIELDS).eq('user_id', user_id).execute().data or [],
        lambda: sb.table('workspace_access').select('workspace_id, access_type').eq('user_id', user_id).execute().data or [],
        lambda: client_member_workspace_access(sb, user_id),
        lambda: client_group_resource_ids_for_admin(sb, user_id),
        lambda: list_panoramas_for_user(sb, user_id),
    )
    client_ws_ids, client_pano_ids = client_group or (set(), set())
    panoramas = list_visible_panoramas(sb, user_id, client_pano_ids, visible=visible or [])

    projects = {str(row['id']): _serialize_project(row, 'owner') for row in owned or []}

    # Access precedence for projects the user does not own matches /api/workspaces.
    access = {wid: 'client' for wid in client_ws_ids}
    access.update(member_access or {})
    for row in direct_access or []:
        if row.get('workspace_id'):
            access[str(row['workspace_id'])] = str(row.get('access_type') or 'viewer')
    fallback = 'admin' if str(role or '').lower() in PLATFORM_ADMIN_ROLES else 'viewer'

    # Only projects that hold a visible panorama are shown, so fetch just those.
    needed = {p['workspace_id'] for p in panoramas if p.get('workspace_id')} - set(projects)
    for chunk in _chunks(sorted(needed)):
        for row in sb.table('workspaces').select(PROJECT_FIELDS).in_('id', chunk).execute().data or []:
            wid = str(row['id'])
            projects[wid] = _serialize_project(row, access.get(wid, fallback))

    ordered = sorted(projects.values(), key=lambda p: (p['access_type'] != 'owner', p['name'].lower()))
    return {'panoramas': panoramas, 'projects': ordered}
