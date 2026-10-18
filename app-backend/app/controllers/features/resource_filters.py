from flask import jsonify, request

from app.core.auth import require_auth
from app.core.concurrency import run_parallel
from app.core.database import get_supabase
from app.services.access_policy import (
    _chunks,
    annotate_resource_rows_with_client_scope,
    client_group_resource_ids_for_admin,
    get_resource_client_scope,
    get_visible_client_options,
)
from app.services.dashboard_service import client_member_workspace_access, dashboard_snapshot, list_visible_panoramas
from app.services.workspace_service import (
    is_workspace_schema_missing,
    list_workspaces as ws_list_workspaces,
    serialize_workspace_row,
)


def _truthy(value):
    return str(value or '').strip().lower() in ('1', 'true', 'yes', 'on')


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

    @app.route('/api/dashboard', methods=['GET'])
    @require_auth
    def get_dashboard(user_id, role):
        """Everything the builder dashboard renders, in one round trip."""
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        return jsonify(dashboard_snapshot(sb, user_id, role))

    @app.route('/api/panoramas', methods=['GET'])
    @require_auth
    def get_panoramas(user_id, role):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        workspace_id = str(request.args.get('workspace_id') or '').strip() or None
        out = list_visible_panoramas(sb, user_id)
        if workspace_id:
            out = [p for p in out if p.get('workspace_id') == workspace_id]
        out = annotate_resource_rows_with_client_scope(sb, out, 'panorama')
        return jsonify(out)

    @app.route('/api/workspaces', methods=['GET'])
    @require_auth
    def list_workspaces(user_id, role):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        lightweight = _truthy(request.args.get('lightweight'))
        is_platform_admin = str(role or '').strip().lower() in ('admin', 'superadmin')
        try:
            include_empty_shared = _truthy(request.args.get('include_empty_shared'))

            def fetch_admin_all():
                if not is_platform_admin:
                    return []
                try:
                    return sb.table('workspaces').select('*' if not lightweight else 'id, user_id, org_id, name, created_at, updated_at, main_panorama_id').execute().data or []
                except Exception:
                    return []

            def best_effort(fn, default):
                def call():
                    try:
                        return fn()
                    except Exception:
                        return default
                return call

            # The four lookups are independent: one parallel stage instead of four. Only a failure
            # of the direct listing propagates (schema errors), as before.
            direct, client_group, member_access, admin_rows = run_parallel(
                lambda: ws_list_workspaces(sb, user_id, lightweight=lightweight, include_empty_shared=include_empty_shared),
                best_effort(lambda: client_group_resource_ids_for_admin(sb, user_id), (set(), set())),
                best_effort(lambda: client_member_workspace_access(sb, user_id), {}),
                fetch_admin_all,
                strict=True,
            )
            by_id = {str(row.get('id')): row for row in (direct or []) if row.get('id') is not None}
            client_ws_ids = set(client_group[0]) if client_group else set()
            member_access = member_access or {}
            client_ws_ids.update(member_access.keys())
            missing = [wid for wid in client_ws_ids if wid not in by_id]

            def fetch_missing():
                rows = []
                for chunk in _chunks(missing):
                    try:
                        rows.extend(sb.table('workspaces').select('*').in_('id', chunk).execute().data or [])
                    except Exception:
                        continue
                return rows

            # Every id that can end up in the response is known now, so the client-scope lookup
            # runs alongside the (rare) fetch of missing client projects.
            scope_ids = list(by_id) + missing + [str(row.get('id')) for row in admin_rows or [] if row.get('id') is not None]
            missing_rows, scope = run_parallel(
                fetch_missing,
                lambda: get_resource_client_scope(sb, workspace_ids=scope_ids).get('workspaces', {}),
            )
            for row in (missing_rows or []):
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
            # Platform admins (not client admins) get to see all projects in CRM Project tab
            # so they can centrally edit details and publish/make-live.
            for row in (admin_rows or []):
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

            rows = list(by_id.values())
            for row in rows:
                meta = (scope or {}).get(str(row.get('id') or '')) or {'client_ids': [], 'client_names': []}
                row['client_ids'] = meta.get('client_ids') or []
                row['client_names'] = meta.get('client_names') or []
            return jsonify(rows)
        except Exception as e:
            if is_workspace_schema_missing(e):
                return jsonify({'error': 'Project storage not configured. Please run db/schema.sql in Supabase SQL Editor.'}), 503
            return jsonify({'error': str(e)}), 500
