"""
Sales route map CRUD operations against Supabase.
This module powers map-image uploads, pointers, and drawable routes.
"""
import uuid
import json
from postgrest.exceptions import APIError


def _generate_share_token():
    return uuid.uuid4().hex[:12]


def _default_marker_icon(marker_type):
    return 'main-star' if str(marker_type or '').strip().lower() == 'main' else 'plot-pin'


def _default_marker_pointer_type(marker_type):
    return 'project' if str(marker_type or '').strip().lower() == 'main' else 'landmark'


def _default_marker_color(marker_type):
    return '#f97316' if str(marker_type or '').strip().lower() == 'main' else '#22d3ee'


def _default_marker_look():
    return 'solid'


def _default_marker_size():
    return 1.0


_ICON_POINTER_TYPE_MAP = {
    'plot-pin': 'landmark',
    'plot-dot': 'landmark',
    'plot-square': 'landmark',
    'plot-gate': 'residence',
    'plot-tree': 'park',
    'plot-office': 'office',
    'poi-school': 'school',
    'poi-college': 'college',
    'poi-hospital': 'hospital',
    'poi-clinic': 'clinic',
    'poi-pharmacy': 'pharmacy',
    'poi-airport': 'airport',
    'poi-railway': 'railway_station',
    'poi-metro': 'metro_station',
    'poi-bus': 'bus_stop',
    'poi-petrol': 'petrol_pump',
    'poi-mall': 'mall',
    'poi-market': 'market',
    'poi-bank': 'bank',
    'poi-restaurant': 'restaurant',
    'poi-hotel': 'hotel',
    'poi-gym': 'gym',
    'poi-park': 'park',
    'poi-garden': 'garden',
    'poi-stadium': 'stadium',
    'poi-temple': 'temple',
    'poi-church': 'church',
    'poi-mosque': 'mosque',
    'poi-police': 'police_station',
    'poi-residence': 'residence',
    'poi-industrial': 'industrial_area',
}

_ALLOWED_POINTER_TYPES = {
    'project', 'landmark', 'residence', 'school', 'college', 'hospital',
    'clinic', 'pharmacy', 'airport', 'railway_station', 'metro_station',
    'bus_stop', 'petrol_pump', 'mall', 'market', 'bank', 'office',
    'restaurant', 'hotel', 'gym', 'park', 'garden', 'stadium',
    'temple', 'church', 'mosque', 'police_station', 'industrial_area',
}

_ALLOWED_MARKER_LOOKS = {'solid', 'soft', 'outline', 'glass', 'light'}


def _normalize_icon_color(icon_color, marker_type='normal'):
    raw = str(icon_color or '').strip().lower()
    if len(raw) == 4 and raw.startswith('#'):
        raw = '#' + raw[1] + raw[1] + raw[2] + raw[2] + raw[3] + raw[3]
    if len(raw) == 7 and raw.startswith('#'):
        try:
            int(raw[1:], 16)
            return raw
        except ValueError:
            return _default_marker_color(marker_type)
    return _default_marker_color(marker_type)


def _normalize_icon_look(icon_look):
    raw = str(icon_look or '').strip().lower()
    return raw if raw in _ALLOWED_MARKER_LOOKS else _default_marker_look()


def _normalize_marker_size(marker_size):
    try:
        size = float(marker_size)
    except (TypeError, ValueError):
        return _default_marker_size()
    if size < 0.6:
        size = 0.6
    if size > 2.4:
        size = 2.4
    return round(size, 2)


def _normalize_pointer_type(pointer_type, marker_type='normal', icon_key=''):
    marker_role = str(marker_type or '').strip().lower() or 'normal'
    if marker_role == 'main':
        return 'project'
    raw = str(pointer_type or '').strip().lower()
    if raw in _ALLOWED_POINTER_TYPES and raw != 'project':
        return raw
    return _ICON_POINTER_TYPE_MAP.get(str(icon_key or '').strip().lower(), _default_marker_pointer_type(marker_role))


