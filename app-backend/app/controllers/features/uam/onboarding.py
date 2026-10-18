"""
Self-service onboarding for users without a client group.

  GET    /api/onboarding/state                    pending request / membership for the caller
  GET    /api/onboarding/client-groups            client groups the caller can ask to join
  GET    /api/onboarding/organizations            builders a new client group can belong to
  POST   /api/onboarding/client-groups            create a client group (caller becomes its Client Admin)
  POST   /api/onboarding/join-requests            ask to join a client group as Sales Agent or Broker
  DELETE /api/onboarding/join-requests/mine       withdraw the pending request

  GET    /api/join-requests                       requests for the groups the caller administers
  POST   /api/join-requests/<id>/approve          add the requester to the group
  POST   /api/join-requests/<id>/reject           decline the request
"""
from datetime import datetime

from flask import jsonify, request

from app.core.auth import require_auth
from app.core.concurrency import run_parallel
from app.core.database import get_supabase
from app.services.portal_identity_service import invalidate_portal_identity
from app.services.uam_reference_service import (
    CLIENT_MEMBER_ROLE_BROKER,
    CLIENT_MEMBER_ROLE_CLIENT_ADMIN,
    CLIENT_MEMBER_ROLE_CLIENT_USER,
    _normalize_client_member_role,
)

from .shared import (
    DEFAULT_CLIENT_MEMBERS_ALLOWED,
    _cascade_access_for_new_member,
    _client_capacity_snapshot,
    _client_member_limit_message,
    _get_caller_org_id,
)

JOIN_ROLES = (CLIENT_MEMBER_ROLE_CLIENT_USER, CLIENT_MEMBER_ROLE_BROKER)
_REQUEST_FIELDS = 'id, client_id, org_id, user_id, member_role, message, status, decided_at, created_at'


def _now():
    return datetime.utcnow().isoformat()


def _iso(row):
    for key in ('created_at', 'decided_at', 'updated_at'):
        if row.get(key):
            row[key] = str(row[key])
    return row


def _member_client_ids(sb, user_id):
    rows = sb.table('client_members').select('client_id').eq('user_id', str(user_id)).execute().data or []
    return {str(r['client_id']) for r in rows if r.get('client_id')}


def _pending_request(sb, user_id):
    rows = (
        sb.table('client_join_requests')
        .select(f'{_REQUEST_FIELDS}, clients(name)')
        .eq('user_id', str(user_id)).eq('status', 'pending')
        .limit(1).execute().data or []
    )
    if not rows:
        return None
    row = _iso(dict(rows[0]))
    row['client_name'] = (row.pop('clients', None) or {}).get('name') or ''
    return row


def _set_profile_org(sb, user_id, org_id):
    sb.table('profiles').update({'org_id': str(org_id), 'updated_at': _now()}).eq('user_id', str(user_id)).execute()


def _can_decide(sb, user_id, role, client):
    """Client Admins of the group, the builder's admins, and superadmins decide join requests."""
    if role == 'superadmin':
        return True
    if role == 'admin' and str(_get_caller_org_id(sb, user_id) or '') == str(client.get('org_id') or ''):
        return True
    rows = (
        sb.table('client_members').select('id')
        .eq('client_id', str(client['id'])).eq('user_id', str(user_id))
        .eq('member_role', CLIENT_MEMBER_ROLE_CLIENT_ADMIN).limit(1).execute().data
    )
    return bool(rows)


