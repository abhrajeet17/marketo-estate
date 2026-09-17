"""
Project: CRUD, access, main_panorama_id. Helpers for serialization and permissions.
"""
import json
import re
from datetime import datetime

from app.core.auth import get_profile
from app.services.panorama_service import get_panorama_by_id, list_panoramas_for_user


def _is_workspace_schema_missing(exc):
    msg = str(exc).lower()
    if 'workspace_id' in msg and ('column' in msg or 'does not exist' in msg):
        return True
    if 'workspaces' in msg and ('relation' in msg or 'does not exist' in msg):
        return True
    if 'workspace_access' in msg and ('relation' in msg or 'does not exist' in msg):
        return True
    if 'workspace_share_endpoints' in msg and ('relation' in msg or 'does not exist' in msg):
        return True
    return False


_SHARE_ENDPOINT_RE = re.compile(r'^[a-z0-9][a-z0-9-]{2,62}$')


def normalize_workspace_share_endpoint(raw_value):
    value = str(raw_value or '').strip().lower()
    if not value:
        return ''
    value = re.sub(r'[^a-z0-9-]+', '-', value)
    value = re.sub(r'-+', '-', value).strip('-')
    if not value:
        return ''
    if not _SHARE_ENDPOINT_RE.match(value):
        return None
    return value


def serialize_workspace_row(row, access_type='owner'):
    out = dict(row or {})
    if out.get('id') is not None:
        out['id'] = str(out.get('id'))
    if out.get('user_id') is not None:
        out['user_id'] = str(out.get('user_id'))
    if out.get('org_id') is not None:
        out['org_id'] = str(out.get('org_id'))
    for k in ('created_at', 'updated_at', 'launch_date'):
        if out.get(k):
            out[k] = str(out.get(k))
    if out.get('main_panorama_id') is not None:
        try:
            out['main_panorama_id'] = int(out['main_panorama_id'])
        except (TypeError, ValueError):
            out['main_panorama_id'] = None
    else:
        out['main_panorama_id'] = None
    if 'is_published' in out:
        out['is_published'] = bool(out.get('is_published'))
    if 'panaroma_menu_config' in out:
        cfg = out.get('panaroma_menu_config')
        if isinstance(cfg, str):
            try:
                out['panaroma_menu_config'] = json.loads(cfg)
            except Exception:
                out['panaroma_menu_config'] = {}
        elif not isinstance(cfg, dict):
            out['panaroma_menu_config'] = {}
    out['access_type'] = access_type
    return out


def get_workspace_by_id(sb, workspace_id):
    r = sb.table('workspaces').select('*').eq('id', workspace_id).limit(1).execute()
    if r.data and len(r.data) > 0:
        return dict(r.data[0])
    return None


def clear_workspace_main_for_panorama(sb, panorama_id):
    try:
        sb.table('workspaces').update({
            'main_panorama_id': None,
            'updated_at': datetime.utcnow().isoformat()
        }).eq('main_panorama_id', panorama_id).execute()
    except Exception:
        pass


def can_manage_workspace(sb, workspace, user_id, role):
    if not workspace:
        return False
    if str(workspace.get('user_id') or '') == str(user_id):
        return True
    if role not in ('admin', 'superadmin'):
        return False
    if role == 'superadmin':
        return True
    try:
        caller = get_profile(sb, user_id) or {}
        caller_org = caller.get('org_id')
    except Exception:
        caller_org = None
    workspace_org = workspace.get('org_id')
    return bool(caller_org and workspace_org and str(caller_org) == str(workspace_org))


