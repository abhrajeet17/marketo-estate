"""
Day Night project CRUD operations against Supabase.
"""
import json
import uuid


def _generate_share_token():
    return uuid.uuid4().hex[:12]


def create_daynight_project(sb, user_id, org_id, name, media_type, workspace_id=None):
    token = _generate_share_token()
    row = {
        'user_id': str(user_id),
        'name': name,
        'media_type': media_type,
        'share_token': token,
    }
    if org_id:
        row['org_id'] = str(org_id)
    if workspace_id:
        row['workspace_id'] = str(workspace_id)
    try:
        resp = sb.table('daynight_projects').insert(row).execute()
    except Exception as e:
        # Backward compatibility when workspace_id column is not yet migrated.
        msg = str(e).lower()
        if 'workspace_id' in row and 'workspace_id' in msg and ('column' in msg or 'does not exist' in msg):
            row.pop('workspace_id', None)
            resp = sb.table('daynight_projects').insert(row).execute()
        else:
            raise
    data = resp.data
    if data and len(data) > 0:
        return data[0]
    return None


def get_daynight_project(sb, project_id):
    resp = sb.table('daynight_projects').select('*').eq('id', str(project_id)).execute()
    data = resp.data
    return data[0] if data else None


def get_daynight_project_by_token(sb, token):
    resp = sb.table('daynight_projects').select('*').eq('share_token', str(token)).execute()
    data = resp.data
    return data[0] if data else None


def list_daynight_projects(sb, user_id, workspace_id=None):
    q = (
        sb.table('daynight_projects')
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
                sb.table('daynight_projects')
                .select('*')
                .eq('user_id', str(user_id))
                .order('created_at', desc=True)
                .execute()
            )
        else:
            raise
    return resp.data or []


def update_daynight_project(sb, project_id, **fields):
    if not fields:
        return None
    clean = {}
    for k, v in fields.items():
        if k in (
            'name', 'stitched_filename', 'stitched_width', 'stitched_height',
            'video_filename', 'video_duration', 'join_positions', 'source_images',
            'drag_speed', 'workspace_id',
        ):
            if k in ('join_positions', 'source_images') and not isinstance(v, str):
                v = json.dumps(v)
            clean[k] = v
    if not clean:
        return None
    resp = sb.table('daynight_projects').update(clean).eq('id', str(project_id)).execute()
    data = resp.data
    return data[0] if data else None


def delete_daynight_project(sb, project_id):
    project = get_daynight_project(sb, project_id)
    if not project:
        return None
    sb.table('daynight_projects').delete().eq('id', str(project_id)).execute()
    return project