def register_uam_onboarding_routes(app):
    @app.route('/api/onboarding/state', methods=['GET'])
    @require_auth
    def onboarding_state(user_id, role):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        try:
            member_ids, pending, last = run_parallel(
                lambda: _member_client_ids(sb, user_id),
                lambda: _pending_request(sb, user_id),
                lambda: sb.table('client_join_requests').select('status, decided_at, clients(name)')
                    .eq('user_id', str(user_id)).neq('status', 'pending')
                    .order('updated_at', desc=True).limit(1).execute().data or [],
                strict=True,
            )
        except Exception as e:
            return jsonify({'error': str(e)}), 500
        last_decision = None
        if last:
            row = last[0]
            last_decision = {
                'status': row.get('status'),
                'client_name': (row.get('clients') or {}).get('name') or '',
                'decided_at': str(row['decided_at']) if row.get('decided_at') else None,
            }
        return jsonify({
            'has_client_group': bool(member_ids),
            'pending_request': pending,
            'last_decision': last_decision,
        })

    @app.route('/api/onboarding/client-groups', methods=['GET'])
    @require_auth
    def onboarding_client_groups(user_id, role):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        try:
            clients, members, mine = run_parallel(
                lambda: sb.table('clients').select('id, name, description, org_id, members_allowed, organizations(name)')
                    .order('name').execute().data or [],
                lambda: sb.table('client_members').select('client_id').execute().data or [],
                lambda: _member_client_ids(sb, user_id),
                strict=True,
            )
        except Exception as e:
            return jsonify({'error': str(e)}), 500
        counts = {}
        for row in members:
            key = str(row.get('client_id'))
            counts[key] = counts.get(key, 0) + 1
        out = []
        for c in clients:
            key = str(c['id'])
            if key in mine:
                continue
            allowed = int(c.get('members_allowed') or DEFAULT_CLIENT_MEMBERS_ALLOWED)
            out.append({
                'id': key,
                'name': c.get('name') or '',
                'description': c.get('description') or '',
                'organization_name': (c.get('organizations') or {}).get('name') or '',
                'member_count': counts.get(key, 0),
                'is_full': counts.get(key, 0) >= allowed,
            })
        return jsonify(out)

    @app.route('/api/onboarding/organizations', methods=['GET'])
    @require_auth
    def onboarding_organizations(user_id, role):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        try:
            rows = sb.table('organizations').select('id, name').order('name').execute().data or []
        except Exception as e:
            return jsonify({'error': str(e)}), 500
        return jsonify([{'id': str(r['id']), 'name': r.get('name') or ''} for r in rows])

    @app.route('/api/onboarding/client-groups', methods=['POST'])
    @require_auth
    def onboarding_create_client_group(user_id, role):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        data = request.get_json(silent=True) or {}
        name = str(data.get('name') or '').strip()
        description = str(data.get('description') or '').strip()
        org_id = str(data.get('org_id') or '').strip()
        if not name:
            return jsonify({'error': 'Client group name is required'}), 400
        if len(name) > 120:
            return jsonify({'error': 'Name must be 120 characters or fewer'}), 400
        if not org_id:
            return jsonify({'error': 'Choose the builder this client group works with'}), 400
        try:
            if _member_client_ids(sb, user_id):
                return jsonify({'error': 'You already belong to a client group'}), 409
            if not sb.table('organizations').select('id').eq('id', org_id).limit(1).execute().data:
                return jsonify({'error': 'Builder not found'}), 404
            created = sb.table('clients').insert({
                'org_id': org_id, 'name': name, 'description': description,
                'members_allowed': DEFAULT_CLIENT_MEMBERS_ALLOWED, 'created_by': str(user_id),
            }).execute().data[0]
            sb.table('client_members').insert({
                'client_id': str(created['id']), 'user_id': str(user_id),
                'member_role': CLIENT_MEMBER_ROLE_CLIENT_ADMIN, 'invited_by': str(user_id),
            }).execute()
            _set_profile_org(sb, user_id, org_id)
            sb.table('client_join_requests').update({'status': 'cancelled', 'updated_at': _now()}) \
                .eq('user_id', str(user_id)).eq('status', 'pending').execute()
        except Exception as e:
            msg = str(e)
            if 'unique' in msg.lower() or '23505' in msg:
                return jsonify({'error': 'A client group with this name already exists for that builder'}), 409
            return jsonify({'error': msg}), 500
        invalidate_portal_identity(user_id)
        return jsonify({'success': True, 'client': {'id': str(created['id']), 'name': created.get('name')}}), 201

    @app.route('/api/onboarding/join-requests', methods=['POST'])
    @require_auth
    def onboarding_request_to_join(user_id, role):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        data = request.get_json(silent=True) or {}
        client_id = str(data.get('client_id') or '').strip()
        member_role = _normalize_client_member_role(data.get('member_role')) or CLIENT_MEMBER_ROLE_CLIENT_USER
        message = str(data.get('message') or '').strip()[:500]
        if not client_id:
            return jsonify({'error': 'Choose a client group'}), 400
        if member_role not in JOIN_ROLES:
            return jsonify({'error': 'You can join as a Sales Agent or a Broker'}), 400
        try:
            client_rows, member_ids, pending = run_parallel(
                lambda: sb.table('clients').select('id, org_id, name').eq('id', client_id).limit(1).execute().data or [],
                lambda: _member_client_ids(sb, user_id),
                lambda: _pending_request(sb, user_id),
                strict=True,
            )
            if not client_rows:
                return jsonify({'error': 'Client group not found'}), 404
            if client_id in member_ids:
                return jsonify({'error': 'You are already a member of this client group'}), 409
            if pending:
                return jsonify({'error': f"You already have a pending request to join {pending['client_name']}"}), 409
            client = client_rows[0]
            row = sb.table('client_join_requests').insert({
                'client_id': client_id, 'org_id': str(client['org_id']), 'user_id': str(user_id),
                'member_role': member_role, 'message': message,
            }).execute().data[0]
        except Exception as e:
            msg = str(e)
            if 'unique' in msg.lower() or '23505' in msg:
                return jsonify({'error': 'You already have a pending request'}), 409
            return jsonify({'error': msg}), 500
        row = _iso(dict(row))
        row['client_name'] = client.get('name') or ''
        return jsonify({'success': True, 'request': row}), 201

    @app.route('/api/onboarding/join-requests/mine', methods=['DELETE'])
    @require_auth
    def onboarding_withdraw_request(user_id, role):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        try:
            sb.table('client_join_requests').update({'status': 'cancelled', 'updated_at': _now()}) \
                .eq('user_id', str(user_id)).eq('status', 'pending').execute()
        except Exception as e:
            return jsonify({'error': str(e)}), 500
        return jsonify({'success': True})

    @app.route('/api/join-requests', methods=['GET'])
    @require_auth
    def list_join_requests(user_id, role):
        """Requests for every group the caller administers (all groups of their builder for admins)."""
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        status = str(request.args.get('status') or 'pending').strip().lower()
        if status not in ('pending', 'approved', 'rejected', 'all'):
            status = 'pending'
        try:
            query = sb.table('client_join_requests').select(f'{_REQUEST_FIELDS}, clients(name)')
            if role == 'superadmin':
                pass
            elif role == 'admin':
                query = query.eq('org_id', str(_get_caller_org_id(sb, user_id) or ''))
            else:
                admin_of = (
                    sb.table('client_members').select('client_id')
                    .eq('user_id', str(user_id)).eq('member_role', CLIENT_MEMBER_ROLE_CLIENT_ADMIN)
                    .execute().data or []
                )
                client_ids = [str(r['client_id']) for r in admin_of]
                if not client_ids:
                    return jsonify({'error': 'Only Client Admins can review join requests'}), 403
                query = query.in_('client_id', client_ids)
            if status != 'all':
                query = query.eq('status', status)
            rows = query.order('created_at', desc=True).limit(200).execute().data or []
            user_ids = list({str(r['user_id']) for r in rows})
            profiles = sb.table('profiles').select('user_id, display_name, email').in_('user_id', user_ids).execute().data if user_ids else []
        except Exception as e:
            return jsonify({'error': str(e)}), 500
        by_user = {str(p['user_id']): p for p in (profiles or [])}
        out = []
        for r in rows:
            item = _iso(dict(r))
            item['client_name'] = (item.pop('clients', None) or {}).get('name') or ''
            person = by_user.get(str(r['user_id'])) or {}
            item['display_name'] = person.get('display_name') or ''
            item['email'] = person.get('email') or ''
            out.append(item)
        return jsonify(out)

    def _load_request_for_decision(sb, request_id, user_id, role):
        rows = (
            sb.table('client_join_requests').select(f'{_REQUEST_FIELDS}, clients(id, name, org_id, members_allowed)')
            .eq('id', str(request_id)).limit(1).execute().data or []
        )
        if not rows:
            return None, None, (jsonify({'error': 'Request not found'}), 404)
        req = rows[0]
        client = req.get('clients') or {}
        if not client or not _can_decide(sb, user_id, role, client):
            return None, None, (jsonify({'error': 'Only this group\'s Client Admin can review this request'}), 403)
        if req.get('status') != 'pending':
            return None, None, (jsonify({'error': f"This request was already {req.get('status')}"}), 409)
        return req, client, None

    @app.route('/api/join-requests/<request_id>/approve', methods=['POST'])
    @require_auth
    def approve_join_request(user_id, role, request_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        data = request.get_json(silent=True) or {}
        try:
            req, client, err = _load_request_for_decision(sb, request_id, user_id, role)
            if err:
                return err
            member_role = _normalize_client_member_role(data.get('member_role') or req.get('member_role'))
            if member_role not in JOIN_ROLES:
                return jsonify({'error': 'Members can join as a Sales Agent or a Broker'}), 400
            capacity = _client_capacity_snapshot(sb, client['id'], client)
            if capacity and capacity['at_capacity']:
                return jsonify({'error': _client_member_limit_message(capacity['members_allowed']), 'code': 'client_member_limit_reached'}), 409
            requester = str(req['user_id'])
            existing = (
                sb.table('client_members').select('id').eq('client_id', str(client['id']))
                .eq('user_id', requester).limit(1).execute().data or []
            )
            if existing:
                member_id = existing[0]['id']
            else:
                member = sb.table('client_members').insert({
                    'client_id': str(client['id']), 'user_id': requester,
                    'member_role': member_role, 'invited_by': str(user_id),
                }).execute().data[0]
                member_id = member['id']
                # The new member gets the projects the group already has.
                _cascade_access_for_new_member(sb, str(client['id']), member_id, requester, member_role, user_id)
            _set_profile_org(sb, requester, client['org_id'])
            sb.table('client_join_requests').update({
                'status': 'approved', 'member_role': member_role,
                'decided_by': str(user_id), 'decided_at': _now(), 'updated_at': _now(),
            }).eq('id', str(request_id)).execute()
        except Exception as e:
            return jsonify({'error': str(e)}), 500
        invalidate_portal_identity(req['user_id'])
        return jsonify({'success': True, 'member_id': member_id, 'member_role': member_role})

    @app.route('/api/join-requests/<request_id>/reject', methods=['POST'])
    @require_auth
    def reject_join_request(user_id, role, request_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        try:
            req, _client, err = _load_request_for_decision(sb, request_id, user_id, role)
            if err:
                return err
            sb.table('client_join_requests').update({
                'status': 'rejected', 'decided_by': str(user_id), 'decided_at': _now(), 'updated_at': _now(),
            }).eq('id', str(request_id)).execute()
        except Exception as e:
            return jsonify({'error': str(e)}), 500
        invalidate_portal_identity(req['user_id'])
        return jsonify({'success': True})
