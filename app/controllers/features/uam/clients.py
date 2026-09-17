import secrets
from datetime import datetime, timedelta
from urllib.parse import urlencode

from flask import jsonify, redirect, request

from app.core.auth import get_profile, require_admin, require_auth
from app.core.database import get_supabase

from .shared import (
    CLIENT_MEMBER_CLIENT_ADMIN_ACCESS_TARGET_ROLES,
    CLIENT_MEMBER_GROUP_ACCESS_ROLES,
    CLIENT_MEMBER_ROLE_BROKER,
    CLIENT_MEMBER_ROLE_CLIENT_ADMIN,
    CLIENT_MEMBER_ROLE_CLIENT_USER,
    DEFAULT_CLIENT_MEMBERS_ALLOWED,
    _accept_client_team_invite_token,
    _build_client_team_invite_link,
    _cascade_access_for_new_member,
    _client_capacity_snapshot,
    _client_admin_has_resource_in_group_scope,
    _client_member_limit_message,
    _get_caller_org_id,
    _get_client_member_row,
    _get_client_member_rows,
    _get_client_org,
    _is_active_pending_client_invite,
    _is_client_admin_of,
    _normalize_client_members_allowed,
    _normalize_client_member_role,
    _project_access_type_for_member_role,
    _propagate_new_member_access_to_group,
    _resource_exists_for_client_access,
    _resource_exists_in_client_member_scope,
    _send_client_team_invite_email,
)


def _unique_values(values):
    seen = set()
    out = []
    for value in values or []:
        if value is None:
            continue
        key = str(value)
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


def _client_member_counts(sb, client_ids):
    client_ids = _unique_values(client_ids)
    counts = {str(client_id): 0 for client_id in client_ids}
    if not client_ids:
        return counts
    rows = sb.table('client_members').select('client_id').in_('client_id', client_ids).execute()
    for row in (rows.data or []):
        client_id = str(row.get('client_id') or '')
        if client_id in counts:
            counts[client_id] += 1
    return counts


def _client_pending_invite_counts(sb, client_ids):
    client_ids = _unique_values(client_ids)
    counts = {str(client_id): 0 for client_id in client_ids}
    if not client_ids:
        return counts
    rows = (
        sb.table('client_team_invites')
        .select('client_id, status, expires_at')
        .in_('client_id', client_ids)
        .eq('status', 'pending')
        .execute()
    )
    for row in (rows.data or []):
        client_id = str(row.get('client_id') or '')
        if client_id in counts and _is_active_pending_client_invite(row):
            counts[client_id] += 1
    return counts


def _with_client_capacity(row, member_counts, pending_invite_counts):
    output = dict(row)
    client_id = str(output.get('id') or '')
    members_allowed = _normalize_client_members_allowed(
        output.get('members_allowed'),
        DEFAULT_CLIENT_MEMBERS_ALLOWED,
    )
    member_count = member_counts.get(client_id, 0)
    pending_invite_count = pending_invite_counts.get(client_id, 0)
    occupied_count = member_count + pending_invite_count
    output['members_allowed'] = members_allowed
    output['member_count'] = member_count
    output['pending_invite_count'] = pending_invite_count
    output['occupied_count'] = occupied_count
    output['remaining_slots'] = max(0, members_allowed - occupied_count)
    output['at_capacity'] = occupied_count >= members_allowed
    return output


def _id_name_map(sb, table_name, ids):
    ids = _unique_values(ids)
    if not ids:
        return {}
    rows = sb.table(table_name).select('id, name').in_('id', ids).execute()
    return {
        str(row.get('id')): row.get('name')
        for row in (rows.data or [])
        if row.get('id') is not None
    }


