"""
Sales flat-360 view CRUD operations against Supabase.
Used for horizontal drag panorama-strip sales tool.
"""
import uuid


def _generate_share_token():
    return uuid.uuid4().hex[:12]


def create_sales_flat360_view(sb, user_id, org_id, name, image_filename, image_width=0, image_height=0, workspace_id=None):
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
    resp = sb.table('sales_flat360_views').insert(row).execute()
    data = resp.data
    return data[0] if data else None


def get_sales_flat360_view(sb, view_id):
    resp = sb.table('sales_flat360_views').select('*').eq('id', str(view_id)).execute()
    data = resp.data
    return data[0] if data else None


def get_sales_flat360_view_by_token(sb, token):
    resp = sb.table('sales_flat360_views').select('*').eq('share_token', str(token)).execute()
    data = resp.data
    return data[0] if data else None


def list_sales_flat360_views(sb, user_id, workspace_id=None):
    q = (
        sb.table('sales_flat360_views')
        .select('*')
        .eq('user_id', str(user_id))
        .order('created_at', desc=True)
    )
    if workspace_id:
        q = q.eq('workspace_id', str(workspace_id))
    resp = q.execute()
    return resp.data or []


def update_sales_flat360_view(sb, view_id, **fields):
    clean = {}
    for k, v in fields.items():
        if k in ('name', 'workspace_id'):
            clean[k] = v
    if not clean:
        return None
    resp = sb.table('sales_flat360_views').update(clean).eq('id', str(view_id)).execute()
    data = resp.data
    return data[0] if data else None


def delete_sales_flat360_view(sb, view_id):
    item = get_sales_flat360_view(sb, view_id)
    if not item:
        return None
    sb.table('sales_flat360_views').delete().eq('id', str(view_id)).execute()
    return item

