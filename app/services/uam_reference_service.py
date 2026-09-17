"""Shared UAM/client-member reference helpers.

Kept in services so non-UAM controllers can use reference-user logic
without importing route modules.
"""

CLIENT_MEMBER_ROLE_CLIENT_ADMIN = 'client_admin'
CLIENT_MEMBER_ROLE_CLIENT_USER = 'client_user'
CLIENT_MEMBER_ROLE_BROKER = 'broker'

CLIENT_MEMBER_ROLE_ALIASES = {
    'sales_agent': CLIENT_MEMBER_ROLE_CLIENT_USER,
}

CLIENT_MEMBER_ALLOWED_ROLES = (
    CLIENT_MEMBER_ROLE_CLIENT_ADMIN,
    CLIENT_MEMBER_ROLE_CLIENT_USER,
    CLIENT_MEMBER_ROLE_BROKER,
)

CLIENT_MEMBER_GROUP_ACCESS_ROLES = (
    CLIENT_MEMBER_ROLE_CLIENT_ADMIN,
    CLIENT_MEMBER_ROLE_CLIENT_USER,
    CLIENT_MEMBER_ROLE_BROKER,
)

CLIENT_MEMBER_CLIENT_ADMIN_ACCESS_TARGET_ROLES = (
    CLIENT_MEMBER_ROLE_CLIENT_USER,
    CLIENT_MEMBER_ROLE_BROKER,
)

CLIENT_MEMBER_BROKER_ROLES = (
    CLIENT_MEMBER_ROLE_BROKER,
)

CLIENT_MEMBER_REFERENCE_ROLES = (
    CLIENT_MEMBER_ROLE_CLIENT_ADMIN,
    CLIENT_MEMBER_ROLE_CLIENT_USER,
    CLIENT_MEMBER_ROLE_BROKER,
)

CLIENT_MEMBER_REFERENCE_ROLE_LABELS = {
    CLIENT_MEMBER_ROLE_CLIENT_ADMIN: 'Client Admin',
    CLIENT_MEMBER_ROLE_CLIENT_USER: 'Sales Agent',
    CLIENT_MEMBER_ROLE_BROKER: 'Broker',
}

def _normalize_client_member_role(member_role):
    role_key = str(member_role or '').strip().lower()
    if not role_key:
        return ''
    return CLIENT_MEMBER_ROLE_ALIASES.get(role_key, role_key)

def _is_broker_member_role(member_role):
    return _normalize_client_member_role(member_role) in CLIENT_MEMBER_BROKER_ROLES

def user_is_broker(sb, user_id, role=None):
    if str(role or '').strip().lower() == CLIENT_MEMBER_ROLE_BROKER:
        return True
    try:
        rows = (
            sb.table('client_members')
            .select('member_role')
            .eq('user_id', str(user_id))
            .execute()
            .data or []
        )
        for row in rows:
            if _is_broker_member_role(row.get('member_role')):
                return True
    except Exception:
        pass
    return False

def user_is_client_admin(sb, user_id):
    try:
        row = (
            sb.table('client_members')
            .select('id')
            .eq('user_id', str(user_id))
            .eq('member_role', CLIENT_MEMBER_ROLE_CLIENT_ADMIN)
            .limit(1)
            .execute()
        )
        return bool(row.data)
    except Exception:
        return False

def _project_reference_client_ids(sb, workspace_id=None, panorama_id=None):
    resolved_workspace_id = str(workspace_id or '').strip() or None
    panorama_ids = []
    if panorama_id is not None and str(panorama_id).strip() != '':
        try:
            panorama_ids.append(int(panorama_id))
        except Exception:
            pass
    if not resolved_workspace_id and panorama_ids:
        try:
            panorama_row = (
                sb.table('panoramas')
                .select('workspace_id')
                .eq('id', int(panorama_ids[0]))
                .limit(1)
                .execute()
            )
            resolved_workspace_id = str(((panorama_row.data or [None])[0] or {}).get('workspace_id') or '').strip() or None
        except Exception:
            resolved_workspace_id = None
    if resolved_workspace_id:
        try:
            panorama_rows = (
                sb.table('panoramas')
                .select('id')
                .eq('workspace_id', str(resolved_workspace_id))
                .execute()
            )
            workspace_panorama_ids = []
            for row in (panorama_rows.data or []):
                try:
                    workspace_panorama_ids.append(int(row.get('id')))
                except Exception:
                    continue
            panorama_ids = list(dict.fromkeys(workspace_panorama_ids + panorama_ids))
        except Exception:
            pass
    member_ids = set()
    try:
        if resolved_workspace_id:
            workspace_access_rows = (
                sb.table('workspace_access')
                .select('client_member_id')
                .eq('workspace_id', str(resolved_workspace_id))
                .execute()
            )
            for row in (workspace_access_rows.data or []):
                mid = row.get('client_member_id')
                if mid:
                    member_ids.add(mid)
    except Exception:
        pass
    try:
        if panorama_ids:
            panorama_access_rows = (
                sb.table('panorama_access')
                .select('client_member_id')
                .in_('panorama_id', panorama_ids)
                .execute()
            )
            for row in (panorama_access_rows.data or []):
                mid = row.get('client_member_id')
                if mid:
                    member_ids.add(mid)
    except Exception:
        pass
    if not member_ids:
        return []
    try:
        member_rows = (
            sb.table('client_members')
            .select('client_id')
            .in_('id', list(member_ids))
            .execute()
        )
    except Exception:
        return []
    client_ids = []
    seen_client_ids = set()
    for row in (member_rows.data or []):
        client_id = str(row.get('client_id') or '').strip()
        if not client_id or client_id in seen_client_ids:
            continue
        seen_client_ids.add(client_id)
        client_ids.append(client_id)
    return client_ids

