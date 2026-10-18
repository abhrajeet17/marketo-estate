from flask import jsonify, request

from app.core.auth import get_profile, require_auth
from app.core.concurrency import run_parallel
from app.core.database import get_supabase
from app.services.uam_reference_service import CLIENT_MEMBER_GROUP_ACCESS_ROLES
from app.services.panorama_service import get_panorama_with_access
from app.services.workspace_service import (
    can_manage_workspace,
    get_workspace_by_id,
    get_workspace_schema_error_response,
    is_workspace_schema_missing,
)

from .shared import _get_caller_org_id, _get_client_member_rows, _project_access_type_for_member_role


def _ws_error_response():
    body, status = get_workspace_schema_error_response()
    return jsonify(body), status


def register_uam_resource_access_routes(app):
    @app.route('/api/workspaces/<workspace_id>/access', methods=['GET'])
    @require_auth
    def get_workspace_access(user_id, role, workspace_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        try:
            workspace = get_workspace_by_id(sb, workspace_id)
        except Exception as e:
            if is_workspace_schema_missing(e):
                return _ws_error_response()
            return jsonify({'error': str(e)}), 500
        if not workspace:
            return jsonify({'error': 'Project not found'}), 404
        if not can_manage_workspace(sb, workspace, user_id, role):
            return jsonify({'error': 'Only owner or admin can list access'}), 403
        try:
            r = sb.table('workspace_access').select('*').eq('workspace_id', workspace_id).execute()
        except Exception as e:
            if is_workspace_schema_missing(e):
                return _ws_error_response()
            return jsonify({'error': str(e)}), 500
        out = []
        for row in (r.data or []):
            item = dict(row)
            if item.get('user_id'):
                item['user_id'] = str(item.get('user_id'))
            if item.get('workspace_id'):
                item['workspace_id'] = str(item.get('workspace_id'))
            if item.get('granted_by'):
                item['granted_by'] = str(item.get('granted_by'))
            if item.get('created_at'):
                item['created_at'] = str(item.get('created_at'))
            out.append(item)
        return jsonify(out)

    @app.route('/api/workspaces/<workspace_id>/access', methods=['POST'])
    @require_auth
    def grant_workspace_access(user_id, role, workspace_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        data = request.get_json(silent=True) or {}
        target_user_id = str(data.get('user_id') or '').strip()
        access_type = str(data.get('access_type') or 'viewer').strip().lower()
        if not target_user_id:
            return jsonify({'error': 'user_id is required'}), 400
        if access_type not in ('client', 'broker', 'viewer'):
            return jsonify({'error': 'access_type must be client, broker, or viewer'}), 400
        if str(target_user_id) == str(user_id):
            return jsonify({'error': 'Cannot grant access to yourself'}), 400
        try:
            workspace = get_workspace_by_id(sb, workspace_id)
        except Exception as e:
            if is_workspace_schema_missing(e):
                return _ws_error_response()
            return jsonify({'error': str(e)}), 500
        if not workspace:
            return jsonify({'error': 'Project not found'}), 404
        if not can_manage_workspace(sb, workspace, user_id, role):
            return jsonify({'error': 'Only owner or admin can grant access'}), 403
        workspace_org = workspace.get('org_id')
        if workspace_org and role != 'superadmin':
            caller = get_profile(sb, user_id) or {}
            target = get_profile(sb, target_user_id) or {}
            caller_org = caller.get('org_id')
            target_org = target.get('org_id')
            if not caller_org or not target_org:
                return jsonify({'error': 'User organization is not set. Ask a SuperAdmin to assign orgs.'}), 403
            if str(caller_org) != str(workspace_org) or str(target_org) != str(workspace_org):
                return jsonify({'error': 'You can only grant access to users in your organization'}), 403
        try:
            sb.table('workspace_access').upsert({
                'workspace_id': workspace_id,
                'user_id': target_user_id,
                'access_type': access_type,
                'granted_by': user_id,
            }, on_conflict='workspace_id,user_id').execute()
            return jsonify({'success': True}), 201
        except Exception as e:
            if is_workspace_schema_missing(e):
                return _ws_error_response()
            return jsonify({'error': str(e)}), 500

    @app.route('/api/workspaces/<workspace_id>/access/<target_user_id>', methods=['DELETE'])
    @require_auth
    def revoke_workspace_access(user_id, role, workspace_id, target_user_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        try:
            workspace = get_workspace_by_id(sb, workspace_id)
        except Exception as e:
            if is_workspace_schema_missing(e):
                return _ws_error_response()
            return jsonify({'error': str(e)}), 500
        if not workspace:
            return jsonify({'error': 'Project not found'}), 404
        if not can_manage_workspace(sb, workspace, user_id, role):
            return jsonify({'error': 'Only owner or admin can revoke access'}), 403
        try:
            sb.table('workspace_access').delete().eq('workspace_id', workspace_id).eq('user_id', target_user_id).execute()
            return jsonify({'success': True})
        except Exception as e:
            if is_workspace_schema_missing(e):
                return _ws_error_response()
            return jsonify({'error': str(e)}), 500

    def _managed_workspace(sb, workspace_id, user_id, role):
        """(workspace, error_response) for a project the caller may manage."""
        try:
            workspace = get_workspace_by_id(sb, workspace_id)
        except Exception as e:
            if is_workspace_schema_missing(e):
                return None, _ws_error_response()
            return None, (jsonify({'error': str(e)}), 500)
        if not workspace:
            return None, (jsonify({'error': 'Project not found'}), 404)
        if not can_manage_workspace(sb, workspace, user_id, role):
            return None, (jsonify({'error': 'Only the project owner or an admin can manage access'}), 403)
        return workspace, None

    def _organization_in_scope(sb, workspace, client_id, user_id):
        """The client organization row when it belongs to the project's builder org."""
        org_id = workspace.get('org_id') or _get_caller_org_id(sb, user_id)
        rows = sb.table('clients').select('id, name').eq('id', str(client_id)).eq('org_id', str(org_id)).limit(1).execute().data
        return rows[0] if rows else None

    @app.route('/api/workspaces/<workspace_id>/organizations', methods=['GET'])
    @require_auth
    def list_workspace_organizations(user_id, role, workspace_id):
        """Every client organization of the project's builder org, with its current access to the project."""
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        workspace, err = _managed_workspace(sb, workspace_id, user_id, role)
        if err:
            return err
        org_id = workspace.get('org_id') or _get_caller_org_id(sb, user_id)
        if not org_id:
            return jsonify({'error': 'Organization not set'}), 403
        try:
            clients, members, grants = run_parallel(
                lambda: sb.table('clients').select('id, name, description').eq('org_id', str(org_id)).order('name').execute().data or [],
                lambda: sb.table('client_members').select('client_id, clients!inner(org_id)').eq('clients.org_id', str(org_id)).execute().data or [],
                lambda: sb.table('workspace_access').select('access_type, client_members!inner(client_id)')
                    .eq('workspace_id', str(workspace_id)).execute().data or [],
                strict=True,
            )
        except Exception as e:
            return jsonify({'error': str(e)}), 500
        member_counts = {}
        for row in members:
            key = str(row.get('client_id'))
            member_counts[key] = member_counts.get(key, 0) + 1
        # Broker rows are always 'broker', so the organization's level is what its other members hold.
        # Members granted one by one (the old per-user flow) show up as partial access.
        access, granted = {}, {}
        for row in grants:
            key = str((row.get('client_members') or {}).get('client_id') or '')
            if not key:
                continue
            granted[key] = granted.get(key, 0) + 1
            if row.get('access_type') in ('client', 'viewer') and access.get(key) != 'client':
                access[key] = row.get('access_type')
        out = []
        for c in clients:
            key = str(c['id'])
            count = member_counts.get(key, 0)
            level = access.get(key) if granted.get(key, 0) >= count else None
            out.append({
                'id': key,
                'name': c.get('name') or '',
                'description': c.get('description') or '',
                'member_count': count,
                'granted_count': granted.get(key, 0),
                'access_type': level,
            })
        return jsonify(out)

    @app.route('/api/workspaces/<workspace_id>/organizations/<client_id>', methods=['PUT'])
    @require_auth
    def grant_workspace_organization(user_id, role, workspace_id, client_id):
        """Give every member of a client organization access to the project (new members inherit it on joining)."""
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        workspace, err = _managed_workspace(sb, workspace_id, user_id, role)
        if err:
            return err
        access_type = str((request.get_json(silent=True) or {}).get('access_type') or 'client').strip().lower()
        if access_type not in ('client', 'viewer'):
            return jsonify({'error': 'access_type must be client or viewer'}), 400
        try:
            if not _organization_in_scope(sb, workspace, client_id, user_id):
                return jsonify({'error': 'Organization not found'}), 404
            members = [
                m for m in _get_client_member_rows(sb, client_id)
                if m.get('id') and m.get('user_id') and m.get('member_role') in CLIENT_MEMBER_GROUP_ACCESS_ROLES
            ]
            if not members:
                return jsonify({'error': 'This organization has no members yet. Add members in User Management first.'}), 400
            sb.table('workspace_access').upsert([
                {
                    'workspace_id': str(workspace_id),
                    'user_id': m['user_id'],
                    'access_type': _project_access_type_for_member_role(access_type, m.get('member_role')),
                    'granted_by': str(user_id),
                    'client_member_id': m['id'],
                }
                for m in members
            ], on_conflict='workspace_id,user_id').execute()
            return jsonify({'success': True, 'member_count': len(members), 'access_type': access_type})
        except Exception as e:
            if is_workspace_schema_missing(e):
                return _ws_error_response()
            return jsonify({'error': str(e)}), 500

    @app.route('/api/workspaces/<workspace_id>/organizations/<client_id>', methods=['DELETE'])
    @require_auth
    def revoke_workspace_organization(user_id, role, workspace_id, client_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        workspace, err = _managed_workspace(sb, workspace_id, user_id, role)
        if err:
            return err
        try:
            if not _organization_in_scope(sb, workspace, client_id, user_id):
                return jsonify({'error': 'Organization not found'}), 404
            member_ids = [m['id'] for m in _get_client_member_rows(sb, client_id) if m.get('id')]
            if member_ids:
                sb.table('workspace_access').delete().eq('workspace_id', str(workspace_id)).in_('client_member_id', member_ids).execute()
            return jsonify({'success': True})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/panoramas/<int:panorama_id>/access', methods=['GET'])
    @require_auth
    def get_panorama_access(user_id, role, panorama_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        panorama, access_type = get_panorama_with_access(sb, panorama_id, user_id)
        if not panorama:
            return jsonify({'error': 'Panorama not found'}), 404
        if access_type != 'owner' and role not in ('admin', 'superadmin'):
            return jsonify({'error': 'Only owner or admin can list access'}), 403
        try:
            r = sb.table('panorama_access').select('*').eq('panorama_id', panorama_id).execute()
            for row in (r.data or []):
                row['user_id'] = str(row['user_id'])
                if row.get('granted_by'):
                    row['granted_by'] = str(row['granted_by'])
            return jsonify(r.data or [])
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/panoramas/<int:panorama_id>/access', methods=['POST'])
    @require_auth
    def grant_panorama_access(user_id, role, panorama_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        panorama, access_type = get_panorama_with_access(sb, panorama_id, user_id)
        if not panorama:
            return jsonify({'error': 'Panorama not found'}), 404
        if access_type != 'owner' and role not in ('admin', 'superadmin'):
            return jsonify({'error': 'Only owner or admin can grant access'}), 403
        data = request.get_json() or {}
        target_user_id = (data.get('user_id') or '').strip()
        at = (data.get('access_type') or 'viewer').lower()
        if at not in ('client', 'broker', 'viewer'):
            at = 'viewer'
        if not target_user_id:
            return jsonify({'error': 'user_id is required'}), 400
        if target_user_id == user_id:
            return jsonify({'error': 'Cannot grant access to yourself'}), 400
        try:
            panorama_org_id = panorama.get('org_id') if isinstance(panorama, dict) else None
        except Exception:
            panorama_org_id = None
        if panorama_org_id and role != 'superadmin':
            try:
                caller = sb.table('profiles').select('org_id').eq('user_id', user_id).limit(1).execute()
                target = sb.table('profiles').select('org_id').eq('user_id', target_user_id).limit(1).execute()
                caller_org = (caller.data or [{}])[0].get('org_id') if hasattr(caller, 'data') else None
                target_org = (target.data or [{}])[0].get('org_id') if hasattr(target, 'data') else None
            except Exception as e:
                msg = str(e).lower()
                if 'org_id' in msg and ('does not exist' in msg or 'column' in msg):
                    return jsonify({'error': 'org_id column missing. Run db/schema.sql in Supabase SQL Editor.'}), 503
                caller_org = None
                target_org = None
            if not caller_org or not target_org:
                return jsonify({'error': 'User organization is not set. Ask a SuperAdmin to assign orgs.'}), 403
            if str(caller_org) != str(panorama_org_id) or str(target_org) != str(panorama_org_id):
                return jsonify({'error': 'You can only grant access to users in your organization'}), 403
        try:
            sb.table('panorama_access').upsert({
                'panorama_id': panorama_id,
                'user_id': target_user_id,
                'access_type': at,
                'granted_by': user_id,
            }, on_conflict='panorama_id,user_id').execute()
            return jsonify({'success': True}), 201
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/panoramas/<int:panorama_id>/access/<target_user_id>', methods=['DELETE'])
    @require_auth
    def revoke_panorama_access(user_id, role, panorama_id, target_user_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        panorama, access_type = get_panorama_with_access(sb, panorama_id, user_id)
        if not panorama:
            return jsonify({'error': 'Panorama not found'}), 404
        if access_type != 'owner' and role not in ('admin', 'superadmin'):
            return jsonify({'error': 'Only owner or admin can revoke access'}), 403
        try:
            sb.table('panorama_access').delete().eq('panorama_id', panorama_id).eq('user_id', target_user_id).execute()
            return jsonify({'success': True})
        except Exception as e:
            return jsonify({'error': str(e)}), 500


