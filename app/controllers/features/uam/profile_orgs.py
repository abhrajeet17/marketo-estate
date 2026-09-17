from datetime import datetime

from flask import jsonify, request

from app import config as app_config
from app.core.auth import get_profile, require_admin, require_auth, require_superadmin
from app.core.database import get_supabase
from app.services.org_service import slugify_org_name
from app.services.uam_reference_service import user_is_broker, user_is_client_admin


def register_uam_profile_org_routes(app):
    @app.route('/api/profile/me', methods=['PUT', 'PATCH'])
    @require_auth
    def update_my_profile(user_id, role):
        data = request.get_json() or {}
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        if 'display_name' not in data and 'email' not in data:
            return jsonify({'error': 'Provide display_name and/or email'}), 400
        display_name = (data.get('display_name') or '').strip() or None if 'display_name' in data else None
        email = (data.get('email') or '').strip() or None if 'email' in data else None
        updated_at = datetime.utcnow().isoformat()
        existing = get_profile(sb, user_id)
        payload = {'updated_at': updated_at}
        if 'display_name' in data:
            payload['display_name'] = display_name
        if 'email' in data:
            payload['email'] = email
        try:
            if existing:
                sb.table('profiles').update(payload).eq('user_id', user_id).execute()
            else:
                full = {
                    'user_id': user_id,
                    'role': (existing.get('role') if existing else 'user'),
                    'updated_at': updated_at,
                }
                if 'display_name' in data:
                    full['display_name'] = display_name
                if 'email' in data:
                    full['email'] = email
                sb.table('profiles').upsert(full, on_conflict='user_id').execute()
            return jsonify({'success': True})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/org/me', methods=['GET'])
    @require_auth
    def get_my_org(user_id, role):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        profile = get_profile(sb, user_id) or {}
        org_id = profile.get('org_id')
        org = None
        if org_id:
            try:
                r = sb.table('organizations').select('id, name, accent_color, created_at, updated_at').eq('id', org_id).limit(1).execute()
                if r.data and len(r.data) > 0:
                    org = dict(r.data[0])
                    for k in ('created_at', 'updated_at'):
                        if k in org and org[k]:
                            org[k] = str(org[k])
            except Exception as e:
                msg = str(e)
                if 'organizations' in msg and ('does not exist' in msg.lower() or 'relation' in msg.lower()):
                    return jsonify({'error': 'organizations table not found. Run db/schema.sql in Supabase SQL Editor.'}), 503
            if org and org.get('name'):
                org['slug'] = slugify_org_name(org.get('name'))
        profile_role = str(profile.get('role') or role or 'user')
        is_broker = user_is_broker(sb, user_id, profile_role)
        is_client_admin = user_is_client_admin(sb, user_id)
        out_profile = {
            'user_id': str(profile.get('user_id') or user_id),
            'role': profile_role,
            'org_id': str(org_id) if org_id else None,
            'display_name': profile.get('display_name'),
            'email': profile.get('email'),
            'is_broker': is_broker,
            'is_client_admin': is_client_admin,
        }
        return jsonify({
            'profile': out_profile,
            'org': org,
            'post_login_path': '/customer-dashboard' if is_broker or is_client_admin else None,
        })

    @app.route('/api/orgs', methods=['GET'])
    @require_superadmin
    def list_orgs(user_id, role):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        try:
            r = sb.table('organizations').select('id, name, accent_color, created_at, updated_at').order('created_at', desc=False).execute()
            out = []
            for row in (r.data or []):
                o = dict(row)
                for k in ('created_at', 'updated_at'):
                    if k in o and o[k]:
                        o[k] = str(o[k])
                out.append(o)
            return jsonify(out)
        except Exception as e:
            msg = str(e)
            if 'organizations' in msg and ('does not exist' in msg.lower() or 'relation' in msg.lower()):
                return jsonify({'error': 'organizations table not found. Run db/schema.sql in Supabase SQL Editor.'}), 503
            return jsonify({'error': msg}), 500

    @app.route('/api/orgs', methods=['POST'])
    @require_superadmin
    def create_org(user_id, role):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        data = request.get_json(silent=True) or {}
        name = str(data.get('name') or '').strip()
        accent = str(data.get('accent_color') or '').strip() or '#c9a962'
        if not name:
            return jsonify({'error': 'name is required'}), 400
        if len(name) > 120:
            return jsonify({'error': 'name must be 120 characters or fewer'}), 400
        if accent and (not accent.startswith('#') or len(accent) not in (4, 7)):
            return jsonify({'error': 'accent_color must be a hex value like #c9a962'}), 400
        now = datetime.utcnow().isoformat()
        try:
            r = sb.table('organizations').insert({
                'name': name,
                'accent_color': accent,
                'created_at': now,
                'updated_at': now,
            }).execute()
            row = (r.data or [None])[0]
            return jsonify({'success': True, 'org': row}), 201
        except Exception as e:
            msg = str(e)
            if 'organizations' in msg and ('does not exist' in msg.lower() or 'relation' in msg.lower()):
                return jsonify({'error': 'organizations table not found. Run db/schema.sql in Supabase SQL Editor.'}), 503
            if 'duplicate' in msg.lower() or 'already exists' in msg.lower() or 'unique' in msg.lower():
                return jsonify({'error': 'Organization name already exists'}), 409
            return jsonify({'error': msg}), 500

    @app.route('/api/orgs/<org_id>', methods=['PATCH', 'PUT'])
    @require_superadmin
    def update_org(user_id, role, org_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        data = request.get_json(silent=True) or {}
        upd = {}
        if 'name' in data:
            name = str(data.get('name') or '').strip()
            if not name:
                return jsonify({'error': 'name cannot be empty'}), 400
            if len(name) > 120:
                return jsonify({'error': 'name must be 120 characters or fewer'}), 400
            upd['name'] = name
        if 'accent_color' in data:
            accent = str(data.get('accent_color') or '').strip()
            if accent and (not accent.startswith('#') or len(accent) not in (4, 7)):
                return jsonify({'error': 'accent_color must be a hex value like #c9a962'}), 400
            upd['accent_color'] = accent or '#c9a962'
        if not upd:
            return jsonify({'error': 'No fields to update'}), 400
        upd['updated_at'] = datetime.utcnow().isoformat()
        try:
            r = sb.table('organizations').update(upd).eq('id', org_id).execute()
            row = (r.data or [None])[0] if hasattr(r, 'data') else None
            return jsonify({'success': True, 'org': row or {**upd, 'id': org_id}})
        except Exception as e:
            msg = str(e)
            if 'organizations' in msg and ('does not exist' in msg.lower() or 'relation' in msg.lower()):
                return jsonify({'error': 'organizations table not found. Run db/schema.sql in Supabase SQL Editor.'}), 503
            return jsonify({'error': msg}), 500

    @app.route('/api/profiles/<target_user_id>', methods=['PATCH'])
    @require_auth
    def superadmin_update_profile(user_id, role, target_user_id):
        if role != 'superadmin':
            return jsonify({'error': 'Forbidden'}), 403
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        data = request.get_json(silent=True) or {}
        upd = {}
        if 'role' in data:
            new_role = str(data.get('role') or '').strip().lower()
            if new_role not in ('superadmin', 'admin', 'user', 'broker'):
                return jsonify({'error': 'role must be superadmin, admin, user, or broker'}), 400
            upd['role'] = new_role
        org_id = None
        if 'org_id' in data or 'orgId' in data:
            raw_org = data.get('org_id') if 'org_id' in data else data.get('orgId')
            raw_org = None if raw_org is None else str(raw_org).strip()
            org_id = raw_org or None
            upd['org_id'] = org_id
        if not upd:
            return jsonify({'error': 'No fields to update'}), 400
        upd['updated_at'] = datetime.utcnow().isoformat()
        try:
            sb.table('profiles').update(upd).eq('user_id', target_user_id).execute()
        except Exception as e:
            msg = str(e)
            if 'profiles' in msg and ('does not exist' in msg.lower() or 'relation' in msg.lower()):
                return jsonify({'error': 'profiles table not found'}), 503
            if 'org_id' in msg.lower() and ('does not exist' in msg.lower() or 'column' in msg.lower()):
                return jsonify({'error': 'org_id column missing. Run db/schema.sql in Supabase SQL Editor.'}), 503
            if 'organizations' in msg and ('does not exist' in msg.lower() or 'relation' in msg.lower()):
                return jsonify({'error': 'organizations table not found. Run db/schema.sql in Supabase SQL Editor.'}), 503
            return jsonify({'error': msg}), 500
        if 'org_id' in upd:
            new_org_id = upd.get('org_id')

            def _batches(values, size=200):
                values = list(values or [])
                for i in range(0, len(values), size):
                    yield values[i:i + size]

            try:
                sb.table('panoramas').update({'org_id': new_org_id, 'updated_at': datetime.utcnow().isoformat()}).eq('user_id', target_user_id).execute()
            except Exception:
                pass
            try:
                shared = sb.table('panorama_access').select('panorama_id').eq('user_id', target_user_id).execute()
                shared_ids = [row.get('panorama_id') for row in (shared.data or []) if row.get('panorama_id') is not None]
                bad_shared_ids = []
                if shared_ids:
                    if new_org_id:
                        panos = []
                        for batch in _batches(shared_ids):
                            r = sb.table('panoramas').select('id, org_id').in_('id', batch).execute()
                            panos.extend(r.data or [])
                        for p in panos:
                            pid = p.get('id')
                            if pid is None:
                                continue
                            if str(p.get('org_id') or '') != str(new_org_id):
                                bad_shared_ids.append(pid)
                    else:
                        bad_shared_ids = list(shared_ids)
                for batch in _batches(bad_shared_ids):
                    sb.table('panorama_access').delete().eq('user_id', target_user_id).in_('panorama_id', batch).execute()
            except Exception:
                pass
            try:
                owned = sb.table('panoramas').select('id').eq('user_id', target_user_id).execute()
                owned_ids = [row.get('id') for row in (owned.data or []) if row.get('id') is not None]
                if owned_ids:
                    if not new_org_id:
                        for batch in _batches(owned_ids):
                            sb.table('panorama_access').delete().in_('panorama_id', batch).execute()
                    else:
                        shared_user_ids = set()
                        for batch in _batches(owned_ids):
                            r = sb.table('panorama_access').select('user_id').in_('panorama_id', batch).execute()
                            for row in (r.data or []):
                                uid = row.get('user_id')
                                if uid:
                                    shared_user_ids.add(str(uid))
                        if shared_user_ids:
                            profs = []
                            for batch in _batches(list(shared_user_ids)):
                                r = sb.table('profiles').select('user_id, org_id').in_('user_id', batch).execute()
                                profs.extend(r.data or [])
                            user_to_org = {str(row.get('user_id')): row.get('org_id') for row in profs if row.get('user_id')}
                            outside_users = [uid for uid in shared_user_ids if str(user_to_org.get(uid) or '') != str(new_org_id)]
                            for outside_uid in outside_users:
                                for batch in _batches(owned_ids):
                                    sb.table('panorama_access').delete().eq('user_id', outside_uid).in_('panorama_id', batch).execute()
            except Exception:
                pass
        return jsonify({'success': True})

    @app.route('/api/profiles', methods=['GET'])
    @require_auth
    def list_profiles(user_id, role):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        org_filter = (request.args.get('org_id') or request.args.get('orgId') or '').strip() or None
        caller_profile = get_profile(sb, user_id) or {}
        caller_org_id = caller_profile.get('org_id')
        try:
            query = sb.table('profiles').select('user_id, role, display_name, email, created_at, org_id')
            if role != 'superadmin':
                if not caller_org_id:
                    return jsonify({'error': 'Your organization is not set. Ask a SuperAdmin to assign your org.'}), 403
                query = query.eq('org_id', caller_org_id)
            elif org_filter:
                query = query.eq('org_id', org_filter)
            r = query.order('created_at', desc=True).execute()
            out = []
            for row in (r.data or []):
                o = dict(row)
                o['user_id'] = str(o['user_id'])
                if o.get('created_at'):
                    o['created_at'] = str(o['created_at'])
                if 'org_id' in o and o.get('org_id'):
                    o['org_id'] = str(o['org_id'])
                out.append(o)
            return jsonify(out)
        except Exception as e:
            msg = str(e)
            if 'org_id' in msg.lower() and ('does not exist' in msg.lower() or 'column' in msg.lower()):
                return jsonify({'error': 'org_id column missing. Run db/schema.sql in Supabase SQL Editor.'}), 503
            return jsonify({'error': msg}), 500

    @app.route('/api/profiles/<user_id>/role', methods=['PUT'])
    @require_admin
    def set_profile_role(admin_id, role, user_id):
        data = request.get_json() or {}
        new_role = (data.get('role') or 'user').lower()
        if new_role not in ('superadmin', 'admin', 'user', 'broker'):
            return jsonify({'error': 'role must be superadmin, admin, user, or broker'}), 400
        if new_role == 'superadmin' and role != 'superadmin':
            return jsonify({'error': 'Only superadmins can grant superadmin role'}), 403
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        try:
            if role != 'superadmin':
                caller = get_profile(sb, admin_id) or {}
                caller_org = caller.get('org_id')
                target = get_profile(sb, user_id) or {}
                target_org = target.get('org_id')
                if not caller_org or not target_org or str(caller_org) != str(target_org):
                    return jsonify({'error': 'You can only manage users in your organization'}), 403
            sb.table('profiles').update({'role': new_role, 'updated_at': datetime.utcnow().isoformat()}).eq('user_id', user_id).execute()
            return jsonify({'success': True})
        except Exception as e:
            msg = str(e)
            if 'org_id' in msg.lower() and ('does not exist' in msg.lower() or 'column' in msg.lower()):
                return jsonify({'error': 'org_id column missing. Run db/schema.sql in Supabase SQL Editor.'}), 503
            if 'role' in msg.lower() and 'check' in msg.lower():
                return jsonify({'error': 'profiles.role constraint does not allow this value. Run db/schema.sql in Supabase SQL Editor.'}), 503
            return jsonify({'error': msg}), 500