def list_workspaces(sb, user_id, lightweight=False, include_empty_shared=False):
    select_fields = 'id, user_id, org_id, name, created_at, updated_at, main_panorama_id'
    try:
        if lightweight:
            owned = (
                sb.table('workspaces')
                .select(select_fields)
                .eq('user_id', user_id)
                .order('updated_at', desc=True)
                .execute()
            )
        else:
            owned = sb.table('workspaces').select('*').eq('user_id', user_id).order('updated_at', desc=True).execute()
    except Exception:
        owned = (
            sb.table('workspaces')
            .select(select_fields)
            .eq('user_id', user_id)
            .order('updated_at', desc=True)
            .execute()
        )

    try:
        shared_acc = sb.table('workspace_access').select('workspace_id, access_type').eq('user_id', user_id).execute()
        shared_rows_data = shared_acc.data or []
    except Exception:
        shared_rows_data = []
    out = []
    by_id = {}
    for row in (owned.data or []):
        item = serialize_workspace_row(row, 'owner')
        by_id[item['id']] = item
        out.append(item)

    shared_map = {}
    for row in shared_rows_data:
        wsid = row.get('workspace_id')
        if not wsid or str(wsid) in by_id:
            continue
        shared_map[str(wsid)] = str(row.get('access_type') or 'viewer')

    if shared_map:
        try:
            if lightweight:
                shared_rows = sb.table('workspaces').select(select_fields).in_('id', list(shared_map.keys())).execute()
            else:
                shared_rows = sb.table('workspaces').select('*').in_('id', list(shared_map.keys())).execute()
        except Exception:
            shared_rows = sb.table('workspaces').select(select_fields).in_('id', list(shared_map.keys())).execute()
        for row in (shared_rows.data or []):
            wsid = str(row.get('id'))
            access_type = shared_map.get(wsid, 'viewer')
            item = serialize_workspace_row(row, access_type)
            by_id[wsid] = item
            out.append(item)

    if lightweight:
        for row in out:
            row['panorama_count'] = 0
        out.sort(key=lambda x: ((x.get('access_type') != 'owner'), str(x.get('name') or '').lower()))
        return out

    counts = {}
    for pano in (list_panoramas_for_user(sb, user_id) or []):
        wsid = pano.get('workspace_id') if isinstance(pano, dict) else None
        if not wsid:
            continue
        key = str(wsid)
        counts[key] = int(counts.get(key, 0)) + 1
    for row in out:
        row['panorama_count'] = int(counts.get(str(row.get('id')), 0))

    if not include_empty_shared:
        out = [row for row in out if str(row.get('access_type') or 'viewer') == 'owner' or int(row.get('panorama_count') or 0) > 0]
    out.sort(key=lambda x: ((x.get('access_type') != 'owner'), str(x.get('name') or '').lower()))
    return out


_PROJECT_KEYS = (
    'location_address', 'location_city', 'location_state', 'location_lat', 'location_lng',
    'google_maps_link', 'rera_registration', 'launch_date', 'possession_date', 'builder_name',
    'project_type', 'total_area', 'description', 'amenities', 'is_published',
    'brochure_url', 'contact_phone', 'contact_email',
)


def project_fields_from_payload(payload):
    out = {}
    for k in _PROJECT_KEYS:
        if k not in payload or payload[k] is None:
            continue
        v = payload[k]
        if k == 'location_lat' or k == 'location_lng':
            try:
                out[k] = float(v)
            except (TypeError, ValueError):
                pass
        elif k == 'launch_date':
            out[k] = str(v).strip() or None
        elif k == 'amenities':
            if isinstance(v, list):
                out[k] = v
            elif isinstance(v, str):
                try:
                    out[k] = json.loads(v)
                except Exception:
                    out[k] = []
        elif k == 'is_published':
            out[k] = str(v).lower() in ('true', '1')
        else:
            out[k] = str(v).strip() if v else ''
    return out


def create_workspace(sb, user_id, name, **project_fields):
    if not name or len(name) > 120:
        raise ValueError('name required and max 120 chars')
    now = datetime.utcnow().isoformat()
    org_id = None
    try:
        profile = get_profile(sb, user_id) or {}
        org_id = profile.get('org_id')
    except Exception:
        pass
    row = {
        'user_id': user_id,
        'org_id': org_id,
        'name': name,
        'created_at': now,
        'updated_at': now,
    }
    for k in _PROJECT_KEYS:
        if k in project_fields and project_fields[k] is not None:
            row[k] = project_fields[k]
    try:
        r = sb.table('workspaces').insert(row).execute()
    except Exception:
        for k in list(row.keys()):
            if k in _PROJECT_KEYS:
                del row[k]
        r = sb.table('workspaces').insert(row).execute()
    created = (r.data or [None])[0]
    return serialize_workspace_row(created or row, 'owner')


