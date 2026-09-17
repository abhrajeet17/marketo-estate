import re
import uuid

from flask import jsonify, redirect, render_template, request

from app.core.auth import get_profile, require_admin
from app.core.database import get_supabase
from app.services.full_view_service import get_config_for_workspace as fv_get_config
from app.services.sales_route_map_service import (
    clear_main_marker as srm_clear_main_marker,
    create_hover_route as srm_create_hover_route,
    create_marker as srm_create_marker,
    create_route as srm_create_route,
    create_sales_map as srm_create,
    delete_hover_route as srm_delete_hover_route,
    delete_marker as srm_delete_marker,
    delete_route as srm_delete_route,
    delete_sales_map as srm_delete,
    get_hover_route as srm_get_hover_route,
    get_marker as srm_get_marker,
    get_next_hover_route_sort_order as srm_next_hover_route_sort,
    get_next_marker_sort_order as srm_next_marker_sort,
    get_next_route_sort_order as srm_next_route_sort,
    get_route as srm_get_route,
    get_sales_map as srm_get,
    get_sales_map_by_token as srm_get_by_token,
    list_hover_routes as srm_list_hover_routes,
    list_markers as srm_list_markers,
    list_routes as srm_list_routes,
    list_sales_maps as srm_list,
    update_hover_route as srm_update_hover_route,
    update_marker as srm_update_marker,
    update_route as srm_update_route,
    update_sales_map as srm_update,
)
from app.services.storage_service import (
    MAX_SALES_MAP_READ_BYTES,
    compress_sales_map_image,
    delete_sales_map_from_s3,
    get_sales_map_s3_url,
    upload_sales_map_to_s3,
)
from app.services.workspace_service import can_manage_workspace, get_workspace_by_id

from .shared import allowed_file, auth_ctx


