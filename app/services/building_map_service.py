"""
Building Map + Building Map Images + Building Zone CRUD operations against Supabase.
"""
import json
import uuid

# Columns added by db/migration_building_plan_links.sql. Older databases lack
# them, so writes retry without them and reads treat them as empty.
ZONE_LINK_FIELDS = ('link_type', 'linked_building_map_id', 'meta')
ZONE_LINK_TYPES = ('', 'panorama', 'floor_plan', 'building_map')
MIGRATION_HINT = 'Run db/migration_building_plan_links.sql in Supabase to enable building plan links'


def _generate_share_token():
    return uuid.uuid4().hex[:12]


def is_missing_schema_error(exc, *names):
    """True when PostgREST says a table/column from `names` does not exist."""
    msg = str(exc or '').lower()
    if not any(n.lower() in msg for n in names):
        return False
    return any(k in msg for k in ('does not exist', 'schema cache', 'could not find', 'pgrst204', 'pgrst205', '42703'))


def zone_link_type(zone):
    """Effective link type of a zone, inferred for rows saved before link_type existed."""
    zone = zone or {}
    lt = str(zone.get('link_type') or '').strip()
    if lt in ZONE_LINK_TYPES and lt:
        return lt
    if zone.get('linked_building_map_id'):
        return 'building_map'
    if zone.get('linked_floor_plan_item_id'):
        return 'floor_plan'
    if zone.get('linked_panorama_id'):
        return 'panorama'
    return ''


def normalize_zone_meta(raw):
    """Keep only the info-card fields the customer view renders."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            raw = {}
    if not isinstance(raw, dict):
        return {}
    out = {}
    for key, cap in (('subtitle', 120), ('configurations', 120), ('unit_type', 120),
                     ('area', 60), ('price', 60), ('label', 40)):
        val = str(raw.get(key) or '').strip()[:cap]
        if val:
            out[key] = val
    for key in ('floors', 'units'):
        try:
            n = int(raw.get(key))
            if 0 <= n <= 100000:
                out[key] = n
        except (TypeError, ValueError):
            pass
    for key in ('size_min', 'size_max'):
        try:
            n = float(raw.get(key))
            if 0 <= n <= 10_000_000:
                out[key] = int(n) if n.is_integer() else n
        except (TypeError, ValueError):
            pass
    status = str(raw.get('status') or '').strip().lower()
    if status in ('available', 'sold', 'hold'):
        out['status'] = status
    if raw.get('hide_interest') in (True, 'true', 1, '1'):
        out['hide_interest'] = True
    # Per-floor statuses for the units of a (shared) floor map: {unit_zone_id: status}.
    us = raw.get('unit_status')
    if isinstance(us, dict):
        clean = {}
        for k, v in list(us.items())[:200]:
            v = str(v or '').strip().lower()
            if str(k).isdigit() and v in ('available', 'sold', 'hold'):
                clean[str(k)] = v
        if clean:
            out['unit_status'] = clean
    return out


def normalize_view_config(raw):
    """Per-map customer view settings."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            raw = {}
    if not isinstance(raw, dict):
        return {}
    out = {}
    level = str(raw.get('level') or '').strip().lower()
    if level in ('aerial', 'tower', 'floor'):
        out['level'] = level
    for key, cap in (('brand_name', 60), ('rera_number', 120), ('vr_tour_url', 500)):
        val = str(raw.get(key) or '').strip()[:cap]
        if val:
            out[key] = val
    if raw.get('show_interest') in (False, 'false', 0, '0'):
        out['show_interest'] = False
    lqip = str(raw.get('lqip') or '')
    if lqip.startswith('data:image/jpeg;base64,') and len(lqip) <= 4000:
        out['lqip'] = lqip
    return out


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
        elif k == 'view_config':
            clean[k] = normalize_view_config(v)
    if not clean:
        return None
    try:
        resp = sb.table('building_maps').update(clean).eq('id', str(map_id)).execute()
    except Exception as exc:
        if 'view_config' not in clean or not is_missing_schema_error(exc, 'view_config'):
            raise
        raise ValueError(MIGRATION_HINT)
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
    try:
        resp = (
            sb.table('building_map_images')
            .select('*')
            .eq('building_map_id', str(map_id))
            .order('sort_order')
            .execute()
        )
    except Exception as exc:
        if is_missing_schema_error(exc, 'building_map_images'):
            return []
        raise
    return resp.data or []


