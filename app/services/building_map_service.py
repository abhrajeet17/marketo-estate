"""
Building Map + Building Map Images + Building Zone CRUD operations against Supabase.
"""
import json
import uuid


def _generate_share_token():
    return uuid.uuid4().hex[:12]


# ---------------------------------------------------------------------------
# Building Map CRUD
# ---------------------------------------------------------------------------

def create_building_map(sb, user_id, org_id, name, image_filename, image_width=0, image_height=0, catalogue_id=None, workspace_id=None):
    token = _generate_share_token()
    row = {
        'user_id': str(user_id),
        'name': name,
        'image_filename': image_filename,
        'image_width': image_width,
        'image_height': image_height,
        'share_token': token,
    }
    if org_id:
        row['org_id'] = str(org_id)
    if catalogue_id:
        row['catalogue_id'] = str(catalogue_id)
    if workspace_id:
        row['workspace_id'] = str(workspace_id)
    resp = sb.table('building_maps').insert(row).execute()
    data = resp.data
    return data[0] if data else None


def get_building_map(sb, map_id):
    resp = sb.table('building_maps').select('*').eq('id', str(map_id)).execute()
    data = resp.data
    return data[0] if data else None


def get_building_map_by_token(sb, token):
    resp = sb.table('building_maps').select('*').eq('share_token', str(token)).execute()
    data = resp.data
    return data[0] if data else None


def list_building_maps(sb, user_id):
    resp = (
        sb.table('building_maps')
        .select('*')
        .eq('user_id', str(user_id))
        .order('created_at', desc=True)
        .execute()
    )
    return resp.data or []


def update_building_map(sb, map_id, **fields):
    clean = {}
    for k, v in fields.items():
        if k in ('name', 'image_filename', 'image_width', 'image_height', 'catalogue_id', 'workspace_id'):
            clean[k] = v
    if not clean:
        return None
    resp = sb.table('building_maps').update(clean).eq('id', str(map_id)).execute()
    data = resp.data
    return data[0] if data else None


def delete_building_map(sb, map_id):
    bm = get_building_map(sb, map_id)
    if not bm:
        return None
    sb.table('building_maps').delete().eq('id', str(map_id)).execute()
    return bm


# ---------------------------------------------------------------------------
# Building Map Images CRUD
# ---------------------------------------------------------------------------

def list_images(sb, map_id):
    resp = (
        sb.table('building_map_images')
        .select('*')
        .eq('building_map_id', str(map_id))
        .order('sort_order')
        .execute()
    )
    return resp.data or []


def get_image(sb, image_id):
    resp = sb.table('building_map_images').select('*').eq('id', str(image_id)).execute()
    data = resp.data
    return data[0] if data else None


def create_image(sb, map_id, name, image_filename, image_width=0, image_height=0, sort_order=0):
    row = {
        'building_map_id': str(map_id),
        'name': name,
        'image_filename': image_filename,
        'image_width': image_width,
        'image_height': image_height,
        'sort_order': sort_order,
    }
    resp = sb.table('building_map_images').insert(row).execute()
    data = resp.data
    return data[0] if data else None


def update_image(sb, image_id, **fields):
    clean = {}
    for k, v in fields.items():
        if k in ('name', 'sort_order'):
            clean[k] = v
    if not clean:
        return None
    resp = sb.table('building_map_images').update(clean).eq('id', str(image_id)).execute()
    data = resp.data
    return data[0] if data else None


def delete_image(sb, image_id):
    img = get_image(sb, image_id)
    if not img:
        return None
    sb.table('building_map_images').delete().eq('id', str(image_id)).execute()
    return img


def get_next_image_sort_order(sb, map_id):
    images = list_images(sb, map_id)
    if not images:
        return 0
    return max(img.get('sort_order', 0) for img in images) + 1


# ---------------------------------------------------------------------------
# Building Zone CRUD
# ---------------------------------------------------------------------------

def list_zones(sb, map_id):
    resp = (
        sb.table('building_zones')
        .select('*')
        .eq('building_map_id', str(map_id))
        .order('floor_number')
        .order('sort_order')
        .execute()
    )
    return resp.data or []


def list_zones_for_image(sb, image_id):
    resp = (
        sb.table('building_zones')
        .select('*')
        .eq('image_id', str(image_id))
        .order('floor_number')
        .order('sort_order')
        .execute()
    )
    return resp.data or []


def get_zone(sb, zone_id):
    resp = sb.table('building_zones').select('*').eq('id', int(zone_id)).execute()
    data = resp.data
    return data[0] if data else None


def create_zone(sb, map_id, name, floor_number, points, color='green',
                linked_panorama_id=None, linked_floor_plan_item_id=None,
                sort_order=0, image_id=None):
    row = {
        'building_map_id': str(map_id),
        'name': name,
        'floor_number': int(floor_number),
        'points': json.dumps(points) if not isinstance(points, str) else points,
        'color': color,
        'sort_order': sort_order,
    }
    if image_id:
        row['image_id'] = str(image_id)
    if linked_panorama_id:
        row['linked_panorama_id'] = int(linked_panorama_id)
    if linked_floor_plan_item_id:
        row['linked_floor_plan_item_id'] = str(linked_floor_plan_item_id)
    resp = sb.table('building_zones').insert(row).execute()
    data = resp.data
    return data[0] if data else None


def batch_create_zones(sb, map_id, zones_data):
    """Create multiple zones at once. zones_data is a list of dicts."""
    rows = []
    for z in zones_data:
        row = {
            'building_map_id': str(map_id),
            'name': z.get('name', 'Zone'),
            'floor_number': int(z.get('floor_number', 0)),
            'points': json.dumps(z['points']) if not isinstance(z.get('points', '[]'), str) else z.get('points', '[]'),
            'color': z.get('color', 'green'),
            'sort_order': int(z.get('sort_order', 0)),
        }
        if z.get('image_id'):
            row['image_id'] = str(z['image_id'])
        if z.get('linked_panorama_id'):
            row['linked_panorama_id'] = int(z['linked_panorama_id'])
        if z.get('linked_floor_plan_item_id'):
            row['linked_floor_plan_item_id'] = str(z['linked_floor_plan_item_id'])
        rows.append(row)
    if not rows:
        return []
    resp = sb.table('building_zones').insert(rows).execute()
    return resp.data or []


def update_zone(sb, zone_id, **fields):
    clean = {}
    for k, v in fields.items():
        if k in ('name', 'floor_number', 'color', 'sort_order',
                 'linked_panorama_id', 'linked_floor_plan_item_id', 'image_id'):
            clean[k] = v
        elif k == 'points':
            clean[k] = json.dumps(v) if not isinstance(v, str) else v
    if not clean:
        return None
    resp = sb.table('building_zones').update(clean).eq('id', int(zone_id)).execute()
    data = resp.data
    return data[0] if data else None


def delete_zone(sb, zone_id):
    zone = get_zone(sb, zone_id)
    if not zone:
        return None
    sb.table('building_zones').delete().eq('id', int(zone_id)).execute()
    return zone


def get_floor_numbers(sb, map_id):
    """Get sorted list of distinct floor numbers for a building map."""
    zones = list_zones(sb, map_id)
    floors = sorted(set(z.get('floor_number', 0) for z in zones))
    return floors