def register_sales_route_map_routes(app):
    def _parse_ratio(value):
        try:
            ratio = float(value)
        except (TypeError, ValueError):
            return None
        if ratio < 0 or ratio > 1:
            return None
        return ratio

    def _parse_distance_km(value):
        if value is None:
            return True, None
        if isinstance(value, str) and not value.strip():
            return True, None
        try:
            distance = float(value)
        except (TypeError, ValueError):
            return False, None
        if distance < 0:
            return False, None
        return True, round(distance, 3)

    def _sanitize_route_line_style(value, fallback='dashed'):
        style = str(value or '').strip().lower()
        if style in ('continuous', 'dashed', 'dotted'):
            return style
        fallback_style = str(fallback or '').strip().lower()
        if fallback_style in ('continuous', 'dashed', 'dotted'):
            return fallback_style
        return None

    _srm_icon_key_re = re.compile(r'^[a-z0-9_-]{1,64}$')
    _srm_allowed_icon_keys = {
        'main-star',
        'main-home',
        'main-flag',
        'main-crown',
        'plot-pin',
        'plot-dot',
        'plot-square',
        'plot-gate',
        'plot-tree',
        'plot-office',
        'poi-school',
        'poi-college',
        'poi-hospital',
        'poi-clinic',
        'poi-pharmacy',
        'poi-airport',
        'poi-railway',
        'poi-metro',
        'poi-bus',
        'poi-petrol',
        'poi-mall',
        'poi-market',
        'poi-bank',
        'poi-restaurant',
        'poi-hotel',
        'poi-gym',
        'poi-park',
        'poi-garden',
        'poi-stadium',
        'poi-temple',
        'poi-church',
        'poi-mosque',
        'poi-police',
        'poi-residence',
        'poi-industrial',
    }

    _srm_pointer_type_icon_map = {
        'project': 'main-home',
        'landmark': 'plot-pin',
        'residence': 'poi-residence',
        'school': 'poi-school',
        'college': 'poi-college',
        'hospital': 'poi-hospital',
        'clinic': 'poi-clinic',
        'pharmacy': 'poi-pharmacy',
        'airport': 'poi-airport',
        'railway_station': 'poi-railway',
        'metro_station': 'poi-metro',
        'bus_stop': 'poi-bus',
        'petrol_pump': 'poi-petrol',
        'mall': 'poi-mall',
        'market': 'poi-market',
        'bank': 'poi-bank',
        'office': 'plot-office',
        'restaurant': 'poi-restaurant',
        'hotel': 'poi-hotel',
        'gym': 'poi-gym',
        'park': 'poi-park',
        'garden': 'poi-garden',
        'stadium': 'poi-stadium',
        'temple': 'poi-temple',
        'church': 'poi-church',
        'mosque': 'poi-mosque',
        'police_station': 'poi-police',
        'industrial_area': 'poi-industrial',
    }
    _srm_icon_to_pointer_type_map = {
        'plot-pin': 'landmark',
        'plot-dot': 'landmark',
        'plot-square': 'landmark',
        'plot-gate': 'residence',
        'plot-tree': 'park',
        'plot-office': 'office',
    }
    _srm_icon_to_pointer_type_map.update({
        icon_key: pointer_type
        for pointer_type, icon_key in _srm_pointer_type_icon_map.items()
    })
    _srm_allowed_pointer_types = set(_srm_pointer_type_icon_map.keys())
    _srm_allowed_pointer_types.discard('project')
    _srm_hex_color_re = re.compile(r'^#(?:[0-9a-f]{3}|[0-9a-f]{6})$')
    _srm_allowed_icon_looks = {'solid', 'soft', 'outline', 'glass', 'light'}

    def _default_srm_pointer_type(marker_type, icon_key=''):
        marker_role = str(marker_type or '').strip().lower()
        if marker_role == 'main':
            return 'project'
        return _srm_icon_to_pointer_type_map.get(str(icon_key or '').strip().lower(), 'landmark')

    def _default_srm_icon_color(marker_type, pointer_type=''):
        marker_role = str(marker_type or '').strip().lower()
        return '#f97316' if marker_role == 'main' else '#22d3ee'

    def _default_srm_icon_look():
        return 'solid'

    def _default_srm_marker_size():
        return 1.0

    def _default_srm_icon(marker_type, pointer_type=''):
        marker_role = str(marker_type or '').strip().lower()
        if marker_role == 'main':
            return _srm_pointer_type_icon_map.get('project', 'main-home')
        normalized_pointer_type = str(pointer_type or '').strip().lower()
        if normalized_pointer_type in _srm_allowed_pointer_types:
            return _srm_pointer_type_icon_map.get(normalized_pointer_type, 'plot-pin')
        return 'plot-pin'

    def _sanitize_srm_pointer_type(value, marker_type='normal', icon_key=''):
        marker_role = str(marker_type or '').strip().lower()
        if marker_role == 'main':
            return 'project'
        raw = str(value or '').strip().lower()
        if not raw:
            return _default_srm_pointer_type(marker_role, icon_key=icon_key)
        if not _srm_icon_key_re.match(raw):
            return None
        if raw not in _srm_allowed_pointer_types:
            return None
        return raw

    def _sanitize_srm_icon_color(value, marker_type='normal', pointer_type=''):
        raw = str(value or '').strip().lower()
        if not raw:
            return _default_srm_icon_color(marker_type, pointer_type=pointer_type)
        if not _srm_hex_color_re.match(raw):
            return None
        if len(raw) == 4:
            return '#' + raw[1] + raw[1] + raw[2] + raw[2] + raw[3] + raw[3]
        return raw

    def _sanitize_srm_icon_look(value):
        raw = str(value or '').strip().lower()
        if not raw:
            return _default_srm_icon_look()
        if not _srm_icon_key_re.match(raw):
            return None
        if raw not in _srm_allowed_icon_looks:
            return None
        return raw

    def _sanitize_srm_marker_size(value):
        if value in (None, ''):
            return _default_srm_marker_size()
        try:
            size = float(value)
        except (TypeError, ValueError):
            return None
        if size < 0.6 or size > 2.4:
            return None
        return round(size, 2)

    def _sanitize_srm_icon_key(value, marker_type='normal', pointer_type=''):
        raw = str(value or '').strip().lower()
        if not raw:
            return _default_srm_icon(marker_type, pointer_type=pointer_type)
        if not _srm_icon_key_re.match(raw):
            return None
        if raw not in _srm_allowed_icon_keys:
            return None
        return raw

    def _sanitize_srm_route_color(value, fallback='#162338'):
        raw = str(value or '').strip().lower()
        if not raw:
            return fallback
        if not _srm_hex_color_re.match(raw):
            return None
        if len(raw) == 4:
            return '#' + raw[1] + raw[1] + raw[2] + raw[2] + raw[3] + raw[3]
        return raw

    def _sanitize_route_points(points):
        if not isinstance(points, list):
            return []
        clean = []
        for point in points:
            if not isinstance(point, dict):
                continue
            x_ratio = _parse_ratio(point.get('x'))
            y_ratio = _parse_ratio(point.get('y'))
            if x_ratio is None or y_ratio is None:
                continue
            clean.append({'x': x_ratio, 'y': y_ratio})
        return clean

    def _sanitize_hover_route_line_style(value, fallback='dashed'):
        return _sanitize_route_line_style(value, fallback=fallback)

    def _ensure_route_endpoints(points, from_marker, to_marker):
        start = {
            'x': float(from_marker.get('x_ratio') or 0),
            'y': float(from_marker.get('y_ratio') or 0),
        }
        end = {
            'x': float(to_marker.get('x_ratio') or 0),
            'y': float(to_marker.get('y_ratio') or 0),
        }
        clean = _sanitize_route_points(points)
        if not clean:
            return [start, end]
        first = clean[0]
        last = clean[-1]
        if abs(first['x'] - start['x']) > 1e-9 or abs(first['y'] - start['y']) > 1e-9:
            clean.insert(0, start)
        if abs(last['x'] - end['x']) > 1e-9 or abs(last['y'] - end['y']) > 1e-9:
            clean.append(end)
        return clean

    def _sync_routes_for_marker(sb, map_id, marker_id, updated_marker=None):
        routes = srm_list_routes(sb, map_id)
        marker_id_str = str(marker_id)
        for route in routes:
            from_id = str(route.get('from_marker_id') or '')
            to_id = str(route.get('to_marker_id') or '')
            if marker_id_str not in (from_id, to_id):
                continue
            from_marker = updated_marker if from_id == marker_id_str else srm_get_marker(sb, from_id)
            to_marker = updated_marker if to_id == marker_id_str else srm_get_marker(sb, to_id)
            if not from_marker or not to_marker:
                continue
            anchored_points = _ensure_route_endpoints(route.get('path_points') or [], from_marker, to_marker)
            try:
                srm_update_route(sb, route.get('id'), path_points=anchored_points)
            except Exception:
                continue

    def _resolve_sales_map_for_admin(sb, map_id, user_id, role):
        smap = srm_get(sb, map_id)
        if not smap:
            return None, (jsonify({'error': 'Not found'}), 404)
        if str(smap.get('user_id')) != str(user_id) and role != 'superadmin':
            return None, (jsonify({'error': 'Forbidden'}), 403)
        return smap, None

    @app.route('/sales-route-maps')
    def sales_route_maps_page():
        return redirect('/salestools?tab=route-maps')

    @app.route('/sales-route-maps/editor/<map_id>')
    def sales_route_map_editor_page(map_id):
        return render_template('sales_route_map_editor.html', map_id=map_id, **auth_ctx())

    @app.route('/api/sales-maps', methods=['GET'])
    @require_admin
    def api_list_sales_maps(user_id, role):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        workspace_id = str(request.args.get('workspace_id') or '').strip() or None
        maps = srm_list(sb, user_id, workspace_id=workspace_id)
        base = (request.url_root or '').rstrip('/')
        for smap in maps:
            markers = srm_list_markers(sb, smap['id'])
            routes = srm_list_routes(sb, smap['id'])
            hover_routes = srm_list_hover_routes(sb, smap['id'])
            smap['image_url'] = get_sales_map_s3_url(smap.get('image_filename'))
            smap['share_url'] = f"{base}/sales-route-map/view/{smap.get('share_token', '')}"
            smap['marker_count'] = len(markers)
            smap['route_count'] = len(routes) + len(hover_routes)
            smap['has_main_marker'] = any((m.get('marker_type') or '') == 'main' for m in markers)
        return jsonify(maps)

    @app.route('/api/sales-maps', methods=['POST'])
    @require_admin
    def api_create_sales_map(user_id, role):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        name = str(request.form.get('name') or 'Sales Route Map').strip() or 'Sales Route Map'
        workspace_id = str(request.form.get('workspace_id') or '').strip() or None
        if workspace_id:
            workspace = get_workspace_by_id(sb, workspace_id)
            if not workspace:
                return jsonify({'error': 'Project not found'}), 404
            if not can_manage_workspace(sb, workspace, user_id, role):
                return jsonify({'error': 'Forbidden'}), 403
        existing = srm_list(sb, user_id)
        if any(m.get('name', '').strip().lower() == name.lower() for m in existing):
            return jsonify({'error': f'A sales route map named "{name}" already exists'}), 409
        file_obj = request.files.get('file')
        if not file_obj:
            return jsonify({'error': 'No file uploaded'}), 400
        if not allowed_file(file_obj.filename):
            return jsonify({'error': 'Invalid file type'}), 400
        raw_bytes = file_obj.read()
        if not raw_bytes or len(raw_bytes) > MAX_SALES_MAP_READ_BYTES:
            return jsonify({'error': 'File too large'}), 400
        jpeg_bytes, width, height = compress_sales_map_image(raw_bytes)
        if not jpeg_bytes:
            return jsonify({'error': 'Failed to process image'}), 400
        filename = f"srm_{uuid.uuid4().hex[:16]}.jpg"
        upload_sales_map_to_s3(filename, jpeg_bytes, 'image/jpeg')
        profile = get_profile(sb, user_id)
        org_id = profile.get('org_id') if profile else None
        smap = srm_create(
            sb,
            user_id,
            org_id,
            name,
            filename,
            width,
            height,
            workspace_id=workspace_id,
        )
        if not smap:
            return jsonify({'error': 'Failed to create sales route map'}), 500
        base = (request.url_root or '').rstrip('/')
        smap['image_url'] = get_sales_map_s3_url(smap.get('image_filename'))
        smap['share_url'] = f"{base}/sales-route-map/view/{smap.get('share_token', '')}"
        smap['marker_count'] = 0
        smap['route_count'] = 0
        smap['has_main_marker'] = False
        return jsonify(smap), 201

    @app.route('/api/sales-maps/<map_id>', methods=['GET'])
    @require_admin
    def api_get_sales_map(user_id, role, map_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        smap, err = _resolve_sales_map_for_admin(sb, map_id, user_id, role)
        if err:
            return err
        markers = srm_list_markers(sb, map_id)
        routes = srm_list_routes(sb, map_id)
        hover_routes = srm_list_hover_routes(sb, map_id)
        base = (request.url_root or '').rstrip('/')
        smap['image_url'] = get_sales_map_s3_url(smap.get('image_filename'))
        smap['share_url'] = f"{base}/sales-route-map/view/{smap.get('share_token', '')}"
        smap['markers'] = markers
        smap['routes'] = routes
        smap['hover_routes'] = hover_routes
        return jsonify(smap)

    @app.route('/api/sales-maps/<map_id>', methods=['PATCH'])
    @require_admin
    def api_update_sales_map(user_id, role, map_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        smap, err = _resolve_sales_map_for_admin(sb, map_id, user_id, role)
        if err:
            return err
        data = request.get_json(silent=True) or {}
        updates = {}
        if 'name' in data:
            updates['name'] = str(data.get('name') or '').strip() or smap.get('name')
        if 'workspace_id' in data:
            workspace_id = str(data.get('workspace_id') or '').strip() or None
            if workspace_id:
                workspace = get_workspace_by_id(sb, workspace_id)
                if not workspace:
                    return jsonify({'error': 'Project not found'}), 404
                if not can_manage_workspace(sb, workspace, user_id, role):
                    return jsonify({'error': 'Forbidden'}), 403
            updates['workspace_id'] = workspace_id
        updated = srm_update(sb, map_id, **updates) if updates else srm_get(sb, map_id)
        if not updated:
            return jsonify({'error': 'Not found'}), 404
        base = (request.url_root or '').rstrip('/')
        updated['image_url'] = get_sales_map_s3_url(updated.get('image_filename'))
        updated['share_url'] = f"{base}/sales-route-map/view/{updated.get('share_token', '')}"
        return jsonify(updated)

    @app.route('/api/sales-maps/<map_id>', methods=['DELETE'])
    @require_admin
    def api_delete_sales_map(user_id, role, map_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        smap, err = _resolve_sales_map_for_admin(sb, map_id, user_id, role)
        if err:
            return err
        delete_sales_map_from_s3(smap.get('image_filename'))
        srm_delete(sb, map_id)
        return jsonify({'success': True})

    @app.route('/api/sales-maps/<map_id>/markers', methods=['GET'])
    @require_admin
    def api_list_sales_map_markers(user_id, role, map_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        _smap, err = _resolve_sales_map_for_admin(sb, map_id, user_id, role)
        if err:
            return err
        return jsonify(srm_list_markers(sb, map_id))

    @app.route('/api/sales-maps/<map_id>/markers', methods=['POST'])
    @require_admin
    def api_create_sales_map_marker(user_id, role, map_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        _smap, err = _resolve_sales_map_for_admin(sb, map_id, user_id, role)
        if err:
            return err
        data = request.get_json(silent=True) or {}
        marker_type = str(data.get('marker_type') or 'normal').strip().lower()
        if marker_type not in ('main', 'normal'):
            return jsonify({'error': 'marker_type must be main or normal'}), 400
        x_ratio = _parse_ratio(data.get('x_ratio'))
        y_ratio = _parse_ratio(data.get('y_ratio'))
        if x_ratio is None or y_ratio is None:
            return jsonify({'error': 'x_ratio and y_ratio must be between 0 and 1'}), 400
        if marker_type == 'main':
            srm_clear_main_marker(sb, map_id)
        label = str(data.get('label') or '').strip()
        pointer_type = _sanitize_srm_pointer_type(
            data.get('pointer_type'),
            marker_type=marker_type,
            icon_key=data.get('icon_key'),
        )
        if pointer_type is None:
            return jsonify({'error': 'pointer_type is invalid'}), 400
        icon_key = _sanitize_srm_icon_key(
            data.get('icon_key'),
            marker_type=marker_type,
            pointer_type=pointer_type,
        )
        if icon_key is None:
            return jsonify({'error': 'icon_key is invalid'}), 400
        icon_color = _sanitize_srm_icon_color(
            data.get('icon_color'),
            marker_type=marker_type,
            pointer_type=pointer_type,
        )
        if icon_color is None:
            return jsonify({'error': 'icon_color is invalid'}), 400
        icon_look = _sanitize_srm_icon_look(data.get('icon_look'))
        if icon_look is None:
            return jsonify({'error': 'icon_look is invalid'}), 400
        marker_size = _sanitize_srm_marker_size(data.get('marker_size'))
        if marker_size is None:
            return jsonify({'error': 'marker_size must be between 0.6 and 2.4'}), 400
        sort_order = srm_next_marker_sort(sb, map_id)
        marker = srm_create_marker(
            sb,
            map_id,
            marker_type,
            label,
            x_ratio,
            y_ratio,
            icon_key=icon_key,
            pointer_type=pointer_type,
            icon_color=icon_color,
            icon_look=icon_look,
            marker_size=marker_size,
            sort_order=sort_order,
        )
        if not marker:
            return jsonify({'error': 'Failed to create marker'}), 500
        return jsonify(marker), 201

    @app.route('/api/sales-map-markers/<marker_id>', methods=['PATCH'])
    @require_admin
    def api_update_sales_map_marker(user_id, role, marker_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        marker = srm_get_marker(sb, marker_id)
        if not marker:
            return jsonify({'error': 'Not found'}), 404
        map_id = marker.get('map_id')
        _smap, err = _resolve_sales_map_for_admin(sb, map_id, user_id, role)
        if err:
            return err
        data = request.get_json(silent=True) or {}
        updates = {}
        if 'marker_type' in data:
            marker_type = str(data.get('marker_type') or '').strip().lower()
            if marker_type not in ('main', 'normal'):
                return jsonify({'error': 'marker_type must be main or normal'}), 400
            if marker_type == 'main':
                srm_clear_main_marker(sb, map_id, exclude_marker_id=marker_id)
            updates['marker_type'] = marker_type
        effective_marker_type = updates.get('marker_type') or str(marker.get('marker_type') or 'normal').strip().lower()
        current_icon_key = str(marker.get('icon_key') or '').strip().lower()
        pointer_type_input = data.get('pointer_type') if 'pointer_type' in data else marker.get('pointer_type')
        icon_key_input = data.get('icon_key') if 'icon_key' in data else current_icon_key
        effective_pointer_type = _sanitize_srm_pointer_type(
            pointer_type_input,
            marker_type=effective_marker_type,
            icon_key=icon_key_input,
        )
        if effective_pointer_type is None:
            return jsonify({'error': 'pointer_type is invalid'}), 400
        if 'label' in data:
            updates['label'] = str(data.get('label') or '').strip()
        if 'pointer_type' in data or 'marker_type' in updates:
            updates['pointer_type'] = effective_pointer_type
        if 'icon_color' in data:
            icon_color = _sanitize_srm_icon_color(
                data.get('icon_color'),
                marker_type=effective_marker_type,
                pointer_type=effective_pointer_type,
            )
            if icon_color is None:
                return jsonify({'error': 'icon_color is invalid'}), 400
            updates['icon_color'] = icon_color
        if 'icon_look' in data:
            icon_look = _sanitize_srm_icon_look(data.get('icon_look'))
            if icon_look is None:
                return jsonify({'error': 'icon_look is invalid'}), 400
            updates['icon_look'] = icon_look
        if 'marker_size' in data:
            marker_size = _sanitize_srm_marker_size(data.get('marker_size'))
            if marker_size is None:
                return jsonify({'error': 'marker_size must be between 0.6 and 2.4'}), 400
            updates['marker_size'] = marker_size
        if 'icon_key' in data:
            icon_key = _sanitize_srm_icon_key(
                data.get('icon_key'),
                marker_type=effective_marker_type,
                pointer_type=effective_pointer_type,
            )
            if icon_key is None:
                return jsonify({'error': 'icon_key is invalid'}), 400
            updates['icon_key'] = icon_key
        elif 'marker_type' in updates or 'pointer_type' in data:
            updates['icon_key'] = _default_srm_icon(effective_marker_type, effective_pointer_type)
        if 'x_ratio' in data:
            x_ratio = _parse_ratio(data.get('x_ratio'))
            if x_ratio is None:
                return jsonify({'error': 'x_ratio must be between 0 and 1'}), 400
            updates['x_ratio'] = x_ratio
        if 'y_ratio' in data:
            y_ratio = _parse_ratio(data.get('y_ratio'))
            if y_ratio is None:
                return jsonify({'error': 'y_ratio must be between 0 and 1'}), 400
            updates['y_ratio'] = y_ratio
        if 'sort_order' in data:
            try:
                updates['sort_order'] = int(data.get('sort_order'))
            except (TypeError, ValueError):
                return jsonify({'error': 'sort_order must be an integer'}), 400
        updated = srm_update_marker(sb, marker_id, **updates) if updates else srm_get_marker(sb, marker_id)
        if updated and ('x_ratio' in updates or 'y_ratio' in updates):
            _sync_routes_for_marker(sb, map_id, marker_id, updated_marker=updated)
        return jsonify(updated)

    @app.route('/api/sales-map-markers/<marker_id>', methods=['DELETE'])
    @require_admin
    def api_delete_sales_map_marker(user_id, role, marker_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        marker = srm_get_marker(sb, marker_id)
        if not marker:
            return jsonify({'error': 'Not found'}), 404
        map_id = marker.get('map_id')
        _smap, err = _resolve_sales_map_for_admin(sb, map_id, user_id, role)
        if err:
            return err
        srm_delete_marker(sb, marker_id)
        return jsonify({'success': True})

    @app.route('/api/sales-maps/<map_id>/routes', methods=['GET'])
    @require_admin
    def api_list_sales_map_routes(user_id, role, map_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        _smap, err = _resolve_sales_map_for_admin(sb, map_id, user_id, role)
        if err:
            return err
        return jsonify(srm_list_routes(sb, map_id))

    @app.route('/api/sales-maps/<map_id>/routes', methods=['POST'])
    @require_admin
    def api_create_sales_map_route(user_id, role, map_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        _smap, err = _resolve_sales_map_for_admin(sb, map_id, user_id, role)
        if err:
            return err
        data = request.get_json(silent=True) or {}
        from_marker_id = str(data.get('from_marker_id') or '').strip()
        to_marker_id = str(data.get('to_marker_id') or '').strip()
        if not from_marker_id or not to_marker_id:
            return jsonify({'error': 'from_marker_id and to_marker_id are required'}), 400
        if from_marker_id == to_marker_id:
            return jsonify({'error': 'Route endpoints must be different markers'}), 400
        from_marker = srm_get_marker(sb, from_marker_id)
        to_marker = srm_get_marker(sb, to_marker_id)
        if not from_marker or not to_marker:
            return jsonify({'error': 'Route marker not found'}), 404
        if str(from_marker.get('map_id')) != str(map_id) or str(to_marker.get('map_id')) != str(map_id):
            return jsonify({'error': 'Route markers must belong to this map'}), 400
        try:
            line_width = max(1, min(12, int(data.get('line_width', 3))))
        except (TypeError, ValueError):
            return jsonify({'error': 'line_width must be an integer'}), 400
        color = _sanitize_srm_route_color(data.get('color'), fallback='#162338')
        if color is None:
            return jsonify({'error': 'color is invalid'}), 400
        line_style = _sanitize_route_line_style(data.get('line_style'), fallback='dashed')
        if line_style is None:
            return jsonify({'error': 'line_style is invalid'}), 400
        distance_valid, distance_km = _parse_distance_km(data.get('distance_km'))
        if not distance_valid:
            return jsonify({'error': 'distance_km must be a number >= 0'}), 400
        points = _ensure_route_endpoints(data.get('path_points') or [], from_marker, to_marker)
        sort_order = srm_next_route_sort(sb, map_id)
        try:
            route = srm_create_route(
                sb,
                map_id,
                from_marker_id,
                to_marker_id,
                points,
                color=color,
                line_width=line_width,
                line_style=line_style,
                distance_km=distance_km,
                sort_order=sort_order,
            )
        except Exception as exc:
            msg = str(exc)
            if 'duplicate key' in msg.lower() or 'unique' in msg.lower():
                return jsonify({'error': 'A route between these pointers already exists'}), 409
            return jsonify({'error': msg}), 500
        if not route:
            return jsonify({'error': 'Failed to create route'}), 500
        return jsonify(route), 201

    @app.route('/api/sales-map-routes/<route_id>', methods=['PATCH'])
    @require_admin
    def api_update_sales_map_route(user_id, role, route_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        route = srm_get_route(sb, route_id)
        if not route:
            return jsonify({'error': 'Not found'}), 404
        map_id = route.get('map_id')
        _smap, err = _resolve_sales_map_for_admin(sb, map_id, user_id, role)
        if err:
            return err
        data = request.get_json(silent=True) or {}

        from_marker_id = str(data.get('from_marker_id') or route.get('from_marker_id') or '').strip()
        to_marker_id = str(data.get('to_marker_id') or route.get('to_marker_id') or '').strip()
        if not from_marker_id or not to_marker_id:
            return jsonify({'error': 'from_marker_id and to_marker_id are required'}), 400
        if from_marker_id == to_marker_id:
            return jsonify({'error': 'Route endpoints must be different markers'}), 400
        from_marker = srm_get_marker(sb, from_marker_id)
        to_marker = srm_get_marker(sb, to_marker_id)
        if not from_marker or not to_marker:
            return jsonify({'error': 'Route marker not found'}), 404
        if str(from_marker.get('map_id')) != str(map_id) or str(to_marker.get('map_id')) != str(map_id):
            return jsonify({'error': 'Route markers must belong to this map'}), 400

        updates = {
            'from_marker_id': from_marker_id,
            'to_marker_id': to_marker_id,
        }
        if 'path_points' in data:
            updates['path_points'] = _ensure_route_endpoints(data.get('path_points') or [], from_marker, to_marker)
        else:
            updates['path_points'] = _ensure_route_endpoints(route.get('path_points') or [], from_marker, to_marker)
        if 'color' in data:
            color = _sanitize_srm_route_color(data.get('color'), fallback='#162338')
            if color is None:
                return jsonify({'error': 'color is invalid'}), 400
            updates['color'] = color
        if 'line_width' in data:
            try:
                updates['line_width'] = max(1, min(12, int(data.get('line_width'))))
            except (TypeError, ValueError):
                return jsonify({'error': 'line_width must be an integer'}), 400
        if 'line_style' in data:
            line_style = _sanitize_route_line_style(data.get('line_style'), fallback='dashed')
            if line_style is None:
                return jsonify({'error': 'line_style is invalid'}), 400
            updates['line_style'] = line_style
        if 'distance_km' in data:
            distance_valid, distance_km = _parse_distance_km(data.get('distance_km'))
            if not distance_valid:
                return jsonify({'error': 'distance_km must be a number >= 0'}), 400
            updates['distance_km'] = distance_km
        if 'sort_order' in data:
            try:
                updates['sort_order'] = int(data.get('sort_order'))
            except (TypeError, ValueError):
                return jsonify({'error': 'sort_order must be an integer'}), 400
        try:
            updated = srm_update_route(sb, route_id, **updates)
        except Exception as exc:
            msg = str(exc)
            if 'duplicate key' in msg.lower() or 'unique' in msg.lower():
                return jsonify({'error': 'A route between these pointers already exists'}), 409
            return jsonify({'error': msg}), 500
        return jsonify(updated)

    @app.route('/api/sales-map-routes/<route_id>', methods=['DELETE'])
    @require_admin
    def api_delete_sales_map_route(user_id, role, route_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        route = srm_get_route(sb, route_id)
        if not route:
            return jsonify({'error': 'Not found'}), 404
        map_id = route.get('map_id')
        _smap, err = _resolve_sales_map_for_admin(sb, map_id, user_id, role)
        if err:
            return err
        srm_delete_route(sb, route_id)
        return jsonify({'success': True})

    @app.route('/api/sales-maps/<map_id>/hover-routes', methods=['GET'])
    @require_admin
    def api_list_sales_map_hover_routes(user_id, role, map_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        _smap, err = _resolve_sales_map_for_admin(sb, map_id, user_id, role)
        if err:
            return err
        return jsonify(srm_list_hover_routes(sb, map_id))

    @app.route('/api/sales-maps/<map_id>/hover-routes', methods=['POST'])
    @require_admin
    def api_create_sales_map_hover_route(user_id, role, map_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        _smap, err = _resolve_sales_map_for_admin(sb, map_id, user_id, role)
        if err:
            return err
        data = request.get_json(silent=True) or {}
        label = str(data.get('label') or '').strip() or 'Independent Route'
        color = _sanitize_srm_route_color(data.get('color'), fallback='#facc15')
        if color is None:
            return jsonify({'error': 'color is invalid'}), 400
        try:
            line_width = max(1, min(12, int(data.get('line_width', 4))))
        except (TypeError, ValueError):
            return jsonify({'error': 'line_width must be an integer'}), 400
        line_style = _sanitize_hover_route_line_style(data.get('line_style'), fallback='dashed')
        if line_style is None:
            return jsonify({'error': 'line_style is invalid'}), 400
        points = _sanitize_route_points(data.get('path_points') or [])
        if len(points) < 2:
            return jsonify({'error': 'At least two path points are required'}), 400
        sort_order = srm_next_hover_route_sort(sb, map_id)
        try:
            route = srm_create_hover_route(
                sb,
                map_id,
                label,
                points,
                color=color,
                line_width=line_width,
                line_style=line_style,
                sort_order=sort_order,
            )
        except Exception as exc:
            return jsonify({'error': str(exc)}), 500
        if not route:
            return jsonify({'error': 'Hover routes are not available until migration_sales_route_map_hover_routes.sql is applied'}), 500
        return jsonify(route), 201

    @app.route('/api/sales-map-hover-routes/<hover_route_id>', methods=['PATCH'])
    @require_admin
    def api_update_sales_map_hover_route(user_id, role, hover_route_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        route = srm_get_hover_route(sb, hover_route_id)
        if not route:
            return jsonify({'error': 'Not found'}), 404
        map_id = route.get('map_id')
        _smap, err = _resolve_sales_map_for_admin(sb, map_id, user_id, role)
        if err:
            return err
        data = request.get_json(silent=True) or {}
        updates = {}
        if 'label' in data:
            updates['label'] = str(data.get('label') or '').strip()
        if 'color' in data:
            color = _sanitize_srm_route_color(data.get('color'), fallback='#facc15')
            if color is None:
                return jsonify({'error': 'color is invalid'}), 400
            updates['color'] = color
        if 'line_width' in data:
            try:
                updates['line_width'] = max(1, min(12, int(data.get('line_width'))))
            except (TypeError, ValueError):
                return jsonify({'error': 'line_width must be an integer'}), 400
        if 'line_style' in data:
            line_style = _sanitize_hover_route_line_style(data.get('line_style'), fallback='dashed')
            if line_style is None:
                return jsonify({'error': 'line_style is invalid'}), 400
            updates['line_style'] = line_style
        if 'path_points' in data:
            points = _sanitize_route_points(data.get('path_points') or [])
            if len(points) < 2:
                return jsonify({'error': 'At least two path points are required'}), 400
            updates['path_points'] = points
        if 'sort_order' in data:
            try:
                updates['sort_order'] = int(data.get('sort_order'))
            except (TypeError, ValueError):
                return jsonify({'error': 'sort_order must be an integer'}), 400
        try:
            updated = srm_update_hover_route(sb, hover_route_id, **updates) if updates else route
        except Exception as exc:
            return jsonify({'error': str(exc)}), 500
        if not updated:
            return jsonify({'error': 'Failed to update hover route'}), 500
        return jsonify(updated)

    @app.route('/api/sales-map-hover-routes/<hover_route_id>', methods=['DELETE'])
    @require_admin
    def api_delete_sales_map_hover_route(user_id, role, hover_route_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        route = srm_get_hover_route(sb, hover_route_id)
        if not route:
            return jsonify({'error': 'Not found'}), 404
        map_id = route.get('map_id')
        _smap, err = _resolve_sales_map_for_admin(sb, map_id, user_id, role)
        if err:
            return err
        srm_delete_hover_route(sb, hover_route_id)
        return jsonify({'success': True})

    @app.route('/sales-route-map/view/<share_token>')
    def sales_route_map_public_view(share_token):
        sb = get_supabase()
        if not sb:
            return "Database not configured", 503
        smap = srm_get_by_token(sb, share_token)
        if not smap:
            return "Not found", 404
        smap['image_url'] = get_sales_map_s3_url(smap.get('image_filename'))
        markers = srm_list_markers(sb, smap['id'])
        routes = srm_list_routes(sb, smap['id'])
        hover_routes = srm_list_hover_routes(sb, smap['id'])
        return render_template(
            'sales_route_map_view.html',
            sales_map=smap,
            markers=markers,
            routes=routes,
            hover_routes=hover_routes,
            embed=(request.args.get('embed', '') == '1'),
            preview_mode=request.args.get('preview', '').strip().lower() or '',
        )

    @app.route('/customer/full-view/sales-map/<map_id>')
    def fv_customer_sales_map_view(map_id):
        sb = get_supabase()
        if not sb:
            return "Database not configured", 503
        smap = srm_get(sb, map_id)
        if not smap:
            return "Not found", 404
        smap['image_url'] = get_sales_map_s3_url(smap.get('image_filename'))
        markers = srm_list_markers(sb, smap['id'])
        routes = srm_list_routes(sb, smap['id'])
        hover_routes = srm_list_hover_routes(sb, smap['id'])
        workspace_id = (request.args.get('workspace_id') or '').strip() or None
        fv_style = {}
        if workspace_id:
            fv_cfg = fv_get_config(sb, workspace_id)
            style_blob = (fv_cfg or {}).get('style')
            if isinstance(style_blob, dict):
                fv_style = style_blob
        return render_template(
            'sales_route_map_view.html',
            sales_map=smap,
            markers=markers,
            routes=routes,
            hover_routes=hover_routes,
            fv_style=fv_style,
            embed=True,
            preview_mode=request.args.get('preview', '').strip().lower() or '',
        )