def _project_reference_users(sb, workspace_id=None, panorama_id=None, client_id=None):
    project_client_ids = _project_reference_client_ids(sb, workspace_id=workspace_id, panorama_id=panorama_id)
    if client_id is not None:
        scoped_client_ids = [cid for cid in project_client_ids if str(cid) == str(client_id)]
    else:
        scoped_client_ids = list(project_client_ids)
    if not scoped_client_ids:
        return {'client_ids': project_client_ids, 'users': []}
    try:
        member_rows = (
            sb.table('client_members')
            .select('client_id, user_id, member_role')
            .in_('client_id', scoped_client_ids)
            .execute()
        )
    except Exception:
        return {'client_ids': project_client_ids, 'users': []}
    client_name_map = {}
    try:
        client_rows = (
            sb.table('clients')
            .select('id, name')
            .in_('id', scoped_client_ids)
            .execute()
        )
        client_name_map = {
            str(row.get('id')): str(row.get('name') or '').strip()
            for row in (client_rows.data or [])
            if row.get('id')
        }
    except Exception:
        client_name_map = {}
    eligible_members = []
    seen_user_ids = set()
    user_ids = []
    for row in (member_rows.data or []):
        member_role = _normalize_client_member_role(row.get('member_role'))
        if member_role not in CLIENT_MEMBER_REFERENCE_ROLES:
            continue
        member_user_id = str(row.get('user_id') or '').strip()
        member_client_id = str(row.get('client_id') or '').strip()
        if not member_user_id or not member_client_id:
            continue
        eligible_members.append({
            'client_id': member_client_id,
            'user_id': member_user_id,
            'member_role': member_role,
        })
        if member_user_id not in seen_user_ids:
            seen_user_ids.add(member_user_id)
            user_ids.append(member_user_id)
    profile_map = {}
    try:
        if user_ids:
            profile_rows = (
                sb.table('profiles')
                .select('user_id, display_name, email')
                .in_('user_id', user_ids)
                .execute()
            )
            profile_map = {
                str(row.get('user_id')): {
                    'display_name': str(row.get('display_name') or '').strip(),
                    'email': str(row.get('email') or '').strip(),
                }
                for row in (profile_rows.data or [])
                if row.get('user_id')
            }
    except Exception:
        profile_map = {}
    out_by_user = {}
    role_priority = {
        CLIENT_MEMBER_ROLE_BROKER: 0,
        CLIENT_MEMBER_ROLE_CLIENT_ADMIN: 1,
        CLIENT_MEMBER_ROLE_CLIENT_USER: 2,
    }
    for member in eligible_members:
        member_user_id = member.get('user_id')
        if not member_user_id:
            continue
        existing = out_by_user.get(member_user_id)
        if not existing:
            profile = profile_map.get(member_user_id) or {}
            existing = {
                'user_id': member_user_id,
                'display_name': profile.get('display_name') or profile.get('email') or member_user_id,
                'email': profile.get('email') or '',
                'member_role': member.get('member_role') or CLIENT_MEMBER_ROLE_CLIENT_USER,
                'member_role_label': CLIENT_MEMBER_REFERENCE_ROLE_LABELS.get(
                    member.get('member_role'),
                    'Reference',
                ),
                'client_ids': [],
                'client_group_names': [],
            }
            out_by_user[member_user_id] = existing
        current_role = member.get('member_role') or CLIENT_MEMBER_ROLE_CLIENT_USER
        if role_priority.get(current_role, 99) < role_priority.get(existing.get('member_role'), 99):
            existing['member_role'] = current_role
            existing['member_role_label'] = CLIENT_MEMBER_REFERENCE_ROLE_LABELS.get(current_role, 'Reference')
        member_client_id = str(member.get('client_id') or '').strip()
        if member_client_id and member_client_id not in existing['client_ids']:
            existing['client_ids'].append(member_client_id)
        client_name = client_name_map.get(member_client_id) or ''
        if client_name and client_name not in existing['client_group_names']:
            existing['client_group_names'].append(client_name)
    users = list(out_by_user.values())
    users.sort(
        key=lambda item: (
            str(item.get('display_name') or '').strip().lower(),
            str(item.get('email') or '').strip().lower(),
            str(item.get('user_id') or '').strip().lower(),
        )
    )
    return {'client_ids': project_client_ids, 'users': users}

