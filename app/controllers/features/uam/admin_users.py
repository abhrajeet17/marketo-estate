from datetime import datetime

from flask import jsonify, request

from app import config as app_config
from app.core.auth import get_profile, require_admin, require_auth
from app.core.database import get_supabase

from .shared import _can_manage_target, _get_caller_org_id


def register_uam_admin_user_routes(app):
    @app.route('/api/admin/users', methods=['POST'])
    @require_auth
    def admin_create_user(user_id, role):
        if role not in ('admin', 'superadmin'):
            return jsonify({'error': 'Only admins can create users'}), 403
        if not app_config.SUPABASE_URL or not app_config.SUPABASE_SERVICE_ROLE_KEY:
            return jsonify({'error': 'Server not configured for creating users'}), 503
        data = request.get_json() or {}
        email = (data.get('email') or '').strip()
        password = data.get('password') or ''
        display_name = (data.get('display_name') or '').strip() or None
        requested_role = str(data.get('role') or 'user').strip().lower()
        if requested_role not in ('admin', 'user', 'superadmin', 'broker'):
            requested_role = 'user'
        if requested_role == 'superadmin' and role != 'superadmin':
            return jsonify({'error': 'Only superadmins can create superadmin users'}), 403
        if not email or not password:
            return jsonify({'error': 'Email and password are required'}), 400
        if len(password) < 6:
            return jsonify({'error': 'Password must be at least 6 characters'}), 400
        try:
            from supabase import create_client
            sb = create_client(app_config.SUPABASE_URL, app_config.SUPABASE_SERVICE_ROLE_KEY)
            resp = sb.auth.admin.create_user({
                'email': email,
                'password': password,
                'email_confirm': True,
            })
            uid = resp.user.id
            org_id = None
            try:
                creator_profile = get_profile(sb, user_id) or {}
                creator_org_id = creator_profile.get('org_id')
            except Exception:
                creator_org_id = None
            if role == 'superadmin':
                raw_org = data.get('org_id') if 'org_id' in data else data.get('orgId')
                raw_org = None if raw_org is None else str(raw_org).strip()
                org_id = raw_org or (str(creator_org_id) if creator_org_id else None)
            else:
                org_id = str(creator_org_id) if creator_org_id else None
                if not org_id:
                    return jsonify({'error': 'Your organization is not set. Ask a SuperAdmin to assign your org.'}), 403
            profile_row = {
                'user_id': uid,
                'role': requested_role,
                'email': getattr(resp.user, 'email', None) or email,
                'display_name': display_name,
                'org_id': org_id,
            }
            try:
                sb.table('profiles').upsert(profile_row, on_conflict='user_id').execute()
            except Exception as e:
                if 'org_id' in str(e).lower():
                    profile_row.pop('org_id', None)
                    sb.table('profiles').upsert(profile_row, on_conflict='user_id').execute()
                else:
                    raise
            return jsonify({'success': True, 'user': {'id': str(uid), 'email': resp.user.email, 'display_name': display_name}}), 201
        except Exception as e:
            err = str(e)
            if 'already registered' in err.lower() or 'already exists' in err.lower():
                return jsonify({'error': 'A user with this email already exists'}), 409
            return jsonify({'error': err or 'Failed to create user'}), 400

    @app.route('/api/admin/org-users', methods=['GET'])
    @require_admin
    def admin_list_org_users(user_id, role):
        """List all users in the admin's org, with role info."""
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        profile = get_profile(sb, user_id) or {}
        org_id = profile.get('org_id')
        if not org_id:
            return jsonify({'error': 'Your organization is not set'}), 403
        try:
            r = sb.table('profiles').select(
                'user_id, display_name, email, role, created_at'
            ).eq('org_id', org_id).order('created_at', desc=True).execute()
            users = []
            for row in (r.data or []):
                if not row.get('user_id') or not str(row['user_id']).strip():
                    continue
                o = dict(row)
                o['user_id'] = str(o['user_id'])
                o['is_self'] = str(o['user_id']) == str(user_id)
                # Admin can't manage other admins (but superadmin can)
                o['can_manage'] = (
                    role == 'superadmin'
                    or (o['role'] not in ('admin', 'superadmin') and not o['is_self'])
                )
                if o.get('created_at'):
                    o['created_at'] = str(o['created_at'])
                users.append(o)
            return jsonify(users)
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/admin/invite-user', methods=['POST'])
    @require_admin
    def admin_invite_user(user_id, role):
        """Send an email invite to a new user. display_name is required."""
        if not app_config.SUPABASE_URL or not app_config.SUPABASE_SERVICE_ROLE_KEY:
            return jsonify({'error': 'Server not configured for inviting users'}), 503
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        caller_profile = get_profile(sb, user_id) or {}
        org_id = caller_profile.get('org_id')
        if not org_id:
            return jsonify({'error': 'Your organization is not set'}), 403

        data = request.get_json() or {}
        email = (data.get('email') or '').strip().lower()
        display_name = (data.get('display_name') or '').strip()
        invite_role = str(data.get('role') or 'user').strip().lower()
        if invite_role not in ('admin', 'user', 'broker'):
            invite_role = 'user'
        if not email or '@' not in email:
            return jsonify({'error': 'Valid email is required'}), 400
        if not display_name:
            return jsonify({'error': 'Display name is required when inviting a user'}), 400

        # Check if user already exists in this org
        try:
            existing = sb.table('profiles').select('user_id, email').eq('email', email).limit(1).execute()
            if existing.data and len(existing.data) > 0:
                return jsonify({'error': 'A user with this email already exists'}), 409
        except Exception:
            pass

        try:
            from supabase import create_client
            admin_sb = create_client(app_config.SUPABASE_URL, app_config.SUPABASE_SERVICE_ROLE_KEY)

            # Use invite_user_by_email to send the invite email
            resp = admin_sb.auth.admin.invite_user_by_email(
                email,
                options={
                    'data': {
                        'display_name': display_name,
                    }
                }
            )
            new_uid = resp.user.id

            # Create the profile immediately so display_name is stored
            profile_row = {
                'user_id': str(new_uid),
                'role': invite_role,
                'email': email,
                'display_name': display_name,
                'org_id': str(org_id),
            }
            try:
                admin_sb.table('profiles').upsert(profile_row, on_conflict='user_id').execute()
            except Exception:
                pass

            # Record the invite
            try:
                admin_sb.table('user_invites').insert({
                    'org_id': str(org_id),
                    'invited_by': str(user_id),
                    'email': email,
                    'display_name': display_name,
                    'role': invite_role,
                    'status': 'pending',
                    'invited_user_id': str(new_uid),
                }).execute()
            except Exception:
                pass  # invite tracking is best-effort

            return jsonify({
                'success': True,
                'user': {
                    'id': str(new_uid),
                    'email': email,
                    'display_name': display_name,
                    'role': invite_role,
                }
            }), 201
        except Exception as e:
            err = str(e)
            if 'already registered' in err.lower() or 'already exists' in err.lower():
                return jsonify({'error': 'A user with this email already exists'}), 409
            return jsonify({'error': err or 'Failed to invite user'}), 400

    @app.route('/api/admin/users/<target_user_id>/details', methods=['PUT', 'PATCH'])
    @require_admin
    def admin_update_user_details(user_id, role, target_user_id):
        """Update display_name and/or email for a user in the org."""
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503

        ok, err_msg, status = _can_manage_target(sb, user_id, role, target_user_id)
        if not ok:
            return jsonify({'error': err_msg}), status

        data = request.get_json() or {}
        payload = {'updated_at': datetime.utcnow().isoformat()}
        if 'display_name' in data:
            dn = (data.get('display_name') or '').strip()
            if not dn:
                return jsonify({'error': 'Display name cannot be empty'}), 400
            payload['display_name'] = dn
        if 'email' in data:
            em = (data.get('email') or '').strip().lower()
            if not em or '@' not in em:
                return jsonify({'error': 'Valid email is required'}), 400
            payload['email'] = em

        if len(payload) <= 1:
            return jsonify({'error': 'Provide display_name and/or email'}), 400

        try:
            sb.table('profiles').update(payload).eq('user_id', target_user_id).execute()

            # Also update email in Supabase Auth if changed
            if 'email' in data and app_config.SUPABASE_SERVICE_ROLE_KEY:
                try:
                    from supabase import create_client
                    admin_sb = create_client(app_config.SUPABASE_URL, app_config.SUPABASE_SERVICE_ROLE_KEY)
                    admin_sb.auth.admin.update_user_by_id(
                        str(target_user_id),
                        {'email': payload['email']}
                    )
                except Exception:
                    pass

            # Update display_name in Supabase Auth user_metadata
            if 'display_name' in data and app_config.SUPABASE_SERVICE_ROLE_KEY:
                try:
                    from supabase import create_client
                    admin_sb = create_client(app_config.SUPABASE_URL, app_config.SUPABASE_SERVICE_ROLE_KEY)
                    admin_sb.auth.admin.update_user_by_id(
                        str(target_user_id),
                        {'user_metadata': {'display_name': payload['display_name']}}
                    )
                except Exception:
                    pass

            return jsonify({'success': True})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/admin/users/<target_user_id>/password', methods=['PUT'])
    @require_admin
    def admin_reset_user_password(user_id, role, target_user_id):
        """Reset password for a user in the org. Admin cannot reset another admin's password."""
        if not app_config.SUPABASE_URL or not app_config.SUPABASE_SERVICE_ROLE_KEY:
            return jsonify({'error': 'Server not configured'}), 503
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503

        ok, err_msg, status = _can_manage_target(sb, user_id, role, target_user_id)
        if not ok:
            return jsonify({'error': err_msg}), status

        data = request.get_json() or {}
        new_password = data.get('password') or ''
        if len(new_password) < 6:
            return jsonify({'error': 'Password must be at least 6 characters'}), 400

        try:
            from supabase import create_client
            admin_sb = create_client(app_config.SUPABASE_URL, app_config.SUPABASE_SERVICE_ROLE_KEY)
            admin_sb.auth.admin.update_user_by_id(
                str(target_user_id),
                {'password': new_password}
            )
            return jsonify({'success': True})
        except Exception as e:
            return jsonify({'error': str(e) or 'Failed to update password'}), 500

    @app.route('/api/admin/users/<target_user_id>/role', methods=['PUT'])
    @require_admin
    def admin_toggle_user_role(user_id, role, target_user_id):
        """Set a user's role among user/admin/broker. Admin cannot change another admin."""
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503

        data = request.get_json() or {}
        new_role = (data.get('role') or 'user').lower()
        if new_role not in ('admin', 'user', 'broker'):
            return jsonify({'error': 'Role must be admin, user, or broker'}), 400

        # Check target's current role
        target_profile = get_profile(sb, target_user_id) or {}
        target_current_role = target_profile.get('role', 'user')
        target_org = target_profile.get('org_id')

        caller_profile = get_profile(sb, user_id) or {}
        caller_org = caller_profile.get('org_id')

        if not caller_org:
            return jsonify({'error': 'Your organization is not set'}), 403
        if str(target_user_id) == str(user_id):
            return jsonify({'error': 'You cannot change your own role'}), 403

        if role != 'superadmin':
            if not target_org or str(target_org) != str(caller_org):
                return jsonify({'error': 'User is not in your organization'}), 403
            # Admin can only promote/demote non-admin users
            if target_current_role in ('admin', 'superadmin'):
                return jsonify({'error': 'You cannot modify another admin user'}), 403

        try:
            sb.table('profiles').update({
                'role': new_role,
                'updated_at': datetime.utcnow().isoformat()
            }).eq('user_id', target_user_id).execute()
            return jsonify({'success': True, 'new_role': new_role})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/admin/users/<target_user_id>', methods=['DELETE'])
    @require_admin
    def admin_delete_user(user_id, role, target_user_id):
        """Delete a user from the org. Admin can only delete normal users."""
        if not app_config.SUPABASE_URL or not app_config.SUPABASE_SERVICE_ROLE_KEY:
            return jsonify({'error': 'Server not configured'}), 503
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503

        ok, err_msg, status = _can_manage_target(sb, user_id, role, target_user_id)
        if not ok:
            return jsonify({'error': err_msg}), status

        try:
            from supabase import create_client
            admin_sb = create_client(app_config.SUPABASE_URL, app_config.SUPABASE_SERVICE_ROLE_KEY)
            # Delete the profile first
            admin_sb.table('profiles').delete().eq('user_id', target_user_id).execute()
            # Delete the auth user (cascades related data via FK)
            admin_sb.auth.admin.delete_user(str(target_user_id))
            return jsonify({'success': True})
        except Exception as e:
            return jsonify({'error': str(e) or 'Failed to delete user'}), 500

    @app.route('/api/admin/invites', methods=['GET'])
    @require_admin
    def admin_list_invites(user_id, role):
        """List all invites sent for the admin's org."""
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        org_id = _get_caller_org_id(sb, user_id)
        if not org_id:
            return jsonify({'error': 'Your organization is not set'}), 403
        try:
            r = sb.table('user_invites').select(
                'id, email, display_name, role, status, created_at'
            ).eq('org_id', org_id).order('created_at', desc=True).execute()
            out = []
            for row in (r.data or []):
                o = dict(row)
                if o.get('created_at'):
                    o['created_at'] = str(o['created_at'])
                out.append(o)
            return jsonify(out)
        except Exception as e:
            msg = str(e)
            if 'user_invites' in msg and ('does not exist' in msg.lower() or 'relation' in msg.lower()):
                return jsonify([])  # table not yet created, return empty
            return jsonify({'error': msg}), 500


