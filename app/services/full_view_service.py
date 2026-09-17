"""
Full View Creator - CRUD for full_view_configs and full_view_tabs.
"""

from datetime import datetime

_ALL_REF_FIELDS = (
    'ref_panorama_id',
    'ref_daynight_id',
    'ref_floor_plan_id',
    'ref_gallery_id',
    'ref_project_plan_id',
    'ref_sales_map_id',
    'ref_sales_flat360_id',
)

# Some deployments created these columns with the wrong SQL type, so we persist
# them inside content_data and hydrate them back onto the row on reads.
_CONTENT_DATA_REF_FIELDS = (
    'ref_daynight_id',
    'ref_project_plan_id',
)


def _as_content_data(value):
    return dict(value) if isinstance(value, dict) else {}


def _as_style_data(value):
    return dict(value) if isinstance(value, dict) else {}


def _normalize_ref_value(value):
    if value in (None, '', 'null'):
        return None
    text = str(value).strip()
    return text or None


def _hydrate_tab_refs(row):
    if not row:
        return row
    tab = dict(row)
    content_data = _as_content_data(tab.get('content_data'))
    for field in _CONTENT_DATA_REF_FIELDS:
        fallback = _normalize_ref_value(content_data.get(field))
        if fallback is not None:
            tab[field] = fallback
    tab['content_data'] = content_data
    return tab


def _prepare_tab_row(row):
    prepared = dict(row)
    content_data = _as_content_data(prepared.get('content_data'))
    for field in _CONTENT_DATA_REF_FIELDS:
        has_field = field in prepared
        value = _normalize_ref_value(prepared.get(field))
        if has_field:
            prepared[field] = None
        if value is None:
            content_data.pop(field, None)
            continue
        content_data[field] = value
    prepared['content_data'] = content_data
    return prepared


def _normalize_config_row(row):
    if not row:
        return row
    config = dict(row)
    config['style'] = _as_style_data(config.get('style'))
    return config


def _to_unix_ts(value):
    if not value:
        return 0.0
    text = str(value).strip()
    if not text:
        return 0.0
    try:
        # Supabase commonly returns UTC timestamps with trailing Z.
        return datetime.fromisoformat(text.replace('Z', '+00:00')).timestamp()
    except Exception:
        return 0.0


def _config_sort_key(row):
    style_blob = _as_style_data((row or {}).get('style'))
    return (
        1 if style_blob else 0,
        1 if bool((row or {}).get('is_active')) else 0,
        _to_unix_ts((row or {}).get('updated_at')),
        _to_unix_ts((row or {}).get('created_at')),
        str((row or {}).get('id') or ''),
    )


def _get_tab(sb, tab_id):
    resp = sb.table('full_view_tabs').select('*').eq('id', str(tab_id)).limit(1).execute()
    return resp.data[0] if resp.data else None


# ---------------------------------------------------------------------------
# Config CRUD
# ---------------------------------------------------------------------------

def get_config_for_workspace(sb, workspace_id):
    resp = (
        sb.table('full_view_configs')
        .select('*')
        .eq('workspace_id', str(workspace_id))
        .execute()
    )
    rows = [_normalize_config_row(row) for row in (resp.data or []) if row]
    if not rows:
        return None
    rows.sort(key=_config_sort_key, reverse=True)
    return rows[0]


def create_config(sb, workspace_id, user_id, org_id=None, style=None):
    row = {
        'workspace_id': str(workspace_id),
        'user_id': str(user_id),
        'is_active': True,
    }
    if style is not None:
        row['style'] = _as_style_data(style)
    if org_id:
        row['org_id'] = str(org_id)
    resp = sb.table('full_view_configs').insert(row).execute()
    return _normalize_config_row(resp.data[0]) if resp.data else None


def update_config(sb, config_id, **fields):
    clean = {k: v for k, v in fields.items() if k in {'is_active'}}
    if 'style' in fields:
        clean['style'] = _as_style_data(fields.get('style'))
    if not clean:
        return None
    clean['updated_at'] = datetime.utcnow().isoformat()
    resp = (
        sb.table('full_view_configs')
        .update(clean)
        .eq('id', str(config_id))
        .execute()
    )
    return _normalize_config_row(resp.data[0]) if resp.data else None


def delete_config(sb, config_id):
    sb.table('full_view_configs').delete().eq('id', str(config_id)).execute()
    return True


# ---------------------------------------------------------------------------
# Tab CRUD
# ---------------------------------------------------------------------------

_TAB_WRITABLE = {
    'icon', 'name', 'tab_type', 'is_visible', 'sort_order', 'content_data',
    'ref_panorama_id', 'ref_daynight_id', 'ref_floor_plan_id',
    'ref_gallery_id', 'ref_project_plan_id', 'ref_sales_map_id', 'ref_sales_flat360_id',
}


def list_tabs(sb, config_id, visible_only=False):
    q = (
        sb.table('full_view_tabs')
        .select('*')
        .eq('config_id', str(config_id))
        .order('sort_order', desc=False)
    )
    if visible_only:
        q = q.eq('is_visible', True)
    resp = q.execute()
    return [_hydrate_tab_refs(row) for row in (resp.data or [])]


def create_tab(sb, config_id, icon, name, tab_type, **kwargs):
    row = {
        'config_id': str(config_id),
        'icon': icon,
        'name': name,
        'tab_type': tab_type,
        'is_visible': kwargs.get('is_visible', True),
        'sort_order': kwargs.get('sort_order', 0),
        'content_data': kwargs.get('content_data') or {},
    }
    for field in _ALL_REF_FIELDS:
        val = kwargs.get(field)
        if val is not None:
            row[field] = val
    row = _prepare_tab_row(row)
    resp = sb.table('full_view_tabs').insert(row).execute()
    return _hydrate_tab_refs(resp.data[0]) if resp.data else None


def update_tab(sb, tab_id, **fields):
    clean = {k: v for k, v in fields.items() if k in _TAB_WRITABLE}
    if not clean:
        return None
    existing = _get_tab(sb, tab_id) or {}
    # Nullify all ref fields when switching types so stale refs don't persist
    if 'tab_type' in clean:
        for f in _ALL_REF_FIELDS:
            if f not in clean:
                clean[f] = None
    if 'content_data' not in clean:
        clean['content_data'] = existing.get('content_data') or {}
    clean = _prepare_tab_row(clean)
    resp = (
        sb.table('full_view_tabs')
        .update(clean)
        .eq('id', str(tab_id))
        .execute()
    )
    return _hydrate_tab_refs(resp.data[0]) if resp.data else None


def delete_tab(sb, tab_id):
    sb.table('full_view_tabs').delete().eq('id', str(tab_id)).execute()
    return True


def reorder_tabs(sb, config_id, tab_ids):
    """Bulk-update sort_order based on position in tab_ids list."""
    for i, tab_id in enumerate(tab_ids):
        sb.table('full_view_tabs').update({'sort_order': i}).eq(
            'id', str(tab_id)
        ).eq('config_id', str(config_id)).execute()
    return True


# ---------------------------------------------------------------------------
# Customer view helper
# ---------------------------------------------------------------------------

def get_config_with_tabs(sb, workspace_id):
    """Return config dict with 'tabs' list (visible only) for the customer view."""
    config = get_config_for_workspace(sb, workspace_id)
    if not config or not config.get('is_active'):
        return None
    tabs = list_tabs(sb, config['id'], visible_only=True)
    return {**config, 'tabs': tabs}