def _normalize_marker_meta(marker):
    if not isinstance(marker, dict):
        return marker
    marker_type = str(marker.get('marker_type') or 'normal').strip().lower() or 'normal'
    icon_key = str(marker.get('icon_key') or '').strip().lower()
    marker['icon_key'] = icon_key or _default_marker_icon(marker_type)
    marker['pointer_type'] = _normalize_pointer_type(marker.get('pointer_type'), marker_type=marker_type, icon_key=marker['icon_key'])
    marker['icon_color'] = _normalize_icon_color(marker.get('icon_color'), marker_type=marker_type)
    marker['icon_look'] = _normalize_icon_look(marker.get('icon_look'))
    marker['marker_size'] = _normalize_marker_size(marker.get('marker_size'))
    return marker


def _is_missing_marker_icon_column_error(exc):
    payload = {}
    raw = exc.args[0] if getattr(exc, 'args', None) else {}
    if isinstance(raw, dict):
        payload = raw
    code = str(payload.get('code') or '')
    message = str(payload.get('message') or str(exc))
    if code and code != 'PGRST204':
        return False
    return "'icon_key'" in message and "'sales_route_map_markers'" in message


def _is_missing_marker_pointer_type_column_error(exc):
    payload = {}
    raw = exc.args[0] if getattr(exc, 'args', None) else {}
    if isinstance(raw, dict):
        payload = raw
    code = str(payload.get('code') or '')
    message = str(payload.get('message') or str(exc))
    if code and code != 'PGRST204':
        return False
    return "'pointer_type'" in message and "'sales_route_map_markers'" in message


def _is_missing_marker_icon_color_column_error(exc):
    payload = {}
    raw = exc.args[0] if getattr(exc, 'args', None) else {}
    if isinstance(raw, dict):
        payload = raw
    code = str(payload.get('code') or '')
    message = str(payload.get('message') or str(exc))
    if code and code != 'PGRST204':
        return False
    return "'icon_color'" in message and "'sales_route_map_markers'" in message


def _is_missing_marker_icon_look_column_error(exc):
    payload = {}
    raw = exc.args[0] if getattr(exc, 'args', None) else {}
    if isinstance(raw, dict):
        payload = raw
    code = str(payload.get('code') or '')
    message = str(payload.get('message') or str(exc))
    if code and code != 'PGRST204':
        return False
    return "'icon_look'" in message and "'sales_route_map_markers'" in message


def _is_missing_marker_size_column_error(exc):
    payload = {}
    raw = exc.args[0] if getattr(exc, 'args', None) else {}
    if isinstance(raw, dict):
        payload = raw
    code = str(payload.get('code') or '')
    message = str(payload.get('message') or str(exc))
    if code and code != 'PGRST204':
        return False
    return "'marker_size'" in message and "'sales_route_map_markers'" in message


def _strip_legacy_marker_fields(payload, exc):
    legacy_payload = dict(payload or {})
    changed = False
    if _is_missing_marker_pointer_type_column_error(exc) and 'pointer_type' in legacy_payload:
        legacy_payload.pop('pointer_type', None)
        changed = True
    if _is_missing_marker_icon_column_error(exc) and 'icon_key' in legacy_payload:
        legacy_payload.pop('icon_key', None)
        changed = True
    if _is_missing_marker_icon_color_column_error(exc) and 'icon_color' in legacy_payload:
        legacy_payload.pop('icon_color', None)
        changed = True
    if _is_missing_marker_icon_look_column_error(exc) and 'icon_look' in legacy_payload:
        legacy_payload.pop('icon_look', None)
        changed = True
    if _is_missing_marker_size_column_error(exc) and 'marker_size' in legacy_payload:
        legacy_payload.pop('marker_size', None)
        changed = True
    return legacy_payload, changed


def _is_missing_route_distance_column_error(exc):
    payload = {}
    raw = exc.args[0] if getattr(exc, 'args', None) else {}
    if isinstance(raw, dict):
        payload = raw
    code = str(payload.get('code') or '')
    message = str(payload.get('message') or str(exc))
    if code and code != 'PGRST204':
        return False
    return "'distance_km'" in message and "'sales_route_map_routes'" in message


