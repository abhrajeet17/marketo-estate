from flask import jsonify, request

from app.core.auth import require_auth
from app.core.database import get_supabase
from app.services.access_policy import (
    annotate_resource_rows_with_client_scope,
    client_group_resource_ids_for_admin,
    get_client_memberships,
    get_visible_client_options,
)
from app.services.panorama_service import list_panoramas_for_user
from app.services.workspace_service import (
    is_workspace_schema_missing,
    list_workspaces as ws_list_workspaces,
    serialize_workspace_row,
)


def _truthy(value):
    return str(value or '').strip().lower() in ('1', 'true', 'yes', 'on')


def _chunks(values, size=200):
    for i in range(0, len(values), size):
        yield values[i:i + size]


def _client_member_workspace_access(sb, user_id):
    try:
        member_ids = [
            row.get('id')
            for row in get_client_memberships(sb, user_id)
            if row.get('id')
        ]
    except Exception:
        member_ids = []
    if not member_ids:
        return {}

    out = {}
    for chunk in _chunks(member_ids):
        try:
            rows = (
                sb.table('workspace_access')
                .select('workspace_id, access_type')
                .in_('client_member_id', chunk)
                .execute()
                .data or []
            )
        except Exception:
            continue
        for row in rows:
            wsid = row.get('workspace_id')
            if wsid:
                out[str(wsid)] = str(row.get('access_type') or 'viewer')
    return out


def register_resource_filters_routes(app):
    @app.route('/api/access/client-options', methods=['GET'])
    @require_auth
    def list_access_client_options(user_id, role):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        try:
            return jsonify(get_visible_client_options(sb, user_id, role))
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/panoramas', methods=['GET'])
    @require_auth
    def get_panoramas(user_id, role):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        workspace_id = str(request.args.get('workspace_id') or '').strip() or None
        items = list_panoramas_for_user(sb, user_id)
        by_id = {}
        for p in items:
            pid = p.get('id')
            if pid is None:
                continue
            by_id[str(pid)] = dict(p)
        try:
            _ws_ids, client_pano_ids = client_group_resource_ids_for_admin(sb, user_id)
            missing = [pid for pid in client_pano_ids if str(pid) not in by_id]
            for chunk in _chunks(missing):
                r = (
                    sb.table('panoramas')
                    .select('id, user_id, workspace_id, name, filename, created_at, updated_at, metadata')
                    .in_('id', chunk)
                    .execute()
                )
                for row in (r.data or []):
                    rid = row.get('id')
                    if rid is not None:
                        by_id[str(rid)] = dict(row)
        except Exception:
            pass
        out = []
        for p in by_id.values():
            o = dict(p)
            o.pop('image_data', None)
            o.pop('image_content_type', None)
            for k in ('created_at', 'updated_at'):
                if k in o and o[k]:
                    o[k] = str(o[k])
            if 'user_id' in o:
                o['user_id'] = str(o['user_id'])
            if 'workspace_id' in o and o.get('workspace_id'):
                o['workspace_id'] = str(o['workspace_id'])
            if workspace_id and str(o.get('workspace_id') or '') != workspace_id:
                continue
            out.append(o)
        out = annotate_resource_rows_with_client_scope(sb, out, 'panorama')
        return jsonify(out)

    @app.route('/api/workspaces', methods=['GET'])
    @require_auth
    def list_workspaces(user_id, role):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        lightweight = _truthy(request.args.get('lightweight'))
        try:
            include_empty_shared = _truthy(request.args.get('include_empty_shared'))
            direct = ws_list_workspaces(sb, user_id, lightweight=lightweight, include_empty_shared=include_empty_shared)
            by_id = {str(row.get('id')): row for row in (direct or []) if row.get('id') is not None}
            try:
                client_ws_ids, _client_pano_ids = client_group_resource_ids_for_admin(sb, user_id)
            except Exception:
                client_ws_ids = set()
            try:
                member_access = _client_member_workspace_access(sb, user_id)
            except Exception:
                member_access = {}
            client_ws_ids.update(member_access.keys())
            missing = [wid for wid in client_ws_ids if wid not in by_id]
            for chunk in _chunks(missing):
                try:
                    wr = sb.table('workspaces').select('*').in_('id', chunk).execute()
                except Exception:
                    continue
                for row in (wr.data or []):
                    wid = row.get('id')
                    if wid is None:
                        continue
                    access_type = member_access.get(str(wid), 'client')
                    if lightweight:
                        by_id[str(wid)] = {
                            'id': str(wid),
                            'name': row.get('name') or f'Project #{wid}',
                            'access_type': access_type,
                        }
                    else:
                        by_id[str(wid)] = serialize_workspace_row(row, access_type)
            out = annotate_resource_rows_with_client_scope(sb, list(by_id.values()), 'workspace')

            # Platform admins (not client admins) get to see all projects in CRM Project tab
            # so they can centrally edit details and publish/make-live.
            if str(role or '').strip().lower() in ('admin', 'superadmin'):
                try:
                    admin_all = sb.table('workspaces').select('*' if not lightweight else 'id, user_id, org_id, name, created_at, updated_at, main_panorama_id').execute()
                    for row in (admin_all.data or []):
                        wid = str(row.get('id'))
                        if wid not in by_id:
                            acc = 'admin'
                            if lightweight:
                                by_id[wid] = {
                                    'id': wid,
                                    'name': row.get('name') or f'Project #{wid}',
                                    'access_type': acc,
                                }
                            else:
                                by_id[wid] = serialize_workspace_row(row, acc)
                except Exception:
                    pass
                out = annotate_resource_rows_with_client_scope(sb, list(by_id.values()), 'workspace')

            return jsonify(out)
        except Exception as e:
            if is_workspace_schema_missing(e):
                return jsonify({'error': 'Project storage not configured. Please run db/schema.sql in Supabase SQL Editor.'}), 503
            return jsonify({'error': str(e)}), 500
