"""Gallery service – CRUD for galleries and gallery items (images/videos)."""

import uuid


def _generate_share_token():
    return uuid.uuid4().hex[:12]


# ---------------------------------------------------------------------------
# Gallery CRUD
# ---------------------------------------------------------------------------

def create_gallery(sb, user_id, org_id, name='Gallery', workspace_id=None):
    token = _generate_share_token()
    row = {
        'user_id': str(user_id),
        'name': name,
        'share_token': token,
    }
    if org_id:
        row['org_id'] = str(org_id)
    if workspace_id:
        row['workspace_id'] = str(workspace_id)
    try:
        resp = sb.table('galleries').insert(row).execute()
    except Exception as e:
        # Backward compatibility when workspace_id column is not yet migrated.
        msg = str(e).lower()
        if 'workspace_id' in row and 'workspace_id' in msg and ('column' in msg or 'does not exist' in msg):
            row.pop('workspace_id', None)
            resp = sb.table('galleries').insert(row).execute()
        else:
            raise
    data = resp.data
    return data[0] if data else None


def get_gallery(sb, gallery_id):
    resp = sb.table('galleries').select('*').eq('id', str(gallery_id)).execute()
    data = resp.data
    return data[0] if data else None


def get_gallery_by_token(sb, token):
    resp = sb.table('galleries').select('*').eq('share_token', str(token)).execute()
    data = resp.data
    return data[0] if data else None


def list_galleries(sb, user_id, workspace_id=None):
    q = (
        sb.table('galleries')
        .select('*')
        .eq('user_id', str(user_id))
    )
    if workspace_id is not None:
        q = q.eq('workspace_id', str(workspace_id))
    try:
        resp = q.order('created_at', desc=True).execute()
    except Exception as e:
        # Backward compatibility when workspace_id column is not yet migrated.
        msg = str(e).lower()
        if workspace_id is not None and 'workspace_id' in msg and ('column' in msg or 'does not exist' in msg):
            resp = (
                sb.table('galleries')
                .select('*')
                .eq('user_id', str(user_id))
                .order('created_at', desc=True)
                .execute()
            )
        else:
            raise
    return resp.data or []


def update_gallery(sb, gallery_id, **fields):
    clean = {}
    for k, v in fields.items():
        if k in ('name', 'workspace_id'):
            clean[k] = v
    if not clean:
        return None
    resp = sb.table('galleries').update(clean).eq('id', str(gallery_id)).execute()
    data = resp.data
    return data[0] if data else None


def delete_gallery(sb, gallery_id):
    gal = get_gallery(sb, gallery_id)
    if not gal:
        return None
    sb.table('galleries').delete().eq('id', str(gallery_id)).execute()
    return gal


# ---------------------------------------------------------------------------
# Gallery Item CRUD
# ---------------------------------------------------------------------------

def list_items(sb, gallery_id):
    resp = (
        sb.table('gallery_items')
        .select('*')
        .eq('gallery_id', str(gallery_id))
        .order('sort_order')
        .execute()
    )
    return resp.data or []


def get_item(sb, item_id):
    resp = sb.table('gallery_items').select('*').eq('id', str(item_id)).execute()
    data = resp.data
    return data[0] if data else None


def create_item(sb, gallery_id, name, filename, media_type='image',
                media_width=0, media_height=0, file_size_bytes=0, sort_order=0,
                is_360=False):
    row = {
        'gallery_id': str(gallery_id),
        'name': name,
        'filename': filename,
        'media_type': media_type,
        'is_360': bool(is_360),
        'media_width': media_width,
        'media_height': media_height,
        'file_size_bytes': file_size_bytes,
        'sort_order': sort_order,
    }
    try:
        resp = sb.table('gallery_items').insert(row).execute()
    except Exception as e:
        # Backward compatibility when is_360 column is not yet migrated.
        msg = str(e).lower()
        if 'is_360' in row and 'is_360' in msg and ('column' in msg or 'does not exist' in msg):
            row.pop('is_360', None)
            resp = sb.table('gallery_items').insert(row).execute()
        else:
            raise
    data = resp.data
    return data[0] if data else None


def update_item(sb, item_id, **fields):
    clean = {}
    for k, v in fields.items():
        if k in ('name', 'sort_order', 'filename', 'media_type',
                 'media_width', 'media_height', 'file_size_bytes', 'is_360'):
            clean[k] = bool(v) if k == 'is_360' else v
    if not clean:
        return None
    try:
        resp = sb.table('gallery_items').update(clean).eq('id', str(item_id)).execute()
    except Exception as e:
        # Backward compatibility when is_360 column is not yet migrated.
        msg = str(e).lower()
        if 'is_360' in clean and 'is_360' in msg and ('column' in msg or 'does not exist' in msg):
            clean.pop('is_360', None)
            if not clean:
                return get_item(sb, item_id)
            resp = sb.table('gallery_items').update(clean).eq('id', str(item_id)).execute()
        else:
            raise
    data = resp.data
    return data[0] if data else None


def delete_item(sb, item_id):
    item = get_item(sb, item_id)
    if not item:
        return None
    sb.table('gallery_items').delete().eq('id', str(item_id)).execute()
    return item


def reorder_items(sb, gallery_id, ordered_ids):
    for idx, item_id in enumerate(ordered_ids):
        sb.table('gallery_items').update({'sort_order': idx}).eq('id', str(item_id)).eq('gallery_id', str(gallery_id)).execute()


def get_next_sort_order(sb, gallery_id):
    items = list_items(sb, gallery_id)
    if not items:
        return 0
    return max(it.get('sort_order', 0) for it in items) + 1