def _is_missing_route_line_style_column_error(exc):
    payload = {}
    raw = exc.args[0] if getattr(exc, 'args', None) else {}
    if isinstance(raw, dict):
        payload = raw
    code = str(payload.get('code') or '')
    message = str(payload.get('message') or str(exc))
    if code and code != 'PGRST204':
        return False
    return "'line_style'" in message and "'sales_route_map_routes'" in message


def _is_missing_hover_route_table_error(exc):
    payload = {}
    raw = exc.args[0] if getattr(exc, 'args', None) else {}
    if isinstance(raw, dict):
        payload = raw
    code = str(payload.get('code') or '')
    message = str(payload.get('message') or str(exc))
    if code and code not in ('PGRST205', '42P01'):
        return False
    return 'sales_route_map_hover_routes' in message


def _normalize_distance_km(value):
    if value in (None, ''):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number < 0:
        return None
    return round(number, 3)


def _normalize_route_line_style(value, fallback='dashed'):
    style = str(value or '').strip().lower()
    if style in ('continuous', 'dashed', 'dotted'):
        return style
    return fallback


def _normalize_route_row(route):
    if not isinstance(route, dict):
        return route
    route['path_points'] = _normalize_points(route.get('path_points'))
    route['distance_km'] = _normalize_distance_km(route.get('distance_km'))
    route['line_style'] = _normalize_route_line_style(route.get('line_style'), 'dashed')
    return route


def _strip_legacy_route_fields(payload, exc):
    legacy_payload = dict(payload or {})
    changed = False
    if _is_missing_route_distance_column_error(exc) and 'distance_km' in legacy_payload:
        legacy_payload.pop('distance_km', None)
        changed = True
    if _is_missing_route_line_style_column_error(exc) and 'line_style' in legacy_payload:
        legacy_payload.pop('line_style', None)
        changed = True
    return legacy_payload, changed


