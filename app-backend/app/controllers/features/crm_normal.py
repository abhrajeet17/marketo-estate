from flask import jsonify, request

from app.core.auth import get_profile, require_auth
from app.core.database import get_supabase
from app.controllers.features.crm_pagination import (
    crm_page_payload,
    crm_parse_page_args,
    crm_parse_sort_args,
)


def _sanitize_search_token(raw):
    """Strip PostgREST filter metacharacters before interpolating into or_()."""
    return (
        str(raw or '')
        .replace('%', '')
        .replace('(', '')
        .replace(')', '')
        .replace(',', '')
        .strip()
    )


def _coerce_coordinate(raw, lo, hi):
    """Numeric lat/lng or None — garbage must not reach the numeric column."""
    if raw is None or str(raw).strip() == '':
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value != value or value < lo or value > hi:
        return None
    return value


def _org_owner_ids_for_admin(sb, user_id):
    """Owner user ids inside an org admin's own org, or None when unknown."""
    try:
        org_id = (get_profile(sb, user_id) or {}).get('org_id')
        if not org_id:
            return None
        rows = sb.table('profiles').select('user_id').eq('org_id', org_id).execute().data or []
        out = [str(r.get('user_id')) for r in rows if r.get('user_id')]
        return out or None
    except Exception:
        return None

NORMAL_PROJECT_SORT_FIELDS = ('name', 'location', 'project_type', 'created_at', 'updated_at')
# 'area' and 'price' are text columns here, so a database sort would compare
# them lexicographically; they stay non-sortable in normal mode.
NORMAL_PLOT_SORT_FIELDS = ('name', 'status', 'description', 'project_name')


_NORMAL_PROJECT_SELECT_EXT = (
    'id, owner_user_id, name, location, description, project_type, '
    'builder_name, location_address, location_city, location_state, '
    'google_maps_link, location_lat, location_lng, rera_registration, total_area, '
    'launch_date, possession_date, contact_phone, contact_email, amenities, custom_fields, '
    'created_at, updated_at'
)


