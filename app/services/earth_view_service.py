"""
Earth View, plot, and marker CRUD operations against Supabase.
"""
import json
import uuid


def _generate_share_token():
    return uuid.uuid4().hex[:12]


def create_earth_view(sb, user_id, org_id, name, center_lng=0, center_lat=20, zoom=3, workspace_id=None):
    token = _generate_share_token()
    row = {
        'user_id': str(user_id),
        'name': name,
        'share_token': token,
        'center_lng': float(center_lng),
        'center_lat': float(center_lat),
        'zoom': float(zoom),
    }
    if org_id:
        row['org_id'] = str(org_id)
    if workspace_id:
        row['workspace_id'] = str(workspace_id)
    try:
        resp = sb.table('earth_views').insert(row).execute()
    except Exception as e:
        # Backward compatibility for deployments without workspace_id on earth_views.
        msg = str(e).lower()
        if 'workspace_id' in row and 'workspace_id' in msg and ('column' in msg or 'does not exist' in msg):
            row.pop('workspace_id', None)
            resp = sb.table('earth_views').insert(row).execute()
        else:
            raise
    data = resp.data
    return data[0] if data else None


def get_earth_view(sb, view_id):
    resp = sb.table('earth_views').select('*').eq('id', str(view_id)).execute()
    data = resp.data
    return data[0] if data else None


def get_earth_view_by_token(sb, token):
    resp = sb.table('earth_views').select('*').eq('share_token', str(token)).execute()
    data = resp.data
    return data[0] if data else None


def list_earth_views(sb, user_id, workspace_id=None):
    q = (
        sb.table('earth_views')
        .select('*')
        .eq('user_id', str(user_id))
    )
    if workspace_id is not None:
        q = q.eq('workspace_id', str(workspace_id))
    try:
        resp = q.order('created_at', desc=True).execute()
    except Exception as e:
        # Backward compatibility for deployments without workspace_id on earth_views.
        msg = str(e).lower()
        if workspace_id is not None and 'workspace_id' in msg and ('column' in msg or 'does not exist' in msg):
            resp = (
                sb.table('earth_views')
                .select('*')
                .eq('user_id', str(user_id))
                .order('created_at', desc=True)
                .execute()
            )
        else:
            raise
    return resp.data or []


def update_earth_view(sb, view_id, **fields):
    clean = {}
    for key, value in fields.items():
        if key in ('name', 'center_lng', 'center_lat', 'zoom', 'workspace_id'):
            clean[key] = value
    if not clean:
        return None
    try:
        resp = sb.table('earth_views').update(clean).eq('id', str(view_id)).execute()
    except Exception as e:
        msg = str(e).lower()
        if 'workspace_id' in clean and 'workspace_id' in msg and ('column' in msg or 'does not exist' in msg):
            clean.pop('workspace_id', None)
            if not clean:
                return get_earth_view(sb, view_id)
            resp = sb.table('earth_views').update(clean).eq('id', str(view_id)).execute()
        else:
            raise
    data = resp.data
    return data[0] if data else None


def delete_earth_view(sb, view_id):
    ev = get_earth_view(sb, view_id)
    if not ev:
        return None
    sb.table('earth_views').delete().eq('id', str(view_id)).execute()
    return ev


def list_plots(sb, earth_view_id):
    resp = (
        sb.table('earth_view_plots')
        .select('*')
        .eq('earth_view_id', str(earth_view_id))
        .order('sort_order')
        .order('created_at')
        .execute()
    )
    rows = resp.data or []
    for row in rows:
        if isinstance(row.get('points'), str):
            try:
                row['points'] = json.loads(row['points'])
            except Exception:
                row['points'] = []
    return rows


def get_plot(sb, plot_id):
    resp = sb.table('earth_view_plots').select('*').eq('id', int(plot_id)).execute()
    data = resp.data
    if data and isinstance(data[0].get('points'), str):
        try:
            data[0]['points'] = json.loads(data[0]['points'])
        except Exception:
            data[0]['points'] = []
    return data[0] if data else None


def create_plot(sb, earth_view_id, name, points, area='', price='', status='available',
                description='', color='green', media_photo='', media_video='',
                linked_panorama_id=None, sort_order=0):
    row = {
        'earth_view_id': str(earth_view_id),
        'name': name,
        'points': json.dumps(points) if not isinstance(points, str) else points,
        'area': area,
        'price': price,
        'status': status,
        'description': description,
        'color': color,
        'media_photo': media_photo,
        'media_video': media_video,
        'sort_order': int(sort_order),
    }
    if linked_panorama_id:
        row['linked_panorama_id'] = int(linked_panorama_id)
    resp = sb.table('earth_view_plots').insert(row).execute()
    data = resp.data
    return data[0] if data else None


def update_plot(sb, plot_id, **fields):
    clean = {}
    for key, value in fields.items():
        if key in ('name', 'area', 'price', 'status', 'description', 'color',
                   'media_photo', 'media_video', 'linked_panorama_id', 'sort_order'):
            clean[key] = value
        elif key == 'points':
            clean[key] = json.dumps(value) if not isinstance(value, str) else value
    if not clean:
        return None
    resp = sb.table('earth_view_plots').update(clean).eq('id', int(plot_id)).execute()
    data = resp.data
    return data[0] if data else None


def delete_plot(sb, plot_id):
    p = get_plot(sb, plot_id)
    if not p:
        return None
    sb.table('earth_view_plots').delete().eq('id', int(plot_id)).execute()
    return p


def list_markers(sb, earth_view_id):
    resp = (
        sb.table('earth_view_markers')
        .select('*')
        .eq('earth_view_id', str(earth_view_id))
        .order('created_at')
        .execute()
    )
    return resp.data or []


def get_marker(sb, marker_id):
    resp = sb.table('earth_view_markers').select('*').eq('id', str(marker_id)).execute()
    data = resp.data
    return data[0] if data else None


def create_marker(sb, earth_view_id, name, longitude, latitude, description='',
                  marker_color='#4ade80', linked_panorama_id=None,
                  media_photo='', media_video=''):
    row = {
        'earth_view_id': str(earth_view_id),
        'name': name,
        'description': description,
        'marker_color': marker_color,
        'longitude': float(longitude),
        'latitude': float(latitude),
        'media_photo': media_photo,
        'media_video': media_video,
    }
    if linked_panorama_id:
        row['linked_panorama_id'] = int(linked_panorama_id)
    resp = sb.table('earth_view_markers').insert(row).execute()
    data = resp.data
    return data[0] if data else None


def update_marker(sb, marker_id, **fields):
    clean = {}
    for key, value in fields.items():
        if key in ('name', 'description', 'marker_color', 'linked_panorama_id',
                   'media_photo', 'media_video', 'longitude', 'latitude'):
            clean[key] = value
    if not clean:
        return None
    resp = sb.table('earth_view_markers').update(clean).eq('id', str(marker_id)).execute()
    data = resp.data
    return data[0] if data else None


def delete_marker(sb, marker_id):
    m = get_marker(sb, marker_id)
    if not m:
        return None
    sb.table('earth_view_markers').delete().eq('id', str(marker_id)).execute()
    return m