def update_workspace(sb, workspace_id, user_id, name=None, main_panorama_id=None, allow_admin_override=False, **project_fields):
    workspace = get_workspace_by_id(sb, workspace_id)
    if not workspace:
        return None
    is_owner = str(workspace.get('user_id') or '') == str(user_id)
    if not is_owner and not allow_admin_override:
        return None
    update_fields = {'updated_at': datetime.utcnow().isoformat()}
    if name is not None:
        if len(name) > 120:
            raise ValueError('name max 120 chars')
        update_fields['name'] = name
    if main_panorama_id is not None:
        if main_panorama_id <= 0:
            update_fields['main_panorama_id'] = None
        else:
            pano = get_panorama_by_id(sb, main_panorama_id)
            if not pano or str(pano.get('workspace_id') or '') != str(workspace_id):
                raise ValueError('Panorama not in workspace')
            update_fields['main_panorama_id'] = main_panorama_id
    for k in _PROJECT_KEYS:
        if k in project_fields:
            update_fields[k] = project_fields[k]
    try:
        sb.table('workspaces').update(update_fields).eq('id', workspace_id).execute()
    except Exception:
        for k in list(update_fields.keys()):
            if k in _PROJECT_KEYS:
                del update_fields[k]
        sb.table('workspaces').update(update_fields).eq('id', workspace_id).execute()
    merged = dict(workspace)
    merged.update(update_fields)
    return serialize_workspace_row(merged, 'owner')


def delete_workspace(sb, workspace_id, user_id, allow_admin_override=False):
    workspace = get_workspace_by_id(sb, workspace_id)
    if not workspace:
        return False
    is_owner = str(workspace.get('user_id') or '') == str(user_id)
    if not is_owner and not allow_admin_override:
        return False
    sb.table('workspaces').delete().eq('id', workspace_id).execute()
    return True


def get_workspace_schema_error_response():
    return {'error': 'Project schema missing. Run db/schema.sql in Supabase SQL Editor.'}, 503


def is_workspace_schema_missing(exc):
    return _is_workspace_schema_missing(exc)


def update_customer_config(sb, workspace_id, user_id, role, config):
    workspace = get_workspace_by_id(sb, workspace_id)
    if not workspace:
        return None
    if not can_manage_workspace(sb, workspace, user_id, role):
        return None
    if not isinstance(config, dict):
        raise ValueError('config must be a JSON object')
    sb.table('workspaces').update({
        'panaroma_menu_config': json.dumps(config),
        'updated_at': datetime.utcnow().isoformat(),
    }).eq('id', workspace_id).execute()
    merged = dict(workspace)
    merged['panaroma_menu_config'] = config
    return serialize_workspace_row(merged, 'owner')


def get_customer_config(sb, workspace_id):
    workspace = get_workspace_by_id(sb, workspace_id)
    if not workspace:
        return None
    cfg = workspace.get('panaroma_menu_config') or workspace.get('panorama_menu_config')
    if cfg is None:
        return {}
    if isinstance(cfg, str):
        try:
            return json.loads(cfg)
        except Exception:
            return {}
    if isinstance(cfg, dict):
        return cfg
    return {}