def register_crm_normal_routes(app):
    @app.route('/api/crm/normal-projects', methods=['GET'])
    @require_auth
    def list_crm_normal_projects(user_id, role):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        page, limit, offset = crm_parse_page_args(default_limit=10, max_limit=100)
        sort_field, sort_desc = crm_parse_sort_args(
            NORMAL_PROJECT_SORT_FIELDS, default_field='updated_at', default_desc=True
        )
        q = _sanitize_search_token(request.args.get('q')).lower()
        role_key = str(role or '').strip().lower()
        # superadmin: global. admin: rows owned by their own org's users, never
        # other orgs'. everyone else: own rows only.
        org_owner_ids = _org_owner_ids_for_admin(sb, user_id) if role_key == 'admin' else None
        base_select = _NORMAL_PROJECT_SELECT_EXT

        def _scoped_query(select_cols):
            query = sb.table('crm_normal_projects').select(select_cols, count='exact')
            if role_key == 'superadmin':
                pass
            elif role_key == 'admin' and org_owner_ids:
                query = query.in_('owner_user_id', org_owner_ids)
            else:
                query = query.eq('owner_user_id', str(user_id))
            return query.order(sort_field, desc=sort_desc)

        query = _scoped_query(base_select)
        if q:
            query = query.or_(f'name.ilike.%{q}%,location.ilike.%{q}%')
        try:
            result = query.range(offset, offset + limit - 1).execute()
        except Exception as e:
            msg = str(e or '')
            if 'column' in msg.lower() and 'does not exist' in msg.lower():
                fallback_query = _scoped_query('id, owner_user_id, name, location, description, project_type, created_at, updated_at')
                if q:
                    fallback_query = fallback_query.or_(f'name.ilike.%{q}%,location.ilike.%{q}%')
                result = fallback_query.range(offset, offset + limit - 1).execute()
            else:
                raise
        items = result.data or []
        for item in items:
            item['crm_mode'] = 'normal'
        total = int(result.count or 0)
        return jsonify(crm_page_payload(items, total, page, limit))

    @app.route('/api/crm/normal-projects', methods=['POST'])
    @require_auth
    def create_crm_normal_project(user_id, role):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        data = request.get_json(silent=True) or {}
        name = str(data.get('name') or '').strip()
        if not name:
            return jsonify({'error': 'Project name is required'}), 400
        row = {
            'owner_user_id': str(user_id),
            'name': name,
            'location': str(data.get('location') or '').strip() or None,
            'description': str(data.get('description') or '').strip() or None,
            'project_type': str(data.get('project_type') or '').strip() or 'residential',
            'builder_name': str(data.get('builder_name') or '').strip() or None,
            'location_address': str(data.get('location_address') or data.get('location') or '').strip() or None,
            'location_city': str(data.get('location_city') or '').strip() or None,
            'location_state': str(data.get('location_state') or '').strip() or None,
            'google_maps_link': str(data.get('google_maps_link') or '').strip() or None,
            'location_lat': _coerce_coordinate(data.get('location_lat'), -90, 90),
            'location_lng': _coerce_coordinate(data.get('location_lng'), -180, 180),
            'rera_registration': str(data.get('rera_registration') or '').strip() or None,
            'total_area': str(data.get('total_area') or '').strip() or None,
            'launch_date': data.get('launch_date') or None,
            'possession_date': str(data.get('possession_date') or '').strip() or None,
            'contact_phone': str(data.get('contact_phone') or '').strip() or None,
            'contact_email': str(data.get('contact_email') or '').strip() or None,
            'amenities': data.get('amenities') if isinstance(data.get('amenities'), list) else [],
            'custom_fields': data.get('custom_fields') if isinstance(data.get('custom_fields'), dict) else {},
        }
        try:
            created = sb.table('crm_normal_projects').insert(row).execute().data or []
        except Exception as e:
            msg = str(e or '')
            if 'column' in msg.lower() and 'does not exist' in msg.lower():
                legacy_row = {
                    'owner_user_id': str(user_id),
                    'name': name,
                    'location': str(data.get('location') or data.get('location_address') or '').strip() or None,
                    'description': str(data.get('description') or '').strip() or None,
                    'project_type': str(data.get('project_type') or '').strip() or 'residential',
                }
                created = sb.table('crm_normal_projects').insert(legacy_row).execute().data or []
            else:
                raise
        out = (created[0] if created else row)
        out['crm_mode'] = 'normal'
        return jsonify(out), 201

    @app.route('/api/crm/normal-plots', methods=['GET'])
    @require_auth
    def list_crm_normal_plots(user_id, role):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        page, limit, offset = crm_parse_page_args(default_limit=10, max_limit=100)
        sort_field, sort_desc = crm_parse_sort_args(
            NORMAL_PLOT_SORT_FIELDS, default_field='updated_at', default_desc=True
        )
        q = _sanitize_search_token(request.args.get('q')).lower()
        project_id = str(request.args.get('project_id') or '').strip()
        query = (
            sb.table('crm_normal_plots')
            .select('id, owner_user_id, project_id, project_name, name, area, price, status, description, panorama_id, custom_fields, created_at, updated_at', count='exact')
            .eq('owner_user_id', str(user_id))
            .order(sort_field, desc=sort_desc)
        )
        if project_id:
            query = query.eq('project_id', project_id)
        if q:
            query = query.or_(f'name.ilike.%{q}%,project_name.ilike.%{q}%,status.ilike.%{q}%')
        result = query.range(offset, offset + limit - 1).execute()
        items = result.data or []
        for item in items:
            item['crm_mode'] = 'normal'
            if item.get('panorama_id') is None:
                item['panorama_id'] = 'none'
        total = int(result.count or 0)
        return jsonify(crm_page_payload(items, total, page, limit))

    @app.route('/api/crm/normal-plots', methods=['POST'])
    @require_auth
    def create_crm_normal_plot(user_id, role):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        data = request.get_json(silent=True) or {}
        name = str(data.get('name') or '').strip()[:120]
        project_name = str(data.get('project_name') or '').strip()[:120]
        if not name:
            return jsonify({'error': 'Plot name is required'}), 400
        if not project_name:
            return jsonify({'error': 'Project name is required'}), 400
        project_id = str(data.get('project_id') or '').strip() or None
        if project_id:
            # A plot may only attach to one of the caller's own normal projects.
            try:
                owned = (
                    sb.table('crm_normal_projects')
                    .select('id')
                    .eq('id', project_id)
                    .eq('owner_user_id', str(user_id))
                    .limit(1)
                    .execute()
                )
            except Exception:
                owned = None
            if not (owned and owned.data):
                return jsonify({'error': 'Project not found'}), 404
        row = {
            'owner_user_id': str(user_id),
            'project_id': project_id,
            'project_name': project_name,
            'name': name,
            'area': str(data.get('area') or '').strip() or None,
            'price': str(data.get('price') or '').strip() or None,
            'status': str(data.get('status') or '').strip() or 'available',
            'description': str(data.get('description') or '').strip() or None,
            'panorama_id': None,
            'custom_fields': data.get('custom_fields') if isinstance(data.get('custom_fields'), dict) else {},
        }
        created = sb.table('crm_normal_plots').insert(row).execute().data or []
        out = (created[0] if created else row)
        out['crm_mode'] = 'normal'
        out['panorama_id'] = 'none'
        return jsonify(out), 201