def list_images_for_maps(sb, map_ids):
    """{map_id: [images]} for many maps in one query."""
    ids = [str(m) for m in map_ids if m]
    out = {m: [] for m in ids}
    if not ids:
        return out
    try:
        rows = (
            sb.table('building_map_images')
            .select('*')
            .in_('building_map_id', ids)
            .order('sort_order')
            .execute()
            .data or []
        )
    except Exception as exc:
        if is_missing_schema_error(exc, 'building_map_images'):
            return out
        raise
    for row in rows:
        out.setdefault(str(row.get('building_map_id')), []).append(row)
    return out


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


def list_zones_for_maps(sb, map_ids):
    """{map_id: [zones]} for many maps in one query."""
    ids = [str(m) for m in map_ids if m]
    out = {m: [] for m in ids}
    if not ids:
        return out
    rows = (
        sb.table('building_zones')
        .select('*')
        .in_('building_map_id', ids)
        .order('floor_number')
        .order('sort_order')
        .execute()
        .data or []
    )
    for row in rows:
        out.setdefault(str(row.get('building_map_id')), []).append(row)
    return out


def list_zones_for_image(sb, image_id):
    try:
        resp = (
            sb.table('building_zones')
            .select('*')
            .eq('image_id', str(image_id))
            .order('floor_number')
            .order('sort_order')
            .execute()
        )
    except Exception as exc:
        if is_missing_schema_error(exc, 'image_id'):
            return []
        raise
    return resp.data or []


def get_zone(sb, zone_id):
    resp = sb.table('building_zones').select('*').eq('id', int(zone_id)).execute()
    data = resp.data
    return data[0] if data else None


def _insert_zone_rows(sb, rows):
    try:
        return sb.table('building_zones').insert(rows).execute().data or []
    except Exception as exc:
        if not is_missing_schema_error(exc, *ZONE_LINK_FIELDS):
            raise
        if any(r.get('linked_building_map_id') or r.get('meta') for r in rows):
            raise ValueError(MIGRATION_HINT)
        stripped = [{k: v for k, v in r.items() if k not in ZONE_LINK_FIELDS} for r in rows]
        return sb.table('building_zones').insert(stripped).execute().data or []


def _apply_link_fields(row, link_type=None, linked_building_map_id=None, meta=None):
    if link_type is not None:
        row['link_type'] = link_type if link_type in ZONE_LINK_TYPES else ''
    if linked_building_map_id:
        row['linked_building_map_id'] = str(linked_building_map_id)
    if meta is not None:
        row['meta'] = normalize_zone_meta(meta)
    return row


def create_zone(sb, map_id, name, floor_number, points, color='green',
                linked_panorama_id=None, linked_floor_plan_item_id=None,
                sort_order=0, image_id=None, link_type=None,
                linked_building_map_id=None, meta=None):
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
    _apply_link_fields(row, link_type, linked_building_map_id, meta)
    data = _insert_zone_rows(sb, [row])
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
        _apply_link_fields(row, z.get('link_type'), z.get('linked_building_map_id'), z.get('meta'))
        rows.append(row)
    if not rows:
        return []
    return _insert_zone_rows(sb, rows)


def update_zone(sb, zone_id, **fields):
    clean = {}
    for k, v in fields.items():
        if k in ('name', 'floor_number', 'color', 'sort_order',
                 'linked_panorama_id', 'linked_floor_plan_item_id', 'image_id',
                 'linked_building_map_id'):
            clean[k] = v
        elif k == 'link_type':
            clean[k] = v if v in ZONE_LINK_TYPES else ''
        elif k == 'meta':
            clean[k] = normalize_zone_meta(v)
        elif k == 'points':
            clean[k] = json.dumps(v) if not isinstance(v, str) else v
    if not clean:
        return None
    try:
        resp = sb.table('building_zones').update(clean).eq('id', int(zone_id)).execute()
    except Exception as exc:
        if not is_missing_schema_error(exc, *ZONE_LINK_FIELDS):
            raise
        if clean.get('linked_building_map_id') or clean.get('meta'):
            raise ValueError(MIGRATION_HINT)
        clean = {k: v for k, v in clean.items() if k not in ZONE_LINK_FIELDS}
        if not clean:
            return get_zone(sb, zone_id)
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