BROKER_REFERRED_CONTACT_FIELDS = (
    'customer_email',
    'customer_phone',
    'customer_address',
    'customer_street',
    'customer_city',
    'customer_state',
    'customer_country',
    'customer_zip_code',
)

BROKER_REFERRED_CONTACT_MASK_LABEL = 'Hidden until broker reveals'

PLATFORM_ADMIN_ROLES = frozenset({'admin', 'superadmin'})


def _is_platform_admin_role(role):
    return str(role or '').strip().lower() in PLATFORM_ADMIN_ROLES


def _interest_has_broker_reference(row):
    return bool(str((row or {}).get('reference_user_id') or '').strip())


def _interest_contact_is_revealed(row):
    return bool(str((row or {}).get('contact_revealed_at') or '').strip())


def _viewer_is_client_staff(sb, user_id):
    try:
        rows = (
            sb.table('client_members')
            .select('member_role')
            .eq('user_id', str(user_id))
            .execute()
            .data or []
        )
    except Exception:
        return False
    for row in rows:
        member_role = _normalize_client_member_role(row.get('member_role'))
        if member_role in (CLIENT_MEMBER_ROLE_CLIENT_ADMIN, CLIENT_MEMBER_ROLE_CLIENT_USER):
            return True
    return False


def viewer_should_mask_broker_referred_contact(sb, user_id, role, reference_scope_user_id=None):
    if reference_scope_user_id:
        return False
    if _is_platform_admin_role(role):
        return False
    return _viewer_is_client_staff(sb, user_id)


def can_user_reveal_broker_referred_contact(user_id, interest_row):
    ref_uid = str((interest_row or {}).get('reference_user_id') or '').strip()
    if not ref_uid:
        return False
    if _interest_contact_is_revealed(interest_row):
        return False
    return ref_uid == str(user_id or '').strip()


def load_broker_refer_interest_reveal_map(sb, interest_ids):
    ids = [str(i).strip() for i in (interest_ids or []) if str(i).strip()]
    if not ids:
        return {}
    out = {}
    chunk_size = 100
    for index in range(0, len(ids), chunk_size):
        chunk = ids[index:index + chunk_size]
        try:
            rows = (
                sb.table('buy_interests')
                .select('id, reference_user_id, contact_revealed_at')
                .in_('id', chunk)
                .execute()
                .data or []
            )
        except Exception:
            continue
        for row in rows:
            row_id = str(row.get('id') or '').strip()
            if row_id:
                out[row_id] = row
    return out


def _mask_broker_referred_contact_values(row):
    for key in BROKER_REFERRED_CONTACT_FIELDS:
        if key in row:
            row[key] = ''


def apply_broker_referred_contact_mask(row, *, user_id, role, reference_scope_user_id=None, sb=None):
    item = dict(row or {})
    ref_uid = str(item.get('reference_user_id') or '').strip()
    revealed = _interest_contact_is_revealed(item)
    can_reveal = can_user_reveal_broker_referred_contact(user_id, item)
    should_mask = (
        ref_uid
        and not revealed
        and sb is not None
        and viewer_should_mask_broker_referred_contact(sb, user_id, role, reference_scope_user_id)
    )
    if should_mask:
        _mask_broker_referred_contact_values(item)
    if item.get('contact_revealed_at'):
        item['contact_revealed_at'] = str(item['contact_revealed_at'])
    item['contact_revealed'] = revealed
    item['contact_hidden'] = bool(should_mask)
    item['can_reveal_contact'] = bool(can_reveal)
    if item.get('contact_hidden'):
        item['contact_hidden_label'] = BROKER_REFERRED_CONTACT_MASK_LABEL
    return item


