from flask import jsonify, request

from app.core.auth import get_profile, require_auth
from app.core.database import get_supabase
from app.services.panorama_service import get_panorama_with_access
from app.services.workspace_service import (
    can_manage_workspace,
    get_workspace_by_id,
    get_workspace_schema_error_response,
    is_workspace_schema_missing,
)


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