def _normalize_ratio(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number < 0 or number > 1:
        return None
    return number


# ---------------------------------------------------------------------------
# Sales map CRUD
# ---------------------------------------------------------------------------


def create_sales_map(sb, user_id, org_id, name, image_filename, image_width=0, image_height=0, workspace_id=None):
    row = {
        'user_id': str(user_id),
        'name': name,
        'image_filename': image_filename,
        'image_width': int(image_width or 0),
        'image_height': int(image_height or 0),
        'share_token': _generate_share_token(),
    }
    if org_id:
        row['org_id'] = str(org_id)
    if workspace_id:
        row['workspace_id'] = str(workspace_id)
    resp = sb.table('sales_route_maps').insert(row).execute()
    data = resp.data
    return data[0] if data else None


def get_sales_map(sb, map_id):
    resp = sb.table('sales_route_maps').select('*').eq('id', str(map_id)).execute()
    data = resp.data
    return data[0] if data else None


def get_sales_map_by_token(sb, token):
    resp = sb.table('sales_route_maps').select('*').eq('share_token', str(token)).execute()
    data = resp.data
    return data[0] if data else None


def list_sales_maps(sb, user_id, workspace_id=None):
    q = (
        sb.table('sales_route_maps')
        .select('*')
        .eq('user_id', str(user_id))
        .order('created_at', desc=True)
    )
    if workspace_id:
        q = q.eq('workspace_id', str(workspace_id))
    resp = q.execute()
    return resp.data or []


def update_sales_map(sb, map_id, **fields):
    clean = {}
    for k, v in fields.items():
        if k in ('name', 'workspace_id'):
            clean[k] = v
    if not clean:
        return None
    resp = sb.table('sales_route_maps').update(clean).eq('id', str(map_id)).execute()
    data = resp.data
    return data[0] if data else None


def delete_sales_map(sb, map_id):
    smap = get_sales_map(sb, map_id)
    if not smap:
        return None
    sb.table('sales_route_maps').delete().eq('id', str(map_id)).execute()
    return smap


# ---------------------------------------------------------------------------
# Marker CRUD
# ---------------------------------------------------------------------------


def list_markers(sb, map_id):
    resp = (
        sb.table('sales_route_map_markers')
        .select('*')
        .eq('map_id', str(map_id))
        .order('sort_order')
        .order('created_at')
        .execute()
    )
    markers = resp.data or []
    return [_normalize_marker_meta(marker) for marker in markers]


def get_marker(sb, marker_id):
    resp = sb.table('sales_route_map_markers').select('*').eq('id', str(marker_id)).execute()
    data = resp.data
    return _normalize_marker_meta(data[0]) if data else None


def get_next_marker_sort_order(sb, map_id):
    markers = list_markers(sb, map_id)
    if not markers:
        return 0
    return max(int(m.get('sort_order', 0) or 0) for m in markers) + 1


def clear_main_marker(sb, map_id, exclude_marker_id=None):
    q = (
        sb.table('sales_route_map_markers')
        .update({'marker_type': 'normal'})
        .eq('map_id', str(map_id))
        .eq('marker_type', 'main')
    )
    if exclude_marker_id:
        q = q.neq('id', str(exclude_marker_id))
    q.execute()
    return True


def create_marker(
    sb,
    map_id,
    marker_type,
    label,
    x_ratio,
    y_ratio,
    icon_key='',
    pointer_type='',
    icon_color='',
    icon_look='',
    marker_size=1.0,
    sort_order=0,
):
    marker_type = str(marker_type or 'normal').strip().lower() or 'normal'
    icon_key = str(icon_key or '').strip().lower() or _default_marker_icon(marker_type)
    pointer_type = _normalize_pointer_type(pointer_type, marker_type=marker_type, icon_key=icon_key)
    icon_color = _normalize_icon_color(icon_color, marker_type=marker_type)
    icon_look = _normalize_icon_look(icon_look)
    marker_size = _normalize_marker_size(marker_size)
    row = {
        'map_id': str(map_id),
        'marker_type': marker_type,
        'pointer_type': pointer_type,
        'label': str(label or '').strip(),
        'icon_key': icon_key,
        'icon_color': icon_color,
        'icon_look': icon_look,
        'marker_size': marker_size,
        'x_ratio': float(x_ratio),
        'y_ratio': float(y_ratio),
        'sort_order': int(sort_order or 0),
    }
    payload = dict(row)
    while True:
        try:
            resp = sb.table('sales_route_map_markers').insert(payload).execute()
            break
        except APIError as exc:
            legacy_payload, changed = _strip_legacy_marker_fields(payload, exc)
            if not changed:
                raise
            payload = legacy_payload
    data = resp.data
    return _normalize_marker_meta(data[0]) if data else None


def update_marker(sb, marker_id, **fields):
    clean = {}
    for k, v in fields.items():
        if k in ('marker_type', 'label', 'sort_order', 'icon_key', 'pointer_type', 'icon_color', 'icon_look'):
            clean[k] = v
        elif k == 'marker_size':
            clean[k] = _normalize_marker_size(v)
        elif k in ('x_ratio', 'y_ratio'):
            clean[k] = float(v)
    if not clean:
        return None
    existing = get_marker(sb, marker_id)
    marker_type = str(clean.get('marker_type') or (existing or {}).get('marker_type') or 'normal').strip().lower() or 'normal'
    icon_key = str(clean.get('icon_key') or (existing or {}).get('icon_key') or '').strip().lower()
    if 'icon_key' in clean:
        clean['icon_key'] = icon_key or _default_marker_icon(marker_type)
    if 'icon_color' in clean:
        clean['icon_color'] = _normalize_icon_color(clean.get('icon_color'), marker_type=marker_type)
    if 'icon_look' in clean:
        clean['icon_look'] = _normalize_icon_look(clean.get('icon_look'))
    if 'pointer_type' in clean or 'marker_type' in clean or 'icon_key' in clean:
        clean['pointer_type'] = _normalize_pointer_type(clean.get('pointer_type') or (existing or {}).get('pointer_type'), marker_type=marker_type, icon_key=clean.get('icon_key') or icon_key)
    payload = dict(clean)
    while True:
        try:
            resp = sb.table('sales_route_map_markers').update(payload).eq('id', str(marker_id)).execute()
            break
        except APIError as exc:
            legacy_payload, changed = _strip_legacy_marker_fields(payload, exc)
            if not changed:
                raise
            if not legacy_payload:
                return get_marker(sb, marker_id)
            payload = legacy_payload
    data = resp.data
    return _normalize_marker_meta(data[0]) if data else None


def delete_marker(sb, marker_id):
    marker = get_marker(sb, marker_id)
    if not marker:
        return None
    sb.table('sales_route_map_markers').delete().eq('id', str(marker_id)).execute()
    return marker


# ---------------------------------------------------------------------------
# Route CRUD
# ---------------------------------------------------------------------------


def _normalize_points(points):
    if isinstance(points, str):
        try:
            parsed = json.loads(points)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return []
    return points if isinstance(points, list) else []


def list_routes(sb, map_id):
    resp = (
        sb.table('sales_route_map_routes')
        .select('*')
        .eq('map_id', str(map_id))
        .order('sort_order')
        .order('created_at')
        .execute()
    )
    routes = resp.data or []
    return [_normalize_route_row(route) for route in routes]


def get_route(sb, route_id):
    resp = sb.table('sales_route_map_routes').select('*').eq('id', str(route_id)).execute()
    data = resp.data
    if not data:
        return None
    return _normalize_route_row(data[0])


def get_next_route_sort_order(sb, map_id):
    routes = list_routes(sb, map_id)
    if not routes:
        return 0
    return max(int(r.get('sort_order', 0) or 0) for r in routes) + 1


def create_route(
    sb,
    map_id,
    from_marker_id,
    to_marker_id,
    path_points,
    color='#162338',
    line_width=3,
    line_style='dashed',
    distance_km=None,
    sort_order=0,
):
    row = {
        'map_id': str(map_id),
        'from_marker_id': str(from_marker_id),
        'to_marker_id': str(to_marker_id),
        'path_points': json.dumps(_normalize_points(path_points)),
        'color': str(color or '#162338'),
        'line_width': int(line_width or 3),
        'line_style': _normalize_route_line_style(line_style, 'dashed'),
        'distance_km': _normalize_distance_km(distance_km),
        'sort_order': int(sort_order or 0),
    }
    try:
        resp = sb.table('sales_route_map_routes').insert(row).execute()
    except APIError as exc:
        legacy_row, changed = _strip_legacy_route_fields(row, exc)
        if not changed:
            raise
        resp = sb.table('sales_route_map_routes').insert(legacy_row).execute()
    data = resp.data
    if not data:
        return None
    return _normalize_route_row(data[0])


def update_route(sb, route_id, **fields):
    clean = {}
    for k, v in fields.items():
        if k in ('from_marker_id', 'to_marker_id', 'color'):
            clean[k] = str(v) if v is not None else None
        elif k in ('line_width', 'sort_order'):
            clean[k] = int(v)
        elif k == 'line_style':
            clean[k] = _normalize_route_line_style(v, 'dashed')
        elif k == 'distance_km':
            clean[k] = _normalize_distance_km(v)
        elif k == 'path_points':
            clean[k] = json.dumps(_normalize_points(v))
    if not clean:
        return None
    try:
        resp = sb.table('sales_route_map_routes').update(clean).eq('id', str(route_id)).execute()
    except APIError as exc:
        legacy_clean, changed = _strip_legacy_route_fields(clean, exc)
        if not changed:
            raise
        if not legacy_clean:
            return get_route(sb, route_id)
        resp = sb.table('sales_route_map_routes').update(legacy_clean).eq('id', str(route_id)).execute()
    data = resp.data
    if not data:
        return None
    return _normalize_route_row(data[0])


def delete_route(sb, route_id):
    route = get_route(sb, route_id)
    if not route:
        return None
    sb.table('sales_route_map_routes').delete().eq('id', str(route_id)).execute()
    return route


# ---------------------------------------------------------------------------
# Independent hover route CRUD
# ---------------------------------------------------------------------------


def _normalize_hover_route_line_style(value, fallback='dashed'):
    return _normalize_route_line_style(value, fallback)


def _normalize_hover_route_row(route):
    if not isinstance(route, dict):
        return route
    route['label'] = str(route.get('label') or '').strip()
    route['path_points'] = _normalize_points(route.get('path_points'))
    route['color'] = str(route.get('color') or '#facc15').strip() or '#facc15'
    try:
        route['line_width'] = max(1, min(12, int(route.get('line_width') or 4)))
    except (TypeError, ValueError):
        route['line_width'] = 4
    route['line_style'] = _normalize_hover_route_line_style(route.get('line_style'), 'dashed')
    return route


def list_hover_routes(sb, map_id):
    try:
        resp = (
            sb.table('sales_route_map_hover_routes')
            .select('*')
            .eq('map_id', str(map_id))
            .order('sort_order')
            .order('created_at')
            .execute()
        )
    except APIError as exc:
        if _is_missing_hover_route_table_error(exc):
            return []
        raise
    routes = resp.data or []
    return [_normalize_hover_route_row(route) for route in routes]


def get_hover_route(sb, hover_route_id):
    try:
        resp = (
            sb.table('sales_route_map_hover_routes')
            .select('*')
            .eq('id', str(hover_route_id))
            .execute()
        )
    except APIError as exc:
        if _is_missing_hover_route_table_error(exc):
            return None
        raise
    data = resp.data
    return _normalize_hover_route_row(data[0]) if data else None


def get_next_hover_route_sort_order(sb, map_id):
    routes = list_hover_routes(sb, map_id)
    if not routes:
        return 0
    return max(int(route.get('sort_order', 0) or 0) for route in routes) + 1


def create_hover_route(
    sb,
    map_id,
    label,
    path_points,
    color='#facc15',
    line_width=4,
    line_style='dashed',
    sort_order=0,
):
    row = {
        'map_id': str(map_id),
        'label': str(label or '').strip(),
        'path_points': json.dumps(_normalize_points(path_points)),
        'color': str(color or '#facc15').strip() or '#facc15',
        'line_width': max(1, min(12, int(line_width or 4))),
        'line_style': _normalize_hover_route_line_style(line_style, 'dashed'),
        'sort_order': int(sort_order or 0),
    }
    try:
        resp = sb.table('sales_route_map_hover_routes').insert(row).execute()
    except APIError as exc:
        if _is_missing_hover_route_table_error(exc):
            return None
        raise
    data = resp.data
    return _normalize_hover_route_row(data[0]) if data else None


def update_hover_route(sb, hover_route_id, **fields):
    clean = {}
    for k, v in fields.items():
        if k in ('label', 'color'):
            clean[k] = str(v or '').strip()
        elif k == 'line_width':
            clean[k] = max(1, min(12, int(v)))
        elif k == 'line_style':
            clean[k] = _normalize_hover_route_line_style(v, 'dashed')
        elif k == 'sort_order':
            clean[k] = int(v)
        elif k == 'path_points':
            clean[k] = json.dumps(_normalize_points(v))
    if not clean:
        return None
    try:
        resp = (
            sb.table('sales_route_map_hover_routes')
            .update(clean)
            .eq('id', str(hover_route_id))
            .execute()
        )
    except APIError as exc:
        if _is_missing_hover_route_table_error(exc):
            return None
        raise
    data = resp.data
    return _normalize_hover_route_row(data[0]) if data else None


def delete_hover_route(sb, hover_route_id):
    route = get_hover_route(sb, hover_route_id)
    if not route:
        return None
    try:
        sb.table('sales_route_map_hover_routes').delete().eq('id', str(hover_route_id)).execute()
    except APIError as exc:
        if _is_missing_hover_route_table_error(exc):
            return None
        raise
    return route