def ensure_panorama_added_to_workspace_config(sb, workspace_id, new_panorama_id, user_id, role):
    workspace = get_workspace_by_id(sb, workspace_id)
    if not workspace or not can_manage_workspace(sb, workspace, user_id, role):
        return
    config = get_customer_config(sb, workspace_id) or {}
    if not isinstance(config.get('panoramaList'), dict):
        config['panoramaList'] = {}
    pl = config['panoramaList']
    if not isinstance(pl.get('hiddenByPanorama'), dict):
        pl['hiddenByPanorama'] = {}
    hbp = pl['hiddenByPanorama']
    new_id = str(new_panorama_id)
    hbp[new_id] = []
    try:
        r = sb.table('panoramas').select('id').eq('workspace_id', workspace_id).eq('is_360', True).execute()
        other_ids = [str(row['id']) for row in (r.data or []) if row.get('id') and str(row['id']) != new_id]
    except Exception:
        other_ids = []
    for oid in other_ids:
        arr = hbp.get(oid)
        if isinstance(arr, list) and new_id in arr:
            hbp[oid] = [x for x in arr if str(x) != new_id]
    try:
        sb.table('workspaces').update({
            'panaroma_menu_config': json.dumps(config),
            'updated_at': datetime.utcnow().isoformat(),
        }).eq('id', workspace_id).execute()
    except Exception:
        pass


def get_workspace_share_endpoint(sb, workspace_id):
    r = sb.table('workspace_share_endpoints').select('*').eq('workspace_id', workspace_id).limit(1).execute()
    if r.data and len(r.data) > 0:
        row = dict(r.data[0])
        if row.get('workspace_id') is not None:
            row['workspace_id'] = str(row.get('workspace_id'))
        if row.get('created_by') is not None:
            row['created_by'] = str(row.get('created_by'))
        if row.get('updated_by') is not None:
            row['updated_by'] = str(row.get('updated_by'))
        if row.get('created_at'):
            row['created_at'] = str(row.get('created_at'))
        if row.get('updated_at'):
            row['updated_at'] = str(row.get('updated_at'))
        return row
    return None


def is_workspace_share_endpoint_available(sb, endpoint, exclude_workspace_id=None):
    normalized = normalize_workspace_share_endpoint(endpoint)
    if normalized is None or not normalized:
        return False
    r = sb.table('workspace_share_endpoints').select('workspace_id').eq('endpoint', normalized).limit(1).execute()
    if not (r.data and len(r.data) > 0):
        return True
    used_by = str((r.data[0] or {}).get('workspace_id') or '')
    if exclude_workspace_id and used_by == str(exclude_workspace_id):
        return True
    return False


def update_workspace_share_endpoint(sb, workspace_id, user_id, role, endpoint):
    workspace = get_workspace_by_id(sb, workspace_id)
    if not workspace:
        return None
    if not can_manage_workspace(sb, workspace, user_id, role):
        return None
    normalized = normalize_workspace_share_endpoint(endpoint)
    now = datetime.utcnow().isoformat()
    existing = get_workspace_share_endpoint(sb, workspace_id)
    if normalized is None:
        raise ValueError('Endpoint must use only lowercase letters, numbers, hyphens, and be 3-63 chars')
    if not normalized:
        if existing:
            sb.table('workspace_share_endpoints').delete().eq('workspace_id', workspace_id).execute()
        return {'workspace_id': str(workspace_id), 'endpoint': None}
    if not is_workspace_share_endpoint_available(sb, normalized, workspace_id):
        raise ValueError('Endpoint already in use')
    if existing:
        sb.table('workspace_share_endpoints').update({
            'endpoint': normalized,
            'updated_by': user_id,
            'updated_at': now,
        }).eq('workspace_id', workspace_id).execute()
    else:
        sb.table('workspace_share_endpoints').insert({
            'workspace_id': workspace_id,
            'endpoint': normalized,
            'created_by': user_id,
            'updated_by': user_id,
            'created_at': now,
            'updated_at': now,
        }).execute()
    return {'workspace_id': str(workspace_id), 'endpoint': normalized}


def get_workspace_id_by_share_endpoint(sb, endpoint):
    normalized = normalize_workspace_share_endpoint(endpoint)
    if normalized is None or not normalized:
        return None
    r = sb.table('workspace_share_endpoints').select('workspace_id').eq('endpoint', normalized).limit(1).execute()
    if not (r.data and len(r.data) > 0):
        return None
    workspace_id = (r.data[0] or {}).get('workspace_id')
    return str(workspace_id) if workspace_id else None