def apply_broker_referred_contact_mask_to_contact(
    contact_row,
    interest_row,
    *,
    user_id,
    role,
    reference_scope_user_id=None,
    sb=None,
):
    item = dict(contact_row or {})
    interest = interest_row or {}
    ref_uid = str(interest.get('reference_user_id') or '').strip()
    revealed = _interest_contact_is_revealed(interest)
    should_mask = (
        ref_uid
        and not revealed
        and sb is not None
        and viewer_should_mask_broker_referred_contact(sb, user_id, role, reference_scope_user_id)
    )
    if should_mask:
        item['email'] = ''
        item['phone'] = ''
        item['address'] = ''
        item['email_norm'] = ''
        item['phone_norm'] = ''
    item['contact_revealed'] = revealed
    item['contact_hidden'] = bool(should_mask)
    if item.get('contact_hidden'):
        item['contact_hidden_label'] = BROKER_REFERRED_CONTACT_MASK_LABEL
    return item


def broker_shareable_workspace_ids(sb, user_id):
    """Workspace ids the user can generate reference share links for.

    Mirrors the access check in GET /api/workspaces/<id>/share-endpoint so a
    broker's CRM lists can be trimmed to plots they can actually share:
    owned workspaces, workspaces with a direct workspace_access row, and
    workspaces reference-linked to one of the user's client groups (any group
    member tagged on a workspace_access/panorama_access row — the reverse of
    _project_reference_client_ids).
    """
    uid = str(user_id or '').strip()
    workspace_ids = set()
    if not uid:
        return workspace_ids
    try:
        rows = sb.table('workspaces').select('id').eq('user_id', uid).execute().data or []
        for row in rows:
            wsid = str(row.get('id') or '').strip()
            if wsid:
                workspace_ids.add(wsid)
    except Exception:
        pass
    try:
        rows = sb.table('workspace_access').select('workspace_id').eq('user_id', uid).execute().data or []
        for row in rows:
            wsid = str(row.get('workspace_id') or '').strip()
            if wsid:
                workspace_ids.add(wsid)
    except Exception:
        pass
    client_ids = []
    seen_client_ids = set()
    try:
        member_rows = sb.table('client_members').select('client_id, member_role').eq('user_id', uid).execute().data or []
    except Exception:
        member_rows = []
    for row in member_rows:
        if _normalize_client_member_role(row.get('member_role')) not in CLIENT_MEMBER_REFERENCE_ROLES:
            continue
        cid = str(row.get('client_id') or '').strip()
        if cid and cid not in seen_client_ids:
            seen_client_ids.add(cid)
            client_ids.append(cid)
    if not client_ids:
        return workspace_ids
    member_ids = []
    try:
        rows = sb.table('client_members').select('id').in_('client_id', client_ids).execute().data or []
        member_ids = [r.get('id') for r in rows if r.get('id')]
    except Exception:
        member_ids = []
    if not member_ids:
        return workspace_ids
    panorama_ids = set()
    try:
        rows = sb.table('workspace_access').select('workspace_id').in_('client_member_id', member_ids).execute().data or []
        for row in rows:
            wsid = str(row.get('workspace_id') or '').strip()
            if wsid:
                workspace_ids.add(wsid)
    except Exception:
        pass
    try:
        rows = sb.table('panorama_access').select('panorama_id').in_('client_member_id', member_ids).execute().data or []
        for row in rows:
            pid = row.get('panorama_id')
            if pid is None:
                continue
            try:
                panorama_ids.add(int(pid))
            except Exception:
                continue
    except Exception:
        pass
    if panorama_ids:
        try:
            rows = sb.table('panoramas').select('workspace_id').in_('id', list(panorama_ids)).execute().data or []
            for row in rows:
                wsid = str(row.get('workspace_id') or '').strip()
                if wsid:
                    workspace_ids.add(wsid)
        except Exception:
            pass
    return workspace_ids


def _validate_project_reference_user(sb, reference_user_id=None, workspace_id=None, panorama_id=None, client_id=None):
    ref_user_id = str(reference_user_id or '').strip()
    catalog = _project_reference_users(
        sb,
        workspace_id=workspace_id,
        panorama_id=panorama_id,
        client_id=client_id,
    )
    if not ref_user_id:
        return None, catalog, None
    for row in (catalog.get('users') or []):
        if str(row.get('user_id') or '') == ref_user_id:
            return ref_user_id, catalog, row
    return None, catalog, None
