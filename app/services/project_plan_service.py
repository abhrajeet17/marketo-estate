"""
Project Plan CRUD operations against Supabase.
A project plan bundles multiple building maps into a single shareable view.
"""
import uuid


def _generate_share_token():
    return uuid.uuid4().hex[:12]


# ---------------------------------------------------------------------------
# Project Plan CRUD
# ---------------------------------------------------------------------------

def create_project_plan(sb, user_id, org_id, name, workspace_id=None):
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
    resp = sb.table('project_plans').insert(row).execute()
    data = resp.data
    return data[0] if data else None


def get_project_plan(sb, plan_id):
    resp = sb.table('project_plans').select('*').eq('id', str(plan_id)).execute()
    data = resp.data
    return data[0] if data else None


def get_project_plan_by_token(sb, token):
    resp = sb.table('project_plans').select('*').eq('share_token', str(token)).execute()
    data = resp.data
    return data[0] if data else None


def list_project_plans(sb, user_id):
    resp = (
        sb.table('project_plans')
        .select('*')
        .eq('user_id', str(user_id))
        .order('created_at', desc=True)
        .execute()
    )
    return resp.data or []


def update_project_plan(sb, plan_id, **fields):
    clean = {}
    for k, v in fields.items():
        if k in ('name', 'workspace_id'):
            clean[k] = v
    if not clean:
        return None
    resp = sb.table('project_plans').update(clean).eq('id', str(plan_id)).execute()
    data = resp.data
    return data[0] if data else None


def delete_project_plan(sb, plan_id):
    plan = get_project_plan(sb, plan_id)
    if not plan:
        return None
    sb.table('project_plans').delete().eq('id', str(plan_id)).execute()
    return plan


# ---------------------------------------------------------------------------
# Project Plan ↔ Building Maps link CRUD
# ---------------------------------------------------------------------------

def list_plan_maps(sb, plan_id):
    resp = (
        sb.table('project_plan_maps')
        .select('*')
        .eq('project_plan_id', str(plan_id))
        .order('sort_order')
        .execute()
    )
    return resp.data or []


def add_map_to_plan(sb, plan_id, building_map_id, sort_order=0):
    row = {
        'project_plan_id': str(plan_id),
        'building_map_id': str(building_map_id),
        'sort_order': sort_order,
    }
    resp = sb.table('project_plan_maps').insert(row).execute()
    data = resp.data
    return data[0] if data else None


def remove_map_from_plan(sb, plan_id, building_map_id):
    sb.table('project_plan_maps').delete() \
        .eq('project_plan_id', str(plan_id)) \
        .eq('building_map_id', str(building_map_id)) \
        .execute()
    return True


def get_next_plan_map_sort_order(sb, plan_id):
    maps = list_plan_maps(sb, plan_id)
    if not maps:
        return 0
    return max(m.get('sort_order', 0) for m in maps) + 1


def reorder_plan_maps(sb, plan_id, ordered_map_ids):
    """Reorder building maps within a plan."""
    for idx, map_id in enumerate(ordered_map_ids):
        sb.table('project_plan_maps') \
            .update({'sort_order': idx}) \
            .eq('project_plan_id', str(plan_id)) \
            .eq('building_map_id', str(map_id)) \
            .execute()
    return list_plan_maps(sb, plan_id)