def register_uam_client_routes(app):
    @app.route('/api/clients', methods=['GET'])
    @require_admin
    def list_clients(user_id, role):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        org_id = _get_caller_org_id(sb, user_id)
        if not org_id:
            return jsonify({'error': 'Organization not set'}), 403
        try:
            r = sb.table('clients').select('id, name, description, members_allowed, created_by, created_at, updated_at').eq('org_id', org_id).order('name').execute()
            client_ids = [row.get('id') for row in (r.data or [])]
            member_counts = _client_member_counts(sb, client_ids)
            pending_invite_counts = _client_pending_invite_counts(sb, client_ids)
            out = []
            for row in (r.data or []):
                o = _with_client_capacity(row, member_counts, pending_invite_counts)
                if o.get('created_at'):
                    o['created_at'] = str(o['created_at'])
                if o.get('updated_at'):
                    o['updated_at'] = str(o['updated_at'])
                out.append(o)
            return jsonify(out)
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/clients', methods=['POST'])
    @require_admin
    def create_client(user_id, role):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        org_id = _get_caller_org_id(sb, user_id)
        if not org_id:
            return jsonify({'error': 'Organization not set'}), 403
        data = request.get_json(silent=True) or {}
        name = (data.get('name') or '').strip()
        description = (data.get('description') or '').strip()
        if not name:
            return jsonify({'error': 'Client name is required'}), 400
        try:
            members_allowed = _normalize_client_members_allowed(
                data.get('members_allowed'),
                DEFAULT_CLIENT_MEMBERS_ALLOWED,
            )
        except ValueError as e:
            return jsonify({'error': str(e)}), 400
        try:
            r = sb.table('clients').insert({
                'org_id': str(org_id), 'name': name, 'description': description,
                'members_allowed': members_allowed,
                'created_by': str(user_id),
            }).execute()
            row = dict(r.data[0]) if r.data else {}
            if row.get('created_at'):
                row['created_at'] = str(row['created_at'])
            row['member_count'] = 0
            row['pending_invite_count'] = 0
            row['occupied_count'] = 0
            row['remaining_slots'] = members_allowed
            row['at_capacity'] = False
            return jsonify(row), 201
        except Exception as e:
            msg = str(e)
            if 'unique' in msg.lower() or '23505' in msg:
                return jsonify({'error': 'A client with this name already exists'}), 409
            return jsonify({'error': msg}), 500

    @app.route('/api/clients/<client_id>', methods=['PATCH', 'PUT'])
    @require_admin
    def update_client(user_id, role, client_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        _client, err = _get_client_org(sb, client_id, user_id, role)
        if err:
            return err
        data = request.get_json(silent=True) or {}
        updates = {}
        if 'name' in data:
            name = (data['name'] or '').strip()
            if not name:
                return jsonify({'error': 'Client name cannot be empty'}), 400
            updates['name'] = name
        if 'description' in data:
            updates['description'] = (data.get('description') or '').strip()
        if 'members_allowed' in data:
            try:
                members_allowed = _normalize_client_members_allowed(data.get('members_allowed'))
            except ValueError as e:
                return jsonify({'error': str(e)}), 400
            try:
                capacity = _client_capacity_snapshot(sb, client_id, _client)
            except Exception as e:
                return jsonify({'error': str(e)}), 500
            if capacity and members_allowed < capacity['occupied_count']:
                return jsonify({
                    'error': (
                        f'Members allowed cannot be lower than the {capacity["occupied_count"]} '
                        'currently occupied member and invitation slots'
                    ),
                    'occupied_count': capacity['occupied_count'],
                }), 400
            updates['members_allowed'] = members_allowed
        if not updates:
            return jsonify({'success': True})
        try:
            sb.table('clients').update(updates).eq('id', client_id).execute()
            return jsonify({'success': True})
        except Exception as e:
            msg = str(e)
            if 'unique' in msg.lower() or '23505' in msg:
                return jsonify({'error': 'A client with this name already exists'}), 409
            return jsonify({'error': msg}), 500

    @app.route('/api/clients/<client_id>', methods=['DELETE'])
    @require_admin
    def delete_client(user_id, role, client_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        _client, err = _get_client_org(sb, client_id, user_id, role)
        if err:
            return err
        try:
            sb.table('clients').delete().eq('id', client_id).execute()
            return jsonify({'success': True})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/clients/mine', methods=['GET'])
    @require_auth
    def list_my_client_groups(user_id, role):
        """Return client groups where the caller is a client_admin."""
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        try:
            rows = sb.table('client_members').select('client_id').eq('user_id', user_id).eq('member_role', 'client_admin').execute()
            client_ids = [r.get('client_id') for r in (rows.data or []) if r.get('client_id')]
            if not client_ids:
                return jsonify([])
            r = sb.table('clients').select('id, name, description, members_allowed, created_at').in_('id', client_ids).order('name').execute()
            selected_client_ids = [row.get('id') for row in (r.data or [])]
            member_counts = _client_member_counts(sb, selected_client_ids)
            pending_invite_counts = _client_pending_invite_counts(sb, selected_client_ids)
            out = []
            for row in (r.data or []):
                o = _with_client_capacity(row, member_counts, pending_invite_counts)
                if o.get('created_at'):
                    o['created_at'] = str(o['created_at'])
                out.append(o)
            return jsonify(out)
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/clients/<client_id>/members', methods=['GET'])
    @require_auth
    def list_client_members(user_id, role, client_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        is_admin = role in ('admin', 'superadmin')
        if not is_admin and not _is_client_admin_of(sb, user_id, client_id):
            return jsonify({'error': 'Forbidden'}), 403
        if is_admin:
            _client, err = _get_client_org(sb, client_id, user_id, role)
            if err:
                return err
        try:
            rows = sb.table('client_members').select('id, user_id, member_role, invited_by, created_at').eq('client_id', client_id).order('created_at').execute()
            member_user_ids = [r.get('user_id') for r in (rows.data or []) if r.get('user_id')]
            profiles_map = {}
            if member_user_ids:
                pr = sb.table('profiles').select('user_id, display_name, email').in_('user_id', member_user_ids).execute()
                for p in (pr.data or []):
                    profiles_map[str(p.get('user_id'))] = p
            out = []
            for row in (rows.data or []):
                o = dict(row)
                o['member_role'] = _normalize_client_member_role(o.get('member_role')) or CLIENT_MEMBER_ROLE_CLIENT_USER
                uid = str(o.get('user_id') or '')
                prof = profiles_map.get(uid, {})
                o['display_name'] = prof.get('display_name') or prof.get('email') or uid
                o['email'] = prof.get('email') or ''
                if o.get('created_at'):
                    o['created_at'] = str(o['created_at'])
                out.append(o)
            return jsonify(out)
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/clients/<client_id>/available-users', methods=['GET'])
    @require_auth
    def list_client_available_users(user_id, role, client_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        is_admin = role in ('admin', 'superadmin')
        if not is_admin and not _is_client_admin_of(sb, user_id, client_id):
            return jsonify({'error': 'Forbidden'}), 403
        try:
            cr = sb.table('clients').select('id, org_id').eq('id', client_id).limit(1).execute()
            client = (cr.data or [None])[0]
            if not client:
                return jsonify({'error': 'Client group not found'}), 404
            org_id = client.get('org_id')
            if not org_id:
                return jsonify([])
            mr = sb.table('client_members').select('user_id').eq('client_id', client_id).execute()
            member_ids = {str(row.get('user_id') or '') for row in (mr.data or []) if row.get('user_id')}
            pr = (
                sb.table('profiles')
                .select('user_id, display_name, email, role')
                .eq('org_id', org_id)
                .order('display_name')
                .execute()
            )
            out = []
            for row in (pr.data or []):
                uid = str(row.get('user_id') or '').strip()
                if not uid or uid in member_ids or uid == str(user_id):
                    continue
                if str(row.get('role') or '').strip().lower() in ('admin', 'superadmin'):
                    continue
                o = dict(row)
                o['user_id'] = uid
                out.append(o)
            return jsonify(out)
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/clients/<client_id>/members', methods=['POST'])
    @require_auth
    def add_client_member(user_id, role, client_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        is_admin = role in ('admin', 'superadmin')
        is_client_admin = _is_client_admin_of(sb, user_id, client_id)
        if not is_admin and not is_client_admin:
            return jsonify({'error': 'Forbidden'}), 403
        if is_admin:
            client, err = _get_client_org(sb, client_id, user_id, role)
            if err:
                return err
        else:
            try:
                r = sb.table('clients').select('id, org_id, members_allowed').eq('id', client_id).limit(1).execute()
                client = r.data[0] if r.data else None
            except Exception:
                client = None
            if not client:
                return jsonify({'error': 'Client group not found'}), 404
        data = request.get_json(silent=True) or {}
        target_user_id = (data.get('user_id') or '').strip()
        member_role = _normalize_client_member_role(data.get('member_role')) or CLIENT_MEMBER_ROLE_CLIENT_USER
        allowed_member_roles = (
            CLIENT_MEMBER_ROLE_CLIENT_ADMIN,
            CLIENT_MEMBER_ROLE_BROKER,
        ) if is_admin else (
            CLIENT_MEMBER_ROLE_CLIENT_USER,
            CLIENT_MEMBER_ROLE_BROKER,
        )
        if member_role not in allowed_member_roles:
            if is_admin:
                return jsonify({'error': 'Platform admins can only add Client Admin or Broker members'}), 400
            return jsonify({'error': 'Client Admin can only add Sales Agent or Broker members'}), 400
        if not target_user_id:
            return jsonify({'error': 'user_id is required'}), 400
        try:
            tp = sb.table('profiles').select('user_id, org_id').eq('user_id', target_user_id).limit(1).execute()
            if not tp.data:
                return jsonify({'error': 'User not found'}), 404
            target_org = tp.data[0].get('org_id')
            client_org = str(client.get('org_id') or '')
            if member_role == CLIENT_MEMBER_ROLE_BROKER and (not target_org or not client_org):
                return jsonify({'error': 'Broker must belong to the same organization as the client group'}), 403
            if target_org and client_org and str(target_org) != client_org:
                return jsonify({'error': 'User is not in your organization'}), 403
        except Exception as e:
            return jsonify({'error': str(e)}), 500
        try:
            capacity = _client_capacity_snapshot(sb, client_id, client)
        except Exception as e:
            return jsonify({'error': str(e)}), 500
        if not capacity:
            return jsonify({'error': 'Client group not found'}), 404
        if capacity['at_capacity']:
            return jsonify({
                'error': _client_member_limit_message(capacity['members_allowed']),
                'code': 'client_member_limit_reached',
                **capacity,
            }), 409
        try:
            r = sb.table('client_members').insert({
                'client_id': str(client_id), 'user_id': str(target_user_id),
                'member_role': member_role, 'invited_by': str(user_id),
            }).execute()
            new_member = r.data[0] if r.data else {}
            new_member_id = new_member.get('id')
            if new_member_id:
                _cascade_access_for_new_member(sb, client_id, new_member_id, target_user_id, member_role, user_id)
                _propagate_new_member_access_to_group(sb, client_id, new_member_id, target_user_id, member_role, user_id)
            return jsonify({'success': True, 'member': new_member}), 201
        except Exception as e:
            msg = str(e)
            if 'unique' in msg.lower() or '23505' in msg:
                return jsonify({'error': 'User is already a member of this client group'}), 409
            return jsonify({'error': msg}), 500

    @app.route('/api/clients/<client_id>/members/<target_user_id>', methods=['PATCH', 'PUT'])
    @require_auth
    def update_client_member_role(user_id, role, client_id, target_user_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        is_admin = role in ('admin', 'superadmin')
        if not is_admin and not _is_client_admin_of(sb, user_id, client_id):
            return jsonify({'error': 'Forbidden'}), 403
        if is_admin:
            _client, err = _get_client_org(sb, client_id, user_id, role)
            if err:
                return err
        data = request.get_json(silent=True) or {}
        new_role = _normalize_client_member_role(data.get('member_role'))
        allowed_new_roles = (
            CLIENT_MEMBER_ROLE_CLIENT_ADMIN,
            CLIENT_MEMBER_ROLE_BROKER,
        ) if is_admin else (
            CLIENT_MEMBER_ROLE_CLIENT_USER,
            CLIENT_MEMBER_ROLE_BROKER,
        )
        if new_role not in allowed_new_roles:
            if is_admin:
                return jsonify({'error': 'Platform admins can only assign Client Admin or Broker roles'}), 400
            return jsonify({'error': 'Client Admin can only assign Sales Agent or Broker roles'}), 400
        try:
            existing = (
                sb.table('client_members')
                .select('member_role')
                .eq('client_id', client_id)
                .eq('user_id', target_user_id)
                .limit(1)
                .execute()
            )
            existing_row = (existing.data or [None])[0]
            if not existing_row:
                return jsonify({'error': 'Member not found'}), 404
            current_role = _normalize_client_member_role(existing_row.get('member_role'))
            if is_admin and current_role in (
                CLIENT_MEMBER_ROLE_CLIENT_USER,
            ):
                return jsonify({'error': 'Sales Agent roles are managed by the Client Admin team'}), 403
            if not is_admin and current_role in (
                CLIENT_MEMBER_ROLE_CLIENT_ADMIN,
            ):
                return jsonify({'error': 'Client Admin roles can only be changed by platform admins'}), 403
            sb.table('client_members').update({'member_role': new_role}).eq('client_id', client_id).eq('user_id', target_user_id).execute()
            return jsonify({'success': True})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/clients/<client_id>/members/<target_user_id>', methods=['DELETE'])
    @require_auth
    def remove_client_member(user_id, role, client_id, target_user_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        is_admin = role in ('admin', 'superadmin')
        if not is_admin and not _is_client_admin_of(sb, user_id, client_id):
            return jsonify({'error': 'Forbidden'}), 403
        if is_admin:
            _client, err = _get_client_org(sb, client_id, user_id, role)
            if err:
                return err
        try:
            if not is_admin:
                target_member = _get_client_member_row(sb, client_id, target_user_id)
                if not target_member:
                    return jsonify({'error': 'Member not found'}), 404
                if target_member.get('member_role') not in (
                    CLIENT_MEMBER_ROLE_CLIENT_USER,
                    CLIENT_MEMBER_ROLE_BROKER,
                ):
                    return jsonify({'error': 'Only Sales Agent or Broker members can be removed by Client Admin'}), 403
            sb.table('client_members').delete().eq('client_id', client_id).eq('user_id', target_user_id).execute()
            return jsonify({'success': True})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/clients/<client_id>/invite', methods=['POST'])
    @require_auth
    def client_invite_user(user_id, role, client_id):
        """Create team invite (email + share-link). User joins group after accepting."""
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        is_admin = role in ('admin', 'superadmin')
        is_client_admin_flag = _is_client_admin_of(sb, user_id, client_id)
        if not is_admin and not is_client_admin_flag:
            return jsonify({'error': 'Forbidden'}), 403
        try:
            cr = sb.table('clients').select('id, org_id, name, members_allowed').eq('id', client_id).limit(1).execute()
            if not cr.data:
                return jsonify({'error': 'Client group not found'}), 404
            client = cr.data[0]
        except Exception as e:
            return jsonify({'error': str(e)}), 500
        org_id = str(client.get('org_id') or '')
        if not org_id:
            return jsonify({'error': 'Client group has no organization'}), 500
        data = request.get_json(silent=True) or {}
        email = (data.get('email') or '').strip().lower()
        display_name = (data.get('display_name') or '').strip()
        member_role = _normalize_client_member_role(data.get('member_role')) or CLIENT_MEMBER_ROLE_CLIENT_USER
        allowed_invite_roles = (
            CLIENT_MEMBER_ROLE_CLIENT_ADMIN,
            CLIENT_MEMBER_ROLE_BROKER,
        ) if is_admin else (
            CLIENT_MEMBER_ROLE_CLIENT_USER,
            CLIENT_MEMBER_ROLE_BROKER,
        )
        if member_role not in allowed_invite_roles:
            if is_admin:
                return jsonify({'error': 'Platform admins can only invite Client Admin or Broker'}), 400
            return jsonify({'error': 'Client Admin can only invite Sales Agent or Broker'}), 400
        if not email or '@' not in email:
            return jsonify({'error': 'Valid email is required'}), 400
        if not display_name:
            return jsonify({'error': 'Display name is required'}), 400
        if member_role == CLIENT_MEMBER_ROLE_BROKER:
            try:
                existing_profile = (
                    sb.table('profiles')
                    .select('user_id, org_id')
                    .eq('email', email)
                    .limit(1)
                    .execute()
                )
                existing_row = (existing_profile.data or [None])[0]
                if existing_row:
                    existing_org = existing_row.get('org_id')
                    if not existing_org or str(existing_org) != str(org_id):
                        return jsonify({'error': 'Broker must belong to the same organization as the client group'}), 403
            except Exception as e:
                return jsonify({'error': str(e)}), 500
        try:
            # Reuse active pending invite for same team/email if present, else create new token.
            existing = (
                sb.table('client_team_invites')
                .select('id, invite_token, status, expires_at')
                .eq('client_id', str(client_id))
                .eq('email', email)
                .order('created_at', desc=True)
                .limit(1)
                .execute()
            )
            token = None
            invite_id = None
            existing_row = (existing.data or [None])[0]
            if existing_row and _is_active_pending_client_invite(existing_row):
                token = str(existing_row.get('invite_token') or '').strip()
                invite_id = existing_row.get('id')
            if not invite_id:
                capacity = _client_capacity_snapshot(sb, client_id, client)
                if not capacity:
                    return jsonify({'error': 'Client group not found'}), 404
                if capacity['at_capacity']:
                    return jsonify({
                        'error': _client_member_limit_message(capacity['members_allowed']),
                        'code': 'client_member_limit_reached',
                        **capacity,
                    }), 409
            if not token:
                token = secrets.token_urlsafe(24)
            invite_link = _build_client_team_invite_link(token)
            now_iso = datetime.utcnow().isoformat()
            expires_iso = (datetime.utcnow() + timedelta(days=7)).isoformat()

            if invite_id:
                sb.table('client_team_invites').update({
                    'display_name': display_name,
                    'member_role': member_role,
                    'invite_link': invite_link,
                    'expires_at': expires_iso,
                    'updated_at': now_iso,
                }).eq('id', invite_id).execute()
            else:
                sb.table('client_team_invites').insert({
                    'client_id': str(client_id),
                    'org_id': str(org_id),
                    'invited_by': str(user_id),
                    'email': email,
                    'display_name': display_name,
                    'member_role': member_role,
                    'invite_token': token,
                    'invite_link': invite_link,
                    'status': 'pending',
                    'expires_at': expires_iso,
                    'created_at': now_iso,
                    'updated_at': now_iso,
                }).execute()

            # Keep legacy invite tracking visible in Invites tab
            try:
                sb.table('user_invites').insert({
                    'org_id': str(org_id),
                    'invited_by': str(user_id),
                    'email': email,
                    'display_name': display_name,
                    'role': 'user',
                    'status': 'pending',
                }).execute()
            except Exception:
                pass

            email_sent = False
            email_error = None
            try:
                inviter_profile = get_profile(sb, user_id) or {}
                inviter_name = str(inviter_profile.get('display_name') or inviter_profile.get('email') or 'Client').strip()
                client_name = str(client.get('name') or 'Team').strip()
                _send_client_team_invite_email(email, inviter_name, client_name, invite_link)
                email_sent = True
            except Exception as e:
                email_error = str(e)

            return jsonify({
                'success': True,
                'invite_link': invite_link,
                'email_sent': email_sent,
                'email_error': email_error,
                'expires_at': expires_iso,
            }), 201
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/public/client-invite/<invite_token>', methods=['GET'])
    def get_public_client_invite(invite_token):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        try:
            r = (
                sb.table('client_team_invites')
                .select('id, client_id, invited_by, email, display_name, member_role, status, expires_at')
                .eq('invite_token', str(invite_token).strip())
                .limit(1)
                .execute()
            )
            row = (r.data or [None])[0]
            if not row:
                return jsonify({'error': 'Invite not found'}), 404
            client_name = ''
            try:
                cr = sb.table('clients').select('name').eq('id', str(row.get('client_id') or '')).limit(1).execute()
                if cr.data:
                    client_name = cr.data[0].get('name') or ''
            except Exception:
                pass
            inviter_name = ''
            try:
                inviter_id = str(row.get('invited_by') or '').strip()
                if inviter_id:
                    pr = sb.table('profiles').select('display_name,email').eq('user_id', inviter_id).limit(1).execute()
                    if pr.data:
                        inviter_name = pr.data[0].get('display_name') or pr.data[0].get('email') or ''
            except Exception:
                pass
            invited_user_exists = False
            invite_email = str(row.get('email') or '').strip()
            if invite_email:
                try:
                    ex = (
                        sb.table('profiles')
                        .select('user_id')
                        .eq('email', invite_email)
                        .limit(1)
                        .execute()
                    )
                    invited_user_exists = bool(ex.data and len(ex.data) > 0)
                    if not invited_user_exists and invite_email != invite_email.lower():
                        ex2 = (
                            sb.table('profiles')
                            .select('user_id')
                            .eq('email', invite_email.lower())
                            .limit(1)
                            .execute()
                        )
                        invited_user_exists = bool(ex2.data and len(ex2.data) > 0)
                except Exception:
                    invited_user_exists = False
            return jsonify({
                'client_name': client_name,
                'inviter_name': inviter_name,
                'display_name': row.get('display_name') or '',
                'email': row.get('email') or '',
                'member_role': _normalize_client_member_role(row.get('member_role')) or CLIENT_MEMBER_ROLE_CLIENT_USER,
                'status': row.get('status') or 'pending',
                'expires_at': row.get('expires_at'),
                'invited_user_exists': invited_user_exists,
            })
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/client-team-invites/accept', methods=['POST'])
    @require_auth
    def accept_client_team_invite(user_id, role):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        data = request.get_json(silent=True) or {}
        token = str(data.get('invite_token') or '').strip()
        ok, payload, status = _accept_client_team_invite_token(sb, token, user_id)
        if not ok:
            return jsonify({'error': payload}), status
        return jsonify({'success': True, 'result': payload})

    @app.route('/api/client-team-invites/mine', methods=['GET'])
    @require_auth
    def list_my_client_team_invites(user_id, role):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        profile = get_profile(sb, user_id) or {}
        email = str(profile.get('email') or '').strip().lower()
        if not email:
            return jsonify([])
        try:
            rows = (
                sb.table('client_team_invites')
                .select('id, client_id, invited_by, email, display_name, member_role, invite_token, status, expires_at, created_at')
                .eq('email', email)
                .eq('status', 'pending')
                .order('created_at', desc=True)
                .execute()
                .data or []
            )
            client_ids = [str(row.get('client_id') or '') for row in rows if row.get('client_id')]
            inviter_ids = [str(row.get('invited_by') or '') for row in rows if row.get('invited_by')]
            clients = _id_name_map(sb, 'clients', client_ids)
            inviters = {}
            if inviter_ids:
                pr = sb.table('profiles').select('user_id, display_name, email').in_('user_id', _unique_values(inviter_ids)).execute()
                for row in (pr.data or []):
                    uid = str(row.get('user_id') or '')
                    if uid:
                        inviters[uid] = row.get('display_name') or row.get('email') or uid
            out = []
            for row in rows:
                o = dict(row)
                cid = str(o.get('client_id') or '')
                inviter_id = str(o.get('invited_by') or '')
                o['client_name'] = clients.get(cid) or cid
                o['inviter_name'] = inviters.get(inviter_id) or ''
                o['member_role'] = _normalize_client_member_role(o.get('member_role')) or CLIENT_MEMBER_ROLE_CLIENT_USER
                if o.get('created_at'):
                    o['created_at'] = str(o['created_at'])
                if o.get('expires_at'):
                    o['expires_at'] = str(o['expires_at'])
                out.append(o)
            return jsonify(out)
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/client-team-invites/<invite_id>/reject', methods=['POST'])
    @require_auth
    def reject_client_team_invite(user_id, role, invite_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        profile = get_profile(sb, user_id) or {}
        email = str(profile.get('email') or '').strip().lower()
        if not email:
            return jsonify({'error': 'Your profile email is required'}), 403
        try:
            r = (
                sb.table('client_team_invites')
                .select('id, email, status')
                .eq('id', str(invite_id))
                .limit(1)
                .execute()
            )
            invite = (r.data or [None])[0]
            if not invite:
                return jsonify({'error': 'Invite not found'}), 404
            if str(invite.get('email') or '').strip().lower() != email:
                return jsonify({'error': 'This invite belongs to a different email address'}), 403
            if str(invite.get('status') or '').lower() != 'pending':
                return jsonify({'error': 'Invite is not pending'}), 400
            sb.table('client_team_invites').update({
                'status': 'rejected',
                'updated_at': datetime.utcnow().isoformat(),
            }).eq('id', str(invite_id)).execute()
            return jsonify({'success': True})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/clients/<client_id>/invites', methods=['GET'])
    @require_auth
    def list_client_team_invites(user_id, role, client_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        is_admin = role in ('admin', 'superadmin')
        if not is_admin and not _is_client_admin_of(sb, user_id, client_id):
            return jsonify({'error': 'Forbidden'}), 403
        if is_admin:
            _client, err = _get_client_org(sb, client_id, user_id, role)
            if err:
                return err
        try:
            r = (
                sb.table('client_team_invites')
                .select('id, email, display_name, member_role, status, invite_link, expires_at, created_at')
                .eq('client_id', str(client_id))
                .order('created_at', desc=True)
                .execute()
            )
            out = []
            for row in (r.data or []):
                o = dict(row)
                o['member_role'] = _normalize_client_member_role(o.get('member_role')) or CLIENT_MEMBER_ROLE_CLIENT_USER
                if o.get('created_at'):
                    o['created_at'] = str(o['created_at'])
                if o.get('expires_at'):
                    o['expires_at'] = str(o['expires_at'])
                out.append(o)
            return jsonify(out)
        except Exception as e:
            msg = str(e)
            if 'client_team_invites' in msg and ('does not exist' in msg.lower() or 'relation' in msg.lower()):
                return jsonify([])
            return jsonify({'error': msg}), 500

    @app.route('/api/clients/<client_id>/invites/<invite_id>/resend', methods=['POST'])
    @require_auth
    def resend_client_team_invite(user_id, role, client_id, invite_id):
        """Resend a pending team invite email and refresh the invite link if needed."""
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        is_admin = role in ('admin', 'superadmin')
        if not is_admin and not _is_client_admin_of(sb, user_id, client_id):
            return jsonify({'error': 'Forbidden'}), 403
        if is_admin:
            _client, err = _get_client_org(sb, client_id, user_id, role)
            if err:
                return err
        try:
            r = (
                sb.table('client_team_invites')
                .select('id, client_id, email, display_name, member_role, status, invite_token, invite_link, expires_at')
                .eq('id', str(invite_id))
                .eq('client_id', str(client_id))
                .limit(1)
                .execute()
            )
            invite = (r.data or [None])[0]
            if not invite:
                return jsonify({'error': 'Invite not found'}), 404
            if str(invite.get('status') or '').strip().lower() != 'pending':
                return jsonify({'error': 'Only pending invites can be resent'}), 400

            cr = sb.table('clients').select('id, name').eq('id', str(client_id)).limit(1).execute()
            client = (cr.data or [None])[0]
            if not client:
                return jsonify({'error': 'Client group not found'}), 404

            token = str(invite.get('invite_token') or '').strip()
            if not token:
                token = secrets.token_urlsafe(24)
            invite_link = _build_client_team_invite_link(token)
            now_iso = datetime.utcnow().isoformat()
            expires_iso = (datetime.utcnow() + timedelta(days=7)).isoformat()
            sb.table('client_team_invites').update({
                'invite_token': token,
                'invite_link': invite_link,
                'expires_at': expires_iso,
                'updated_at': now_iso,
            }).eq('id', str(invite_id)).execute()

            email_sent = False
            email_error = None
            try:
                inviter_profile = get_profile(sb, user_id) or {}
                inviter_name = str(inviter_profile.get('display_name') or inviter_profile.get('email') or 'Client').strip()
                client_name = str(client.get('name') or 'Team').strip()
                invite_email = str(invite.get('email') or '').strip()
                _send_client_team_invite_email(invite_email, inviter_name, client_name, invite_link)
                email_sent = True
            except Exception as e:
                email_error = str(e)

            return jsonify({
                'success': True,
                'invite_link': invite_link,
                'email_sent': email_sent,
                'email_error': email_error,
                'expires_at': expires_iso,
            })
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/client-invite/<invite_token>')
    def client_team_invite_page(invite_token):
        token = str(invite_token or '').strip()
        mode = 'signup'
        invite_email = ''
        sb = get_supabase()
        if sb and token:
            try:
                r = (
                    sb.table('client_team_invites')
                    .select('email')
                    .eq('invite_token', token)
                    .limit(1)
                    .execute()
                )
                row = (r.data or [None])[0]
                if row:
                    invite_email = str(row.get('email') or '').strip()
                    exists = False
                    if invite_email:
                        ex = (
                            sb.table('profiles')
                            .select('user_id')
                            .eq('email', invite_email)
                            .limit(1)
                            .execute()
                        )
                        exists = bool(ex.data and len(ex.data) > 0)
                        if not exists and invite_email != invite_email.lower():
                            ex2 = (
                                sb.table('profiles')
                                .select('user_id')
                                .eq('email', invite_email.lower())
                                .limit(1)
                                .execute()
                            )
                            exists = bool(ex2.data and len(ex2.data) > 0)
                    mode = 'signin' if exists else 'signup'
            except Exception:
                pass
        params = {'client_invite': token, 'mode': mode}
        if invite_email:
            params['email'] = invite_email
        return redirect('/login?' + urlencode(params))

    @app.route('/api/clients/<client_id>/access', methods=['GET'])
    @require_auth
    def get_client_access(user_id, role, client_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        is_admin = role in ('admin', 'superadmin')
        actor_member = None
        if is_admin:
            _client, err = _get_client_org(sb, client_id, user_id, role)
            if err:
                return err
        else:
            actor_member = _get_client_member_row(sb, client_id, user_id)
            if not actor_member or actor_member.get('member_role') != CLIENT_MEMBER_ROLE_CLIENT_ADMIN:
                return jsonify({'error': 'Forbidden'}), 403
        target_user_id = str(request.args.get('target_user_id') or '').strip()
        try:
            all_members = _get_client_member_rows(sb, client_id)
            if target_user_id:
                target_member = None
                for member in all_members:
                    if str(member.get('user_id') or '') == target_user_id:
                        target_member = member
                        break
                if not target_member:
                    return jsonify({'error': 'Member not found'}), 404
                target_role = target_member.get('member_role') or ''
                if not is_admin and target_role not in CLIENT_MEMBER_CLIENT_ADMIN_ACCESS_TARGET_ROLES:
                    return jsonify({'error': 'Client admins can only manage Sales Agent and Broker access'}), 403
                member_ids = [target_member.get('id')] if target_member.get('id') else []
            else:
                visible_roles = CLIENT_MEMBER_GROUP_ACCESS_ROLES if is_admin else (
                    CLIENT_MEMBER_ROLE_CLIENT_ADMIN,
                    CLIENT_MEMBER_ROLE_CLIENT_USER,
                    CLIENT_MEMBER_ROLE_BROKER,
                )
                member_ids = [
                    m.get('id')
                    for m in all_members
                    if m.get('id') and m.get('member_role') in visible_roles
                ]
            workspace_list, panorama_list = [], []
            if member_ids:
                wa = sb.table('workspace_access').select('workspace_id, access_type').in_('client_member_id', member_ids).execute()
                seen_ws = set()
                workspace_access = []
                for row in (wa.data or []):
                    wsid = row.get('workspace_id')
                    if wsid not in seen_ws:
                        seen_ws.add(wsid)
                        workspace_access.append((wsid, row.get('access_type')))
                workspace_names = _id_name_map(sb, 'workspaces', [wsid for wsid, _access in workspace_access])
                for wsid, access_type in workspace_access:
                    workspace_list.append({
                        'workspace_id': wsid,
                        'name': workspace_names.get(str(wsid)) or str(wsid),
                        'access_type': access_type,
                    })
                pa = sb.table('panorama_access').select('panorama_id, access_type').in_('client_member_id', member_ids).execute()
                seen_pa = set()
                panorama_access = []
                for row in (pa.data or []):
                    pid = row.get('panorama_id')
                    if pid not in seen_pa:
                        seen_pa.add(pid)
                        panorama_access.append((pid, row.get('access_type')))
                panorama_names = _id_name_map(sb, 'panoramas', [pid for pid, _access in panorama_access])
                for pid, access_type in panorama_access:
                    panorama_list.append({
                        'panorama_id': pid,
                        'name': panorama_names.get(str(pid)) or str(pid),
                        'access_type': access_type,
                    })
            return jsonify({'workspaces': workspace_list, 'panoramas': panorama_list})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/clients/<client_id>/access', methods=['POST'])
    @require_auth
    def grant_client_access(user_id, role, client_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        is_admin = role in ('admin', 'superadmin')
        actor_member = None
        if is_admin:
            _client, err = _get_client_org(sb, client_id, user_id, role)
            if err:
                return err
        else:
            actor_member = _get_client_member_row(sb, client_id, user_id)
            if not actor_member or actor_member.get('member_role') != CLIENT_MEMBER_ROLE_CLIENT_ADMIN:
                return jsonify({'error': 'Forbidden'}), 403
        data = request.get_json(silent=True) or {}
        resource_type = (data.get('resource_type') or '').strip()
        resource_id = data.get('resource_id')
        access_type = (data.get('access_type') or 'client').strip()
        target_user_id = str(data.get('target_user_id') or '').strip()
        if resource_type not in ('workspace', 'panorama'):
            return jsonify({'error': 'resource_type must be workspace or panorama'}), 400
        if not resource_id:
            return jsonify({'error': 'resource_id is required'}), 400
        if access_type not in ('client', 'broker', 'viewer'):
            access_type = 'client'
        if not _resource_exists_for_client_access(sb, resource_type, resource_id):
            return jsonify({'error': 'Resource not found'}), 404
        if not is_admin:
            if not _client_admin_has_resource_in_group_scope(
                sb, actor_member.get('id'), user_id, resource_type, resource_id
            ):
                return jsonify({'error': 'You can only manage access for projects already available to your client group and assigned to you'}), 403
        try:
            all_members = _get_client_member_rows(sb, client_id)
            if target_user_id:
                targets = [m for m in all_members if str(m.get('user_id') or '') == target_user_id]
                if not targets:
                    return jsonify({'error': 'Member not found'}), 404
                target_member = targets[0]
                target_role = target_member.get('member_role') or ''
                if not is_admin and target_role not in CLIENT_MEMBER_CLIENT_ADMIN_ACCESS_TARGET_ROLES:
                    return jsonify({'error': 'Client admins can only manage Sales Agent and Broker access'}), 403
                if is_admin and target_role == CLIENT_MEMBER_ROLE_BROKER:
                    scoped_member_ids = [
                        m.get('id')
                        for m in all_members
                        if m.get('id') and m.get('member_role') in CLIENT_MEMBER_GROUP_ACCESS_ROLES
                    ]
                    if not _resource_exists_in_client_member_scope(sb, resource_type, resource_id, scoped_member_ids):
                        return jsonify({'error': 'Broker access can only be granted from projects already assigned to this client group'}), 400
                members_to_update = [target_member]
            else:
                target_roles = CLIENT_MEMBER_GROUP_ACCESS_ROLES if is_admin else CLIENT_MEMBER_CLIENT_ADMIN_ACCESS_TARGET_ROLES
                members_to_update = [m for m in all_members if m.get('member_role') in target_roles]
            granted = 0
            for member in members_to_update:
                member_id = member.get('id')
                member_uid = str(member.get('user_id') or '')
                if not member_uid or not member_id:
                    continue
                try:
                    member_access_type = _project_access_type_for_member_role(access_type, member.get('member_role'))
                    if resource_type == 'workspace':
                        sb.table('workspace_access').upsert({'workspace_id': str(resource_id), 'user_id': member_uid, 'access_type': member_access_type, 'granted_by': str(user_id), 'client_member_id': member_id}, on_conflict='workspace_id,user_id').execute()
                    else:
                        sb.table('panorama_access').upsert({'panorama_id': int(resource_id), 'user_id': member_uid, 'access_type': member_access_type, 'granted_by': str(user_id), 'client_member_id': member_id}, on_conflict='panorama_id,user_id').execute()
                    granted += 1
                except Exception:
                    pass
            return jsonify({'success': True, 'granted_count': granted})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/clients/<client_id>/access', methods=['DELETE'])
    @require_auth
    def revoke_client_access(user_id, role, client_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        is_admin = role in ('admin', 'superadmin')
        actor_member = None
        if is_admin:
            _client, err = _get_client_org(sb, client_id, user_id, role)
            if err:
                return err
        else:
            actor_member = _get_client_member_row(sb, client_id, user_id)
            if not actor_member or actor_member.get('member_role') != CLIENT_MEMBER_ROLE_CLIENT_ADMIN:
                return jsonify({'error': 'Forbidden'}), 403
        data = request.get_json(silent=True) or {}
        resource_type = (data.get('resource_type') or '').strip()
        resource_id = data.get('resource_id')
        target_user_id = str(data.get('target_user_id') or '').strip()
        if resource_type not in ('workspace', 'panorama'):
            return jsonify({'error': 'resource_type must be workspace or panorama'}), 400
        if not resource_id:
            return jsonify({'error': 'resource_id is required'}), 400
        if not _resource_exists_for_client_access(sb, resource_type, resource_id):
            return jsonify({'error': 'Resource not found'}), 404
        if not is_admin:
            if not _client_admin_has_resource_in_group_scope(
                sb, actor_member.get('id'), user_id, resource_type, resource_id
            ):
                return jsonify({'error': 'You can only manage access for projects already available to your client group and assigned to you'}), 403
        try:
            all_members = _get_client_member_rows(sb, client_id)
            if target_user_id:
                targets = [m for m in all_members if str(m.get('user_id') or '') == target_user_id]
                if not targets:
                    return jsonify({'error': 'Member not found'}), 404
                target_member = targets[0]
                target_role = target_member.get('member_role') or ''
                if not is_admin and target_role not in CLIENT_MEMBER_CLIENT_ADMIN_ACCESS_TARGET_ROLES:
                    return jsonify({'error': 'Client admins can only manage Sales Agent and Broker access'}), 403
                member_ids = [target_member.get('id')] if target_member.get('id') else []
            else:
                target_roles = CLIENT_MEMBER_GROUP_ACCESS_ROLES if is_admin else CLIENT_MEMBER_CLIENT_ADMIN_ACCESS_TARGET_ROLES
                member_ids = [m.get('id') for m in all_members if m.get('id') and m.get('member_role') in target_roles]
            if not member_ids:
                return jsonify({'success': True})
            if resource_type == 'workspace':
                sb.table('workspace_access').delete().in_('client_member_id', member_ids).eq('workspace_id', str(resource_id)).execute()
            else:
                sb.table('panorama_access').delete().in_('client_member_id', member_ids).eq('panorama_id', int(resource_id)).execute()
            return jsonify({'success': True})
        except Exception as e:
            return jsonify({'error': str(e)}), 500


