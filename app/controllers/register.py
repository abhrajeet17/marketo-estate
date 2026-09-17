"""
Register all Flask routes. Uses app.core and app.services only.

Scaling policy:
- If an API route in this file is edited, move the touched route(s) into
  app/controllers/features/<domain>.py in the same change.
- Do not add new long-term API routes here; add them in feature modules and
  wire them via register_<feature>_routes(app).
"""
import json
import os
import re
import secrets
import time
import uuid
from html import escape
from datetime import datetime, timedelta
from urllib.parse import urlencode

import requests as _requests

from flask import request, jsonify, render_template, redirect, Response, send_from_directory, current_app, make_response
from werkzeug.utils import secure_filename
from werkzeug.exceptions import RequestEntityTooLarge
from itsdangerous import BadSignature, SignatureExpired

from app import config as app_config
from app.controllers.features.crm_pagination import crm_page_payload, crm_parse_page_args
from app.controllers.features import (
    register_asset_routes,
    register_crm_broker_routes,
    register_crm_contact_routes,
    register_crm_lock_routes,
    register_crm_master_routes,
    register_crm_normal_routes,
    register_crm_plot_routes,
    register_crm_quote_routes,
    register_crm_record_list_routes,
    register_daynight_routes,
    register_full_view_routes,
    register_gallery_routes,
    register_page_access_routes,
    register_resource_filters_routes,
    register_sales_route_map_routes,
    register_uam_routes,
)
from app.core.database import get_supabase
from app.services.access_policy import client_group_resource_ids_for_admin
from app.services.uam_reference_service import (
    BROKER_REFERRED_CONTACT_FIELDS,
    CLIENT_MEMBER_ROLE_BROKER,
    CLIENT_MEMBER_ROLE_CLIENT_ADMIN,
    CLIENT_MEMBER_ROLE_CLIENT_USER,
    _interest_has_broker_reference,
    _interest_contact_is_revealed,
    _is_broker_member_role,
    _normalize_client_member_role,
    _project_reference_users,
    _validate_project_reference_user,
    apply_broker_referred_contact_mask,
    apply_broker_referred_contact_mask_to_contact,
    can_user_reveal_broker_referred_contact,
    user_is_client_admin,
    viewer_should_mask_broker_referred_contact,
)
from app.core.auth import get_profile, require_auth, require_admin
from app.core.serializers import (
    page_access_serializer,
    panorama_upload_serializer,
    plot_upload_serializer,
    marker_upload_serializer,
    daynight_upload_serializer,
)
from app.services.panorama_service import (
    get_panorama_with_access,
    get_panorama_by_id,
    get_mobile_panorama_by_parent_id,
    can_edit_plots,
    can_delete_panorama,
)
from app.services.workspace_service import (
    get_workspace_by_id,
    serialize_workspace_row,
    clear_workspace_main_for_panorama,
    can_manage_workspace,
    create_workspace as ws_create_workspace,
    update_workspace as ws_update_workspace,
    delete_workspace as ws_delete_workspace,
    get_workspace_schema_error_response,
    is_workspace_schema_missing,
    project_fields_from_payload,
    update_customer_config as ws_update_customer_config,
    get_customer_config as ws_get_customer_config,
    ensure_panorama_added_to_workspace_config as ws_ensure_panorama_added_to_workspace_config,
    get_workspace_share_endpoint as ws_get_workspace_share_endpoint,
    is_workspace_share_endpoint_available as ws_is_workspace_share_endpoint_available,
    update_workspace_share_endpoint as ws_update_workspace_share_endpoint,
    get_workspace_id_by_share_endpoint as ws_get_workspace_id_by_share_endpoint,
    normalize_workspace_share_endpoint as ws_normalize_workspace_share_endpoint,
)
from app.services.storage_service import (
    use_s3,
    get_s3_client,
    panorama_object_key,
    get_panorama_s3_url,
    get_panorama_thumb_s3_url,
    generate_panorama_thumb_bytes,
    upload_panorama_thumb_to_s3,
    MAX_PANORAMA_THUMB_READ_BYTES,
    get_panorama_optimized_s3_url,
    generate_panorama_optimized_bytes,
    upload_panorama_optimized_to_s3,
    MAX_PANORAMA_OPTIMIZED_READ_BYTES,
    plot_object_key,
    get_plot_s3_url,
    delete_plot_from_s3,
    marker_object_key,
    marker_thumb_object_key,
    get_marker_s3_url,
    delete_marker_from_s3,
    voiceover_object_key,
    get_voiceover_s3_url,
    delete_voiceover_from_s3,
    panorama_audio_object_key,
    get_panorama_audio_s3_url,
    delete_panorama_audio_from_s3,
    MAX_PANORAMA_AUDIO_BYTES,
    delete_panorama_from_s3,
    upload_panorama_to_s3,
    read_uploaded_file_bytes,
    compress_marker_image,
    probe_image_dimensions,
    upload_daynight_to_s3,
    daynight_object_key,
    get_daynight_s3_url,
    delete_daynight_from_s3,
    stitch_images_horizontally,
    MAX_DAYNIGHT_IMAGE_READ_BYTES,
    buffer_uploaded_file,
    convert_floorplan_to_webp_lossless,
    upload_floorplan_to_s3,
    get_floorplan_s3_url,
    delete_floorplan_from_s3,
    MAX_FLOORPLAN_READ_BYTES,
    compress_building_map_image,
    upload_building_map_to_s3,
    get_building_map_s3_url,
    delete_building_map_from_s3,
    MAX_BUILDING_MAP_READ_BYTES,
    MAX_GALLERY_READ_BYTES,
    compress_sales_map_image,
    upload_sales_map_to_s3,
    get_sales_map_s3_url,
    delete_sales_map_from_s3,
    MAX_SALES_MAP_READ_BYTES,
    compress_sales_flat360_image,
    upload_sales_flat360_to_s3,
    get_sales_flat360_s3_url,
    delete_sales_flat360_from_s3,
    MAX_SALES_FLAT360_READ_BYTES,
)
from app.services.org_service import get_org_name_and_slug_for_panorama
from app.services.plot_service import fetch_plots, create_plot as plot_create, get_plot_panorama_id, delete_plot as plot_delete, update_plot as plot_update, update_plot_label_position as plot_update_label_position
from app.services.daynight_service import (
    create_daynight_project as dn_create,
    get_daynight_project as dn_get,
    get_daynight_project_by_token as dn_get_by_token,
    list_daynight_projects as dn_list,
    update_daynight_project as dn_update,
    delete_daynight_project as dn_delete,
)
from app.services.floorplan_service import (
    create_catalogue as fp_create_catalogue,
    get_catalogue as fp_get_catalogue,
    get_catalogue_by_token as fp_get_catalogue_by_token,
    list_catalogues as fp_list_catalogues,
    update_catalogue as fp_update_catalogue,
    delete_catalogue as fp_delete_catalogue,
    list_items as fp_list_items,
    get_item as fp_get_item,
    create_item as fp_create_item,
    update_item as fp_update_item,
    delete_item as fp_delete_item,
    reorder_items as fp_reorder_items,
    get_next_sort_order as fp_next_sort_order,
    catalogue_name_exists as fp_name_exists,
    get_item_counts as fp_get_item_counts,
    get_item_previews as fp_get_item_previews,
)
from app.services.building_map_service import (
    create_building_map as bm_create,
    get_building_map as bm_get,
    get_building_map_by_token as bm_get_by_token,
    list_building_maps as bm_list,
    update_building_map as bm_update,
    delete_building_map as bm_delete,
    list_images as bm_list_images,
    get_image as bm_get_image,
    create_image as bm_create_image,
    update_image as bm_update_image,
    delete_image as bm_delete_image,
    get_next_image_sort_order as bm_next_image_sort,
    list_zones as bm_list_zones,
    list_zones_for_image as bm_list_zones_for_image,
    get_zone as bm_get_zone,
    create_zone as bm_create_zone,
    batch_create_zones as bm_batch_create_zones,
    update_zone as bm_update_zone,
    delete_zone as bm_delete_zone,
    get_floor_numbers as bm_get_floors,
)
from app.services.project_plan_service import (
    create_project_plan as pp_create,
    get_project_plan as pp_get,
    get_project_plan_by_token as pp_get_by_token,
    list_project_plans as pp_list,
    update_project_plan as pp_update,
    delete_project_plan as pp_delete,
    list_plan_maps as pp_list_maps,
    add_map_to_plan as pp_add_map,
    remove_map_from_plan as pp_remove_map,
    get_next_plan_map_sort_order as pp_next_sort,
    reorder_plan_maps as pp_reorder,
)
from app.services.sales_route_map_service import (
    create_sales_map as srm_create,
    get_sales_map as srm_get,
    get_sales_map_by_token as srm_get_by_token,
    list_sales_maps as srm_list,
    update_sales_map as srm_update,
    delete_sales_map as srm_delete,
    list_markers as srm_list_markers,
    get_marker as srm_get_marker,
    create_marker as srm_create_marker,
    update_marker as srm_update_marker,
    delete_marker as srm_delete_marker,
    clear_main_marker as srm_clear_main_marker,
    get_next_marker_sort_order as srm_next_marker_sort,
    list_routes as srm_list_routes,
    get_route as srm_get_route,
    create_route as srm_create_route,
    update_route as srm_update_route,
    delete_route as srm_delete_route,
    get_next_route_sort_order as srm_next_route_sort,
    list_hover_routes as srm_list_hover_routes,
    get_hover_route as srm_get_hover_route,
    create_hover_route as srm_create_hover_route,
    update_hover_route as srm_update_hover_route,
    delete_hover_route as srm_delete_hover_route,
    get_next_hover_route_sort_order as srm_next_hover_route_sort,
)
from app.services.sales_flat360_service import (
    create_sales_flat360_view as sf360_create,
    get_sales_flat360_view as sf360_get,
    get_sales_flat360_view_by_token as sf360_get_by_token,
    list_sales_flat360_views as sf360_list,
    update_sales_flat360_view as sf360_update,
    delete_sales_flat360_view as sf360_delete,
)
from app.services.full_view_service import (
    get_config_for_workspace as fv_get_config,
    create_config as fv_create_config,
    update_config as fv_update_config,
    delete_config as fv_delete_config,
    list_tabs as fv_list_tabs,
    create_tab as fv_create_tab,
    update_tab as fv_update_tab,
    delete_tab as fv_delete_tab,
    reorder_tabs as fv_reorder_tabs,
    get_config_with_tabs as fv_get_config_with_tabs,
)
from app.services.earth_view_service import (
    create_earth_view as ev_create,
    get_earth_view as ev_get,
    get_earth_view_by_token as ev_get_by_token,
    list_earth_views as ev_list,
    update_earth_view as ev_update,
    delete_earth_view as ev_delete,
    list_plots as ev_list_plots,
    get_plot as ev_get_plot,
    create_plot as ev_create_plot,
    update_plot as ev_update_plot,
    delete_plot as ev_delete_plot,
    list_markers as ev_list_markers,
    get_marker as ev_get_marker,
    create_marker as ev_create_marker,
    update_marker as ev_update_marker,
    delete_marker as ev_delete_marker,
)
from app.config import (
    ALLOWED_EXTENSIONS,
    ALLOWED_AUDIO_EXTENSIONS,
    ALLOWED_VIDEO_EXTENSIONS,
    IMAGE_CONTENT_TYPES,
    AUDIO_CONTENT_TYPES,
    VIDEO_CONTENT_TYPES,
    CONTENT_TYPE_TO_EXT,
    PAGE_ACCESS_TOKEN_TTL,
    SUPABASE_S3_BUCKET,
    SUPABASE_S3_SIGNED_URL_TTL,
    SUPABASE_S3_UPLOAD_URL_TTL,
    MAX_DAYNIGHT_VIDEO_BYTES,
)

MAX_PLOT_IMAGE_BYTES = int(os.environ.get('MAX_PLOT_IMAGE_BYTES', str(25 * 1024 * 1024)))
MAX_MARKER_IMAGE_BYTES = int(os.environ.get('MAX_MARKER_IMAGE_BYTES', str(5 * 1024 * 1024)))
MAX_MARKER_VOICEOVER_BYTES = 10 * 1024 * 1024
ALLOWED_IMAGE_EXTENSIONS = ALLOWED_EXTENSIONS


def _detect_ext_from_content_type(content_type):
    ext = (content_type or '').lower().strip()
    ext = CONTENT_TYPE_TO_EXT.get(ext, 'jpg')
    return ext if ext in ALLOWED_EXTENSIONS else 'jpg'


def _detect_video_ext_from_content_type(content_type):
    content_type = str(content_type or '').split(';', 1)[0].lower().strip()
    for ext, mime in VIDEO_CONTENT_TYPES.items():
        if content_type == mime:
            return ext
    if content_type in ('video/x-m4v',):
        return 'mp4'
    return ''


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def auth_ctx():
    return {'supabase_url': app_config.SUPABASE_URL, 'supabase_anon_key': app_config.SUPABASE_ANON_KEY}


def _ws_error_response():
    body, status = get_workspace_schema_error_response()
    return jsonify(body), status


def _workspace_share_payload(workspace_id, custom_endpoint=None):
    base = (request.url_root or '').rstrip('/')
    default_url = f"{base}/customer/project/{workspace_id}"
    full_view_default_url = f"{base}/customer/full-view/{workspace_id}"
    normalized = ws_normalize_workspace_share_endpoint(custom_endpoint)
    custom = normalized or None
    custom_url = f"{base}/panoview/{custom}" if custom else None
    full_view_custom_url = f"{base}/fullview/{custom}" if custom else None
    return {
        'workspace_id': str(workspace_id),
        'default_url': default_url,
        'custom_endpoint': custom,
        'custom_url': custom_url,
        'effective_url': custom_url or default_url,
        'full_view_default_url': full_view_default_url,
        'full_view_custom_url': full_view_custom_url,
        'full_view_effective_url': full_view_custom_url or full_view_default_url,
    }


def register_routes(app):

    def _json_payload():
        """Best-effort JSON body parser that also handles text/plain payloads."""
        data = request.get_json(silent=True)
        if isinstance(data, dict):
            return data
        raw = request.get_data(cache=True, as_text=True) or ''
        if raw:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                pass
        return {}
    secret_key = app.secret_key or app_config.SECRET_KEY

    def _load_panorama_for_page_mode(panorama_id, mode):
        sb = get_supabase()
        if not sb:
            return None, None, ("Database not configured", 503)
        token = str(request.args.get('pt') or '').strip()
        if not token:
            return None, None, ("Forbidden", 403)
        try:
            payload = page_access_serializer(secret_key).loads(token, max_age=int(PAGE_ACCESS_TOKEN_TTL))
        except SignatureExpired:
            return None, None, ("Page access token expired", 403)
        except BadSignature:
            return None, None, ("Invalid page access token", 403)
        token_mode = str(payload.get('mode') or '').strip().lower()
        if token_mode != str(mode or '').strip().lower():
            return None, None, ("Invalid page access token", 403)
        try:
            token_panorama_id = int(payload.get('pid'))
        except Exception:
            token_panorama_id = None
        if token_panorama_id != int(panorama_id):
            return None, None, ("Invalid page access token", 403)
        token_user_id = str(payload.get('uid') or '').strip()
        if not token_user_id:
            return None, None, ("Invalid page access token", 403)
        panorama, access_type = get_panorama_with_access(sb, panorama_id, token_user_id)
        if not panorama:
            return None, None, ("Panorama not found", 404)
        if token_mode == 'admin':
            if access_type != 'owner':
                return None, None, ("Forbidden", 403)
        elif token_mode == 'client':
            if access_type not in ('owner', 'client') and not user_is_client_admin(sb, token_user_id):
                return None, None, ("Forbidden", 403)
        else:
            return None, None, ("Invalid page mode", 400)
        return sb, panorama, None

    _crm_access_cache = {}

    def _crm_access_cache_get(key, ttl_seconds=8):
        row = _crm_access_cache.get(key)
        if not row:
            return None
        if (time.time() - float(row.get('ts') or 0)) > ttl_seconds:
            _crm_access_cache.pop(key, None)
            return None
        return row.get('data')

    def _crm_access_cache_set(key, data):
        if len(_crm_access_cache) > 2000:
            _crm_access_cache.clear()
        _crm_access_cache[key] = {'ts': time.time(), 'data': data}

    def _crm_panorama_ids(sb, user_id, role='user'):
        normalized_role = str(role or 'user').strip().lower()
        cache_key = ('crm_panorama_ids', str(user_id), normalized_role)
        cached = _crm_access_cache_get(cache_key, ttl_seconds=8)
        if cached is not None:
            return list(cached)

        def _crm_allows_access_type(access_type, client_member_id=None):
            at = str(access_type or '').strip().lower()
            if at in ('owner', 'client', 'broker'):
                return True
            # Client groups can intentionally grant viewer access for shared CRM visibility.
            if at == 'viewer' and client_member_id:
                return True
            return False

        if normalized_role in ('admin', 'superadmin'):
            try:
                if normalized_role == 'superadmin':
                    out = _fetch_panorama_ids(sb)
                    _crm_access_cache_set(cache_key, out)
                    return out
                if normalized_role == 'admin':
                    caller = get_profile(sb, user_id) or {}
                    caller_org = caller.get('org_id')
                    if caller_org:
                        out = _fetch_panorama_ids(sb, lambda q: q.eq('org_id', caller_org))
                        _crm_access_cache_set(cache_key, out)
                        return out
            except Exception:
                pass
        # Regular users: run all 4 access queries in parallel for speed
        from concurrent.futures import ThreadPoolExecutor, as_completed
        ids = set()

        def _fetch_owned():
            result = set()
            try:
                owned = sb.table('panoramas').select('id').eq('user_id', user_id).execute()
                for row in (owned.data or []):
                    try: result.add(int(row.get('id')))
                    except Exception: pass
            except Exception: pass
            return result

        def _fetch_panorama_access():
            result = set()
            try:
                access_rows = (
                    sb.table('panorama_access')
                    .select('panorama_id, access_type, client_member_id')
                    .eq('user_id', user_id)
                    .execute()
                )
                for row in (access_rows.data or []):
                    try:
                        if _crm_allows_access_type(row.get('access_type'), row.get('client_member_id')):
                            result.add(int(row.get('panorama_id')))
                    except Exception:
                        pass
            except Exception:
                pass
            return result

        def _fetch_workspace_access():
            result = set()
            try:
                ws_rows = (
                    sb.table('workspace_access')
                    .select('workspace_id, access_type, client_member_id')
                    .eq('user_id', user_id)
                    .execute()
                )
                ws_ids = []
                for row in (ws_rows.data or []):
                    if _crm_allows_access_type(row.get('access_type'), row.get('client_member_id')):
                        wsid = row.get('workspace_id')
                        if wsid:
                            ws_ids.append(wsid)
                if ws_ids:
                    ws_panos = sb.table('panoramas').select('id').in_('workspace_id', ws_ids).execute()
                    for row in (ws_panos.data or []):
                        try: result.add(int(row.get('id')))
                        except Exception: pass
            except Exception: pass
            return result

        def _fetch_lock_access():
            result = set()
            try:
                lock_access = sb.table('plot_lock_access').select('panorama_id').eq('user_id', user_id).execute()
                for row in (lock_access.data or []):
                    try: result.add(int(row.get('panorama_id')))
                    except Exception: pass
            except Exception: pass
            return result

        def _fetch_broker_access():
            """Brokers get CRM-only access to panoramas their client group admin can access."""
            result = set()
            try:
                member_rows = (
                    sb.table('client_members')
                    .select('client_id')
                    .eq('user_id', user_id)
                    .in_('member_role', [CLIENT_MEMBER_ROLE_BROKER])
                    .execute()
                )
                client_ids = [r.get('client_id') for r in (member_rows.data or []) if r.get('client_id')]
                if not client_ids:
                    return result
                admin_rows = sb.table('client_members').select('user_id').in_('client_id', client_ids).eq('member_role', 'client_admin').execute()
                admin_ids = list({r.get('user_id') for r in (admin_rows.data or []) if r.get('user_id')})
                if not admin_ids:
                    return result
                # panorama_access rows for those admins
                pa = sb.table('panorama_access').select('panorama_id, access_type, client_member_id').in_('user_id', admin_ids).execute()
                for row in (pa.data or []):
                    try:
                        if _crm_allows_access_type(row.get('access_type'), row.get('client_member_id')):
                            result.add(int(row.get('panorama_id')))
                    except Exception:
                        pass
                # workspace_access rows for those admins -> panorama ids
                wa = sb.table('workspace_access').select('workspace_id, access_type, client_member_id').in_('user_id', admin_ids).execute()
                ws_ids = []
                for row in (wa.data or []):
                    if _crm_allows_access_type(row.get('access_type'), row.get('client_member_id')):
                        wsid = row.get('workspace_id')
                        if wsid:
                            ws_ids.append(wsid)
                if ws_ids:
                    wp = sb.table('panoramas').select('id').in_('workspace_id', ws_ids).execute()
                    for row in (wp.data or []):
                        try: result.add(int(row.get('id')))
                        except Exception: pass
            except Exception: pass
            return result

        def _fetch_client_admin_group_access():
            result = set()
            try:
                _workspace_ids, group_panorama_ids = client_group_resource_ids_for_admin(sb, user_id)
                result.update(group_panorama_ids)
            except Exception:
                pass
            return result

        with ThreadPoolExecutor(max_workers=6) as executor:
            futures = [
                executor.submit(_fetch_owned),
                executor.submit(_fetch_panorama_access),
                executor.submit(_fetch_workspace_access),
                executor.submit(_fetch_lock_access),
                executor.submit(_fetch_broker_access),
                executor.submit(_fetch_client_admin_group_access),
            ]
            for future in as_completed(futures):
                try:
                    ids.update(future.result())
                except Exception:
                    pass
        out = sorted(ids)
        _crm_access_cache_set(cache_key, out)
        return out

    def _fetch_panorama_ids(sb, query_builder=None):
        ids = set()
        page_size = 500
        start = 0
        while True:
            q = sb.table('panoramas').select('id')
            if callable(query_builder):
                q = query_builder(q)
            if q is None:
                break
            rows = []
            try:
                r = q.range(start, start + page_size - 1).execute()
                rows = r.data or []
            except Exception:
                if start > 0:
                    break
                r = q.execute()
                rows = r.data or []
            for row in rows:
                try:
                    ids.add(int(row.get('id')))
                except Exception:
                    pass
            if len(rows) < page_size:
                break
            start += page_size
        return sorted(ids)

    def _normalize_email(value):
        return str(value or '').strip().lower()

    def _normalize_phone(value):
        return re.sub(r'[^0-9]+', '', str(value or ''))

    def _normalize_name(value):
        return re.sub(r'\s+', ' ', str(value or '').strip()).lower()

    def _safe_json(value, fallback):
        if isinstance(value, (dict, list)):
            return value
        return fallback

    # Bounds for the custom_fields jsonb sweep: it copies every unrecognized
    # request key, so without caps a single request can bloat rows unboundedly.
    _CUSTOM_FIELDS_MAX_KEYS = 50
    _CUSTOM_FIELDS_MAX_KEY_LEN = 64
    _CUSTOM_FIELDS_MAX_VALUE_LEN = 2000

    def _clean_custom_field_value(value):
        if value is None or isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value
        if isinstance(value, str):
            return value[:_CUSTOM_FIELDS_MAX_VALUE_LEN]
        # Nested structures are kept but bounded via their JSON size.
        try:
            encoded = json.dumps(value)
        except Exception:
            return None
        if len(encoded) > _CUSTOM_FIELDS_MAX_VALUE_LEN:
            return None
        return value

    def _extract_custom_fields_payload(data, known_keys):
        payload = {}
        if isinstance(data.get('custom_fields'), dict):
            for k, v in data.get('custom_fields').items():
                key = str(k or '').strip()[:_CUSTOM_FIELDS_MAX_KEY_LEN]
                if key:
                    payload[key] = _clean_custom_field_value(v)
        known = {str(k or '').strip() for k in (known_keys or []) if str(k or '').strip()}
        for k, v in (data or {}).items():
            key = str(k or '').strip()
            if not key or key in known or key == 'custom_fields':
                continue
            payload[key[:_CUSTOM_FIELDS_MAX_KEY_LEN]] = _clean_custom_field_value(v)
        if len(payload) > _CUSTOM_FIELDS_MAX_KEYS:
            payload = dict(list(payload.items())[:_CUSTOM_FIELDS_MAX_KEYS])
        return payload

    def _is_truthy(value):
        if isinstance(value, bool):
            return value
        s = str(value or '').strip().lower()
        return s in ('1', 'true', 'yes', 'y', 'on')

    def _accessible_panorama_org_map(sb, panorama_ids):
        out = {}
        if not panorama_ids:
            return out
        normalized = []
        seen = set()
        for pid in panorama_ids:
            try:
                p_int = int(pid)
            except Exception:
                continue
            if p_int in seen:
                continue
            seen.add(p_int)
            normalized.append(p_int)
        if not normalized:
            return out
        cache_key = ('crm_panorama_org_map', tuple(sorted(normalized)))
        cached = _crm_access_cache_get(cache_key, ttl_seconds=8)
        if cached is not None:
            return dict(cached)
        try:
            r = sb.table('panoramas').select('id, org_id, name').in_('id', normalized).execute()
            for row in (r.data or []):
                pid = row.get('id')
                if pid is None:
                    continue
                out[int(pid)] = {
                    'org_id': row.get('org_id'),
                    'panorama_name': row.get('name') or '',
                }
        except Exception:
            pass
        _crm_access_cache_set(cache_key, out)
        return out

    def _crm_org_ids_for_panoramas(sb, panorama_ids):
        pmap = _accessible_panorama_org_map(sb, panorama_ids)
        out = []
        seen = set()
        for v in pmap.values():
            oid = v.get('org_id')
            if oid and str(oid) not in seen:
                seen.add(str(oid))
                out.append(str(oid))
        return out

    def _is_admin_role(role):
        return str(role or '').strip().lower() in ('admin', 'superadmin')

    def _crm_user_client_ids(sb, user_id):
        try:
            r = sb.table('client_members').select('client_id').eq('user_id', str(user_id)).execute()
            out = []
            seen = set()
            for row in (r.data or []):
                cid = str(row.get('client_id') or '').strip()
                if not cid or cid in seen:
                    continue
                seen.add(cid)
                out.append(cid)
            return out
        except Exception:
            return []

    def _crm_user_client_ids_for_panorama(sb, user_id, panorama_id):
        try:
            pa = (
                sb.table('panorama_access')
                .select('client_member_id')
                .eq('user_id', str(user_id))
                .eq('panorama_id', int(panorama_id))
                .execute()
            )
            member_ids = [row.get('client_member_id') for row in (pa.data or []) if row.get('client_member_id')]
            if not member_ids:
                return []
            cm = sb.table('client_members').select('client_id').in_('id', member_ids).execute()
            out = []
            seen = set()
            for row in (cm.data or []):
                cid = str(row.get('client_id') or '').strip()
                if not cid or cid in seen:
                    continue
                seen.add(cid)
                out.append(cid)
            return out
        except Exception:
            return []

    def _crm_client_scope_ids(sb, user_id, role):
        if _is_admin_role(role):
            return None
        return _crm_user_client_ids(sb, user_id)

    def _crm_pick_client_id_for_create(sb, user_id, role, requested_client_id=None, panorama_id=None):
        req = str(requested_client_id or '').strip() or None
        if _is_admin_role(role):
            if req:
                return req, None
            if panorama_id is not None:
                pano_client_ids = _crm_user_client_ids_for_panorama(sb, user_id, panorama_id)
                if len(pano_client_ids) == 1:
                    return pano_client_ids[0], None
            return None, None
        member_client_ids = _crm_user_client_ids(sb, user_id)
        if not member_client_ids:
            return None, (jsonify({'error': 'You are not assigned to any client group'}), 403)
        if req:
            if req not in member_client_ids:
                return None, (jsonify({'error': 'Forbidden for this client group'}), 403)
            return req, None
        if panorama_id is not None:
            pano_client_ids = _crm_user_client_ids_for_panorama(sb, user_id, panorama_id)
            candidates = [cid for cid in pano_client_ids if cid in member_client_ids]
            if len(candidates) == 1:
                return candidates[0], None
            if len(candidates) > 1:
                return None, (jsonify({'error': 'Multiple client groups match this panorama. Provide client_id explicitly'}), 400)
        if len(member_client_ids) == 1:
            return member_client_ids[0], None
        return None, (jsonify({'error': 'Multiple client groups available. Provide client_id explicitly'}), 400)

    def _crm_apply_client_scope(query, client_ids, client_column='client_id'):
        if client_ids is None:
            return query
        if not client_ids:
            return None
        return query.in_(client_column, client_ids)

    def _crm_interest_reference_scope_user_id(sb, user_id, role, client_ids=None):
        if _is_admin_role(role):
            return None
        try:
            q = (
                sb.table('client_members')
                .select('client_id, member_role')
                .eq('user_id', str(user_id))
            )
            if client_ids:
                q = q.in_('client_id', client_ids)
            rows = q.execute().data or []
        except Exception:
            return None
        has_reference_scope = False
        for row in rows:
            member_role = _normalize_client_member_role(row.get('member_role'))
            if member_role == CLIENT_MEMBER_ROLE_CLIENT_ADMIN:
                return None
            if member_role == CLIENT_MEMBER_ROLE_BROKER:
                has_reference_scope = True
        return str(user_id) if has_reference_scope else None

    def _crm_apply_broker_interest_visibility(query, broker_user_id):
        broker_uid = str(broker_user_id or '').strip()
        if not broker_uid:
            return query
        # Strict broker visibility: only interests referenced to broker OR created by broker.
        return query.or_(f"reference_user_id.eq.{broker_uid},submitted_by.eq.{broker_uid}")

    def _crm_apply_broker_referred_contact_mask(row, *, user_id, role, reference_scope_user_id=None, sb=None):
        return apply_broker_referred_contact_mask(
            row,
            user_id=user_id,
            role=role,
            reference_scope_user_id=reference_scope_user_id,
            sb=sb or get_supabase(),
        )

    def _crm_deny_hidden_broker_referred_contact(sb, user_id, role, reference_scope_user_id, interest):
        if (
            _interest_has_broker_reference(interest)
            and not _interest_contact_is_revealed(interest)
            and viewer_should_mask_broker_referred_contact(sb, user_id, role, reference_scope_user_id)
        ):
            return jsonify({'error': 'Contact details are hidden until the referring broker reveals them'}), 403
        return None

    def _crm_reference_linked_ids(sb, reference_user_id, panorama_ids, client_ids=None, requested_client_id=None):
        ref_uid = str(reference_user_id or '').strip()
        if not ref_uid or not panorama_ids:
            return [], []
        try:
            q = (
                sb.table('buy_interests')
                .select('id, contact_id')
                .in_('panorama_id', panorama_ids)
            )
            q = _crm_apply_broker_interest_visibility(q, ref_uid)
            req_client_id = str(requested_client_id or '').strip()
            if req_client_id:
                q = q.eq('client_id', req_client_id)
            rows = q.execute().data or []
        except Exception:
            return [], []
        interest_ids = []
        contact_ids = []
        seen_interests = set()
        seen_contacts = set()
        for row in rows:
            interest_id = str(row.get('id') or '').strip()
            if interest_id and interest_id not in seen_interests:
                seen_interests.add(interest_id)
                interest_ids.append(interest_id)
            contact_id = str(row.get('contact_id') or '').strip()
            if contact_id and contact_id not in seen_contacts:
                seen_contacts.add(contact_id)
                contact_ids.append(contact_id)
        try:
            if interest_ids:
                cq = sb.table('crm_contacts').select('id').in_('source_interest_id', interest_ids)
                req_client_id = str(requested_client_id or '').strip()
                if req_client_id:
                    cq = cq.eq('client_id', req_client_id)
                if cq is not None:
                    for row in (cq.execute().data or []):
                        contact_id = str(row.get('id') or '').strip()
                        if contact_id and contact_id not in seen_contacts:
                            seen_contacts.add(contact_id)
                            contact_ids.append(contact_id)
        except Exception:
            pass
        return interest_ids, contact_ids

    def _crm_profile_in_org(sb, user_id_to_check, org_id):
        if not org_id:
            return True
        cache_key = ('crm_profile_in_org', str(user_id_to_check), str(org_id))
        cached = _crm_access_cache_get(cache_key, ttl_seconds=8)
        if cached is not None:
            return bool(cached)
        try:
            r = (
                sb.table('profiles')
                .select('user_id')
                .eq('user_id', str(user_id_to_check))
                .eq('org_id', str(org_id))
                .limit(1)
                .execute()
            )
            out = bool(r.data)
            _crm_access_cache_set(cache_key, out)
            return out
        except Exception:
            _crm_access_cache_set(cache_key, False)
            return False

    def _merge_quote_template_inputs(template_payload, request_inputs):
        tp = _safe_json(template_payload, {})
        rq = _safe_json(request_inputs, {})
        if isinstance(tp, dict) and isinstance(rq, dict):
            merged = dict(tp)
            merged.update(rq)
            return merged
        if isinstance(rq, dict):
            return rq
        return tp if isinstance(tp, dict) else {}

    def _mark_interest_qualified_for_deal(sb, interest_id, contact_id, now_iso):
        if not interest_id:
            return
        try:
            ex = (
                sb.table('buy_interests')
                .select('contacted_at, created_at, updated_at')
                .eq('id', str(interest_id))
                .limit(1)
                .execute()
            )
            row = (ex.data or [{}])[0]
            ct = row.get('contacted_at') or row.get('updated_at') or row.get('created_at') or now_iso
            sb.table('buy_interests').update({
                'status': 'qualified',
                'is_contacted': True,
                'contacted_at': str(ct) if ct else now_iso,
                'contact_id': str(contact_id),
                'updated_at': now_iso,
            }).eq('id', str(interest_id)).execute()
        except Exception:
            pass

    def _find_contact_by_email_or_phone(sb, org_id, email_norm, phone_norm, panorama_ids, client_id=None):
        if not email_norm and not phone_norm:
            return None
        def _base_query():
            q = sb.table('crm_contacts').select(
                'id, org_id, client_id, panorama_id, full_name, email, phone, email_norm, phone_norm, notes, created_at, updated_at'
            )
            # Both filters together: an org-wide match outside the caller's
            # panoramas must never be picked as a merge target — the caller
            # could then update/delete a contact they cannot even see.
            if org_id:
                q = q.eq('org_id', org_id)
            if panorama_ids:
                q = q.in_('panorama_id', panorama_ids)
            if client_id:
                q = q.eq('client_id', str(client_id))
            return q
        if email_norm:
            rows = (_base_query().eq('email_norm', email_norm).order('updated_at', desc=True).limit(1).execute().data or [])
            if rows:
                return rows[0]
        if phone_norm:
            rows = (_base_query().eq('phone_norm', phone_norm).order('updated_at', desc=True).limit(1).execute().data or [])
            if rows:
                return rows[0]
        return None

    _UNSET = object()

    def _contact_birthday_value(raw):
        """Normalise a birthday for a nullable `date` column ('' would be a type error)."""
        value = str(raw if raw is not None else '').strip()
        return value or None

    def _merge_contact_payload(existing, full_name='', email='', phone='', notes='', birthday=_UNSET, address=_UNSET):
        ex_name = str(existing.get('full_name') or '').strip()
        ex_email = str(existing.get('email') or '').strip()
        ex_phone = str(existing.get('phone') or '').strip()
        ex_notes = str(existing.get('notes') or '').strip()
        ex_email_norm = _normalize_email(existing.get('email_norm') or ex_email)
        ex_phone_norm = _normalize_phone(existing.get('phone_norm') or ex_phone)
        incoming_name = str(full_name or '').strip()
        incoming_email = str(email or '').strip()
        incoming_phone = str(phone or '').strip()
        incoming_notes = str(notes or '').strip()
        incoming_email_norm = _normalize_email(incoming_email)
        incoming_phone_norm = _normalize_phone(incoming_phone)

        out_name = ex_name
        if incoming_name:
            if not out_name:
                out_name = incoming_name
            else:
                # Case/space-insensitive same-name updates prefer the richer formatting.
                if _normalize_name(out_name) == _normalize_name(incoming_name):
                    out_name = incoming_name if len(incoming_name) >= len(out_name) else out_name

        out_email = ex_email
        out_email_norm = ex_email_norm
        if incoming_email_norm:
            if (not ex_email_norm) or (ex_email_norm == incoming_email_norm):
                out_email = incoming_email
                out_email_norm = incoming_email_norm

        out_phone = ex_phone
        out_phone_norm = ex_phone_norm
        if incoming_phone_norm:
            if (not ex_phone_norm) or (ex_phone_norm == incoming_phone_norm):
                out_phone = incoming_phone
                out_phone_norm = incoming_phone_norm

        out_notes = ex_notes
        if incoming_notes:
            out_notes = incoming_notes if not ex_notes else ex_notes

        # Birthday/address: an explicit value from the caller wins (including a
        # deliberate clear); _UNSET means the caller did not touch the field.
        out_birthday = existing.get('birthday')
        if birthday is not _UNSET:
            out_birthday = birthday
        out_address = str(existing.get('address') or '').strip()
        if address is not _UNSET:
            out_address = str(address or '').strip()

        return {
            'full_name': out_name,
            'email': out_email,
            'phone': out_phone,
            'email_norm': out_email_norm,
            'phone_norm': out_phone_norm,
            'notes': out_notes,
            'birthday': out_birthday,
            'address': out_address,
        }

    def _relink_contact_references(sb, from_contact_id, to_contact_id):
        if not from_contact_id or not to_contact_id or str(from_contact_id) == str(to_contact_id):
            return
        try:
            sb.table('buy_interests').update({'contact_id': str(to_contact_id)}).eq('contact_id', str(from_contact_id)).execute()
        except Exception:
            pass
        try:
            sb.table('crm_deals').update({'contact_id': str(to_contact_id)}).eq('contact_id', str(from_contact_id)).execute()
        except Exception:
            pass
        try:
            sb.table('crm_deal_quotes').update({'contact_id': str(to_contact_id)}).eq('contact_id', str(from_contact_id)).execute()
        except Exception:
            pass

    def _touch_deal_active_state_from_stage(stage):
        st = str(stage or '').strip().lower()
        return st not in ('won', 'lost')

    # Small in-process cache for CRM list endpoints to reduce repeated latency.
    _crm_cache = {}
    _crm_cache_version = {'v': 1}

    def _crm_cache_bump():
        _crm_cache_version['v'] = int(_crm_cache_version.get('v', 1)) + 1
        if len(_crm_cache) > 500:
            _crm_cache.clear()

    def _crm_cache_get(key, ttl_seconds=3):
        row = _crm_cache.get(key)
        if not row:
            return None
        ts = row.get('ts', 0)
        if (time.time() - ts) > ttl_seconds:
            _crm_cache.pop(key, None)
            return None
        return row.get('data')

    def _crm_cache_set(key, data):
        _crm_cache[key] = {'ts': time.time(), 'data': data}

    def _is_transient_supabase_error(err):
        msg = str(err or '').lower()
        transient_tokens = (
            'connectionterminated',
            'connection terminated',
            'connection closed',
            'server closed the connection',
            'stream error',
            'eof',
            'timeout',
            'timed out',
            'temporarily unavailable',
        )
        return any(token in msg for token in transient_tokens)

    def _with_supabase_retry(fn, attempts=2, sleep_seconds=0.18):
        last_err = None
        tries = max(1, int(attempts or 1))
        for idx in range(tries):
            try:
                return fn()
            except Exception as err:
                last_err = err
                if not _is_transient_supabase_error(err) or idx >= (tries - 1):
                    raise
                time.sleep(sleep_seconds)
        if last_err:
            raise last_err

    @app.errorhandler(RequestEntityTooLarge)
    def handle_request_too_large(_error):
        if request.path.startswith('/api/'):
            max_bytes = current_app.config.get('MAX_CONTENT_LENGTH') or 0
            max_mb = max(1, int(max_bytes / (1024 * 1024))) if max_bytes else 0
            hint = f' (max {max_mb}MB)' if max_mb else ''
            return jsonify({'error': f'Upload too large{hint}'}), 413
        return _error

    # ----- Public routes -----
    @app.route('/')
    def index():
        return render_template('landing.html', **auth_ctx())

    @app.route('/favicon.ico')
    def favicon():
        return redirect('/static/Marketostate/Marketostate%20Favicon.svg', code=302)

    @app.route('/login')
    def login_page():
        return render_template('login.html', **auth_ctx())

    @app.route('/signup')
    def signup_page():
        return redirect('/login?mode=signup')

    @app.route('/auth/callback')
    def auth_callback():
        return render_template('auth_callback.html', **auth_ctx())

    @app.route('/dashboard')
    @app.route('/dashboard/<user_id>')
    def dashboard(user_id=None):
        return render_template('dashboard.html', user_id=user_id, **auth_ctx())

    @app.route('/crm')
    def crm_page():
        from flask import make_response
        resp = make_response(render_template('crm.html', **auth_ctx()))
        resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate'
        resp.headers['Pragma'] = 'no-cache'
        return resp

    @app.route('/explore')
    @app.route('/portal')
    def customer_portal():
        return render_template('portal.html', **auth_ctx())

    @app.route('/admin/<int:panorama_id>')
    def admin(panorama_id):
        sb, panorama, err = _load_panorama_for_page_mode(panorama_id, 'admin')
        if err:
            return err
        org_name, org_slug = get_org_name_and_slug_for_panorama(sb, panorama)
        mobile_panorama = get_mobile_panorama_by_parent_id(sb, panorama_id)
        workspace_id = (panorama or {}).get('workspace_id')
        workspace_panoramas = load_customer_workspace_panoramas(sb, workspace_id) if workspace_id else []
        return render_template('editor.html', panorama=panorama, mobile_panorama=mobile_panorama, mode='admin', org_name=org_name, org_slug=org_slug, workspace_id=workspace_id, workspace_panoramas=workspace_panoramas, **auth_ctx())

    def load_customer_workspace_panoramas(sb, workspace_id, main_id=None):
        workspace_panoramas = []
        if not workspace_id:
            return workspace_panoramas
        try:
            r = sb.table('panoramas').select('id, name, filename, is_360').eq('workspace_id', workspace_id).order('id').execute()
            rows = list(r.data or [])
            if main_id is not None:
                try:
                    mid = int(main_id)
                except Exception:
                    mid = None
                if mid is not None:
                    def sort_key(p):
                        pid = p.get('id')
                        if pid == mid:
                            return (0, pid or 0)
                        return (1, pid or 0)
                    rows.sort(key=sort_key)
            for p in rows:
                workspace_panoramas.append({
                    'id': p.get('id'),
                    'name': (p.get('name') or '').strip() or ('Panorama #' + str(p.get('id') or '')),
                    'filename': p.get('filename') or '',
                    'is_360': bool(p.get('is_360')),
                })
        except Exception:
            pass
        return workspace_panoramas

    def load_mobile_panorama_map(sb, parent_panorama_ids):
        out = {}
        ids = []
        seen = set()
        for raw in (parent_panorama_ids or []):
            try:
                pid = int(raw)
            except Exception:
                continue
            if pid in seen:
                continue
            seen.add(pid)
            ids.append(pid)
        if not ids:
            return out
        try:
            r = (
                sb.table('mobile_panoramas')
                .select('id, panorama_parent_id, name, filename, original_filename, width, height, is_360')
                .in_('panorama_parent_id', ids)
                .order('id')
                .execute()
            )
            for row in (r.data or []):
                try:
                    parent_id = int(row.get('panorama_parent_id'))
                except Exception:
                    continue
                out[str(parent_id)] = {
                    'id': row.get('id'),
                    'panorama_parent_id': row.get('panorama_parent_id'),
                    'name': row.get('name') or '',
                    'filename': row.get('filename') or '',
                    'original_filename': row.get('original_filename') or '',
                    'width': row.get('width') or 0,
                    'height': row.get('height') or 0,
                    'is_360': bool(row.get('is_360')),
                }
        except Exception:
            pass
        return out

    def build_customer_workspace_context(sb, panorama):
        workspace_id = (panorama or {}).get('workspace_id')
        customer_view_config = {}
        workspace_panoramas = []
        mobile_panorama_map = {}
        if workspace_id:
            try:
                customer_view_config = ws_get_customer_config(sb, workspace_id) or {}
            except Exception:
                pass
            workspace_panoramas = load_customer_workspace_panoramas(
                sb,
                workspace_id,
                (get_workspace_by_id(sb, workspace_id) or {}).get('main_panorama_id')
            )
        parent_ids = [p.get('id') for p in (workspace_panoramas or []) if p and p.get('id') is not None]
        if panorama and panorama.get('id') is not None:
            parent_ids.append(panorama.get('id'))
        mobile_panorama_map = load_mobile_panorama_map(sb, parent_ids)
        return workspace_id, workspace_panoramas, customer_view_config, mobile_panorama_map

    def render_customer_panorama_template(sb, panorama, org_name, canonical_slug, full_view=False, initial_panorama_id=None, embed_mode=False):
        workspace_id, workspace_panoramas, customer_view_config, mobile_panorama_map = build_customer_workspace_context(sb, panorama)
        fv_config = None
        if workspace_id and not embed_mode:
            fv_config = fv_get_config_with_tabs(sb, workspace_id)
        resp = make_response(render_template(
            'customer_3d.html',
            panorama=panorama,
            org_name=org_name,
            org_slug=canonical_slug,
            full_view=full_view,
            embed_mode=embed_mode,
            workspace_panoramas=workspace_panoramas,
            initial_panorama_id=initial_panorama_id,
            workspace_id=workspace_id,
            customer_view_config=customer_view_config,
            mobile_panorama_map=mobile_panorama_map,
            fv_config=fv_config,
            **auth_ctx()
        ))
        # Keep customer panorama pages warm for fast tab switching.
        if embed_mode:
            resp.headers['Cache-Control'] = 'private, max-age=120, stale-while-revalidate=240'
        else:
            resp.headers['Cache-Control'] = 'private, max-age=45, stale-while-revalidate=90'
        return resp

    @app.route('/customer/edit/<workspace_id>')
    def customer_edit_view(workspace_id):
        sb = get_supabase()
        if not sb:
            return "Database not configured", 503
        workspace = get_workspace_by_id(sb, workspace_id)
        if not workspace:
            return "Project not found", 404
        main_id = workspace.get('main_panorama_id')
        panorama = None
        if main_id:
            panorama = get_panorama_by_id(sb, main_id)
        if not panorama:
            try:
                r = sb.table('panoramas').select('*').eq('workspace_id', workspace_id).order('id').limit(1).execute()
                if r.data and len(r.data) > 0:
                    panorama = dict(r.data[0])
            except Exception:
                pass
        if not panorama:
            return "No panorama in this project", 404
        org_name, canonical_slug = get_org_name_and_slug_for_panorama(sb, panorama)
        workspace_panoramas = load_customer_workspace_panoramas(sb, workspace_id, main_id)
        return render_template(
            'customer_edit.html',
            panorama=panorama,
            org_name=org_name,
            org_slug=canonical_slug,
            workspace_id=workspace_id,
            workspace_name=workspace.get('name', ''),
            workspace_panoramas=workspace_panoramas,
            initial_panorama_id=panorama.get('id'),
            customer_view_config={},
            **auth_ctx()
        )

    @app.route('/customer/<int:panorama_id>')
    def customer(panorama_id):
        sb = get_supabase()
        if not sb:
            return "Database not configured", 503
        panorama = get_panorama_by_id(sb, panorama_id)
        if not panorama:
            return "Panorama not found", 404
        _org_name, org_slug = get_org_name_and_slug_for_panorama(sb, panorama)
        qs = request.query_string.decode('utf-8') if request.query_string else ''
        suffix = ('?' + qs) if qs else ''
        is_360 = bool((panorama or {}).get('is_360'))
        if is_360:
            return redirect(f"/customer/{org_slug}/3d/{panorama_id}{suffix}", code=302)
        return redirect(f"/customer/{org_slug}/{panorama_id}{suffix}", code=302)

    @app.route('/customer/<org_slug>/<int:panorama_id>')
    def customer_with_org(org_slug, panorama_id):
        sb = get_supabase()
        if not sb:
            return "Database not configured", 503
        panorama = get_panorama_by_id(sb, panorama_id)
        if not panorama:
            return "Panorama not found", 404
        org_name, canonical_slug = get_org_name_and_slug_for_panorama(sb, panorama)
        qs = request.query_string.decode('utf-8') if request.query_string else ''
        suffix = ('?' + qs) if qs else ''
        if bool((panorama or {}).get('is_360')):
            return redirect(f"/customer/{canonical_slug}/3d/{panorama_id}{suffix}", code=302)
        if str(org_slug or '').lower() != str(canonical_slug).lower():
            return redirect(f"/customer/{canonical_slug}/{panorama_id}{suffix}", code=302)
        return render_customer_panorama_template(sb, panorama, org_name, canonical_slug)

    @app.route('/client/<int:panorama_id>')
    def client(panorama_id):
        sb, panorama, err = _load_panorama_for_page_mode(panorama_id, 'client')
        if err:
            return err
        org_name, org_slug = get_org_name_and_slug_for_panorama(sb, panorama)
        return render_template('client.html', panorama=panorama, mode='client', org_name=org_name, org_slug=org_slug, **auth_ctx())

    @app.route('/admin/3d/<int:panorama_id>')
    def admin_3d(panorama_id):
        sb, panorama, err = _load_panorama_for_page_mode(panorama_id, 'admin')
        if err:
            return err
        org_name, org_slug = get_org_name_and_slug_for_panorama(sb, panorama)
        workspace_panoramas = []
        customer_view_config = {}
        full_view_panorama_ids = []
        full_view_panorama_tab_map = {}
        workspace_id = (panorama or {}).get('workspace_id')
        if workspace_id:
            try:
                r = sb.table('panoramas').select('id, name, filename, is_360').eq('workspace_id', workspace_id).eq('is_360', True).order('id').execute()
                rows = list(r.data or [])
                for p in rows:
                    workspace_panoramas.append({
                        'id': p.get('id'),
                        'name': (p.get('name') or '').strip() or ('Panorama #' + str(p.get('id') or '')),
                        'filename': p.get('filename') or '',
                        'is_360': bool(p.get('is_360')),
                    })
                customer_view_config = ws_get_customer_config(sb, workspace_id) or {}
                try:
                    fv_cfg = fv_get_config(sb, workspace_id) or {}
                    fv_config_id = str((fv_cfg or {}).get('id') or '').strip()
                    tabs = fv_list_tabs(sb, fv_config_id) if fv_config_id else []
                    seen_fv_refs = set()
                    for tab in (tabs or []):
                        if not isinstance(tab, dict):
                            continue
                        raw_ref = tab.get('ref_panorama_id')
                        if raw_ref in (None, '', 'null'):
                            continue
                        try:
                            ref_panorama_id = int(raw_ref)
                        except Exception:
                            continue
                        ref_key = str(ref_panorama_id)
                        if ref_key not in seen_fv_refs:
                            full_view_panorama_ids.append(ref_panorama_id)
                            seen_fv_refs.add(ref_key)
                        tab_name = str(tab.get('name') or '').strip()
                        if tab_name:
                            tab_names = full_view_panorama_tab_map.setdefault(ref_key, [])
                            if tab_name not in tab_names:
                                tab_names.append(tab_name)
                except Exception:
                    pass
            except Exception:
                pass
        crm_master_client_id = ''
        try:
            from app.services.uam_reference_service import _project_reference_client_ids
            ref_client_ids = _project_reference_client_ids(sb, workspace_id=workspace_id, panorama_id=panorama_id)
            if ref_client_ids:
                crm_master_client_id = str(ref_client_ids[0])
        except Exception:
            pass
        return render_template(
            'admin_3d.html',
            panorama=panorama,
            org_name=org_name,
            org_slug=org_slug,
            workspace_id=workspace_id,
            workspace_panoramas=workspace_panoramas,
            customer_view_config=customer_view_config,
            full_view_panorama_ids=full_view_panorama_ids,
            full_view_panorama_tab_map=full_view_panorama_tab_map,
            crm_master_client_id=crm_master_client_id,
            **auth_ctx(),
        )

    @app.route('/client/3d/<int:panorama_id>')
    def client_3d(panorama_id):
        sb, panorama, err = _load_panorama_for_page_mode(panorama_id, 'client')
        if err:
            return err
        org_name, org_slug = get_org_name_and_slug_for_panorama(sb, panorama)
        return render_template('client_3d.html', panorama=panorama, org_name=org_name, org_slug=org_slug, **auth_ctx())

    @app.route('/customer/3d/<int:panorama_id>')
    def customer_3d(panorama_id):
        sb = get_supabase()
        if not sb:
            return "Database not configured", 503
        panorama = get_panorama_by_id(sb, panorama_id)
        if not panorama:
            return "Panorama not found", 404
        _org_name, org_slug = get_org_name_and_slug_for_panorama(sb, panorama)
        qs = request.query_string.decode('utf-8') if request.query_string else ''
        suffix = ('?' + qs) if qs else ''
        is_360 = bool((panorama or {}).get('is_360'))
        if not is_360:
            return redirect(f"/customer/{org_slug}/{panorama_id}{suffix}", code=302)
        return redirect(f"/customer/{org_slug}/3d/{panorama_id}{suffix}", code=302)

    @app.route('/customer/<org_slug>/3d/<int:panorama_id>')
    def customer_3d_with_org(org_slug, panorama_id):
        sb = get_supabase()
        if not sb:
            return "Database not configured", 503
        panorama = get_panorama_by_id(sb, panorama_id)
        if not panorama:
            return "Panorama not found", 404
        org_name, canonical_slug = get_org_name_and_slug_for_panorama(sb, panorama)
        qs = request.query_string.decode('utf-8') if request.query_string else ''
        suffix = ('?' + qs) if qs else ''
        if not bool((panorama or {}).get('is_360')):
            return redirect(f"/customer/{canonical_slug}/{panorama_id}{suffix}", code=302)
        if str(org_slug or '').lower() != str(canonical_slug).lower():
            return redirect(f"/customer/{canonical_slug}/3d/{panorama_id}{suffix}", code=302)
        return render_customer_panorama_template(sb, panorama, org_name, canonical_slug)

    @app.route('/customer/project/<workspace_id>')
    def customer_project_view(workspace_id):
        sb = get_supabase()
        if not sb:
            return "Database not configured", 503
        workspace = get_workspace_by_id(sb, workspace_id)
        if not workspace or not workspace.get('is_published'):
            return "Project not found", 404
        main_id = workspace.get('main_panorama_id')
        if not main_id:
            return "Project has no main panorama", 404
        panorama = get_panorama_by_id(sb, main_id)
        requested_pano = (request.args.get('pano') or '').strip()
        if requested_pano:
            try:
                requested_pano_id = int(requested_pano)
            except Exception:
                requested_pano_id = None
            try:
                main_numeric_id = int(main_id)
            except Exception:
                main_numeric_id = None
            if requested_pano_id is not None and requested_pano_id != main_numeric_id:
                requested_row = get_panorama_by_id(sb, requested_pano_id)
                if requested_row and str(requested_row.get('workspace_id') or '') == str(workspace_id):
                    panorama = requested_row
        if not panorama:
            return "Panorama not found", 404
        org_name, canonical_slug = get_org_name_and_slug_for_panorama(sb, panorama)
        embed_mode = str(request.args.get('embed') or '').strip() == '1'
        # IMPORTANT: Keep this URL stable (no redirects). It should always open the
        # current workspace main panorama, even if the main panorama changes later.
        return render_customer_panorama_template(sb, panorama, org_name, canonical_slug, embed_mode=embed_mode)

    @app.route('/panoview/<endpoint>')
    def customer_project_share_view(endpoint):
        sb = get_supabase()
        if not sb:
            return "Database not configured", 503
        workspace_id = ws_get_workspace_id_by_share_endpoint(sb, endpoint)
        if not workspace_id:
            return "Project not found", 404
        workspace = get_workspace_by_id(sb, workspace_id)
        if not workspace or not workspace.get('is_published'):
            return "Project not found", 404
        main_id = workspace.get('main_panorama_id')
        if not main_id:
            return "Project has no main panorama", 404
        panorama = get_panorama_by_id(sb, main_id)
        if not panorama:
            return "Panorama not found", 404
        org_name, canonical_slug = get_org_name_and_slug_for_panorama(sb, panorama)
        return render_customer_panorama_template(sb, panorama, org_name, canonical_slug)

    @app.route('/uploads/<filename>')
    def uploaded_file(filename):
        size = request.args.get('size', '').strip().lower()
        use_thumb = size == 'thumb'
        use_optimized = size == 'optimized'
        opt_cache_ttl = max(int(SUPABASE_S3_SIGNED_URL_TTL), 3600)
        if use_thumb:
            thumb_url = get_panorama_thumb_s3_url(filename)
            if thumb_url:
                resp = redirect(thumb_url, code=302)
                try:
                    resp.headers['Cache-Control'] = f'private, max-age={int(SUPABASE_S3_SIGNED_URL_TTL)}'
                except Exception:
                    resp.headers['Cache-Control'] = 'private, max-age=900'
                return resp
            client = get_s3_client()
            if client:
                key = panorama_object_key(filename)
                try:
                    obj = client.get_object(Bucket=SUPABASE_S3_BUCKET, Key=key)
                    body = obj.get('Body')
                    data = body.read(MAX_PANORAMA_THUMB_READ_BYTES) if body else b''
                    if body:
                        try:
                            body.close()
                        except Exception:
                            pass
                    if data:
                        thumb_bytes = generate_panorama_thumb_bytes(data)
                        if thumb_bytes:
                            upload_panorama_thumb_to_s3(filename, thumb_bytes)
                            resp = Response(thumb_bytes, mimetype='image/jpeg')
                            resp.headers['Cache-Control'] = 'private, max-age=86400'
                            return resp
                except Exception:
                    pass
            local_path = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
            if os.path.isfile(local_path):
                try:
                    with open(local_path, 'rb') as f:
                        data = f.read(MAX_PANORAMA_THUMB_READ_BYTES)
                    thumb_bytes = generate_panorama_thumb_bytes(data)
                    if thumb_bytes:
                        return Response(thumb_bytes, mimetype='image/jpeg', headers={'Cache-Control': 'private, max-age=86400'})
                except Exception:
                    pass
        if use_optimized:
            opt_url = get_panorama_optimized_s3_url(filename)
            if opt_url:
                resp = redirect(opt_url, code=302)
                resp.headers['Cache-Control'] = f'private, max-age={opt_cache_ttl}'
                return resp
            client = get_s3_client()
            if client:
                key = panorama_object_key(filename)
                try:
                    obj = client.get_object(Bucket=SUPABASE_S3_BUCKET, Key=key)
                    body = obj.get('Body')
                    data = body.read(MAX_PANORAMA_OPTIMIZED_READ_BYTES) if body else b''
                    if body:
                        try:
                            body.close()
                        except Exception:
                            pass
                    if data:
                        opt_bytes = generate_panorama_optimized_bytes(data)
                        if opt_bytes:
                            upload_panorama_optimized_to_s3(filename, opt_bytes)
                            resp = Response(opt_bytes, mimetype='image/jpeg')
                            resp.headers['Cache-Control'] = f'private, max-age={opt_cache_ttl}'
                            return resp
                except Exception:
                    pass
        s3_url = get_panorama_s3_url(filename)
        if s3_url:
            resp = redirect(s3_url, code=302)
            try:
                resp.headers['Cache-Control'] = f'private, max-age={int(SUPABASE_S3_SIGNED_URL_TTL)}'
            except Exception:
                resp.headers['Cache-Control'] = 'private, max-age=900'
            return resp
        resp = send_from_directory(current_app.config['UPLOAD_FOLDER'], filename)
        try:
            if use_thumb:
                resp.headers.setdefault('Cache-Control', 'public, max-age=86400')
            elif use_optimized:
                resp.headers.setdefault('Cache-Control', f'public, max-age={int(opt_cache_ttl)}')
            else:
                resp.headers.setdefault('Cache-Control', 'public, max-age=604800')
        except Exception:
            pass
        return resp

    # ----- API: public (no auth) -----
    @app.route('/api/public/panoramas/<int:panorama_id>', methods=['GET'])
    def public_get_panorama(panorama_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        panorama = get_panorama_by_id(sb, panorama_id)
        if not panorama:
            return jsonify({'error': 'Panorama not found'}), 404
        out = dict(panorama)
        out.pop('user_id', None)
        for k in ('created_at', 'updated_at'):
            if k in out and out[k]:
                out[k] = str(out[k])
        return jsonify(out)

    @app.route('/api/public/panoramas/<int:panorama_id>/plots', methods=['GET'])
    def public_get_plots(panorama_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        panorama = get_panorama_by_id(sb, panorama_id)
        if not panorama:
            return jsonify({'error': 'Panorama not found'}), 404
        try:
            fields_base = (
                'id, panorama_id, name, area, price, status, description, color, '
                'media_photo, media_video, points, created_at, updated_at, image_filename'
            )
            fields_with_links = (
                'id, panorama_id, name, area, price, status, description, color, '
                'media_photo, media_video, linked_panorama_id, points, created_at, updated_at, image_filename'
            )
            fields_with_label = fields_with_links + ', label_longitude, label_latitude'
            try:
                r = sb.table('plots').select(fields_with_label).eq('panorama_id', panorama_id).order('created_at').execute()
            except Exception:
                try:
                    r = sb.table('plots').select(fields_with_links).eq('panorama_id', panorama_id).order('created_at').execute()
                except Exception as e2:
                    if 'linked_panorama_id' in str(e2).lower():
                        r = sb.table('plots').select(fields_base).eq('panorama_id', panorama_id).order('created_at').execute()
                    else:
                        raise
            plots = []
            for row in (r.data or []):
                p = dict(row)
                if isinstance(p.get('points'), str):
                    try:
                        p['points'] = json.loads(p['points'])
                    except Exception:
                        p['points'] = []
                p['has_image'] = bool(p.get('image_filename'))
                p.pop('image_filename', None)
                if p.get('label_longitude') is not None:
                    try:
                        p['label_longitude'] = float(p['label_longitude'])
                    except (TypeError, ValueError):
                        p['label_longitude'] = None
                if p.get('label_latitude') is not None:
                    try:
                        p['label_latitude'] = float(p['label_latitude'])
                    except (TypeError, ValueError):
                        p['label_latitude'] = None
                plots.append(p)
            # Enrich with lock status
            try:
                plot_ids = [p['id'] for p in plots if p.get('id')]
                locked_ids = set()
                if plot_ids:
                    for ci in range(0, len(plot_ids), 50):
                        chunk = plot_ids[ci:ci+50]
                        lr = sb.table('plot_locks').select('plot_id').in_('plot_id', chunk).execute()
                        for lrow in (lr.data or []):
                            locked_ids.add(lrow.get('plot_id'))
                for p in plots:
                    p['is_locked'] = p.get('id') in locked_ids
            except Exception:
                for p in plots:
                    p['is_locked'] = False
            return jsonify(plots)
        except Exception as e:
            msg = str(e)
            if 'image_filename' in msg.lower() and ('does not exist' in msg.lower() or 'column' in msg.lower()):
                return jsonify({'error': 'image_filename column missing. Run db/schema.sql in Supabase SQL Editor.'}), 503
            return jsonify({'error': msg}), 500

    @app.route('/api/public/workspaces/<workspace_id>/reference-users', methods=['GET'])
    def public_workspace_reference_users(workspace_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        workspace = get_workspace_by_id(sb, workspace_id)
        if not workspace or not workspace.get('is_published'):
            return jsonify({'error': 'Project not found'}), 404
        catalog = _project_reference_users(sb, workspace_id=workspace_id)
        return jsonify({
            'workspace_id': str(workspace_id),
            'client_ids': catalog.get('client_ids') or [],
            'reference_users': catalog.get('users') or [],
        })

    @app.route('/api/public/panoramas/<int:panorama_id>/reference-users', methods=['GET'])
    def public_panorama_reference_users(panorama_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        panorama = get_panorama_by_id(sb, panorama_id)
        if not panorama:
            return jsonify({'error': 'Panorama not found'}), 404
        catalog = _project_reference_users(sb, panorama_id=panorama_id)
        return jsonify({
            'panorama_id': int(panorama_id),
            'client_ids': catalog.get('client_ids') or [],
            'reference_users': catalog.get('users') or [],
        })

    @app.route('/api/public/plots/<int:plot_id>/image', methods=['GET'])
    def public_get_plot_image(plot_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        try:
            try:
                pl = sb.table('plots').select('panorama_id, image_filename, image_content_type').eq('id', plot_id).limit(1).execute()
            except Exception as e:
                if 'image_content_type' in str(e).lower():
                    pl = sb.table('plots').select('panorama_id, image_filename').eq('id', plot_id).limit(1).execute()
                else:
                    raise
            if not pl.data or len(pl.data) == 0:
                return jsonify({'error': 'Plot not found'}), 404
            row = pl.data[0]
            panorama_id = row.get('panorama_id')
            try:
                panorama_id = int(panorama_id)
            except Exception:
                panorama_id = None
        except Exception as e:
            msg = str(e).lower()
            if ('image_filename' in msg or 'image_content_type' in msg) and ('does not exist' in msg or 'column' in msg):
                return jsonify({'error': 'image_filename column missing. Run db/schema.sql in Supabase SQL Editor.'}), 503
            return jsonify({'error': 'Not found'}), 404
        if panorama_id is None or not get_panorama_by_id(sb, panorama_id):
            return jsonify({'error': 'Not found'}), 404
        image_filename = row.get('image_filename') or ''
        if not image_filename:
            return jsonify({'error': 'No image'}), 404
        client = get_s3_client()
        if not client:
            return jsonify({'error': 'Supabase S3 is not configured'}), 503
        try:
            obj = client.get_object(Bucket=SUPABASE_S3_BUCKET, Key=plot_object_key(image_filename))
            body = obj.get('Body')
            data = body.read() if body else b''
            try:
                if body:
                    body.close()
            except Exception:
                pass
            content_type = obj.get('ContentType') or row.get('image_content_type') or 'image/jpeg'
        except Exception:
            return jsonify({'error': 'Image not found'}), 404
        resp = Response(data, mimetype=str(content_type or 'image/jpeg'))
        resp.headers['Cache-Control'] = 'private, max-age=900'
        return resp

    @app.route('/api/public/panoramas/<int:panorama_id>/markers', methods=['GET'])
    def public_list_markers(panorama_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        panorama = get_panorama_by_id(sb, panorama_id)
        if not panorama:
            return jsonify({'error': 'Panorama not found'}), 404
        style_columns_supported = True
        link_columns_supported = True
        link_mode_columns_supported = True
        image_columns_supported = True
        base_cols = ['id', 'plot_id', 'name', 'description', 'longitude', 'latitude', 'status', 'created_at']
        style_cols = ['marker_style', 'marker_icon', 'marker_color', 'rotation_x', 'rotation_y', 'rotation_z']
        link_cols = ['linked_panorama_id']
        link_mode_cols = ['link_mode']
        voiceover_columns_supported = True

        def build_columns():
            cols = list(base_cols)
            if image_columns_supported:
                cols.insert(4, 'image_filename')
            if voiceover_columns_supported:
                cols.append('voiceover_filename')
            if link_columns_supported:
                cols.extend(link_cols)
            if link_mode_columns_supported:
                cols.extend(link_mode_cols)
            if style_columns_supported:
                cols.extend(style_cols)
            return ', '.join(cols)

        def is_style_column_error(err):
            msg = str(err).lower()
            return 'marker_style' in msg or 'marker_icon' in msg or 'marker_color' in msg

        def is_link_column_error(err):
            msg = str(err).lower()
            return 'linked_panorama_id' in msg or 'linked panorama' in msg

        def is_link_mode_column_error(err):
            msg = str(err).lower()
            return 'link_mode' in msg and ('does not exist' in msg or 'column' in msg)

        def is_image_column_error(err):
            msg = str(err).lower()
            return 'image_filename' in msg

        def is_voiceover_column_error(err):
            msg = str(err).lower()
            return 'voiceover_filename' in msg and ('does not exist' in msg or 'column' in msg)

        last_error = None
        for _ in range(4):
            try:
                r = (
                    sb.table('plot_markers')
                    .select(build_columns())
                    .eq('plot_id', str(panorama_id))
                    .order('created_at', desc=False)
                    .execute()
                )
                markers = r.data or []
                # Enrich with lock status
                try:
                    marker_ids = [str(m.get('id', '')) for m in markers if m.get('id')]
                    locked_ids = set()
                    if marker_ids:
                        for i in range(0, len(marker_ids), 50):
                            chunk = marker_ids[i:i+50]
                            lr = sb.table('plot_locks').select('plot_id').in_('plot_id', chunk).execute()
                            for row in (lr.data or []):
                                locked_ids.add(str(row.get('plot_id', '')))
                    for m in markers:
                        m['is_locked'] = str(m.get('id', '')) in locked_ids
                except Exception:
                    # If plot_locks table doesn't exist yet, just return without lock info
                    for m in markers:
                        m['is_locked'] = False
                return jsonify(markers)
            except Exception as e:
                last_error = e
                changed = False
                if style_columns_supported and is_style_column_error(e):
                    style_columns_supported = False
                    changed = True
                if link_columns_supported and is_link_column_error(e):
                    link_columns_supported = False
                    changed = True
                if link_mode_columns_supported and is_link_mode_column_error(e):
                    link_mode_columns_supported = False
                    changed = True
                if image_columns_supported and is_image_column_error(e):
                    image_columns_supported = False
                    changed = True
                if voiceover_columns_supported and is_voiceover_column_error(e):
                    voiceover_columns_supported = False
                    changed = True
                if not changed:
                    break
        return jsonify({'error': str(last_error or 'Failed to load markers')}), 500

    @app.route('/api/public/markers/<marker_id>/image', methods=['GET'])
    def public_get_marker_image(marker_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        try:
            r = sb.table('plot_markers').select('id, plot_id, image_filename').eq('id', marker_id).limit(1).execute()
            if not r.data:
                return jsonify({'error': 'Marker not found'}), 404
            row = r.data[0]
        except Exception as e:
            msg = str(e).lower()
            if 'image_filename' in msg and ('does not exist' in msg or 'column' in msg):
                return jsonify({'error': 'image_filename column missing. Run db/schema.sql in Supabase SQL Editor.'}), 503
            return jsonify({'error': 'Marker not found'}), 404
        plot_id = str(row.get('plot_id') or '').strip()
        try:
            panorama_id = int(plot_id)
        except Exception:
            panorama_id = None
        if panorama_id is not None and not get_panorama_by_id(sb, panorama_id):
            return jsonify({'error': 'Not found'}), 404
        image_filename = row.get('image_filename') or ''
        if not image_filename:
            return jsonify({'error': 'No image'}), 404
        client = get_s3_client()
        if not client:
            return jsonify({'error': 'Supabase S3 is not configured'}), 503
        use_thumb = request.args.get('size') == 'thumb'
        key = marker_object_key(image_filename)
        if use_thumb:
            thumb_key = marker_thumb_object_key(image_filename)
            if thumb_key:
                try:
                    obj = client.get_object(Bucket=SUPABASE_S3_BUCKET, Key=thumb_key)
                    body = obj.get('Body')
                    data = body.read() if body else b''
                    try:
                        if body:
                            body.close()
                    except Exception:
                        pass
                    content_type = obj.get('ContentType') or 'image/jpeg'
                    resp = Response(data, mimetype=str(content_type or 'image/jpeg'))
                    resp.headers['Cache-Control'] = 'private, max-age=900'
                    return resp
                except Exception:
                    pass
        try:
            obj = client.get_object(Bucket=SUPABASE_S3_BUCKET, Key=key)
            body = obj.get('Body')
            data = body.read() if body else b''
            try:
                if body:
                    body.close()
            except Exception:
                pass
            content_type = obj.get('ContentType') or 'image/jpeg'
        except Exception:
            return jsonify({'error': 'Image not found'}), 404
        resp = Response(data, mimetype=str(content_type or 'image/jpeg'))
        resp.headers['Cache-Control'] = 'private, max-age=900'
        return resp

    @app.route('/api/public/markers/<marker_id>/voiceover', methods=['GET'])
    def public_get_marker_voiceover(marker_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        try:
            r = sb.table('plot_markers').select('id, plot_id, voiceover_filename').eq('id', marker_id).limit(1).execute()
            if not r.data:
                return jsonify({'error': 'Marker not found'}), 404
            row = r.data[0]
        except Exception as e:
            msg = str(e).lower()
            if 'voiceover_filename' in msg and ('does not exist' in msg or 'column' in msg):
                return jsonify({'error': 'voiceover_filename column missing. Run db/schema.sql in Supabase SQL Editor.'}), 503
            return jsonify({'error': 'Marker not found'}), 404
        plot_id = str(row.get('plot_id') or '').strip()
        try:
            panorama_id = int(plot_id)
        except Exception:
            panorama_id = None
        if panorama_id is not None and not get_panorama_by_id(sb, panorama_id):
            return jsonify({'error': 'Not found'}), 404
        voiceover_filename = row.get('voiceover_filename') or ''
        if not voiceover_filename:
            return jsonify({'error': 'No voice-over'}), 404
        url = get_voiceover_s3_url(voiceover_filename)
        if not url:
            return jsonify({'error': 'Voice-over not found'}), 404
        return jsonify({'url': url})

    @app.route('/api/public/buy-interests', methods=['POST'])
    def public_create_buy_interest():
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        data = request.get_json(silent=True) or {}
        request_origin = str(data.get('origin') or '').strip().lower()
        panorama_id = data.get('panorama_id')
        try:
            panorama_id = int(panorama_id)
        except Exception:
            panorama_id = None
        customer_name = str(data.get('customer_name') or data.get('name') or '').strip()
        customer_email = str(data.get('customer_email') or data.get('email') or '').strip()
        customer_phone = str(data.get('customer_phone') or data.get('phone') or '').strip()
        customer_birthday = str(data.get('customer_birthday') or data.get('birthday') or '').strip()
        customer_street = str(data.get('customer_street') or data.get('street') or '').strip()
        customer_city = str(data.get('customer_city') or data.get('city') or '').strip()
        customer_state = str(data.get('customer_state') or data.get('state') or '').strip()
        customer_country = str(data.get('customer_country') or data.get('country') or '').strip()
        customer_zip_code = str(data.get('customer_zip_code') or data.get('zip_code') or '').strip()
        customer_address = str(data.get('customer_address') or data.get('address') or '').strip()
        if not customer_address:
            customer_address = ', '.join([x for x in [customer_street, customer_city, customer_state, customer_country, customer_zip_code] if x])
        title = str(data.get('title') or '').strip()
        if not title:
            first = str(customer_name or '').strip().split(' ')[0].replace('.', '').lower() if customer_name else ''
            if first in ('mr', 'mrs', 'ms', 'dr'):
                title = 'Dr' if first == 'dr' else first.capitalize()
        description = str(data.get('description') or '').strip()
        category = str(data.get('category') or '').strip()
        requested_lead_source = str(data.get('lead_source') or '').strip()
        lead_source = 'SalesTool' if request_origin == 'plot' else (requested_lead_source or 'SalesTool')
        requested_reference_user_id = str(data.get('reference_user_id') or '').strip()
        items = data.get('items') or data.get('plots') or []
        if not isinstance(items, list):
            items = []
        if not panorama_id and request_origin == 'manual_normal':
            try:
                pano_ids_for_manual = _crm_panorama_ids(sb, user_id, role)
                if pano_ids_for_manual:
                    panorama_id = int(pano_ids_for_manual[0])
            except Exception:
                panorama_id = None
        if not panorama_id:
            return jsonify({'error': 'panorama_id is required'}), 400
        if not customer_name:
            return jsonify({'error': 'Name is required'}), 400
        if not customer_email or '@' not in customer_email:
            return jsonify({'error': 'Valid email is required'}), 400
        if not customer_phone:
            return jsonify({'error': 'Contact number is required'}), 400
        if len(description) > 500:
            return jsonify({'error': 'Description must be 500 characters or less'}), 400
        if not category:
            return jsonify({'error': 'Category is required'}), 400
        # Same field caps the update route enforces; without them a create can
        # store values the edit form can never round-trip.
        for _field_label, _field_value, _field_cap in (
            ('Name', customer_name, 100),
            ('Email', customer_email, 254),
            ('Contact number', customer_phone, 40),
            ('Title', title, 40),
            ('Category', category, 100),
            ('Street', customer_street, 100),
            ('City', customer_city, 100),
            ('State', customer_state, 100),
            ('Country', customer_country, 100),
            ('Zip code', customer_zip_code, 40),
            ('Address', customer_address, 500),
        ):
            if len(_field_value) > _field_cap:
                return jsonify({'error': f'{_field_label} must be {_field_cap} characters or less'}), 400
        if customer_birthday:
            # buy_interests.customer_birthday is a date column; reject bad
            # formats here instead of surfacing a raw DB type error as a 500.
            try:
                customer_birthday = datetime.strptime(customer_birthday, '%Y-%m-%d').strftime('%Y-%m-%d')
            except ValueError:
                return jsonify({'error': 'Birthday must be in YYYY-MM-DD format'}), 400
        panorama = get_panorama_by_id(sb, panorama_id)
        if not panorama:
            return jsonify({'error': 'Panorama not found'}), 404
        reference_user_id, reference_catalog, reference_row = _validate_project_reference_user(
            sb,
            reference_user_id=requested_reference_user_id,
            panorama_id=panorama_id,
        )
        if requested_reference_user_id and not reference_user_id:
            return jsonify({'error': 'Selected reference is not available for this project'}), 400
        plot_ids = []
        for item in items:
            if isinstance(item, (int, float, str)):
                raw = item
            elif isinstance(item, dict):
                raw = item.get('plot_id') if 'plot_id' in item else item.get('id')
            else:
                raw = None
            if raw is None or str(raw).strip() == '':
                continue
            try:
                plot_ids.append(int(raw))
            except Exception:
                continue
        plot_ids = list(dict.fromkeys(plot_ids))
        if not plot_ids:
            return jsonify({'error': 'At least one plot is required'}), 400
        # Plots may come from any panorama in the same workspace (workspace
        # linked panoramas contribute plots from different panorama_ids), but
        # never from unrelated panoramas — otherwise arbitrary plot ids could
        # be enumerated cross-tenant via the snapshot echoed back below.
        allowed_plot_pano_ids = {int(panorama_id)}
        try:
            _plots_ws_id = (panorama or {}).get('workspace_id')
            if _plots_ws_id:
                wp = sb.table('panoramas').select('id').eq('workspace_id', _plots_ws_id).execute()
                for row in (wp.data or []):
                    if row.get('id') is not None:
                        allowed_plot_pano_ids.add(int(row.get('id')))
        except Exception:
            pass
        plots_snapshot = []
        try:
            r = (
                sb.table('plots')
                .select('id, panorama_id, name, area, price, status')
                .in_('id', plot_ids)
                .in_('panorama_id', sorted(allowed_plot_pano_ids))
                .execute()
            )
            found = {int(row.get('id')): row for row in (r.data or []) if row and row.get('id') is not None}
            for pid in plot_ids:
                row = found.get(int(pid))
                if not row:
                    continue
                plots_snapshot.append({
                    'plot_id': int(row.get('id')),
                    'panorama_id': int(row.get('panorama_id')) if row.get('panorama_id') else panorama_id,
                    'name': row.get('name') or '',
                    'area': row.get('area') or '',
                    'price': row.get('price') or '',
                    'status': row.get('status') or '',
                })
        except Exception as e:
            msg = str(e)
            if 'plots' in msg and ('does not exist' in msg.lower() or 'relation' in msg.lower()):
                return jsonify({'error': 'plots table not found. Run db/schema.sql in Supabase SQL Editor.'}), 503
            return jsonify({'error': msg}), 500
        if not plots_snapshot and request_origin == 'manual_normal':
            try:
                normal_plot_ids = [int(x) for x in (data.get('normal_plot_ids') or []) if str(x).strip()]
            except Exception:
                normal_plot_ids = []
            if not normal_plot_ids:
                normal_plot_ids = plot_ids[:]
            if normal_plot_ids:
                nr = (
                    sb.table('crm_normal_plots')
                    .select('id, project_id, project_name, name, area, price, status')
                    .eq('owner_user_id', str(user_id))
                    .in_('id', normal_plot_ids)
                    .execute()
                )
                for row in (nr.data or []):
                    plots_snapshot.append({
                        'plot_id': int(row.get('id')),
                        'normal_plot_id': int(row.get('id')),
                        'normal_project_id': row.get('project_id'),
                        'normal_project_name': row.get('project_name') or '',
                        'name': row.get('name') or '',
                        'area': row.get('area') or '',
                        'price': row.get('price') or '',
                        'status': row.get('status') or '',
                    })
        if not plots_snapshot:
            return jsonify({'error': 'No valid plots found'}), 400
        client_id = None
        if reference_row:
            reference_client_ids = list(reference_row.get('client_ids') or [])
            if reference_client_ids:
                client_id = str(reference_client_ids[0])
        if not client_id:
            project_client_ids = list(reference_catalog.get('client_ids') or [])
            if len(project_client_ids) == 1:
                client_id = str(project_client_ids[0])
        now = datetime.utcnow().isoformat()
        insert_row = {
            'panorama_id': panorama_id,
            'client_id': client_id,
            'submitted_by': None,
            'reference_user_id': reference_user_id,
            'customer_name': customer_name,
            'customer_email': customer_email,
            'customer_phone': customer_phone,
            'customer_birthday': customer_birthday or None,
            'customer_address': customer_address or None,
            'customer_street': customer_street or None,
            'customer_city': customer_city or None,
            'customer_state': customer_state or None,
            'customer_country': customer_country or None,
            'customer_zip_code': customer_zip_code or None,
            'title': title or None,
            'description': description or None,
            'lead_source': lead_source,
            'category': category,
            'plots': plots_snapshot,
            'status': 'new',
            'is_contacted': False,
            'contacted_at': None,
            'notes': '',
            'created_at': now,
            'updated_at': now,
        }
        insert_row['custom_fields'] = _extract_custom_fields_payload(data, set(insert_row.keys()))
        try:
            r = sb.table('buy_interests').insert(insert_row).execute()
            row = (r.data or [None])[0] if hasattr(r, 'data') else None
            _crm_cache_bump()
            return jsonify({'success': True, 'buy_interest': row or insert_row}), 201
        except Exception as e:
            msg = str(e)
            if any(col in msg for col in ('customer_birthday', 'customer_address', 'customer_street', 'customer_city', 'customer_state', 'customer_country', 'customer_zip_code', 'title', 'description')) and ('column' in msg.lower() or 'schema cache' in msg.lower()):
                legacy_row = dict(insert_row)
                legacy_row.pop('customer_birthday', None)
                legacy_row.pop('customer_address', None)
                legacy_row.pop('customer_street', None)
                legacy_row.pop('customer_city', None)
                legacy_row.pop('customer_state', None)
                legacy_row.pop('customer_country', None)
                legacy_row.pop('customer_zip_code', None)
                legacy_row.pop('title', None)
                legacy_row.pop('description', None)
                try:
                    r = sb.table('buy_interests').insert(legacy_row).execute()
                    row = (r.data or [None])[0] if hasattr(r, 'data') else None
                    _crm_cache_bump()
                    return jsonify({'success': True, 'buy_interest': row or legacy_row}), 201
                except Exception as legacy_error:
                    msg = str(legacy_error)
            if 'buy_interests' in msg and ('does not exist' in msg.lower() or 'relation' in msg.lower()):
                return jsonify({'error': 'buy_interests table not found. Run db/schema.sql in Supabase SQL Editor.'}), 503
            return jsonify({'error': msg}), 500

    @app.route('/api/public/portal/projects', methods=['GET'])
    def public_portal_projects():
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        q = request.args.get('q', '').strip()
        city = request.args.get('city', '').strip()
        project_type = request.args.get('type', '').strip()
        sort = request.args.get('sort', 'newest').strip()
        page = max(1, int(request.args.get('page', 1)))
        per_page = min(50, max(1, int(request.args.get('per_page', 12))))
        offset_val = (page - 1) * per_page
        try:
            query = sb.table('workspaces').select('*').eq('is_published', True)
            if city:
                query = query.ilike('location_city', f'%{city}%')
            if project_type:
                query = query.eq('project_type', project_type)
            if q:
                query = query.or_(
                    f'name.ilike.%{q}%,location_address.ilike.%{q}%,location_city.ilike.%{q}%,'
                    f'builder_name.ilike.%{q}%,description.ilike.%{q}%,rera_registration.ilike.%{q}%'
                )
            if sort == 'oldest':
                query = query.order('created_at', desc=False)
            else:
                query = query.order('created_at', desc=True)
            result = query.range(offset_val, offset_val + per_page - 1).execute()
            rows = list(result.data or [])
        except Exception as e:
            msg = str(e).lower()
            if 'does not exist' in msg or 'column' in msg or '42703' in msg:
                return jsonify({'projects': [], 'total': 0, 'page': page, 'per_page': per_page, 'cities': []})
            return jsonify({'error': str(e)}), 500

        workspace_ids = [str(r.get('id')) for r in rows if r.get('id')]
        main_pano_ids = [r.get('main_panorama_id') for r in rows if r.get('main_panorama_id')]
        main_panos = {}
        if main_pano_ids:
            try:
                pano_r = sb.table('panoramas').select('id, filename, is_360').in_('id', main_pano_ids).execute()
                for p in (pano_r.data or []):
                    main_panos[int(p.get('id'))] = p
            except Exception:
                pass

        panorama_ids = []
        ws_to_panos = {}
        try:
            panos_r = sb.table('panoramas').select('id, workspace_id').in_('workspace_id', workspace_ids).execute()
            for p in (panos_r.data or []):
                ws_id = str(p.get('workspace_id') or '')
                if ws_id not in ws_to_panos:
                    ws_to_panos[ws_id] = []
                pid = p.get('id')
                ws_to_panos[ws_id].append(pid)
                panorama_ids.append(pid)
        except Exception:
            pass

        plot_stats = {}
        if panorama_ids:
            try:
                plots_result = sb.table('plots').select('panorama_id, id, price, status').in_('panorama_id', panorama_ids).execute()
                for plot in (plots_result.data or []):
                    pid = plot.get('panorama_id')
                    if pid not in plot_stats:
                        plot_stats[pid] = {'count': 0, 'prices': [], 'available': 0, 'sold': 0, 'hold': 0}
                    stats = plot_stats[pid]
                    stats['count'] += 1
                    status = (plot.get('status') or '').lower()
                    if status == 'available':
                        stats['available'] += 1
                    elif status == 'sold':
                        stats['sold'] += 1
                    elif status in ('on_hold', 'reserved'):
                        stats['hold'] += 1
                    price_str = str(plot.get('price') or '').strip()
                    if price_str:
                        try:
                            numeric = float(''.join(c for c in price_str if c.isdigit() or c == '.'))
                            if numeric > 0:
                                stats['prices'].append(numeric)
                        except (ValueError, TypeError):
                            pass
            except Exception:
                pass

        ws_plot_stats = {}
        for ws_id, pano_ids in ws_to_panos.items():
            agg = {'count': 0, 'prices': [], 'available': 0, 'sold': 0, 'hold': 0}
            for pid in pano_ids:
                s = plot_stats.get(pid, {})
                agg['count'] += s.get('count', 0)
                agg['available'] += s.get('available', 0)
                agg['sold'] += s.get('sold', 0)
                agg['hold'] += s.get('hold', 0)
                agg['prices'].extend(s.get('prices', []))
            ws_plot_stats[ws_id] = agg

        org_ids = list(set(r.get('org_id') for r in rows if r.get('org_id')))
        org_map = {}
        if org_ids:
            try:
                org_result = sb.table('organizations').select('id, name, accent_color').in_('id', org_ids).execute()
                for org in (org_result.data or []):
                    org_map[org['id']] = org
            except Exception:
                pass

        projects = []
        for row in rows:
            ws_id = str(row.get('id'))
            main_id = row.get('main_panorama_id')
            main_pano = main_panos.get(int(main_id), {}) if main_id else {}
            stats = ws_plot_stats.get(ws_id, {'count': 0, 'prices': [], 'available': 0, 'sold': 0, 'hold': 0})
            prices = stats['prices']
            avg_price = sum(prices) / len(prices) if prices else 0
            min_price = min(prices) if prices else 0
            max_price = max(prices) if prices else 0
            org = org_map.get(row.get('org_id'), {})
            amenities = row.get('amenities') or []
            if isinstance(amenities, str):
                try:
                    amenities = json.loads(amenities)
                except Exception:
                    amenities = []

            projects.append({
                'id': ws_id,
                'main_panorama_id': int(main_id) if main_id else None,
                'name': row.get('name', ''),
                'filename': main_pano.get('filename', ''),
                'is_360': bool(main_pano.get('is_360')),
                'location_address': row.get('location_address', ''),
                'location_city': row.get('location_city', ''),
                'location_state': row.get('location_state', ''),
                'location_lat': row.get('location_lat'),
                'location_lng': row.get('location_lng'),
                'rera_registration': row.get('rera_registration', ''),
                'launch_date': str(row.get('launch_date') or ''),
                'possession_date': row.get('possession_date', ''),
                'builder_name': row.get('builder_name', ''),
                'project_type': row.get('project_type', 'residential'),
                'total_area': row.get('total_area', ''),
                'description': row.get('description', ''),
                'amenities': amenities,
                'contact_phone': row.get('contact_phone', ''),
                'contact_email': row.get('contact_email', ''),
                'google_maps_link': row.get('google_maps_link', ''),
                'org_name': org.get('name', ''),
                'org_accent': org.get('accent_color', '#c9a962'),
                'plot_count': stats['count'],
                'available_plots': stats['available'],
                'sold_plots': stats['sold'],
                'hold_plots': stats['hold'],
                'avg_price': round(avg_price, 2),
                'min_price': round(min_price, 2),
                'max_price': round(max_price, 2),
                'created_at': str(row.get('created_at') or ''),
                'updated_at': str(row.get('updated_at') or ''),
            })

        total = len(projects)
        if len(rows) == per_page:
            try:
                count_q = sb.table('workspaces').select('id', count='exact').eq('is_published', True)
                if city:
                    count_q = count_q.ilike('location_city', f'%{city}%')
                if project_type:
                    count_q = count_q.eq('project_type', project_type)
                if q:
                    count_q = count_q.or_(
                        f'name.ilike.%{q}%,location_address.ilike.%{q}%,location_city.ilike.%{q}%,'
                        f'builder_name.ilike.%{q}%,description.ilike.%{q}%'
                    )
                count_result = count_q.execute()
                total = getattr(count_result, 'count', None) or len(projects)
            except Exception:
                total = offset_val + len(projects) + 1

        cities = []
        try:
            city_q = sb.table('workspaces').select('location_city').eq('is_published', True)
            city_result = city_q.execute()
            city_set = set()
            for r in (city_result.data or []):
                c = (r.get('location_city') or '').strip()
                if c and c not in city_set:
                    city_set.add(c)
                    cities.append(c)
            cities.sort()
        except Exception:
            pass

        return jsonify({
            'projects': projects,
            'total': total,
            'page': page,
            'per_page': per_page,
            'cities': cities,
        })

    # ----- API: require Authorization Bearer token -----
    @app.route('/api/workspaces', methods=['POST'])
    @require_admin
    def create_workspace(user_id, role):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        payload = request.get_json(silent=True) or request.form or {}
        name = str(payload.get('name') or '').strip()
        if not name:
            return jsonify({'error': 'name is required'}), 400
        if len(name) > 120:
            return jsonify({'error': 'name must be 120 characters or fewer'}), 400
        project_fields = project_fields_from_payload(payload)
        try:
            ws = ws_create_workspace(sb, user_id, name, **project_fields)
            return jsonify({'success': True, 'workspace': ws}), 201
        except Exception as e:
            if is_workspace_schema_missing(e):
                return _ws_error_response()
            msg = str(e).lower()
            if 'duplicate' in msg or 'unique' in msg or 'already exists' in msg:
                return jsonify({'error': 'Project name already exists'}), 409
            return jsonify({'error': str(e)}), 500

    @app.route('/api/workspaces/<workspace_id>', methods=['GET'])
    @require_auth
    def get_workspace(user_id, role, workspace_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        try:
            workspace = get_workspace_by_id(sb, workspace_id)
        except Exception as e:
            if is_workspace_schema_missing(e):
                return _ws_error_response()
            return jsonify({'error': str(e)}), 500
        if not workspace:
            return jsonify({'error': 'Project not found'}), 404
        is_platform_admin = str(role or '').strip().lower() in ('admin', 'superadmin')
        access = 'owner' if str(workspace.get('user_id') or '') == str(user_id) else None
        if access is None:
            if is_platform_admin:
                access = 'admin'
            else:
                shared = sb.table('workspace_access').select('access_type').eq('workspace_id', workspace_id).eq('user_id', user_id).limit(1).execute()
                if not (shared.data and len(shared.data) > 0):
                    return jsonify({'error': 'Project not found'}), 404
                access = (shared.data[0].get('access_type') or 'viewer')
        ws = serialize_workspace_row(workspace, access)
        return jsonify(ws)

    @app.route('/api/workspaces/<workspace_id>', methods=['PATCH', 'PUT'])
    @require_admin
    def rename_workspace(user_id, role, workspace_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        payload = request.get_json(silent=True) or request.form or {}
        name = str(payload.get('name') or '').strip() if payload.get('name') is not None else None
        main_panorama_id = payload.get('main_panorama_id')
        if main_panorama_id is not None:
            try:
                main_panorama_id = int(main_panorama_id)
            except (TypeError, ValueError):
                main_panorama_id = None
        project_fields = project_fields_from_payload(payload)
        if not name and main_panorama_id is None and not project_fields:
            return jsonify({'error': 'Provide at least one field to update'}), 400
        if name is not None and len(name) > 120:
            return jsonify({'error': 'name must be 120 characters or fewer'}), 400
        try:
            workspace = get_workspace_by_id(sb, workspace_id)
        except Exception as e:
            if is_workspace_schema_missing(e):
                return _ws_error_response()
            return jsonify({'error': str(e)}), 500
        if not workspace:
            return jsonify({'error': 'Project not found'}), 404
        is_owner = str(workspace.get('user_id') or '') == str(user_id)
        is_platform_admin = str(role or '').strip().lower() in ('admin', 'superadmin')
        if not is_owner and not is_platform_admin:
            return jsonify({'error': 'Only Project owner can update'}), 403
        try:
            ws = ws_update_workspace(sb, workspace_id, user_id, name=name, main_panorama_id=main_panorama_id, allow_admin_override=is_platform_admin, **project_fields)
            return jsonify({'success': True, 'workspace': ws})
        except ValueError as ve:
            err = str(ve)
            if 'Panorama' in err or 'workspace' in err.lower():
                return jsonify({'error': err}), 400
            if 'name' in err.lower():
                return jsonify({'error': err}), 400
            return jsonify({'error': err}), 400
        except Exception as e:
            if is_workspace_schema_missing(e):
                return _ws_error_response()
            msg = str(e).lower()
            if 'duplicate' in msg or 'unique' in msg or 'already exists' in msg:
                return jsonify({'error': 'Project name already exists'}), 409
            return jsonify({'error': str(e)}), 500

    @app.route('/api/workspaces/<workspace_id>', methods=['DELETE'])
    @require_admin
    def delete_workspace(user_id, role, workspace_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        try:
            workspace = get_workspace_by_id(sb, workspace_id)
        except Exception as e:
            if is_workspace_schema_missing(e):
                return _ws_error_response()
            return jsonify({'error': str(e)}), 500
        if not workspace:
            return jsonify({'error': 'Project not found'}), 404
        is_owner = str(workspace.get('user_id') or '') == str(user_id)
        is_platform_admin = str(role or '').strip().lower() in ('admin', 'superadmin')
        if not is_owner and not is_platform_admin:
            return jsonify({'error': 'Only Project owner can delete'}), 403
        try:
            ok = ws_delete_workspace(sb, workspace_id, user_id, allow_admin_override=is_platform_admin)
            if ok:
                return jsonify({'success': True})
            return jsonify({'error': 'Delete failed'}), 500
        except Exception as e:
            if is_workspace_schema_missing(e):
                return _ws_error_response()
            return jsonify({'error': str(e)}), 500

    @app.route('/api/workspaces/<workspace_id>/customer-view-config', methods=['GET'])
    def get_workspace_customer_view_config_public(workspace_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        try:
            workspace = get_workspace_by_id(sb, workspace_id)
        except Exception as e:
            if is_workspace_schema_missing(e):
                return _ws_error_response()
            return jsonify({'error': str(e)}), 500
        if not workspace:
            return jsonify({'error': 'Project not found'}), 404
        config = ws_get_customer_config(sb, workspace_id)
        return jsonify({'success': True, 'config': config or {}})

    @app.route('/api/workspaces/<workspace_id>/customer-config', methods=['GET'])
    @require_admin
    def get_workspace_customer_config(user_id, role, workspace_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        try:
            workspace = get_workspace_by_id(sb, workspace_id)
        except Exception as e:
            if is_workspace_schema_missing(e):
                return _ws_error_response()
            return jsonify({'error': str(e)}), 500
        if not workspace:
            return jsonify({'error': 'Project not found'}), 404
        if not can_manage_workspace(sb, workspace, user_id, role):
            return jsonify({'error': 'Forbidden'}), 403
        config = ws_get_customer_config(sb, workspace_id)
        return jsonify({'success': True, 'config': config or {}})

    @app.route('/api/workspaces/<workspace_id>/customer-config', methods=['PATCH', 'PUT'])
    @require_admin
    def update_workspace_customer_config(user_id, role, workspace_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        payload = request.get_json(silent=True) or {}
        config = payload.get('config')
        if not isinstance(config, dict):
            return jsonify({'error': 'config must be a JSON object'}), 400
        try:
            result = ws_update_customer_config(sb, workspace_id, user_id, role, config)
        except Exception as e:
            if is_workspace_schema_missing(e):
                return _ws_error_response()
            return jsonify({'error': str(e)}), 500
        if not result:
            return jsonify({'error': 'Project not found or forbidden'}), 404
        return jsonify({'success': True, 'config': config})

    @app.route('/api/workspaces/share-endpoint/check', methods=['POST'])
    @require_admin
    def check_workspace_share_endpoint(user_id, role):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        payload = request.get_json(silent=True) or {}
        endpoint = str(payload.get('endpoint') or '')
        workspace_id = str(payload.get('workspace_id') or '').strip() or None
        normalized = ws_normalize_workspace_share_endpoint(endpoint)
        if normalized is None:
            return jsonify({'success': True, 'available': False, 'normalized_endpoint': None, 'error': 'Endpoint must use only lowercase letters, numbers, hyphens, and be 3-63 chars'})
        if not normalized:
            return jsonify({'success': True, 'available': False, 'normalized_endpoint': '', 'error': 'Endpoint is required'})
        try:
            if workspace_id:
                workspace = get_workspace_by_id(sb, workspace_id)
                if not workspace:
                    return jsonify({'error': 'Project not found'}), 404
                if not can_manage_workspace(sb, workspace, user_id, role):
                    return jsonify({'error': 'Forbidden'}), 403
            available = ws_is_workspace_share_endpoint_available(sb, normalized, workspace_id)
            return jsonify({'success': True, 'available': bool(available), 'normalized_endpoint': normalized})
        except Exception as e:
            if is_workspace_schema_missing(e):
                return _ws_error_response()
            return jsonify({'error': str(e)}), 500

    @app.route('/api/workspaces/<workspace_id>/share-endpoint', methods=['GET'])
    @require_auth
    def get_workspace_share_endpoint(user_id, role, workspace_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        try:
            workspace = get_workspace_by_id(sb, workspace_id)
            if not workspace:
                return jsonify({'error': 'Project not found'}), 404
            # Allow owner/admin OR users with project access (client/viewer)
            has_access = can_manage_workspace(sb, workspace, user_id, role)
            if not has_access:
                try:
                    acc = sb.table('workspace_access').select('access_type').eq('workspace_id', workspace_id).eq('user_id', user_id).limit(1).execute()
                    has_access = bool(acc.data and len(acc.data) > 0)
                except Exception:
                    pass
            if not has_access:
                try:
                    ref_catalog = _project_reference_users(sb, workspace_id=workspace_id)
                    has_access = any(
                        str(row.get('user_id') or '') == str(user_id)
                        for row in (ref_catalog.get('users') or [])
                    )
                except Exception:
                    has_access = False
            if not has_access:
                return jsonify({'error': 'Forbidden'}), 403
            row = ws_get_workspace_share_endpoint(sb, workspace_id) or {}
            payload = _workspace_share_payload(workspace_id, row.get('endpoint'))
            return jsonify({'success': True, 'share': payload})
        except Exception as e:
            if is_workspace_schema_missing(e):
                return _ws_error_response()
            return jsonify({'error': str(e)}), 500

    @app.route('/api/workspaces/<workspace_id>/share-endpoint', methods=['PATCH', 'PUT'])
    @require_admin
    def update_workspace_share_endpoint(user_id, role, workspace_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        payload = request.get_json(silent=True) or {}
        endpoint = payload.get('endpoint')
        try:
            result = ws_update_workspace_share_endpoint(sb, workspace_id, user_id, role, endpoint)
            if not result:
                return jsonify({'error': 'Project not found or forbidden'}), 404
            share = _workspace_share_payload(workspace_id, result.get('endpoint'))
            return jsonify({'success': True, 'share': share})
        except ValueError as ve:
            return jsonify({'error': str(ve)}), 400
        except Exception as e:
            if is_workspace_schema_missing(e):
                return _ws_error_response()
            return jsonify({'error': str(e)}), 500

    @app.route('/api/panoramas/upload-url', methods=['POST'])
    @require_admin
    def create_panorama_upload_url(user_id, role):
        if not use_s3():
            return jsonify({'error': 'Supabase S3 is not configured'}), 503
        payload = request.get_json(silent=True) or request.form or {}
        original_filename = str(payload.get('original_filename') or payload.get('filename') or '').strip()
        if not original_filename:
            return jsonify({'error': 'original_filename is required'}), 400
        max_bytes = current_app.config.get('MAX_CONTENT_LENGTH') or 0
        try:
            size_bytes = int(payload.get('size_bytes') or payload.get('size') or 0)
        except Exception:
            size_bytes = 0
        if max_bytes and size_bytes and size_bytes > max_bytes:
            max_mb = max(1, int(max_bytes / (1024 * 1024)))
            return jsonify({'error': f'Upload too large (max {max_mb}MB)'}), 413
        name = str(payload.get('name') or 'panorama').strip()
        if len(name) > 120:
            name = name[:120]
        content_type_hint = str(payload.get('content_type') or '').lower().strip()
        ext = original_filename.rsplit('.', 1)[-1].lower() if '.' in original_filename else ''
        if ext not in ALLOWED_EXTENSIONS and content_type_hint:
            ext = _detect_ext_from_content_type(content_type_hint)
        if ext not in ALLOWED_EXTENSIONS:
            return jsonify({'error': 'File type not allowed'}), 400
        safe_project = secure_filename(name) or 'panorama'
        unique = uuid.uuid4().hex[:10]
        filename = f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{safe_project}_{unique}.{ext}"
        image_content_type = IMAGE_CONTENT_TYPES.get(ext, 'image/jpeg')
        client = get_s3_client()
        if not client:
            return jsonify({'error': 'Supabase S3 is not fully configured'}), 503
        key = panorama_object_key(filename)
        try:
            upload_url = client.generate_presigned_url(
                ClientMethod='put_object',
                Params={'Bucket': SUPABASE_S3_BUCKET, 'Key': key, 'ContentType': image_content_type},
                ExpiresIn=int(SUPABASE_S3_UPLOAD_URL_TTL),
            )
        except Exception as e:
            current_app.logger.exception('Failed to generate panorama upload URL')
            return jsonify({'error': str(e)}), 500
        token = panorama_upload_serializer(secret_key).dumps({
            'user_id': str(user_id),
            'filename': filename,
            'content_type': image_content_type,
        })
        return jsonify({
            'filename': filename,
            'upload_url': upload_url,
            'upload_token': token,
            'content_type': image_content_type,
            'max_bytes': max_bytes,
            'expires_in': int(SUPABASE_S3_UPLOAD_URL_TTL),
        })

    @app.route('/api/panoramas', methods=['POST'])
    @require_admin
    def create_panorama(user_id, role):
        def _coerce_dim(value):
            try:
                n = int(str(value).strip())
                if n < 0:
                    return 0
                return min(n, 200000)
            except Exception:
                return 0
        payload = request.form or {}
        name = payload.get('name', 'Untitled Panorama')
        is_360 = str(payload.get('is_360', 'false')).lower() == 'true'
        workspace_id = str(payload.get('workspace_id') or '').strip() or None
        width = _coerce_dim(payload.get('width'))
        height = _coerce_dim(payload.get('height'))
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        stored_ok = False
        local_filepath = None
        file = request.files.get('file')
        if file:
            if use_s3():
                return jsonify({'error': 'Direct upload required. Use /api/panoramas/upload-url.'}), 400
            if file.filename == '':
                return jsonify({'error': 'No file selected'}), 400
            if not allowed_file(file.filename):
                return jsonify({'error': 'File type not allowed'}), 400
            original_filename = secure_filename(file.filename) or 'upload'
            ext = original_filename.rsplit('.', 1)[1].lower()
            safe_project = secure_filename(name) or 'panorama'
            unique = uuid.uuid4().hex[:10]
            filename = f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{safe_project}_{unique}.{ext}"
            image_content_type = IMAGE_CONTENT_TYPES.get(ext, 'image/jpeg')
            try:
                if use_s3():
                    upload_panorama_to_s3(filename, file.stream, image_content_type)
                    stored_ok = True
                else:
                    local_filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
                    file.save(local_filepath)
                    stored_ok = True
            except Exception as e:
                current_app.logger.exception('Panorama file storage failed')
                return jsonify({'error': str(e)}), 500
        else:
            filename = os.path.basename(str(payload.get('filename') or '')).strip()
            upload_token = str(payload.get('upload_token') or '').strip()
            if not filename:
                return jsonify({'error': 'filename is required'}), 400
            if not upload_token:
                return jsonify({'error': 'upload_token is required'}), 400
            if not allowed_file(filename):
                return jsonify({'error': 'File type not allowed'}), 400
            if not use_s3():
                return jsonify({'error': 'Supabase S3 is not configured'}), 503
            try:
                signed = panorama_upload_serializer(secret_key).loads(
                    upload_token,
                    max_age=int(SUPABASE_S3_UPLOAD_URL_TTL),
                )
            except SignatureExpired:
                return jsonify({'error': 'upload_token expired; request a new upload URL'}), 400
            except BadSignature:
                return jsonify({'error': 'Invalid upload_token'}), 400
            if str(signed.get('user_id')) != str(user_id) or str(signed.get('filename')) != filename:
                return jsonify({'error': 'Invalid upload_token'}), 403
            ext = filename.rsplit('.', 1)[1].lower()
            image_content_type = str(signed.get('content_type') or IMAGE_CONTENT_TYPES.get(ext, 'image/jpeg'))
            client = get_s3_client()
            if not client:
                return jsonify({'error': 'Supabase S3 is not fully configured'}), 503
            try:
                head = client.head_object(Bucket=SUPABASE_S3_BUCKET, Key=panorama_object_key(filename))
                stored_ok = True
            except Exception:
                return jsonify({'error': 'Upload not found. Re-upload and try again.'}), 400
            try:
                size_bytes = int(head.get('ContentLength') or 0)
            except Exception:
                size_bytes = 0
            max_bytes = current_app.config.get('MAX_CONTENT_LENGTH') or 0
            if max_bytes and size_bytes and size_bytes > max_bytes:
                delete_panorama_from_s3(filename)
                max_mb = max(1, int(max_bytes / (1024 * 1024)))
                return jsonify({'error': f'Upload too large (max {max_mb}MB)'}), 413
            try:
                obj = client.get_object(Bucket=SUPABASE_S3_BUCKET, Key=panorama_object_key(filename))
                body = obj.get('Body')
                data = body.read(MAX_PANORAMA_THUMB_READ_BYTES) if body else b''
                if body:
                    try:
                        body.close()
                    except Exception:
                        pass
                if data:
                    thumb_bytes = generate_panorama_thumb_bytes(data)
                    if thumb_bytes:
                        upload_panorama_thumb_to_s3(filename, thumb_bytes)
                    opt_bytes = generate_panorama_optimized_bytes(data)
                    if opt_bytes:
                        upload_panorama_optimized_to_s3(filename, opt_bytes)
            except Exception:
                pass
            original_filename = secure_filename(str(payload.get('original_filename') or filename)) or 'upload'
        try:
            org_id = None
            try:
                profile = get_profile(sb, user_id) or {}
                org_id = profile.get('org_id')
            except Exception:
                org_id = None
            if workspace_id:
                try:
                    workspace = get_workspace_by_id(sb, workspace_id)
                except Exception as e:
                    if is_workspace_schema_missing(e):
                        return _ws_error_response()
                    return jsonify({'error': str(e)}), 500
                if not workspace:
                    return jsonify({'error': 'Project not found'}), 404
                if str(workspace.get('user_id') or '') != str(user_id):
                    return jsonify({'error': 'You can only upload into your own workspace'}), 403
                ws_org = workspace.get('org_id')
                if org_id and ws_org and str(org_id) != str(ws_org):
                    return jsonify({'error': 'Project organization does not match your profile'}), 403
            insert_row = {
                'user_id': user_id,
                'org_id': org_id,
                'workspace_id': workspace_id,
                'name': name,
                'filename': filename,
                'original_filename': original_filename,
                'width': width,
                'height': height,
                'is_360': is_360,
                'image_content_type': image_content_type,
            }
            try:
                r = sb.table('panoramas').insert(insert_row).execute()
            except Exception as e:
                msg = str(e).lower()
                if (('workspace_id' in msg and ('column' in msg or 'does not exist' in msg)) or ('org_id' in msg)):
                    retry_row = dict(insert_row)
                    if 'workspace_id' in msg and ('column' in msg or 'does not exist' in msg):
                        retry_row.pop('workspace_id', None)
                    if 'org_id' in msg:
                        retry_row.pop('org_id', None)
                    try:
                        r = sb.table('panoramas').insert(retry_row).execute()
                        insert_row = retry_row
                    except Exception as e2:
                        msg2 = str(e2).lower()
                        changed = False
                        if 'workspace_id' in msg2 and ('column' in msg2 or 'does not exist' in msg2):
                            retry_row.pop('workspace_id', None)
                            changed = True
                        if 'org_id' in msg2:
                            retry_row.pop('org_id', None)
                            changed = True
                        if not changed:
                            raise
                        r = sb.table('panoramas').insert(retry_row).execute()
                        insert_row = retry_row
                else:
                    raise
            if not r.data or len(r.data) == 0:
                raise RuntimeError('Insert failed')
            panorama_id = r.data[0]['id']

            # Auto-set as main if this is a 360 panorama in a folder with no main
            if workspace_id and is_360:
                try:
                    ws_row = get_workspace_by_id(sb, workspace_id)
                    if ws_row and not ws_row.get('main_panorama_id'):
                        sb.table('workspaces').update({
                            'main_panorama_id': panorama_id,
                            'updated_at': datetime.utcnow().isoformat(),
                        }).eq('id', workspace_id).execute()
                except Exception:
                    pass
                try:
                    ws_ensure_panorama_added_to_workspace_config(sb, workspace_id, panorama_id, user_id, role)
                except Exception:
                    pass

            return jsonify({
                'id': panorama_id,
                'name': name,
                'filename': filename,
                'width': width,
                'height': height,
                'is_360': is_360,
                'workspace_id': workspace_id,
                'access_type': 'owner',
            }), 201
        except Exception as e:
            current_app.logger.exception('Panorama upload failed')
            if stored_ok:
                if use_s3():
                    delete_panorama_from_s3(filename)
                elif local_filepath and os.path.exists(local_filepath):
                    try:
                        os.remove(local_filepath)
                    except Exception:
                        pass
            return jsonify({'error': str(e)}), 500

    @app.route('/api/panoramas/<int:panorama_id>', methods=['DELETE'])
    @require_admin
    def delete_panorama(user_id, role, panorama_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        panorama, access_type = get_panorama_with_access(sb, panorama_id, user_id)
        if not panorama:
            return jsonify({'error': 'Panorama not found'}), 404
        if not can_delete_panorama(access_type):
            return jsonify({'error': 'Only the owner can delete this panorama'}), 403

        # If deleting the main panorama, set a new main first so customer links keep working
        payload = request.get_json(silent=True) or {}
        new_main_id = payload.get('new_main_panorama_id')
        workspace_id = panorama.get('workspace_id')
        if new_main_id and workspace_id:
            try:
                new_main_id = int(new_main_id)
                # Verify the new main panorama exists and belongs to the same workspace
                new_pano = get_panorama_by_id(sb, new_main_id)
                if not new_pano:
                    return jsonify({'error': 'New main panorama not found'}), 400
                if str(new_pano.get('workspace_id') or '') != str(workspace_id):
                    return jsonify({'error': 'New main panorama must be in the same project'}), 400
                # Update workspace main_panorama_id to the new panorama
                sb.table('workspaces').update({
                    'main_panorama_id': new_main_id,
                    'updated_at': datetime.utcnow().isoformat()
                }).eq('id', workspace_id).execute()
            except (TypeError, ValueError):
                return jsonify({'error': 'Invalid new_main_panorama_id'}), 400
        else:
            # No replacement specified — clear the main reference
            clear_workspace_main_for_panorama(sb, panorama_id)

        filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], panorama['filename'])
        delete_panorama_from_s3(panorama['filename'])
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
            except Exception:
                pass
        try:
            sb.table('panoramas').delete().eq('id', panorama_id).execute()
        except Exception as e:
            return jsonify({'error': str(e)}), 500
        return jsonify({'success': True})

    @app.route('/api/panoramas/<int:panorama_id>/generate-optimized', methods=['POST'])
    @require_admin
    def generate_panorama_optimized(user_id, role, panorama_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        panorama = get_panorama_by_id(sb, panorama_id)
        if not panorama:
            return jsonify({'error': 'Panorama not found'}), 404
        filename = panorama.get('filename')
        if not filename:
            return jsonify({'error': 'No file associated'}), 400
        opt_url = get_panorama_optimized_s3_url(filename)
        if opt_url:
            return jsonify({'success': True, 'exists': True})
        client = get_s3_client()
        if not client:
            return jsonify({'error': 'S3 not configured'}), 503
        try:
            obj = client.get_object(Bucket=SUPABASE_S3_BUCKET, Key=panorama_object_key(filename))
            body = obj.get('Body')
            data = body.read(MAX_PANORAMA_OPTIMIZED_READ_BYTES) if body else b''
            if body:
                try:
                    body.close()
                except Exception:
                    pass
            if not data:
                return jsonify({'error': 'Could not read source image'}), 500
            opt_bytes = generate_panorama_optimized_bytes(data)
            if not opt_bytes:
                return jsonify({'error': 'Optimized version not smaller than original; original is already efficient'}), 200
            upload_panorama_optimized_to_s3(filename, opt_bytes)
            return jsonify({'success': True, 'size': len(opt_bytes), 'original_size': len(data)})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/panoramas/<int:panorama_id>/mobile', methods=['GET'])
    @require_auth
    def get_mobile_panorama(user_id, role, panorama_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        panorama, access_type = get_panorama_with_access(sb, panorama_id, user_id)
        if not panorama or str((panorama or {}).get('source_table') or 'panoramas') != 'panoramas':
            return jsonify({'error': 'Panorama not found'}), 404
        if not can_edit_plots(access_type):
            return jsonify({'error': 'Forbidden'}), 403
        mobile = get_mobile_panorama_by_parent_id(sb, panorama_id)
        return jsonify({'mobile_panorama': mobile})

    @app.route('/api/panoramas/<int:panorama_id>/mobile', methods=['POST', 'PUT'])
    @require_admin
    def create_or_update_mobile_panorama(user_id, role, panorama_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        parent, access_type = get_panorama_with_access(sb, panorama_id, user_id)
        if not parent or str((parent or {}).get('source_table') or 'panoramas') != 'panoramas':
            return jsonify({'error': 'Panorama not found'}), 404
        if str(parent.get('user_id') or '') != str(user_id) and access_type != 'owner':
            return jsonify({'error': 'Only owner can manage mobile image'}), 403
        file = request.files.get('file')
        if not file or not getattr(file, 'filename', ''):
            return jsonify({'error': 'file is required'}), 400
        if not allowed_file(file.filename):
            return jsonify({'error': 'File type not allowed'}), 400
        name = str((request.form or {}).get('name') or (parent.get('name') or 'Mobile Panorama')).strip()
        if len(name) > 120:
            name = name[:120]
        original_filename = secure_filename(file.filename) or 'upload'
        ext = original_filename.rsplit('.', 1)[1].lower()
        safe_project = secure_filename(name) or 'mobile_panorama'
        unique = uuid.uuid4().hex[:10]
        filename = f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{safe_project}_{unique}.{ext}"
        image_content_type = IMAGE_CONTENT_TYPES.get(ext, 'image/jpeg')
        stored_ok = False
        local_filepath = None
        try:
            try:
                w, h = probe_image_dimensions(file.stream)
            except Exception:
                w, h = 0, 0
            if use_s3():
                upload_panorama_to_s3(filename, file.stream, image_content_type)
            else:
                local_filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
                file.save(local_filepath)
            stored_ok = True
            existing = get_mobile_panorama_by_parent_id(sb, panorama_id)
            row = {
                'user_id': parent.get('user_id'),
                'org_id': parent.get('org_id'),
                'workspace_id': parent.get('workspace_id'),
                'panorama_parent_id': panorama_id,
                'name': name,
                'filename': filename,
                'original_filename': original_filename,
                'width': int(w or 0),
                'height': int(h or 0),
                'is_360': False,
                'use_animated_icons': False,
                'start_view': None,
                'image_content_type': image_content_type,
                'updated_at': datetime.utcnow().isoformat(),
            }
            if existing and existing.get('id'):
                sb.table('mobile_panoramas').update(row).eq('id', existing.get('id')).execute()
                mobile_id = existing.get('id')
                old_filename = str(existing.get('filename') or '').strip()
                if old_filename and old_filename != filename:
                    delete_panorama_from_s3(old_filename)
                    old_path = os.path.join(current_app.config['UPLOAD_FOLDER'], old_filename)
                    if os.path.isfile(old_path):
                        try:
                            os.remove(old_path)
                        except Exception:
                            pass
            else:
                row['created_at'] = datetime.utcnow().isoformat()
                r = sb.table('mobile_panoramas').insert(row).execute()
                if not r.data:
                    raise RuntimeError('Insert failed')
                mobile_id = r.data[0].get('id')
            mobile = get_mobile_panorama_by_parent_id(sb, panorama_id)
            return jsonify({'success': True, 'id': mobile_id, 'mobile_panorama': mobile})
        except Exception as e:
            if stored_ok:
                delete_panorama_from_s3(filename)
                if local_filepath and os.path.exists(local_filepath):
                    try:
                        os.remove(local_filepath)
                    except Exception:
                        pass
            return jsonify({'error': str(e)}), 500

    @app.route('/api/panoramas/<int:panorama_id>', methods=['PUT', 'PATCH'])
    @require_auth
    def rename_panorama(user_id, role, panorama_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        panorama, access_type = get_panorama_with_access(sb, panorama_id, user_id)
        # Fallback: allow admins / superadmins who have CRM access
        if not panorama:
            normalized_role = str(role or 'user').strip().lower()
            if normalized_role in ('admin', 'superadmin'):
                crm_ids = _crm_panorama_ids(sb, user_id, role)
                if panorama_id in crm_ids:
                    try:
                        r = sb.table('panoramas').select('*').eq('id', panorama_id).limit(1).execute()
                        if r.data and len(r.data) > 0:
                            panorama = r.data[0]
                            access_type = 'owner'
                    except Exception:
                        pass
        if not panorama:
            return jsonify({'error': 'Panorama not found'}), 404
        if not can_edit_plots(access_type):
            return jsonify({'error': 'You do not have permission to edit this panorama'}), 403
        payload = request.get_json(silent=True) or request.form or {}
        name = str(payload.get('name', '')).strip() if payload.get('name') is not None else None
        use_animated_icons = payload.get('use_animated_icons')
        start_view = payload.get('start_view') if 'start_view' in payload else None
        if use_animated_icons is not None:
            use_animated_icons = bool(use_animated_icons) if use_animated_icons not in (True, False) else use_animated_icons
        update_fields = {'updated_at': datetime.utcnow().isoformat()}
        if name is not None:
            if not name:
                return jsonify({'error': 'Name is required'}), 400
            if len(name) > 120:
                return jsonify({'error': 'Name must be 120 characters or fewer'}), 400
            update_fields['name'] = name
        if use_animated_icons is not None:
            update_fields['use_animated_icons'] = use_animated_icons
        if start_view is not None:
            if start_view is False:
                update_fields['start_view'] = None
            elif start_view is None:
                update_fields['start_view'] = None
            elif isinstance(start_view, dict):
                lon = start_view.get('longitude')
                lat = start_view.get('latitude')
                zoom = start_view.get('zoom')
                try:
                    lon = float(lon) if lon is not None else None
                    lat = float(lat) if lat is not None else None
                    zoom = float(zoom) if zoom is not None else None
                except Exception:
                    return jsonify({'error': 'Invalid start_view'}), 400
                if lon is None or lat is None:
                    return jsonify({'error': 'start_view must include longitude and latitude'}), 400
                next_view = {'longitude': lon, 'latitude': lat}
                if zoom is not None:
                    next_view['zoom'] = zoom
                update_fields['start_view'] = next_view
            else:
                return jsonify({'error': 'Invalid start_view'}), 400
        if len(update_fields) <= 1:
            return jsonify({'error': 'Provide at least one field to update'}), 400
        try:
            response = sb.table('panoramas').update(update_fields).eq('id', panorama_id).execute()
            err = getattr(response, 'error', None)
            if err:
                message = getattr(err, 'message', None) or str(err)
                return jsonify({'error': message}), 500
            row = None
            data = getattr(response, 'data', None)
            if isinstance(data, list) and data:
                row = data[0]
            if not row:
                try:
                    fetch = sb.table('panoramas').select('id, name, updated_at, use_animated_icons').eq('id', panorama_id).limit(1).execute()
                except Exception:
                    fetch = sb.table('panoramas').select('id, name, updated_at').eq('id', panorama_id).limit(1).execute()
                ferr = getattr(fetch, 'error', None)
                if ferr:
                    message = getattr(ferr, 'message', None) or str(ferr)
                    return jsonify({'error': message}), 500
                fdata = getattr(fetch, 'data', None)
                if isinstance(fdata, list) and fdata:
                    row = fdata[0]
            if row:
                out = {
                    'id': row.get('id', panorama_id),
                    'name': row.get('name', name) if name is not None else row.get('name'),
                    'updated_at': str(row.get('updated_at') or datetime.utcnow().isoformat()),
                }
                if 'use_animated_icons' in row:
                    out['use_animated_icons'] = bool(row.get('use_animated_icons'))
                if 'start_view' in row:
                    out['start_view'] = row.get('start_view')
                return jsonify(out)
        except Exception as e:
            return jsonify({'error': str(e)}), 500
        out = {'id': panorama_id, 'updated_at': datetime.utcnow().isoformat()}
        if name is not None:
            out['name'] = name
        if use_animated_icons is not None:
            out['use_animated_icons'] = use_animated_icons
        if start_view is not None:
            out['start_view'] = update_fields.get('start_view')
        return jsonify(out)

    # ── Panorama Audio Upload ──
    @app.route('/api/panoramas/<int:panorama_id>/audio', methods=['POST'])
    @require_auth
    def upload_panorama_audio(user_id, role, panorama_id):
        if not use_s3():
            return jsonify({'error': 'Supabase S3 is not configured'}), 503
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        panorama, access_type = get_panorama_with_access(sb, panorama_id, user_id)
        if not panorama:
            return jsonify({'error': 'Panorama not found'}), 404
        if not can_edit_plots(access_type):
            return jsonify({'error': 'Forbidden'}), 403
        old_filename = str(panorama.get('audio_filename') or '').strip()
        file_storage = request.files.get('file') or request.files.get('audio')
        if not file_storage or not getattr(file_storage, 'filename', None):
            return jsonify({'error': 'No audio file (use form field "file" or "audio")'}), 400
        filename_orig = (file_storage.filename or '').strip()
        ext = (filename_orig.rsplit('.', 1)[-1].lower() if '.' in filename_orig else '').strip()
        if ext not in ALLOWED_AUDIO_EXTENSIONS:
            return jsonify({'error': 'Audio type not allowed. Use: mp3, wav, m4a, ogg, webm'}), 400
        data = read_uploaded_file_bytes(file_storage, MAX_PANORAMA_AUDIO_BYTES)
        if len(data) > MAX_PANORAMA_AUDIO_BYTES:
            return jsonify({'error': f'Audio too large (max {MAX_PANORAMA_AUDIO_BYTES // (1024*1024)}MB)'}), 413
        if not data:
            return jsonify({'error': 'Empty file'}), 400
        unique = uuid.uuid4().hex[:10]
        filename = f"pano_audio_{panorama_id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{unique}.{ext}"
        content_type = AUDIO_CONTENT_TYPES.get(ext, 'audio/mpeg')
        client = get_s3_client()
        if not client:
            return jsonify({'error': 'Supabase S3 is not configured'}), 503
        try:
            client.put_object(
                Bucket=SUPABASE_S3_BUCKET,
                Key=panorama_audio_object_key(filename),
                Body=data,
                ContentType=content_type,
            )
        except Exception as e:
            current_app.logger.exception('Panorama audio S3 upload failed')
            return jsonify({'error': str(e)}), 500
        try:
            sb.table('panoramas').update({
                'audio_filename': filename,
                'updated_at': datetime.utcnow().isoformat(),
            }).eq('id', panorama_id).execute()
        except Exception as e:
            current_app.logger.exception('Failed to update panorama audio_filename')
            try:
                delete_panorama_audio_from_s3(filename)
            except Exception:
                pass
            return jsonify({'error': 'Failed to save'}), 500
        if old_filename and old_filename != filename:
            delete_panorama_audio_from_s3(old_filename)
        audio_url = get_panorama_audio_s3_url(filename)
        return jsonify({'success': True, 'audio_filename': filename, 'audio_url': audio_url})

    @app.route('/api/panoramas/<int:panorama_id>/audio', methods=['DELETE'])
    @require_auth
    def delete_panorama_audio(user_id, role, panorama_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        panorama, access_type = get_panorama_with_access(sb, panorama_id, user_id)
        if not panorama:
            return jsonify({'error': 'Panorama not found'}), 404
        if not can_edit_plots(access_type):
            return jsonify({'error': 'Forbidden'}), 403
        old_filename = str(panorama.get('audio_filename') or '').strip()
        if not old_filename:
            return jsonify({'success': True})
        try:
            sb.table('panoramas').update({
                'audio_filename': None,
                'updated_at': datetime.utcnow().isoformat(),
            }).eq('id', panorama_id).execute()
        except Exception as e:
            return jsonify({'error': str(e)}), 500
        delete_panorama_audio_from_s3(old_filename)
        return jsonify({'success': True})

    @app.route('/api/panoramas/<int:panorama_id>/audio-url', methods=['GET'])
    def get_panorama_audio_url(panorama_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        try:
            r = sb.table('panoramas').select('audio_filename').eq('id', panorama_id).limit(1).execute()
            if not r.data:
                return jsonify({'error': 'Panorama not found'}), 404
            fname = (r.data[0].get('audio_filename') or '').strip()
        except Exception:
            return jsonify({'error': 'audio_filename column missing'}), 503
        if not fname:
            return jsonify({'audio_url': None})
        url = get_panorama_audio_s3_url(fname)
        return jsonify({'audio_url': url})

    # ── Resolve Google Maps short links & reverse-geocode ──
    @app.route('/api/resolve-maps-link', methods=['POST'])
    @require_auth
    def resolve_maps_link(user_id, role):
        payload = request.get_json(silent=True) or {}
        link = str(payload.get('link') or '').strip()
        if not link:
            return jsonify({'error': 'No link provided'}), 400

        # Follow redirects for short URLs (maps.app.goo.gl, goo.gl, etc.)
        resolved_url = link
        if 'goo.gl/' in link or 'maps.app.goo.gl/' in link:
            try:
                resp = _requests.head(link, allow_redirects=True, timeout=10,
                                      headers={'User-Agent': 'Mozilla/5.0'})
                resolved_url = resp.url
            except Exception:
                try:
                    resp = _requests.get(link, allow_redirects=True, timeout=10,
                                         stream=True,
                                         headers={'User-Agent': 'Mozilla/5.0'})
                    resolved_url = resp.url
                    resp.close()
                except Exception:
                    return jsonify({'error': 'Could not resolve short URL'}), 400

        # Extract coordinates from the resolved URL
        coords = None
        patterns = [
            r'@(-?\d+\.\d+),(-?\d+\.\d+)',
            r'!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)',
            r'q=(-?\d+\.\d+),(-?\d+\.\d+)',
            r'place/(-?\d+\.\d+),(-?\d+\.\d+)',
            r'll=(-?\d+\.\d+),(-?\d+\.\d+)',
            r'center=(-?\d+\.\d+),(-?\d+\.\d+)',
        ]
        for pat in patterns:
            m = re.search(pat, resolved_url)
            if m:
                coords = {'lat': float(m.group(1)), 'lng': float(m.group(2))}
                break

        if not coords:
            return jsonify({'error': 'Could not extract coordinates from link', 'resolved_url': resolved_url}), 400

        result = {'lat': coords['lat'], 'lng': coords['lng'], 'resolved_url': resolved_url}

        # Reverse geocode using Nominatim (free, no API key needed)
        try:
            geo_resp = _requests.get(
                'https://nominatim.openstreetmap.org/reverse',
                params={'lat': coords['lat'], 'lon': coords['lng'], 'format': 'json', 'addressdetails': '1'},
                headers={'User-Agent': 'RealEstatePanorama/1.0'},
                timeout=8,
            )
            if geo_resp.status_code == 200:
                geo = geo_resp.json()
                addr = geo.get('address', {})
                # Build readable address
                address_parts = []
                for key in ('road', 'neighbourhood', 'suburb', 'hamlet', 'village'):
                    if addr.get(key):
                        address_parts.append(addr[key])
                result['address'] = ', '.join(address_parts) if address_parts else geo.get('display_name', '')
                result['city'] = addr.get('city') or addr.get('town') or addr.get('village') or addr.get('county') or ''
                result['state'] = addr.get('state') or ''
        except Exception:
            pass

        return jsonify(result)

    @app.route('/api/panoramas/<int:panorama_id>/workspace', methods=['PATCH', 'PUT'])
    @require_admin
    def move_panorama_to_workspace(user_id, role, panorama_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        panorama, access_type = get_panorama_with_access(sb, panorama_id, user_id)
        if not panorama:
            return jsonify({'error': 'Panorama not found'}), 404
        if access_type != 'owner':
            return jsonify({'error': 'Only owner can move this panorama'}), 403
        payload = request.get_json(silent=True) or request.form or {}
        workspace_id = payload.get('workspace_id')
        workspace_id = None if workspace_id in (None, '', 'null') else str(workspace_id).strip()
        if workspace_id:
            try:
                workspace = get_workspace_by_id(sb, workspace_id)
            except Exception as e:
                if is_workspace_schema_missing(e):
                    return _ws_error_response()
                return jsonify({'error': str(e)}), 500
            if not workspace:
                return jsonify({'error': 'Project not found'}), 404
            if str(workspace.get('user_id') or '') != str(user_id):
                return jsonify({'error': 'You can only move to your own workspace'}), 403
            panorama_org = panorama.get('org_id')
            workspace_org = workspace.get('org_id')
            if panorama_org and workspace_org and str(panorama_org) != str(workspace_org):
                return jsonify({'error': 'Project organization mismatch'}), 403
        clear_workspace_main_for_panorama(sb, panorama_id)
        try:
            r = (
                sb.table('panoramas')
                .update({'workspace_id': workspace_id, 'updated_at': datetime.utcnow().isoformat()})
                .eq('id', panorama_id)
                .execute()
            )
        except Exception as e:
            if is_workspace_schema_missing(e):
                return _ws_error_response()
            return jsonify({'error': str(e)}), 500
        row = (r.data or [None])[0] if hasattr(r, 'data') else None
        current_workspace_id = (row or {}).get('workspace_id')

        # Auto-set as main if this is a 360 panorama dropped into a folder with no main
        if workspace_id and panorama.get('is_360'):
            try:
                ws_row = get_workspace_by_id(sb, workspace_id)
                if ws_row and not ws_row.get('main_panorama_id'):
                    sb.table('workspaces').update({
                        'main_panorama_id': panorama_id,
                        'updated_at': datetime.utcnow().isoformat(),
                    }).eq('id', workspace_id).execute()
            except Exception:
                pass
            try:
                ws_ensure_panorama_added_to_workspace_config(sb, workspace_id, panorama_id, user_id, role)
            except Exception:
                pass

        return jsonify({
            'success': True,
            'panorama': {
                'id': panorama_id,
                'workspace_id': str(current_workspace_id or workspace_id) if (current_workspace_id or workspace_id) else None,
                'updated_at': str((row or {}).get('updated_at') or datetime.utcnow().isoformat()),
            }
        })

    @app.route('/api/panoramas/<int:panorama_id>/plots', methods=['GET'])
    @require_auth
    def get_plots(user_id, role, panorama_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        panorama, access_type = get_panorama_with_access(sb, panorama_id, user_id)
        if not panorama:
            return jsonify({'error': 'Panorama not found'}), 404
        try:
            plots = fetch_plots(sb, panorama_id)
            return jsonify(plots)
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/panoramas/<int:panorama_id>/plots', methods=['POST'])
    @require_auth
    def create_plot(user_id, role, panorama_id):
        data = request.get_json()
        if not data or not data.get('name') or not data.get('points'):
            return jsonify({'error': 'Name and points are required'}), 400
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        panorama, access_type = get_panorama_with_access(sb, panorama_id, user_id)
        if not panorama:
            return jsonify({'error': 'Panorama not found'}), 404
        if not can_edit_plots(access_type):
            return jsonify({'error': 'You cannot add plots'}), 403
        try:
            plot_id = plot_create(sb, panorama_id, data)
            return jsonify({'id': plot_id, **data}), 201
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/plots/<int:plot_id>', methods=['DELETE'])
    @require_auth
    def delete_plot(user_id, role, plot_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        try:
            pl = sb.table('plots').select('panorama_id, image_filename').eq('id', plot_id).limit(1).execute()
            if not pl.data or len(pl.data) == 0:
                return jsonify({'error': 'Plot not found'}), 404
            panorama_id = pl.data[0]['panorama_id']
        except Exception:
            return jsonify({'error': 'Not found'}), 404
        panorama, access_type = get_panorama_with_access(sb, panorama_id, user_id)
        if not panorama or not can_edit_plots(access_type):
            return jsonify({'error': 'Forbidden'}), 403
        try:
            plot_delete(sb, plot_id)
            return jsonify({'success': True})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/plots/<int:plot_id>', methods=['PUT'])
    @require_auth
    def update_plot(user_id, role, plot_id):
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Body required'}), 400
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        panorama_id = get_plot_panorama_id(sb, plot_id)
        if not panorama_id:
            return jsonify({'error': 'Plot not found'}), 404
        panorama, access_type = get_panorama_with_access(sb, panorama_id, user_id)
        if not panorama or not can_edit_plots(access_type):
            return jsonify({'error': 'Forbidden'}), 403
        try:
            plot_update(sb, plot_id, data)
            return jsonify({'success': True})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/plots/<int:plot_id>/label-position', methods=['PATCH', 'PUT'])
    @require_auth
    def update_plot_label_position(user_id, role, plot_id):
        data = request.get_json(silent=True) or {}
        try:
            lon = data.get('label_longitude') if 'label_longitude' in data else data.get('longitude')
            lat = data.get('label_latitude') if 'label_latitude' in data else data.get('latitude')
        except Exception:
            lon, lat = None, None
        if lon is None and lat is None:
            return jsonify({'error': 'label_longitude and label_latitude (or longitude and latitude) required'}), 400
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        panorama_id = get_plot_panorama_id(sb, plot_id)
        if not panorama_id:
            return jsonify({'error': 'Plot not found'}), 404
        panorama, access_type = get_panorama_with_access(sb, panorama_id, user_id)
        if not panorama or not can_edit_plots(access_type):
            return jsonify({'error': 'Forbidden'}), 403
        try:
            lon_f = float(lon) if lon is not None else None
            lat_f = float(lat) if lat is not None else None
        except (TypeError, ValueError):
            return jsonify({'error': 'Invalid longitude or latitude'}), 400
        try:
            plot_update_label_position(sb, plot_id, lon_f, lat_f)
            return jsonify({'success': True, 'label_longitude': lon_f, 'label_latitude': lat_f})
        except Exception as e:
            if 'label_longitude' in str(e).lower() or 'label_latitude' in str(e).lower():
                return jsonify({'error': 'Plot label position not supported. Run db/schema.sql in Supabase SQL Editor.'}), 503
            return jsonify({'error': str(e)}), 500

    @app.route('/api/plots/<int:plot_id>/image', methods=['GET'])
    @require_auth
    def get_plot_image(user_id, role, plot_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        try:
            try:
                pl = sb.table('plots').select('panorama_id, image_filename, image_content_type').eq('id', plot_id).limit(1).execute()
            except Exception as e:
                if 'image_content_type' in str(e).lower():
                    pl = sb.table('plots').select('panorama_id, image_filename').eq('id', plot_id).limit(1).execute()
                else:
                    raise
            if not pl.data or len(pl.data) == 0:
                return jsonify({'error': 'Plot not found'}), 404
            row = pl.data[0]
            panorama_id = row['panorama_id']
        except Exception as e:
            msg = str(e).lower()
            if 'image_filename' in msg and ('does not exist' in msg or 'column' in msg):
                return jsonify({'error': 'image_filename column missing. Run db/schema.sql in Supabase SQL Editor.'}), 503
            return jsonify({'error': 'Not found'}), 404
        panorama, _ = get_panorama_with_access(sb, panorama_id, user_id)
        if not panorama:
            return jsonify({'error': 'Forbidden'}), 403
        image_filename = row.get('image_filename') or ''
        if not image_filename:
            return jsonify({'error': 'No image'}), 404
        client = get_s3_client()
        if not client:
            return jsonify({'error': 'Supabase S3 is not configured'}), 503
        try:
            obj = client.get_object(Bucket=SUPABASE_S3_BUCKET, Key=plot_object_key(image_filename))
            body = obj.get('Body')
            data = body.read() if body else b''
            try:
                if body:
                    body.close()
            except Exception:
                pass
            content_type = obj.get('ContentType') or row.get('image_content_type') or 'image/jpeg'
        except Exception:
            return jsonify({'error': 'Image not found'}), 404
        resp = Response(data, mimetype=str(content_type or 'image/jpeg'))
        resp.headers['Cache-Control'] = 'private, max-age=900'
        return resp

    @app.route('/api/plots/<int:plot_id>/image/upload-url', methods=['POST'])
    @require_auth
    def create_plot_image_upload_url(user_id, role, plot_id):
        if not use_s3():
            return jsonify({'error': 'Supabase S3 is not configured'}), 503
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        panorama_id = get_plot_panorama_id(sb, plot_id)
        if not panorama_id:
            return jsonify({'error': 'Plot not found'}), 404
        panorama, access_type = get_panorama_with_access(sb, panorama_id, user_id)
        if not panorama or not can_edit_plots(access_type):
            return jsonify({'error': 'Forbidden'}), 403
        payload = request.get_json(silent=True) or request.form or {}
        original_filename = str(payload.get('original_filename') or payload.get('filename') or '').strip()
        if not original_filename:
            return jsonify({'error': 'original_filename is required'}), 400
        try:
            size_bytes = int(payload.get('size_bytes') or payload.get('size') or 0)
        except Exception:
            size_bytes = 0
        if size_bytes and size_bytes > MAX_PLOT_IMAGE_BYTES:
            return jsonify({'error': f'Image too large (max {MAX_PLOT_IMAGE_BYTES // (1024*1024)}MB)'}), 413
        content_type_hint = str(payload.get('content_type') or '').lower().strip()
        ext = original_filename.rsplit('.', 1)[-1].lower() if '.' in original_filename else ''
        if ext not in ALLOWED_IMAGE_EXTENSIONS and content_type_hint:
            ext = _detect_ext_from_content_type(content_type_hint)
        if ext not in ALLOWED_IMAGE_EXTENSIONS:
            return jsonify({'error': 'File type not allowed. Use: png, jpg, jpeg, gif, webp'}), 400
        unique = uuid.uuid4().hex[:10]
        filename = f"plot_{plot_id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{unique}.{ext}"
        content_type = IMAGE_CONTENT_TYPES.get(ext, 'image/jpeg')
        client = get_s3_client()
        if not client:
            return jsonify({'error': 'Supabase S3 is not fully configured'}), 503
        try:
            upload_url = client.generate_presigned_url(
                ClientMethod='put_object',
                Params={'Bucket': SUPABASE_S3_BUCKET, 'Key': plot_object_key(filename), 'ContentType': content_type},
                ExpiresIn=int(SUPABASE_S3_UPLOAD_URL_TTL),
            )
        except Exception as e:
            current_app.logger.exception('Failed to generate plot image upload URL')
            return jsonify({'error': str(e)}), 500
        token = plot_upload_serializer(secret_key).dumps({
            'user_id': str(user_id),
            'plot_id': int(plot_id),
            'filename': filename,
            'content_type': content_type,
        })
        return jsonify({
            'filename': filename,
            'upload_url': upload_url,
            'upload_token': token,
            'content_type': content_type,
            'max_bytes': MAX_PLOT_IMAGE_BYTES,
            'expires_in': int(SUPABASE_S3_UPLOAD_URL_TTL),
        })

    @app.route('/api/plots/<int:plot_id>/image', methods=['POST', 'PUT'])
    @require_auth
    def upload_plot_image(user_id, role, plot_id):
        if not use_s3():
            return jsonify({'error': 'Supabase S3 is not configured'}), 503
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        try:
            pl = sb.table('plots').select('panorama_id, image_filename').eq('id', plot_id).limit(1).execute()
            if not pl.data or len(pl.data) == 0:
                return jsonify({'error': 'Plot not found'}), 404
            panorama_id = pl.data[0]['panorama_id']
            old_filename = str(pl.data[0].get('image_filename') or '').strip()
        except Exception as e:
            msg = str(e).lower()
            if 'image_filename' in msg and ('does not exist' in msg or 'column' in msg):
                return jsonify({'error': 'image_filename column missing. Run db/schema.sql in Supabase SQL Editor.'}), 503
            return jsonify({'error': 'Not found'}), 404
        panorama, access_type = get_panorama_with_access(sb, panorama_id, user_id)
        if not panorama or not can_edit_plots(access_type):
            return jsonify({'error': 'Forbidden'}), 403
        client = get_s3_client()
        if not client:
            return jsonify({'error': 'Supabase S3 is not fully configured'}), 503
        if request.files.get('file'):
            file = request.files.get('file')
            original_filename = str(getattr(file, 'filename', '') or '').strip()
            if not original_filename:
                return jsonify({'error': 'file is required'}), 400
            content_type_hint = str(getattr(file, 'mimetype', '') or '').lower().strip()
            ext = original_filename.rsplit('.', 1)[-1].lower() if '.' in original_filename else ''
            if ext not in ALLOWED_IMAGE_EXTENSIONS and content_type_hint:
                ext = _detect_ext_from_content_type(content_type_hint)
            if ext not in ALLOWED_IMAGE_EXTENSIONS:
                return jsonify({'error': 'File type not allowed. Use: png, jpg, jpeg, gif, webp'}), 400
            try:
                raw = read_uploaded_file_bytes(file, MAX_PLOT_IMAGE_BYTES)
            except ValueError as ve:
                if str(ve) == 'file_too_large':
                    return jsonify({'error': f'Image too large (max {MAX_PLOT_IMAGE_BYTES // (1024*1024)}MB)'}), 413
                return jsonify({'error': 'Invalid upload'}), 400
            unique = uuid.uuid4().hex[:10]
            filename = f"plot_{plot_id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{unique}.{ext}"
            content_type = IMAGE_CONTENT_TYPES.get(ext, 'image/jpeg')
            try:
                client.put_object(
                    Bucket=SUPABASE_S3_BUCKET,
                    Key=plot_object_key(filename),
                    Body=raw,
                    ContentType=content_type,
                )
            except Exception as e:
                current_app.logger.exception('Direct plot image upload failed')
                return jsonify({'error': str(e) or 'Upload failed'}), 500
            try:
                try:
                    sb.table('plots').update({
                        'image_filename': filename,
                        'image_content_type': content_type,
                    }).eq('id', plot_id).execute()
                except Exception as ee:
                    if 'image_content_type' in str(ee).lower():
                        sb.table('plots').update({'image_filename': filename}).eq('id', plot_id).execute()
                    else:
                        raise
                sb.table('panoramas').update({'updated_at': datetime.utcnow().isoformat()}).eq('id', panorama_id).execute()
            except Exception as e:
                msg = str(e).lower()
                if 'image_filename' in msg and ('does not exist' in msg or 'column' in msg):
                    return jsonify({'error': 'image_filename column missing. Run db/schema.sql in Supabase SQL Editor.'}), 503
                return jsonify({'error': str(e)}), 500
            if old_filename and old_filename != filename:
                delete_plot_from_s3(old_filename)
            return jsonify({'success': True, 'filename': filename})
        payload = request.form or {}
        filename = os.path.basename(str(payload.get('filename') or '')).strip()
        upload_token = str(payload.get('upload_token') or '').strip()
        if not filename:
            return jsonify({'error': 'filename is required'}), 400
        if not upload_token:
            return jsonify({'error': 'upload_token is required'}), 400
        try:
            signed = plot_upload_serializer(secret_key).loads(upload_token, max_age=int(SUPABASE_S3_UPLOAD_URL_TTL))
        except SignatureExpired:
            return jsonify({'error': 'upload_token expired; request a new upload URL'}), 400
        except BadSignature:
            return jsonify({'error': 'Invalid upload_token'}), 400
        if str(signed.get('user_id')) != str(user_id) or int(signed.get('plot_id')) != int(plot_id) or str(signed.get('filename')) != filename:
            return jsonify({'error': 'Invalid upload_token'}), 403
        head = None
        for attempt in range(5):
            try:
                head = client.head_object(Bucket=SUPABASE_S3_BUCKET, Key=plot_object_key(filename))
                break
            except Exception:
                if attempt < 4:
                    time.sleep(0.15 * (attempt + 1))
                    continue
                return jsonify({'error': 'Upload not found. Re-upload and try again.'}), 400
        try:
            size_bytes = int(head.get('ContentLength') or 0)
        except Exception:
            size_bytes = 0
        if size_bytes and size_bytes > MAX_PLOT_IMAGE_BYTES:
            delete_plot_from_s3(filename)
            return jsonify({'error': f'Image too large (max {MAX_PLOT_IMAGE_BYTES // (1024*1024)}MB)'}), 413
        try:
            try:
                sb.table('plots').update({
                    'image_filename': filename,
                    'image_content_type': str(signed.get('content_type') or ''),
                }).eq('id', plot_id).execute()
            except Exception as ee:
                if 'image_content_type' in str(ee).lower():
                    sb.table('plots').update({'image_filename': filename}).eq('id', plot_id).execute()
                else:
                    raise
            sb.table('panoramas').update({'updated_at': datetime.utcnow().isoformat()}).eq('id', panorama_id).execute()
        except Exception as e:
            msg = str(e).lower()
            if 'image_filename' in msg and ('does not exist' in msg or 'column' in msg):
                return jsonify({'error': 'image_filename column missing. Run db/schema.sql in Supabase SQL Editor.'}), 503
            return jsonify({'error': str(e)}), 500
        if old_filename and old_filename != filename:
            delete_plot_from_s3(old_filename)
        return jsonify({'success': True})

    @app.route('/api/markers/<marker_id>/image', methods=['GET'])
    @require_auth
    def get_marker_image(user_id, role, marker_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        try:
            r = sb.table('plot_markers').select('id, plot_id, image_filename').eq('id', marker_id).limit(1).execute()
            if not r.data:
                return jsonify({'error': 'Marker not found'}), 404
            row = r.data[0]
        except Exception as e:
            msg = str(e).lower()
            if 'image_filename' in msg and ('does not exist' in msg or 'column' in msg):
                return jsonify({'error': 'image_filename column missing. Run db/schema.sql in Supabase SQL Editor.'}), 503
            return jsonify({'error': 'Marker not found'}), 404
        plot_id = str(row.get('plot_id') or '').strip()
        if not plot_id:
            return jsonify({'error': 'Invalid marker'}), 400
        try:
            panorama_id = int(plot_id)
        except Exception:
            return jsonify({'error': 'Invalid marker reference'}), 400
        panorama, _ = get_panorama_with_access(sb, panorama_id, user_id)
        if not panorama:
            return jsonify({'error': 'Forbidden'}), 403
        image_filename = row.get('image_filename') or ''
        if not image_filename:
            return jsonify({'error': 'No image'}), 404
        client = get_s3_client()
        if not client:
            return jsonify({'error': 'Supabase S3 is not configured'}), 503
        use_thumb = request.args.get('size') == 'thumb'
        key = marker_object_key(image_filename)
        if use_thumb:
            thumb_key = marker_thumb_object_key(image_filename)
            if thumb_key:
                try:
                    obj = client.get_object(Bucket=SUPABASE_S3_BUCKET, Key=thumb_key)
                    body = obj.get('Body')
                    data = body.read() if body else b''
                    try:
                        if body:
                            body.close()
                    except Exception:
                        pass
                    content_type = obj.get('ContentType') or 'image/jpeg'
                    resp = Response(data, mimetype=str(content_type or 'image/jpeg'))
                    resp.headers['Cache-Control'] = 'private, max-age=900'
                    return resp
                except Exception:
                    pass
        try:
            obj = client.get_object(Bucket=SUPABASE_S3_BUCKET, Key=key)
            body = obj.get('Body')
            data = body.read() if body else b''
            try:
                if body:
                    body.close()
            except Exception:
                pass
            content_type = obj.get('ContentType') or 'image/jpeg'
        except Exception:
            return jsonify({'error': 'Image not found'}), 404
        resp = Response(data, mimetype=str(content_type or 'image/jpeg'))
        resp.headers['Cache-Control'] = 'private, max-age=900'
        return resp

    @app.route('/api/markers/<marker_id>/voiceover', methods=['GET'])
    @require_auth
    def get_marker_voiceover(user_id, role, marker_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        try:
            r = sb.table('plot_markers').select('id, plot_id, voiceover_filename').eq('id', marker_id).limit(1).execute()
            if not r.data:
                return jsonify({'error': 'Marker not found'}), 404
            row = r.data[0]
        except Exception as e:
            msg = str(e).lower()
            if 'voiceover_filename' in msg and ('does not exist' in msg or 'column' in msg):
                return jsonify({'error': 'voiceover_filename column missing. Run db/schema.sql in Supabase SQL Editor.'}), 503
            return jsonify({'error': 'Marker not found'}), 404
        plot_id = str(row.get('plot_id') or '').strip()
        if not plot_id:
            return jsonify({'error': 'Invalid marker'}), 400
        try:
            panorama_id = int(plot_id)
        except Exception:
            return jsonify({'error': 'Invalid marker reference'}), 400
        panorama, _ = get_panorama_with_access(sb, panorama_id, user_id)
        if not panorama:
            return jsonify({'error': 'Forbidden'}), 403
        voiceover_filename = row.get('voiceover_filename') or ''
        if not voiceover_filename:
            return jsonify({'error': 'No voice-over'}), 404
        url = get_voiceover_s3_url(voiceover_filename)
        if not url:
            return jsonify({'error': 'Voice-over not found'}), 404
        return jsonify({'url': url})

    @app.route('/api/markers/<marker_id>/voiceover', methods=['POST'])
    @require_auth
    def upload_marker_voiceover(user_id, role, marker_id):
        if not use_s3():
            return jsonify({'error': 'Supabase S3 is not configured'}), 503
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        try:
            r = sb.table('plot_markers').select('id, plot_id, voiceover_filename').eq('id', marker_id).limit(1).execute()
            if not r.data:
                return jsonify({'error': 'Marker not found'}), 404
            row = r.data[0]
        except Exception as e:
            msg = str(e).lower()
            if 'voiceover_filename' in msg and ('does not exist' in msg or 'column' in msg):
                return jsonify({'error': 'voiceover_filename column missing. Run db/schema.sql in Supabase SQL Editor.'}), 503
            return jsonify({'error': 'Marker not found'}), 404
        plot_id = str(row.get('plot_id') or '').strip()
        if not plot_id:
            return jsonify({'error': 'Invalid marker'}), 400
        try:
            panorama_id = int(plot_id)
        except Exception:
            return jsonify({'error': 'Invalid marker reference'}), 400
        panorama, access_type = get_panorama_with_access(sb, panorama_id, user_id)
        if not panorama or not can_edit_plots(access_type):
            return jsonify({'error': 'Forbidden'}), 403
        old_filename = str(row.get('voiceover_filename') or '').strip()
        file_storage = request.files.get('file') or request.files.get('voiceover')
        if not file_storage or not getattr(file_storage, 'filename', None):
            return jsonify({'error': 'No audio file (use form field "file" or "voiceover")'}), 400
        filename_orig = (file_storage.filename or '').strip()
        ext = (filename_orig.rsplit('.', 1)[-1].lower() if '.' in filename_orig else '').strip()
        if ext not in ALLOWED_AUDIO_EXTENSIONS:
            return jsonify({'error': 'Audio type not allowed. Use: mp3, wav, m4a, ogg, webm'}), 400
        data = read_uploaded_file_bytes(file_storage, MAX_MARKER_VOICEOVER_BYTES)
        if len(data) > MAX_MARKER_VOICEOVER_BYTES:
            return jsonify({'error': f'Voice-over too large (max {MAX_MARKER_VOICEOVER_BYTES // (1024*1024)}MB)'}), 413
        if not data:
            return jsonify({'error': 'Empty file'}), 400
        unique = uuid.uuid4().hex[:10]
        filename = f"voice_{marker_id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{unique}.{ext}"
        content_type = AUDIO_CONTENT_TYPES.get(ext, 'audio/mpeg')
        client = get_s3_client()
        if not client:
            return jsonify({'error': 'Supabase S3 is not configured'}), 503
        try:
            client.put_object(
                Bucket=SUPABASE_S3_BUCKET,
                Key=voiceover_object_key(filename),
                Body=data,
                ContentType=content_type,
            )
        except Exception as e:
            current_app.logger.exception('Voice-over S3 upload failed')
            return jsonify({'error': str(e)}), 500
        try:
            sb.table('plot_markers').update({
                'voiceover_filename': filename,
                'updated_at': datetime.utcnow().isoformat(),
            }).eq('id', marker_id).execute()
        except Exception as e:
            current_app.logger.exception('Failed to update marker voiceover_filename')
            try:
                delete_voiceover_from_s3(filename)
            except Exception:
                pass
            return jsonify({'error': 'Failed to save'}), 500
        if old_filename and old_filename != filename:
            delete_voiceover_from_s3(old_filename)
        return jsonify({'success': True, 'voiceover_filename': filename})

    @app.route('/api/markers/<marker_id>/image/upload-url', methods=['POST'])
    @require_auth
    def create_marker_image_upload_url(user_id, role, marker_id):
        if not use_s3():
            return jsonify({'error': 'Supabase S3 is not configured'}), 503
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        try:
            r = sb.table('plot_markers').select('id, plot_id').eq('id', marker_id).limit(1).execute()
            if not r.data:
                return jsonify({'error': 'Marker not found'}), 404
            row = r.data[0]
        except Exception:
            return jsonify({'error': 'Marker not found'}), 404
        plot_id = str(row.get('plot_id') or '').strip()
        if not plot_id:
            return jsonify({'error': 'Invalid marker'}), 400
        try:
            panorama_id = int(plot_id)
        except Exception:
            return jsonify({'error': 'Invalid marker reference'}), 400
        panorama, access_type = get_panorama_with_access(sb, panorama_id, user_id)
        if not panorama or not can_edit_plots(access_type):
            return jsonify({'error': 'Forbidden'}), 403
        payload = request.get_json(silent=True) or request.form or {}
        original_filename = str(payload.get('original_filename') or payload.get('filename') or '').strip()
        if not original_filename:
            return jsonify({'error': 'original_filename is required'}), 400
        try:
            size_bytes = int(payload.get('size_bytes') or payload.get('size') or 0)
        except Exception:
            size_bytes = 0
        if size_bytes and size_bytes > MAX_MARKER_IMAGE_BYTES:
            return jsonify({'error': f'Image too large (max {MAX_MARKER_IMAGE_BYTES // (1024*1024)}MB)'}), 413
        content_type_hint = str(payload.get('content_type') or '').lower().strip()
        ext = original_filename.rsplit('.', 1)[-1].lower() if '.' in original_filename else ''
        if ext not in ALLOWED_IMAGE_EXTENSIONS and content_type_hint:
            ext = _detect_ext_from_content_type(content_type_hint)
        if ext not in ALLOWED_IMAGE_EXTENSIONS:
            return jsonify({'error': 'File type not allowed. Use: png, jpg, jpeg, gif, webp'}), 400
        unique = uuid.uuid4().hex[:10]
        filename = f"marker_{marker_id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{unique}.{ext}"
        content_type = IMAGE_CONTENT_TYPES.get(ext, 'image/jpeg')
        client = get_s3_client()
        if not client:
            return jsonify({'error': 'Supabase S3 is not fully configured'}), 503
        try:
            upload_url = client.generate_presigned_url(
                ClientMethod='put_object',
                Params={'Bucket': SUPABASE_S3_BUCKET, 'Key': marker_object_key(filename), 'ContentType': content_type},
                ExpiresIn=int(SUPABASE_S3_UPLOAD_URL_TTL),
            )
        except Exception as e:
            current_app.logger.exception('Failed to generate marker image upload URL')
            return jsonify({'error': str(e)}), 500
        token = marker_upload_serializer(secret_key).dumps({
            'user_id': str(user_id),
            'marker_id': str(marker_id),
            'filename': filename,
            'content_type': content_type,
        })
        return jsonify({
            'filename': filename,
            'upload_url': upload_url,
            'upload_token': token,
            'content_type': content_type,
            'max_bytes': MAX_MARKER_IMAGE_BYTES,
            'expires_in': int(SUPABASE_S3_UPLOAD_URL_TTL),
        })

    @app.route('/api/markers/<marker_id>/image', methods=['POST', 'PUT'])
    @require_auth
    def upload_marker_image(user_id, role, marker_id):
        if not use_s3():
            return jsonify({'error': 'Supabase S3 is not configured'}), 503
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        try:
            r = sb.table('plot_markers').select('id, plot_id, image_filename').eq('id', marker_id).limit(1).execute()
            if not r.data:
                return jsonify({'error': 'Marker not found'}), 404
            row = r.data[0]
            old_filename = str(row.get('image_filename') or '').strip()
        except Exception as e:
            msg = str(e).lower()
            if 'image_filename' in msg and ('does not exist' in msg or 'column' in msg):
                return jsonify({'error': 'image_filename column missing. Run db/schema.sql in Supabase SQL Editor.'}), 503
            return jsonify({'error': 'Marker not found'}), 404
        plot_id = str(row.get('plot_id') or '').strip()
        if not plot_id:
            return jsonify({'error': 'Invalid marker'}), 400
        try:
            panorama_id = int(plot_id)
        except Exception:
            return jsonify({'error': 'Invalid marker reference'}), 400
        panorama, access_type = get_panorama_with_access(sb, panorama_id, user_id)
        if not panorama or not can_edit_plots(access_type):
            return jsonify({'error': 'Forbidden'}), 403
        client = get_s3_client()
        if not client:
            return jsonify({'error': 'Supabase S3 is not fully configured'}), 503
        if request.files.get('file'):
            file = request.files.get('file')
            original_filename = str(getattr(file, 'filename', '') or '').strip()
            if not original_filename:
                return jsonify({'error': 'file is required'}), 400
            content_type_hint = str(getattr(file, 'mimetype', '') or '').lower().strip()
            ext = original_filename.rsplit('.', 1)[-1].lower() if '.' in original_filename else ''
            if ext not in ALLOWED_IMAGE_EXTENSIONS and content_type_hint:
                ext = _detect_ext_from_content_type(content_type_hint)
            if ext not in ALLOWED_IMAGE_EXTENSIONS:
                return jsonify({'error': 'File type not allowed. Use: png, jpg, jpeg, gif, webp'}), 400
            try:
                raw = read_uploaded_file_bytes(file, MAX_MARKER_IMAGE_BYTES)
            except ValueError as ve:
                if str(ve) == 'file_too_large':
                    return jsonify({'error': f'Image too large (max {MAX_MARKER_IMAGE_BYTES // (1024*1024)}MB)'}), 413
                return jsonify({'error': 'Invalid upload'}), 400
            unique = uuid.uuid4().hex[:10]
            compressed = compress_marker_image(raw)
            if compressed:
                full_bytes, thumb_bytes = compressed
                filename = f"marker_{marker_id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{unique}.jpg"
                content_type = 'image/jpeg'
                body_to_upload = full_bytes
                thumb_key = marker_thumb_object_key(filename)
            else:
                filename = f"marker_{marker_id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{unique}.{ext}"
                content_type = IMAGE_CONTENT_TYPES.get(ext, 'image/jpeg')
                body_to_upload = raw
                thumb_key = None
            try:
                client.put_object(
                    Bucket=SUPABASE_S3_BUCKET,
                    Key=marker_object_key(filename),
                    Body=body_to_upload,
                    ContentType=content_type,
                )
            except Exception as e:
                current_app.logger.exception('Direct marker image upload failed')
                return jsonify({'error': str(e) or 'Upload failed'}), 500
            if thumb_key and compressed:
                try:
                    client.put_object(
                        Bucket=SUPABASE_S3_BUCKET,
                        Key=thumb_key,
                        Body=thumb_bytes,
                        ContentType='image/jpeg',
                    )
                except Exception:
                    pass
            try:
                sb.table('plot_markers').update({'image_filename': filename}).eq('id', marker_id).execute()
            except Exception as e:
                msg = str(e).lower()
                if 'image_filename' in msg and ('does not exist' in msg or 'column' in msg):
                    return jsonify({'error': 'image_filename column missing. Run db/schema.sql in Supabase SQL Editor.'}), 503
                return jsonify({'error': str(e)}), 500
            if old_filename and old_filename != filename:
                delete_marker_from_s3(old_filename)
            return jsonify({'success': True, 'filename': filename})
        payload = request.form or {}
        filename = os.path.basename(str(payload.get('filename') or '')).strip()
        upload_token = str(payload.get('upload_token') or '').strip()
        if not filename:
            return jsonify({'error': 'filename is required'}), 400
        if not upload_token:
            return jsonify({'error': 'upload_token is required'}), 400
        try:
            signed = marker_upload_serializer(secret_key).loads(upload_token, max_age=int(SUPABASE_S3_UPLOAD_URL_TTL))
        except SignatureExpired:
            return jsonify({'error': 'upload_token expired; request a new upload URL'}), 400
        except BadSignature:
            return jsonify({'error': 'Invalid upload_token'}), 400
        if str(signed.get('user_id')) != str(user_id) or str(signed.get('marker_id')) != str(marker_id) or str(signed.get('filename')) != filename:
            return jsonify({'error': 'Invalid upload_token'}), 403
        head = None
        for attempt in range(5):
            try:
                head = client.head_object(Bucket=SUPABASE_S3_BUCKET, Key=marker_object_key(filename))
                break
            except Exception:
                if attempt < 4:
                    time.sleep(0.15 * (attempt + 1))
                    continue
                return jsonify({'error': 'Upload not found. Re-upload and try again.'}), 400
        try:
            size_bytes = int(head.get('ContentLength') or 0)
        except Exception:
            size_bytes = 0
        if size_bytes and size_bytes > MAX_MARKER_IMAGE_BYTES:
            delete_marker_from_s3(filename)
            return jsonify({'error': f'Image too large (max {MAX_MARKER_IMAGE_BYTES // (1024*1024)}MB)'}), 413
        try:
            sb.table('plot_markers').update({'image_filename': filename}).eq('id', marker_id).execute()
        except Exception as e:
            msg = str(e).lower()
            if 'image_filename' in msg and ('does not exist' in msg or 'column' in msg):
                return jsonify({'error': 'image_filename column missing. Run db/schema.sql in Supabase SQL Editor.'}), 503
            return jsonify({'error': str(e)}), 500
        if old_filename and old_filename != filename:
            delete_marker_from_s3(old_filename)
        return jsonify({'success': True})

    @app.route('/api/crm/panoramas', methods=['GET'])
    @require_auth
    def list_crm_panoramas(user_id, role):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        panorama_ids = _crm_panorama_ids(sb, user_id, role)
        if not panorama_ids:
            return jsonify([])
        cache_key = (
            'crm_panoramas',
            _crm_cache_version.get('v', 1),
            str(user_id),
            str(role or ''),
            tuple(panorama_ids),
        )
        cached = _crm_cache_get(cache_key, ttl_seconds=5)
        if cached is not None:
            return jsonify(cached)
        out_by_id = {}
        ws_ids_needed = set()
        chunk_size = 100
        try:
            for i in range(0, len(panorama_ids), chunk_size):
                chunk = panorama_ids[i:i + chunk_size]
                try:
                    r = sb.table('panoramas').select('id, name, workspace_id, created_at, updated_at').in_('id', chunk).execute()
                except Exception:
                    r = sb.table('panoramas').select('id, name, created_at, updated_at').in_('id', chunk).execute()
                for row in (r.data or []):
                    try:
                        pid = int(row.get('id'))
                    except Exception:
                        continue
                    wsid = row.get('workspace_id') or None
                    item = {
                        'id': pid,
                        'name': str(row.get('name') or f'Panorama #{pid}'),
                        'workspace_id': str(wsid) if wsid else None,
                        'created_at': str(row.get('created_at') or ''),
                        'updated_at': str(row.get('updated_at') or ''),
                    }
                    out_by_id[pid] = item
                    if wsid:
                        ws_ids_needed.add(str(wsid))
        except Exception as e:
            msg = str(e)
            if 'panoramas' in msg and ('does not exist' in msg.lower() or 'relation' in msg.lower()):
                return jsonify({'error': 'panoramas table not found'}), 503
            return jsonify({'error': msg}), 500
        # Fetch Project names for project grouping
        ws_names = {}
        if ws_ids_needed:
            try:
                ws_list = list(ws_ids_needed)
                for i in range(0, len(ws_list), chunk_size):
                    chunk = ws_list[i:i + chunk_size]
                    wr = sb.table('workspaces').select('id, name').in_('id', chunk).execute()
                    for row in (wr.data or []):
                        ws_names[str(row.get('id'))] = str(row.get('name') or '')
            except Exception:
                pass
        for item in out_by_id.values():
            wsid = item.get('workspace_id')
            item['workspace_name'] = ws_names.get(wsid, '') if wsid else ''
        out = list(out_by_id.values())
        out.sort(key=lambda x: (x.get('updated_at') or '', x.get('name') or ''), reverse=True)
        _crm_cache_set(cache_key, out)
        return jsonify(out)

    @app.route('/api/buy-interests', methods=['POST'])
    @require_auth
    def create_buy_interest(user_id, role):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        data = request.get_json(silent=True) or {}
        panorama_id = data.get('panorama_id')
        try:
            panorama_id = int(panorama_id)
        except Exception:
            panorama_id = None
        customer_name = str(data.get('customer_name') or data.get('name') or '').strip()
        customer_email = str(data.get('customer_email') or data.get('email') or '').strip()
        customer_phone = str(data.get('customer_phone') or data.get('phone') or '').strip()
        customer_birthday = str(data.get('customer_birthday') or data.get('birthday') or '').strip()
        customer_street = str(data.get('customer_street') or data.get('street') or '').strip()
        customer_city = str(data.get('customer_city') or data.get('city') or '').strip()
        customer_state = str(data.get('customer_state') or data.get('state') or '').strip()
        customer_country = str(data.get('customer_country') or data.get('country') or '').strip()
        customer_zip_code = str(data.get('customer_zip_code') or data.get('zip_code') or '').strip()
        customer_address = str(data.get('customer_address') or data.get('address') or '').strip()
        if not customer_address:
            customer_address = ', '.join([x for x in [customer_street, customer_city, customer_state, customer_country, customer_zip_code] if x])
        title = str(data.get('title') or '').strip()
        if not title:
            first = str(customer_name or '').strip().split(' ')[0].replace('.', '').lower() if customer_name else ''
            if first in ('mr', 'mrs', 'ms', 'dr'):
                title = 'Dr' if first == 'dr' else first.capitalize()
        description = str(data.get('description') or '').strip()
        category = str(data.get('category') or '').strip()
        request_origin = str(data.get('origin') or '').strip().lower()
        requested_lead_source = str(data.get('lead_source') or '').strip()
        lead_source = 'SalesTool' if request_origin == 'plot' else (requested_lead_source or 'SalesTool')
        requested_reference_user_id = str(data.get('reference_user_id') or '').strip()
        items = data.get('items') or data.get('plots') or []
        if not isinstance(items, list):
            items = []
        if not panorama_id and request_origin == 'manual_normal':
            try:
                pano_ids_for_manual = _crm_panorama_ids(sb, user_id, role)
                if pano_ids_for_manual:
                    panorama_id = int(pano_ids_for_manual[0])
            except Exception:
                panorama_id = None
        if not panorama_id:
            return jsonify({'error': 'panorama_id is required'}), 400
        if not customer_name:
            return jsonify({'error': 'Name is required'}), 400
        if not customer_email or '@' not in customer_email:
            return jsonify({'error': 'Valid email is required'}), 400
        if not customer_phone:
            return jsonify({'error': 'Contact number is required'}), 400
        if len(description) > 500:
            return jsonify({'error': 'Description must be 500 characters or less'}), 400
        if not category:
            return jsonify({'error': 'Category is required'}), 400
        # Same field caps the update route enforces; without them a create can
        # store values the edit form can never round-trip.
        for _field_label, _field_value, _field_cap in (
            ('Name', customer_name, 100),
            ('Email', customer_email, 254),
            ('Contact number', customer_phone, 40),
            ('Title', title, 40),
            ('Category', category, 100),
            ('Street', customer_street, 100),
            ('City', customer_city, 100),
            ('State', customer_state, 100),
            ('Country', customer_country, 100),
            ('Zip code', customer_zip_code, 40),
            ('Address', customer_address, 500),
        ):
            if len(_field_value) > _field_cap:
                return jsonify({'error': f'{_field_label} must be {_field_cap} characters or less'}), 400
        if customer_birthday:
            # buy_interests.customer_birthday is a date column; reject bad
            # formats here instead of surfacing a raw DB type error as a 500.
            try:
                customer_birthday = datetime.strptime(customer_birthday, '%Y-%m-%d').strftime('%Y-%m-%d')
            except ValueError:
                return jsonify({'error': 'Birthday must be in YYYY-MM-DD format'}), 400
        panorama, access_type = get_panorama_with_access(sb, panorama_id, user_id)
        if not panorama:
            return jsonify({'error': 'Panorama not found'}), 404
        plot_ids = []
        for item in items:
            if isinstance(item, (int, float, str)):
                raw = item
            elif isinstance(item, dict):
                raw = item.get('plot_id') if 'plot_id' in item else item.get('id')
            else:
                raw = None
            if raw is None or str(raw).strip() == '':
                continue
            try:
                plot_ids.append(int(raw))
            except Exception:
                continue
        plot_ids = list(dict.fromkeys(plot_ids))
        if not plot_ids:
            return jsonify({'error': 'At least one plot is required'}), 400
        # Plots may come from any panorama in the same workspace (workspace
        # linked panoramas contribute plots from different panorama_ids), but
        # never from unrelated panoramas — otherwise arbitrary plot ids could
        # be enumerated cross-tenant via the snapshot echoed back below.
        allowed_plot_pano_ids = {int(panorama_id)}
        try:
            _plots_ws_id = (panorama or {}).get('workspace_id')
            if _plots_ws_id:
                wp = sb.table('panoramas').select('id').eq('workspace_id', _plots_ws_id).execute()
                for row in (wp.data or []):
                    if row.get('id') is not None:
                        allowed_plot_pano_ids.add(int(row.get('id')))
        except Exception:
            pass
        plots_snapshot = []
        try:
            r = (
                sb.table('plots')
                .select('id, panorama_id, name, area, price, status')
                .in_('id', plot_ids)
                .in_('panorama_id', sorted(allowed_plot_pano_ids))
                .execute()
            )
            found = {int(row.get('id')): row for row in (r.data or []) if row and row.get('id') is not None}
            for pid in plot_ids:
                row = found.get(int(pid))
                if not row:
                    continue
                plots_snapshot.append({
                    'plot_id': int(row.get('id')),
                    'panorama_id': int(row.get('panorama_id')) if row.get('panorama_id') else panorama_id,
                    'name': row.get('name') or '',
                    'area': row.get('area') or '',
                    'price': row.get('price') or '',
                    'status': row.get('status') or '',
                })
        except Exception as e:
            msg = str(e)
            if 'plots' in msg and ('does not exist' in msg.lower() or 'relation' in msg.lower()):
                return jsonify({'error': 'plots table not found. Run db/schema.sql in Supabase SQL Editor.'}), 503
            return jsonify({'error': msg}), 500
        if not plots_snapshot and request_origin == 'manual_normal':
            try:
                normal_plot_ids = [int(x) for x in (data.get('normal_plot_ids') or []) if str(x).strip()]
            except Exception:
                normal_plot_ids = []
            if not normal_plot_ids:
                normal_plot_ids = plot_ids[:]
            if normal_plot_ids:
                nr = (
                    sb.table('crm_normal_plots')
                    .select('id, project_id, project_name, name, area, price, status')
                    .eq('owner_user_id', str(user_id))
                    .in_('id', normal_plot_ids)
                    .execute()
                )
                for row in (nr.data or []):
                    plots_snapshot.append({
                        'plot_id': int(row.get('id')),
                        'normal_plot_id': int(row.get('id')),
                        'normal_project_id': row.get('project_id'),
                        'normal_project_name': row.get('project_name') or '',
                        'name': row.get('name') or '',
                        'area': row.get('area') or '',
                        'price': row.get('price') or '',
                        'status': row.get('status') or '',
                    })
        if not plots_snapshot:
            return jsonify({'error': 'No valid plots found'}), 400
        requested_client_id = data.get('client_id')
        client_id, client_err = _crm_pick_client_id_for_create(
            sb,
            user_id,
            role,
            requested_client_id=requested_client_id,
            panorama_id=panorama_id,
        )
        if client_err:
            return client_err
        reference_scope_user_id = _crm_interest_reference_scope_user_id(
            sb,
            user_id,
            role,
            client_ids=[client_id] if client_id else None,
        )
        resolved_reference_user_id = requested_reference_user_id or reference_scope_user_id or ''
        reference_user_id, _reference_catalog, _reference_row = _validate_project_reference_user(
            sb,
            reference_user_id=resolved_reference_user_id,
            panorama_id=panorama_id,
            client_id=client_id,
        )
        if resolved_reference_user_id and not reference_user_id:
            return jsonify({'error': 'Selected reference is not available for this project'}), 400
        now = datetime.utcnow().isoformat()
        insert_row = {
            'panorama_id': panorama_id,
            'client_id': client_id,
            'submitted_by': user_id,
            'reference_user_id': reference_user_id,
            'customer_name': customer_name,
            'customer_email': customer_email,
            'customer_phone': customer_phone,
            'customer_birthday': customer_birthday or None,
            'customer_address': customer_address or None,
            'customer_street': customer_street or None,
            'customer_city': customer_city or None,
            'customer_state': customer_state or None,
            'customer_country': customer_country or None,
            'customer_zip_code': customer_zip_code or None,
            'title': title or None,
            'description': description or None,
            'lead_source': lead_source,
            'category': category,
            'plots': plots_snapshot,
            'status': 'new',
            'is_contacted': False,
            'contacted_at': None,
            'notes': '',
            'created_at': now,
            'updated_at': now,
        }
        try:
            r = sb.table('buy_interests').insert(insert_row).execute()
            row = (r.data or [None])[0] if hasattr(r, 'data') else None
            _crm_cache_bump()
            return jsonify({'success': True, 'buy_interest': row or insert_row}), 201
        except Exception as e:
            msg = str(e)
            if any(col in msg for col in ('customer_birthday', 'customer_address', 'customer_street', 'customer_city', 'customer_state', 'customer_country', 'customer_zip_code', 'title', 'description')) and ('column' in msg.lower() or 'schema cache' in msg.lower()):
                legacy_row = dict(insert_row)
                legacy_row.pop('customer_birthday', None)
                legacy_row.pop('customer_address', None)
                legacy_row.pop('customer_street', None)
                legacy_row.pop('customer_city', None)
                legacy_row.pop('customer_state', None)
                legacy_row.pop('customer_country', None)
                legacy_row.pop('customer_zip_code', None)
                legacy_row.pop('title', None)
                legacy_row.pop('description', None)
                try:
                    r = sb.table('buy_interests').insert(legacy_row).execute()
                    row = (r.data or [None])[0] if hasattr(r, 'data') else None
                    _crm_cache_bump()
                    return jsonify({'success': True, 'buy_interest': row or legacy_row}), 201
                except Exception as legacy_error:
                    msg = str(legacy_error)
            if 'buy_interests' in msg and ('does not exist' in msg.lower() or 'relation' in msg.lower()):
                return jsonify({'error': 'buy_interests table not found. Run db/schema.sql in Supabase SQL Editor.'}), 503
            return jsonify({'error': msg}), 500

    @app.route('/api/buy-interests/<interest_id>', methods=['PUT', 'PATCH'])
    @require_auth
    def update_buy_interest(user_id, role, interest_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        data = request.get_json(silent=True) or {}
        upd = {}
        now = datetime.utcnow().isoformat()
        panorama_ids = _crm_panorama_ids(sb, user_id, role)
        if not panorama_ids:
            return jsonify({'error': 'Forbidden'}), 403
        client_scope_ids = _crm_client_scope_ids(sb, user_id, role)
        if client_scope_ids is not None and not client_scope_ids:
            return jsonify({'error': 'Forbidden'}), 403
        reference_scope_user_id = _crm_interest_reference_scope_user_id(sb, user_id, role, client_scope_ids)
        existing_interest = _get_interest_for_user(
            sb,
            interest_id,
            panorama_ids,
            client_ids=client_scope_ids,
            reference_user_id=reference_scope_user_id,
        )
        if not existing_interest:
            return jsonify({'error': 'Not found or access denied'}), 404

        if any(key in data for key in BROKER_REFERRED_CONTACT_FIELDS):
            if (
                _interest_has_broker_reference(existing_interest)
                and not _interest_contact_is_revealed(existing_interest)
                and viewer_should_mask_broker_referred_contact(
                    sb,
                    user_id,
                    role,
                    reference_scope_user_id,
                )
            ):
                return jsonify({'error': 'Contact details are hidden until the referring broker reveals them'}), 403

        if 'reference_user_id' in data:
            pano_id = existing_interest.get('panorama_id')
            try:
                pano_id = int(pano_id) if pano_id is not None else None
            except Exception:
                pano_id = None
            raw_ref = data.get('reference_user_id')
            if raw_ref is None or str(raw_ref).strip() == '':
                upd['reference_user_id'] = None
            else:
                if not pano_id:
                    return jsonify({'error': 'Interest project is missing'}), 400
                reference_user_id, _reference_catalog, _reference_row = _validate_project_reference_user(
                    sb,
                    reference_user_id=str(raw_ref).strip(),
                    panorama_id=pano_id,
                    client_id=existing_interest.get('client_id'),
                )
                if not reference_user_id:
                    return jsonify({'error': 'Invalid reference for this project'}), 400
                upd['reference_user_id'] = reference_user_id
        if 'assigned_to' in data:
            iq = (
                sb.table('buy_interests')
                .select('panorama_id')
                .eq('id', str(interest_id))
                .in_('panorama_id', panorama_ids)
            )
            if reference_scope_user_id:
                iq = _crm_apply_broker_interest_visibility(iq, reference_scope_user_id)
            ir = iq.limit(1).execute()
            if not ir.data:
                return jsonify({'error': 'Not found or access denied'}), 404
            pano_id = int(ir.data[0].get('panorama_id'))
            pmap = _accessible_panorama_org_map(sb, [pano_id])
            org_id = (pmap.get(pano_id) or {}).get('org_id')
            raw_at = data.get('assigned_to')
            if raw_at is None or str(raw_at).strip() == '':
                upd['assigned_to'] = None
                upd['assigned_at'] = None
            else:
                uid = str(raw_at).strip()
                if org_id and not _crm_profile_in_org(sb, uid, org_id):
                    return jsonify({'error': 'Assignee must belong to the project organization'}), 400
                upd['assigned_to'] = uid
                upd['assigned_at'] = now
        if 'is_contacted' in data:
            mark_contacted = _is_truthy(data.get('is_contacted'))
            upd['is_contacted'] = mark_contacted
            upd['status'] = 'contacted' if mark_contacted else 'new'
            upd['contacted_at'] = now if mark_contacted else None
        if 'status' in data:
            status = str(data.get('status') or '').strip().lower()
            if status not in ('new', 'contacted'):
                return jsonify({'error': 'Invalid status. Interests support only new/contacted'}), 400
            upd['is_contacted'] = (status == 'contacted')
            upd['status'] = status
            upd['contacted_at'] = now if status == 'contacted' else None
        if 'notes' in data:
            upd['notes'] = str(data.get('notes') or '').strip()
        for key in (
            'lead_source',
            'lead_category',
            'lead_status',
            'campaign_type',
            'campaign_status',
            'deal_stage',
            'title',
            'description',
            'customer_street',
            'customer_city',
            'customer_state',
            'customer_country',
            'customer_zip_code',
            'customer_address',
        ):
            if key in data:
                if key == 'lead_source':
                    existing_source = str(existing_interest.get('lead_source') or '').strip().lower()
                    has_plot_origin = isinstance(existing_interest.get('plots'), list) and len(existing_interest.get('plots') or []) > 0
                    if has_plot_origin and existing_source == 'salestool':
                        return jsonify({'error': 'Lead Source is locked for plot-origin interests'}), 400
                value = str(data.get(key) or '').strip()
                if key in ('title', 'customer_zip_code') and len(value) > 40:
                    return jsonify({'error': f'{key} must be 40 characters or less'}), 400
                if key in ('description', 'customer_address') and len(value) > 500:
                    return jsonify({'error': f'{key} must be 500 characters or less'}), 400
                if key not in ('description', 'customer_address') and len(value) > 100:
                    return jsonify({'error': f'{key} must be 100 characters or less'}), 400
                upd[key] = value or None
        dynamic_custom_fields = _extract_custom_fields_payload(data, set(upd.keys()) | {'is_contacted', 'status', 'assigned_to', 'reference_user_id', 'notes'})
        if dynamic_custom_fields:
            upd['custom_fields'] = dynamic_custom_fields
        if not upd:
            return jsonify({'error': 'Nothing to update'}), 400
        upd['updated_at'] = now
        # Single query: update only if the interest belongs to an accessible panorama
        try:
            uq = sb.table('buy_interests').update(upd).eq('id', interest_id).in_('panorama_id', panorama_ids)
            uq = _crm_apply_client_scope(uq, client_scope_ids)
            if uq is None:
                return jsonify({'error': 'Not found or access denied'}), 404
            if reference_scope_user_id:
                uq = _crm_apply_broker_interest_visibility(uq, reference_scope_user_id)
            r = uq.execute()
            if not r.data or len(r.data) == 0:
                return jsonify({'error': 'Not found or access denied'}), 404
            _crm_cache_bump()
            return jsonify({'success': True})
        except Exception as e:
            msg = str(e)
            if 'buy_interests' in msg and ('does not exist' in msg.lower() or 'relation' in msg.lower()):
                return jsonify({'error': 'buy_interests table not found. Run db/schema.sql in Supabase SQL Editor.'}), 503
            return jsonify({'error': msg}), 500

    @app.route('/api/buy-interests/<interest_id>/reveal-contact', methods=['POST'])
    @require_auth
    def reveal_buy_interest_contact(user_id, role, interest_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        panorama_ids = _crm_panorama_ids(sb, user_id, role)
        if not panorama_ids:
            return jsonify({'error': 'Forbidden'}), 403
        client_scope_ids = _crm_client_scope_ids(sb, user_id, role)
        if client_scope_ids is not None and not client_scope_ids:
            return jsonify({'error': 'Forbidden'}), 403
        reference_scope_user_id = _crm_interest_reference_scope_user_id(sb, user_id, role, client_scope_ids)
        existing_interest = _get_interest_for_user(
            sb,
            interest_id,
            panorama_ids,
            client_ids=client_scope_ids,
            reference_user_id=reference_scope_user_id,
        )
        if not existing_interest:
            return jsonify({'error': 'Not found or access denied'}), 404
        if not can_user_reveal_broker_referred_contact(user_id, existing_interest):
            return jsonify({'error': 'Only the referring broker can reveal this contact'}), 403
        now = datetime.utcnow().isoformat()
        try:
            uq = (
                sb.table('buy_interests')
                .update({'contact_revealed_at': now, 'updated_at': now})
                .eq('id', str(interest_id))
                .in_('panorama_id', panorama_ids)
            )
            if reference_scope_user_id:
                uq = _crm_apply_broker_interest_visibility(uq, reference_scope_user_id)
            r = uq.execute()
            if not r.data:
                return jsonify({'error': 'Not found or access denied'}), 404
            _crm_cache_bump()
            return jsonify({'success': True, 'contact_revealed_at': now})
        except Exception as e:
            msg = str(e)
            if 'contact_revealed_at' in msg and ('column' in msg.lower() or 'schema cache' in msg.lower()):
                return jsonify({
                    'error': 'contact_revealed_at column not found. Run db/migration_broker_contact_reveal.sql in Supabase.'
                }), 503
            return jsonify({'error': msg}), 500

    @app.route('/api/buy-interests/<interest_id>', methods=['DELETE'])
    @require_auth
    def delete_buy_interest(user_id, role, interest_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        panorama_ids = _crm_panorama_ids(sb, user_id, role)
        if not panorama_ids:
            return jsonify({'error': 'Forbidden'}), 403
        client_scope_ids = _crm_client_scope_ids(sb, user_id, role)
        if client_scope_ids is not None and not client_scope_ids:
            return jsonify({'error': 'Forbidden'}), 403
        reference_scope_user_id = _crm_interest_reference_scope_user_id(sb, user_id, role, client_scope_ids)
        try:
            eq = (
                sb.table('buy_interests')
                .select('id')
                .eq('id', str(interest_id))
                .in_('panorama_id', panorama_ids)
            )
            if reference_scope_user_id:
                eq = _crm_apply_broker_interest_visibility(eq, reference_scope_user_id)
            existing = eq.limit(1).execute()
            if not (existing.data or []):
                return jsonify({'error': 'Not found or access denied'}), 404
            dq = sb.table('buy_interests').delete().eq('id', str(interest_id)).in_('panorama_id', panorama_ids)
            if reference_scope_user_id:
                dq = _crm_apply_broker_interest_visibility(dq, reference_scope_user_id)
            dq.execute()
            _crm_cache_bump()
            return jsonify({'success': True})
        except Exception as e:
            msg = str(e)
            if 'buy_interests' in msg and ('does not exist' in msg.lower() or 'relation' in msg.lower()):
                return jsonify({'error': 'buy_interests table not found. Run db/schema.sql in Supabase SQL Editor.'}), 503
            return jsonify({'error': msg}), 500

    def _get_interest_for_user(sb, interest_id, panorama_ids, client_ids=None, reference_user_id=None):
        if not panorama_ids:
            return None
        try:
            q = (
                sb.table('buy_interests')
                .select('id, client_id, panorama_id, contact_id, reference_user_id, contact_revealed_at, submitted_by, customer_name, customer_email, customer_phone, customer_birthday, customer_address, customer_street, customer_city, customer_state, customer_country, customer_zip_code, lead_source, lead_category, lead_status, campaign_type, campaign_status, deal_stage, title, description, category, plots, notes, custom_fields, created_at, is_contacted, contacted_at, status, assigned_to, assigned_at')
                .eq('id', str(interest_id))
                .in_('panorama_id', panorama_ids)
            )
            # Same client-group isolation as the list endpoints: a record a
            # scoped user cannot list must not be fetchable/mutable by id.
            q = _crm_apply_client_scope(q, client_ids)
            if q is None:
                return None
            if reference_user_id:
                q = _crm_apply_broker_interest_visibility(q, str(reference_user_id))
            r = q.limit(1).execute()
            rows = r.data or []
            return rows[0] if rows else None
        except Exception:
            return None

    def _get_contact_for_user(sb, contact_id, panorama_ids, client_ids=None):
        if not panorama_ids:
            return None
        try:
            q = (
                sb.table('crm_contacts')
                .select('id, org_id, client_id, panorama_id, full_name, email, phone, birthday, address, '
                        'email_norm, phone_norm, notes, custom_fields, created_at, updated_at')
                .eq('id', str(contact_id))
                .in_('panorama_id', panorama_ids)
            )
            q = _crm_apply_client_scope(q, client_ids)
            if q is None:
                return None
            r = q.limit(1).execute()
            rows = r.data or []
            return rows[0] if rows else None
        except Exception:
            return None

    @app.route('/api/crm/contacts', methods=['POST'])
    @require_auth
    def create_crm_contact(user_id, role):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        data = request.get_json(silent=True) or {}
        panorama_ids = _crm_panorama_ids(sb, user_id, role)
        if not panorama_ids:
            return jsonify({'error': 'Forbidden'}), 403
        panorama_id = data.get('panorama_id')
        try:
            panorama_id = int(panorama_id) if panorama_id is not None else int(panorama_ids[0])
        except Exception:
            panorama_id = None
        if not panorama_id or panorama_id not in panorama_ids:
            return jsonify({'error': 'Invalid panorama_id'}), 400
        full_name = str(data.get('full_name') or data.get('name') or '').strip()
        email = str(data.get('email') or '').strip()
        phone = str(data.get('phone') or '').strip()
        notes = str(data.get('notes') or '').strip()
        birthday = _contact_birthday_value(data.get('birthday'))
        address = str(data.get('address') or '').strip()
        if not full_name:
            return jsonify({'error': 'Contact name is required'}), 400
        if not email and not phone:
            return jsonify({'error': 'Email or phone is required'}), 400
        pmap = _accessible_panorama_org_map(sb, [panorama_id])
        org_id = (pmap.get(panorama_id) or {}).get('org_id')
        client_id, client_err = _crm_pick_client_id_for_create(
            sb,
            user_id,
            role,
            requested_client_id=data.get('client_id'),
            panorama_id=panorama_id,
        )
        if client_err:
            return client_err
        email_norm = _normalize_email(email)
        phone_norm = _normalize_phone(phone)
        existing = _find_contact_by_email_or_phone(sb, org_id, email_norm, phone_norm, [panorama_id], client_id=client_id)
        now = datetime.utcnow().isoformat()
        if existing:
            upd = _merge_contact_payload(
                existing,
                full_name=full_name,
                email=email,
                phone=phone,
                notes=notes,
                birthday=birthday,
                address=address,
            )
            upd['updated_at'] = now
            sb.table('crm_contacts').update(upd).eq('id', existing.get('id')).execute()
            _crm_cache_bump()
            merged_contact = dict(existing)
            merged_contact.update(upd)
            return jsonify({'success': True, 'contact': merged_contact, 'merged': True})
        row = {
            'org_id': org_id,
            'client_id': client_id,
            'panorama_id': panorama_id,
            'full_name': full_name,
            'email': email,
            'phone': phone,
            'email_norm': email_norm,
            'phone_norm': phone_norm,
            'source_interest_id': None,
            'created_by': user_id,
            'notes': notes,
            'birthday': birthday,
            'address': address,
            'custom_fields': _extract_custom_fields_payload(
                data,
                {'full_name', 'name', 'email', 'phone', 'notes', 'birthday', 'address', 'panorama_id', 'client_id'},
            ),
            'created_at': now,
            'updated_at': now,
        }
        r = sb.table('crm_contacts').insert(row).execute()
        created = (r.data or [row])[0]
        _crm_cache_bump()
        return jsonify({'success': True, 'contact': created, 'merged': False}), 201

    @app.route('/api/crm/contacts/<contact_id>', methods=['PATCH'])
    @require_auth
    def update_crm_contact(user_id, role, contact_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        panorama_ids = _crm_panorama_ids(sb, user_id, role)
        client_scope_ids = _crm_client_scope_ids(sb, user_id, role)
        contact = _get_contact_for_user(sb, contact_id, panorama_ids, client_ids=client_scope_ids)
        if not contact:
            return jsonify({'error': 'Not found or access denied'}), 404
        data = request.get_json(silent=True) or {}
        if not any(k in data for k in ('full_name', 'email', 'phone', 'notes', 'birthday', 'address', 'custom_fields')):
            return jsonify({'error': 'Nothing to update'}), 400
        incoming_name = str(data.get('full_name') or contact.get('full_name') or '').strip()
        incoming_email = str(data.get('email') or contact.get('email') or '').strip()
        incoming_phone = str(data.get('phone') or contact.get('phone') or '').strip()
        incoming_notes = str(data.get('notes') or contact.get('notes') or '').strip()
        # Birthday and address are editable to blank, so an explicit key clears them.
        incoming_birthday = (
            _contact_birthday_value(data.get('birthday')) if 'birthday' in data
            else _contact_birthday_value(contact.get('birthday'))
        )
        incoming_address = (
            str(data.get('address') or '').strip() if 'address' in data
            else str(contact.get('address') or '').strip()
        )
        now = datetime.utcnow().isoformat()
        upd = _merge_contact_payload(
            contact,
            full_name=incoming_name,
            email=incoming_email,
            phone=incoming_phone,
            notes=incoming_notes,
            birthday=incoming_birthday,
            address=incoming_address,
        )
        dynamic_contact_custom = _extract_custom_fields_payload(
            data, {'full_name', 'email', 'phone', 'notes', 'birthday', 'address'}
        )
        if dynamic_contact_custom:
            upd['custom_fields'] = dynamic_contact_custom
        upd['updated_at'] = now
        org_id = contact.get('org_id')
        try:
            pano_id = int(contact.get('panorama_id')) if contact.get('panorama_id') is not None else None
        except Exception:
            pano_id = None
        dup = _find_contact_by_email_or_phone(
            sb,
            org_id,
            upd.get('email_norm') or _normalize_email(incoming_email),
            upd.get('phone_norm') or _normalize_phone(incoming_phone),
            [pano_id] if pano_id else panorama_ids,
            client_id=contact.get('client_id'),
        )
        if dup and str(dup.get('id')) != str(contact_id):
            dup_upd = _merge_contact_payload(
                dup,
                full_name=upd.get('full_name'),
                email=upd.get('email'),
                phone=upd.get('phone'),
                notes=upd.get('notes'),
                birthday=upd.get('birthday'),
                address=upd.get('address'),
            )
            dup_upd['updated_at'] = now
            sb.table('crm_contacts').update(dup_upd).eq('id', str(dup.get('id'))).execute()
            _relink_contact_references(sb, str(contact_id), str(dup.get('id')))
            sb.table('crm_contacts').delete().eq('id', str(contact_id)).execute()
            _crm_cache_bump()
            merged_contact = dict(dup)
            merged_contact.update(dup_upd)
            # The list endpoint masks broker-referred contacts for client
            # staff; the merged-contact response must not hand the same
            # values back unmasked.
            try:
                ir = (
                    sb.table('buy_interests')
                    .select('reference_user_id, contact_revealed_at')
                    .eq('contact_id', str(dup.get('id')))
                    .order('created_at', desc=True)
                    .limit(20)
                    .execute()
                )
                linked_interest = next(
                    (r_row for r_row in (ir.data or [])
                     if _interest_has_broker_reference(r_row) and not _interest_contact_is_revealed(r_row)),
                    None,
                )
            except Exception:
                linked_interest = None
            if linked_interest:
                reference_scope_user_id = _crm_interest_reference_scope_user_id(sb, user_id, role, client_scope_ids)
                merged_contact = apply_broker_referred_contact_mask_to_contact(
                    merged_contact,
                    linked_interest,
                    user_id=user_id,
                    role=role,
                    reference_scope_user_id=reference_scope_user_id,
                    sb=sb,
                )
            return jsonify({'success': True, 'merged': True, 'contact': merged_contact})
        sb.table('crm_contacts').update(upd).eq('id', str(contact_id)).execute()
        _crm_cache_bump()
        return jsonify({'success': True, 'merged': False})

    @app.route('/api/crm/interests/<interest_id>/create-contact', methods=['POST'])
    @require_auth
    def create_contact_from_interest(user_id, role, interest_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        panorama_ids = _crm_panorama_ids(sb, user_id, role)
        if not panorama_ids:
            return jsonify({'error': 'Forbidden'}), 403
        client_scope_ids = _crm_client_scope_ids(sb, user_id, role)
        reference_scope_user_id = _crm_interest_reference_scope_user_id(sb, user_id, role, client_scope_ids)
        interest = _get_interest_for_user(
            sb,
            interest_id,
            panorama_ids,
            client_ids=client_scope_ids,
            reference_user_id=reference_scope_user_id,
        )
        if not interest:
            return jsonify({'error': 'Interest not found'}), 404
        hidden_denied = _crm_deny_hidden_broker_referred_contact(
            sb, user_id, role, reference_scope_user_id, interest
        )
        if hidden_denied:
            return hidden_denied
        panorama_id = int(interest.get('panorama_id'))
        pmap = _accessible_panorama_org_map(sb, [panorama_id])
        org_id = (pmap.get(panorama_id) or {}).get('org_id')
        full_name = str(interest.get('customer_name') or '').strip()
        email = str(interest.get('customer_email') or '').strip()
        phone = str(interest.get('customer_phone') or '').strip()
        interest_client_id = interest.get('client_id')
        birthday = _contact_birthday_value(interest.get('customer_birthday'))
        address = str(interest.get('customer_address') or '').strip()
        email_norm = _normalize_email(email)
        phone_norm = _normalize_phone(phone)
        existing = _find_contact_by_email_or_phone(sb, org_id, email_norm, phone_norm, [panorama_id], client_id=interest_client_id)
        now = datetime.utcnow().isoformat()
        if existing:
            upd = _merge_contact_payload(
                existing,
                full_name=full_name,
                email=email,
                phone=phone,
                notes=existing.get('notes') or '',
                birthday=birthday,
                address=address,
            )
            upd['updated_at'] = now
            sb.table('crm_contacts').update(upd).eq('id', existing.get('id')).execute()
            sb.table('buy_interests').update({
                'contact_id': existing.get('id'),
                'updated_at': now,
            }).eq('id', str(interest_id)).execute()
            _crm_cache_bump()
            merged_contact = dict(existing)
            merged_contact.update(upd)
            return jsonify({'success': True, 'contact': merged_contact, 'merged': True})
        row = {
            'org_id': org_id,
            'client_id': interest_client_id,
            'panorama_id': panorama_id,
            'full_name': full_name,
            'email': email,
            'phone': phone,
            'birthday': birthday,
            'address': address,
            'email_norm': email_norm,
            'phone_norm': phone_norm,
            'source_interest_id': str(interest_id),
            'created_by': user_id,
            'notes': '',
            'created_at': now,
            'updated_at': now,
        }
        r = sb.table('crm_contacts').insert(row).execute()
        created = (r.data or [row])[0]
        sb.table('buy_interests').update({
            'contact_id': created.get('id'),
            'updated_at': now,
        }).eq('id', str(interest_id)).execute()
        _crm_cache_bump()
        return jsonify({'success': True, 'contact': created, 'merged': False}), 201

    @app.route('/api/crm/interests/<interest_id>/create-deal', methods=['POST'])
    @require_auth
    def create_deal_from_interest(user_id, role, interest_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        panorama_ids = _crm_panorama_ids(sb, user_id, role)
        if not panorama_ids:
            return jsonify({'error': 'Forbidden'}), 403
        client_scope_ids = _crm_client_scope_ids(sb, user_id, role)
        reference_scope_user_id = _crm_interest_reference_scope_user_id(sb, user_id, role, client_scope_ids)
        interest = _get_interest_for_user(
            sb,
            interest_id,
            panorama_ids,
            client_ids=client_scope_ids,
            reference_user_id=reference_scope_user_id,
        )
        if not interest:
            return jsonify({'error': 'Interest not found'}), 404
        panorama_id = int(interest.get('panorama_id'))
        if panorama_id not in panorama_ids:
            return jsonify({'error': 'Forbidden'}), 403
        data = request.get_json(silent=True) or {}
        contact_id = data.get('contact_id') or interest.get('contact_id')
        interest_client_id = interest.get('client_id')
        if not interest_client_id:
            interest_client_id, client_err = _crm_pick_client_id_for_create(
                sb, user_id, role, requested_client_id=data.get('client_id'), panorama_id=panorama_id
            )
            if client_err:
                return client_err
        if not contact_id:
            return jsonify({'error': 'Create or link a contact first'}), 400
        contact = _get_contact_for_user(sb, contact_id, panorama_ids, client_ids=client_scope_ids)
        if not contact:
            return jsonify({'error': 'Linked contact not found'}), 404
        existing_active = (
            sb.table('crm_deals')
            .select('id, stage, is_active')
            .eq('interest_id', str(interest_id))
            .eq('is_active', True)
            .limit(1)
            .execute()
        )
        if existing_active.data:
            return jsonify({'error': 'An active deal already exists for this interest'}), 409
        pmap = _accessible_panorama_org_map(sb, [panorama_id])
        pinfo = pmap.get(panorama_id) or {}
        plots = _safe_json(interest.get('plots'), [])
        requested_plots = _safe_json(data.get('plots'), None)
        if isinstance(requested_plots, list):
            cleaned = []
            for p in requested_plots:
                if not isinstance(p, dict):
                    continue
                pid_raw = p.get('plot_id') if p.get('plot_id') is not None else p.get('id')
                try:
                    pid = int(str(pid_raw).strip()) if pid_raw is not None and str(pid_raw).strip() != '' else None
                except Exception:
                    pid = None
                cleaned.append({
                    'plot_id': pid,
                    'id': pid,
                    'name': str(p.get('name') or '').strip(),
                    'area': str(p.get('area') or '').strip(),
                    'price': str(p.get('price') or '').strip(),
                    'status': str(p.get('status') or 'available').strip().lower() or 'available',
                })
            # If user selected at least one plot in the drawer, honor that selection.
            if cleaned:
                plots = cleaned
        amount = ''
        if isinstance(plots, list):
            prices = [str((p or {}).get('price') or '').strip() for p in plots]
            prices = [x for x in prices if x]
            if len(prices) == 1:
                amount = prices[0]
            elif len(prices) > 1:
                amount = prices[0] + ' + more'
        now = datetime.utcnow().isoformat()
        row = {
            'org_id': pinfo.get('org_id'),
            'client_id': interest_client_id,
            'panorama_id': panorama_id,
            'interest_id': str(interest_id),
            'contact_id': str(contact_id),
            'title': str(data.get('title') or (contact.get('full_name') or interest.get('customer_name') or 'Deal')).strip(),
            'stage': str(data.get('stage') or 'new').strip().lower() or 'new',
            'is_active': True,
            'amount': str(data.get('amount') or amount or '').strip(),
            'currency': 'INR',
            'plots': plots if isinstance(plots, list) else [],
            'project_name': pinfo.get('panorama_name') or '',
            'notes': str(data.get('notes') or interest.get('notes') or '').strip(),
            'custom_fields': _extract_custom_fields_payload(data, {'contact_id', 'client_id', 'title', 'stage', 'amount', 'plots', 'notes'}) or _safe_json(interest.get('custom_fields'), {}),
            'created_by': user_id,
            'created_at': now,
            'updated_at': now,
        }
        if row['stage'] not in ('new', 'contacted', 'site_visit', 'negotiation', 'won', 'lost'):
            row['stage'] = 'new'
        row['is_active'] = _touch_deal_active_state_from_stage(row['stage'])
        r = sb.table('crm_deals').insert(row).execute()
        created = (r.data or [row])[0]
        _mark_interest_qualified_for_deal(sb, str(interest_id), str(contact_id), now)
        _crm_cache_bump()
        return jsonify({'success': True, 'deal': created}), 201

    @app.route('/api/crm/interests/<interest_id>/convert', methods=['POST'])
    @require_auth
    def convert_interest_to_contact_and_deal(user_id, role, interest_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        panorama_ids = _crm_panorama_ids(sb, user_id, role)
        if not panorama_ids:
            return jsonify({'error': 'Forbidden'}), 403
        client_scope_ids = _crm_client_scope_ids(sb, user_id, role)
        reference_scope_user_id = _crm_interest_reference_scope_user_id(sb, user_id, role, client_scope_ids)
        interest = _get_interest_for_user(
            sb,
            interest_id,
            panorama_ids,
            client_ids=client_scope_ids,
            reference_user_id=reference_scope_user_id,
        )
        if not interest:
            return jsonify({'error': 'Interest not found'}), 404
        hidden_denied = _crm_deny_hidden_broker_referred_contact(
            sb, user_id, role, reference_scope_user_id, interest
        )
        if hidden_denied:
            return hidden_denied
        panorama_id = int(interest.get('panorama_id'))
        if panorama_id not in panorama_ids:
            return jsonify({'error': 'Forbidden'}), 403
        data = request.get_json(silent=True) or {}
        contact_id = data.get('contact_id') or interest.get('contact_id')
        interest_client_id = interest.get('client_id')
        if not interest_client_id:
            interest_client_id, client_err = _crm_pick_client_id_for_create(
                sb, user_id, role, requested_client_id=data.get('client_id'), panorama_id=panorama_id
            )
            if client_err:
                return client_err
        if contact_id:
            contact = _get_contact_for_user(sb, contact_id, panorama_ids, client_ids=client_scope_ids)
            if not contact:
                return jsonify({'error': 'Linked contact not found'}), 404
        else:
            pmap0 = _accessible_panorama_org_map(sb, [panorama_id])
            org_id = (pmap0.get(panorama_id) or {}).get('org_id')
            full_name = str(interest.get('customer_name') or '').strip()
            email = str(interest.get('customer_email') or '').strip()
            phone = str(interest.get('customer_phone') or '').strip()
            birthday = _contact_birthday_value(interest.get('customer_birthday'))
            address = str(interest.get('customer_address') or '').strip()
            email_norm = _normalize_email(email)
            phone_norm = _normalize_phone(phone)
            existing = _find_contact_by_email_or_phone(sb, org_id, email_norm, phone_norm, [panorama_id], client_id=interest_client_id)
            now0 = datetime.utcnow().isoformat()
            if existing:
                upd = _merge_contact_payload(
                    existing,
                    full_name=full_name,
                    email=email,
                    phone=phone,
                    notes=existing.get('notes') or '',
                    birthday=birthday,
                    address=address,
                )
                upd['updated_at'] = now0
                sb.table('crm_contacts').update(upd).eq('id', existing.get('id')).execute()
                sb.table('buy_interests').update({
                    'contact_id': existing.get('id'),
                    'updated_at': now0,
                }).eq('id', str(interest_id)).execute()
                contact_id = existing.get('id')
                contact = dict(existing)
                contact.update(upd)
            else:
                row_c = {
                    'org_id': org_id,
                    'client_id': interest_client_id,
                    'panorama_id': panorama_id,
                    'full_name': full_name,
                    'email': email,
                    'phone': phone,
                    'birthday': birthday,
                    'address': address,
                    'email_norm': email_norm,
                    'phone_norm': phone_norm,
                    'source_interest_id': str(interest_id),
                    'created_by': user_id,
                    'notes': '',
                    'created_at': now0,
                    'updated_at': now0,
                }
                r_c = sb.table('crm_contacts').insert(row_c).execute()
                contact = (r_c.data or [row_c])[0]
                contact_id = contact.get('id')
                sb.table('buy_interests').update({
                    'contact_id': str(contact_id),
                    'updated_at': now0,
                }).eq('id', str(interest_id)).execute()
        existing_active = (
            sb.table('crm_deals')
            .select('id, stage, is_active')
            .eq('interest_id', str(interest_id))
            .eq('is_active', True)
            .limit(1)
            .execute()
        )
        if existing_active.data:
            return jsonify({'error': 'An active deal already exists for this interest', 'contact': contact}), 409
        pmap = _accessible_panorama_org_map(sb, [panorama_id])
        pinfo = pmap.get(panorama_id) or {}
        plots = _safe_json(interest.get('plots'), [])
        amount = ''
        if isinstance(plots, list):
            prices = [str((p or {}).get('price') or '').strip() for p in plots]
            prices = [x for x in prices if x]
            if len(prices) == 1:
                amount = prices[0]
            elif len(prices) > 1:
                amount = prices[0] + ' + more'
        now = datetime.utcnow().isoformat()
        row = {
            'org_id': pinfo.get('org_id'),
            'client_id': interest_client_id,
            'panorama_id': panorama_id,
            'interest_id': str(interest_id),
            'contact_id': str(contact_id),
            'title': str(data.get('title') or (contact.get('full_name') or interest.get('customer_name') or 'Deal')).strip(),
            'stage': str(data.get('stage') or 'new').strip().lower() or 'new',
            'is_active': True,
            'amount': str(data.get('amount') or amount or '').strip(),
            'currency': 'INR',
            'plots': plots if isinstance(plots, list) else [],
            'project_name': pinfo.get('panorama_name') or '',
            'notes': str(data.get('notes') or interest.get('notes') or '').strip(),
            'custom_fields': _extract_custom_fields_payload(data, {'contact_id', 'client_id', 'title', 'stage', 'amount', 'plots', 'notes'}) or _safe_json(interest.get('custom_fields'), {}),
            'created_by': user_id,
            'created_at': now,
            'updated_at': now,
        }
        if row['stage'] not in ('new', 'contacted', 'site_visit', 'negotiation', 'won', 'lost'):
            row['stage'] = 'new'
        row['is_active'] = _touch_deal_active_state_from_stage(row['stage'])
        r = sb.table('crm_deals').insert(row).execute()
        created = (r.data or [row])[0]
        _mark_interest_qualified_for_deal(sb, str(interest_id), str(contact_id), now)
        _crm_cache_bump()
        return jsonify({'success': True, 'contact': contact, 'deal': created}), 201

    @app.route('/api/crm/deals', methods=['POST'])
    @require_auth
    def create_crm_deal(user_id, role):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        panorama_ids = _crm_panorama_ids(sb, user_id, role)
        if not panorama_ids:
            return jsonify({'error': 'Forbidden'}), 403
        client_scope_ids = _crm_client_scope_ids(sb, user_id, role)
        data = request.get_json(silent=True) or {}
        panorama_id = data.get('panorama_id')
        try:
            panorama_id = int(panorama_id)
        except Exception:
            panorama_id = None
        if not panorama_id or panorama_id not in panorama_ids:
            return jsonify({'error': 'Invalid panorama_id'}), 400
        contact_id = data.get('contact_id')
        if not contact_id:
            return jsonify({'error': 'contact_id is required'}), 400
        contact = _get_contact_for_user(sb, contact_id, panorama_ids, client_ids=client_scope_ids)
        if not contact:
            return jsonify({'error': 'Contact not found'}), 404
        client_id, client_err = _crm_pick_client_id_for_create(
            sb,
            user_id,
            role,
            requested_client_id=data.get('client_id') or contact.get('client_id'),
            panorama_id=panorama_id,
        )
        if client_err:
            return client_err
        stage = str(data.get('stage') or 'new').strip().lower()
        if stage not in ('new', 'contacted', 'site_visit', 'negotiation', 'won', 'lost'):
            return jsonify({'error': 'Invalid stage'}), 400
        interest_id = str(data.get('interest_id') or '').strip() or None
        if interest_id:
            existing_active = (
                sb.table('crm_deals')
                .select('id')
                .eq('interest_id', interest_id)
                .eq('is_active', True)
                .limit(1)
                .execute()
            )
            if existing_active.data:
                return jsonify({'error': 'An active deal already exists for this interest'}), 409
        pmap = _accessible_panorama_org_map(sb, [panorama_id])
        now = datetime.utcnow().isoformat()
        # Same per-item plot cleaning as create_deal_from_interest — any list
        # shape must not be stored verbatim.
        raw_plots = _safe_json(data.get('plots'), [])
        deal_plots = []
        if isinstance(raw_plots, list):
            for p in raw_plots:
                if not isinstance(p, dict):
                    continue
                pid_raw = p.get('plot_id') if p.get('plot_id') is not None else p.get('id')
                try:
                    pid = int(str(pid_raw).strip()) if pid_raw is not None and str(pid_raw).strip() != '' else None
                except Exception:
                    pid = None
                deal_plots.append({
                    'plot_id': pid,
                    'id': pid,
                    'name': str(p.get('name') or '').strip()[:120],
                    'area': str(p.get('area') or '').strip()[:60],
                    'price': str(p.get('price') or '').strip()[:60],
                    'status': str(p.get('status') or 'available').strip().lower()[:30] or 'available',
                })
        currency = re.sub(r'[^A-Za-z]', '', str(data.get('currency') or 'INR'))[:8].upper() or 'INR'
        row = {
            'org_id': (pmap.get(panorama_id) or {}).get('org_id'),
            'client_id': client_id,
            'panorama_id': panorama_id,
            'interest_id': interest_id,
            'contact_id': str(contact_id),
            'title': str(data.get('title') or contact.get('full_name') or 'Deal').strip()[:200],
            'stage': stage,
            'is_active': _touch_deal_active_state_from_stage(stage),
            'amount': str(data.get('amount') or '').strip()[:60],
            'currency': currency,
            'plots': deal_plots,
            'project_name': str(data.get('project_name') or (pmap.get(panorama_id) or {}).get('panorama_name') or '').strip()[:200],
            'notes': str(data.get('notes') or '').strip()[:2000],
            'custom_fields': _extract_custom_fields_payload(data, {'panorama_id', 'contact_id', 'client_id', 'interest_id', 'title', 'stage', 'amount', 'currency', 'plots', 'project_name', 'notes'}),
            'created_by': user_id,
            'created_at': now,
            'updated_at': now,
        }
        r = sb.table('crm_deals').insert(row).execute()
        created = (r.data or [row])[0]
        if interest_id:
            _mark_interest_qualified_for_deal(sb, str(interest_id), str(contact_id), now)
        _crm_cache_bump()
        return jsonify({'success': True, 'deal': created}), 201

    @app.route('/api/crm/deals/<deal_id>', methods=['PATCH'])
    @require_auth
    def update_crm_deal(user_id, role, deal_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        panorama_ids = _crm_panorama_ids(sb, user_id, role)
        if not panorama_ids:
            return jsonify({'error': 'Forbidden'}), 403
        client_scope_ids = _crm_client_scope_ids(sb, user_id, role)
        reference_scope_user_id = _crm_interest_reference_scope_user_id(sb, user_id, role, client_scope_ids)
        reference_interest_ids, _reference_contact_ids = [], []
        if reference_scope_user_id:
            reference_interest_ids, _reference_contact_ids = _crm_reference_linked_ids(
                sb,
                reference_scope_user_id,
                panorama_ids,
                client_ids=client_scope_ids,
            )
            if not reference_interest_ids:
                return jsonify({'error': 'Not found or access denied'}), 404
        q_existing = (
            sb.table('crm_deals')
            .select('id, panorama_id, stage')
            .eq('id', str(deal_id))
        )
        q_existing = q_existing.in_('panorama_id', panorama_ids)
        q_existing = _crm_apply_client_scope(q_existing, client_scope_ids)
        if q_existing is None:
            return jsonify({'error': 'Not found or access denied'}), 404
        if reference_scope_user_id:
            q_existing = q_existing.in_('interest_id', reference_interest_ids)
        existing = q_existing.limit(1).execute()
        if not existing.data:
            return jsonify({'error': 'Not found or access denied'}), 404
        data = request.get_json(silent=True) or {}
        upd = {}
        for key in ('title', 'amount', 'currency', 'project_name', 'notes'):
            if key in data:
                upd[key] = str(data.get(key) or '').strip()
        if 'plots' in data:
            upd['plots'] = _safe_json(data.get('plots'), [])
        if 'contact_id' in data:
            cid = str(data.get('contact_id') or '').strip()
            if not cid:
                return jsonify({'error': 'contact_id cannot be empty'}), 400
            contact = _get_contact_for_user(sb, cid, panorama_ids, client_ids=client_scope_ids)
            if not contact:
                return jsonify({'error': 'Contact not found'}), 404
            upd['contact_id'] = cid
        if 'stage' in data:
            stage = str(data.get('stage') or '').strip().lower()
            if stage not in ('new', 'contacted', 'site_visit', 'negotiation', 'won', 'lost'):
                return jsonify({'error': 'Invalid stage'}), 400
            upd['stage'] = stage
            upd['is_active'] = _touch_deal_active_state_from_stage(stage)
        dynamic_deal_custom = _extract_custom_fields_payload(data, set(upd.keys()) | {'title', 'amount', 'currency', 'project_name', 'notes', 'plots', 'contact_id', 'stage'})
        if dynamic_deal_custom:
            upd['custom_fields'] = dynamic_deal_custom
        if not upd:
            return jsonify({'error': 'Nothing to update'}), 400
        upd['updated_at'] = datetime.utcnow().isoformat()
        # Scope the UPDATE itself, not just the pre-check, so the row cannot
        # slip out of scope between the read and the write.
        q_update = sb.table('crm_deals').update(upd).eq('id', str(deal_id)).in_('panorama_id', panorama_ids)
        q_update = _crm_apply_client_scope(q_update, client_scope_ids)
        if q_update is None:
            return jsonify({'error': 'Not found or access denied'}), 404
        if reference_scope_user_id:
            q_update = q_update.in_('interest_id', reference_interest_ids)
        r = q_update.execute()
        if not r.data:
            return jsonify({'error': 'Not found or access denied'}), 404
        _crm_cache_bump()
        return jsonify({'success': True})

    @app.route('/api/crm/deals/<deal_id>/move-stage', methods=['POST'])
    @require_auth
    def move_crm_deal_stage(user_id, role, deal_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        data = request.get_json(silent=True) or {}
        stage = str(data.get('stage') or '').strip().lower()
        if stage not in ('new', 'contacted', 'site_visit', 'negotiation', 'won', 'lost'):
            return jsonify({'error': 'Invalid stage'}), 400
        panorama_ids = _crm_panorama_ids(sb, user_id, role)
        if not panorama_ids:
            return jsonify({'error': 'Forbidden'}), 403
        client_scope_ids = _crm_client_scope_ids(sb, user_id, role)
        reference_scope_user_id = _crm_interest_reference_scope_user_id(sb, user_id, role, client_scope_ids)
        reference_interest_ids, _reference_contact_ids = [], []
        if reference_scope_user_id:
            reference_interest_ids, _reference_contact_ids = _crm_reference_linked_ids(
                sb,
                reference_scope_user_id,
                panorama_ids,
                client_ids=client_scope_ids,
            )
            if not reference_interest_ids:
                return jsonify({'error': 'Not found or access denied'}), 404
        upd = {
            'stage': stage,
            'is_active': _touch_deal_active_state_from_stage(stage),
            'updated_at': datetime.utcnow().isoformat(),
        }
        q_move = (
            sb.table('crm_deals')
            .update(upd)
            .eq('id', str(deal_id))
        )
        q_move = q_move.in_('panorama_id', panorama_ids)
        q_move = _crm_apply_client_scope(q_move, client_scope_ids)
        if q_move is None:
            return jsonify({'error': 'Not found or access denied'}), 404
        if reference_scope_user_id:
            q_move = q_move.in_('interest_id', reference_interest_ids)
        r = q_move.execute()
        if not r.data:
            return jsonify({'error': 'Not found or access denied'}), 404
        _crm_cache_bump()
        return jsonify({'success': True})

    @app.route('/api/crm/deals/<deal_id>/quotation/preview', methods=['POST'])
    @require_auth
    def preview_deal_quote(user_id, role, deal_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        panorama_ids = _crm_panorama_ids(sb, user_id, role)
        if not panorama_ids:
            return jsonify({'error': 'Forbidden'}), 403
        client_scope_ids = _crm_client_scope_ids(sb, user_id, role)
        # Brokers may only quote their own referred deals — same narrowing as
        # update_crm_deal, otherwise this route leaks other brokers' contacts.
        reference_scope_user_id = _crm_interest_reference_scope_user_id(sb, user_id, role, client_scope_ids)
        reference_interest_ids = []
        if reference_scope_user_id:
            reference_interest_ids, _reference_contact_ids = _crm_reference_linked_ids(
                sb,
                reference_scope_user_id,
                panorama_ids,
                client_ids=client_scope_ids,
            )
            if not reference_interest_ids:
                return jsonify({'error': 'Deal not found'}), 404
        drq = (
            sb.table('crm_deals')
            .select('id, org_id, client_id, panorama_id, contact_id, interest_id, title, stage, amount, currency, plots, project_name')
            .eq('id', str(deal_id))
        )
        drq = drq.in_('panorama_id', panorama_ids)
        if client_scope_ids is not None:
            drq = _crm_apply_client_scope(drq, client_scope_ids)
            if drq is None:
                return jsonify({'error': 'Deal not found'}), 404
        if reference_scope_user_id:
            drq = drq.in_('interest_id', reference_interest_ids)
        dr = drq.limit(1).execute()
        if not dr.data:
            return jsonify({'error': 'Deal not found'}), 404
        deal = dr.data[0]
        # A quote snapshots the raw contact record into its payload; viewers
        # the broker has not revealed the contact to must not mint one.
        if deal.get('interest_id'):
            try:
                ir = (
                    sb.table('buy_interests')
                    .select('reference_user_id, contact_revealed_at')
                    .eq('id', str(deal.get('interest_id')))
                    .limit(1)
                    .execute()
                )
                linked_interest = (ir.data or [None])[0]
            except Exception:
                linked_interest = None
            if linked_interest:
                deny = _crm_deny_hidden_broker_referred_contact(sb, user_id, role, reference_scope_user_id, linked_interest)
                if deny:
                    return deny
        deal.pop('interest_id', None)
        contact = None
        if deal.get('contact_id'):
            contact = _get_contact_for_user(sb, deal.get('contact_id'), panorama_ids, client_ids=client_scope_ids)
        payload = request.get_json(silent=True) or {}
        template_id = str(payload.get('template_id') or '').strip() or None
        inputs_raw = {k: v for k, v in payload.items() if k != 'template_id'}
        tpl_payload = {}
        resolved_template_id = None
        if template_id:
            tr = (
                sb.table('crm_quote_templates')
                .select('id, org_id, panorama_id, template_payload')
                .eq('id', template_id)
                .limit(1)
                .execute()
            )
            if not tr.data:
                return jsonify({'error': 'Template not found'}), 404
            tpl = tr.data[0]
            d_org = deal.get('org_id')
            t_org = tpl.get('org_id')
            if d_org and t_org and str(d_org) != str(t_org):
                return jsonify({'error': 'Template does not belong to this deal organization'}), 400
            t_pano = tpl.get('panorama_id')
            if t_pano is not None and int(deal.get('panorama_id') or 0) != int(t_pano):
                return jsonify({'error': 'Template is not valid for this panorama'}), 400
            tpl_payload = tpl.get('template_payload') or {}
            resolved_template_id = str(tpl.get('id'))
        merged_inputs = _merge_quote_template_inputs(tpl_payload, inputs_raw)
        quote_payload = {
            'deal': deal,
            'contact': contact or {},
            'inputs': merged_inputs,
            'generated_at': datetime.utcnow().isoformat(),
        }
        token = secrets.token_urlsafe(24)
        now = datetime.utcnow().isoformat()
        row = {
            'deal_id': str(deal_id),
            'contact_id': str(deal.get('contact_id') or '') or None,
            'template_id': resolved_template_id,
            'quote_payload': quote_payload,
            'share_token': token,
            'sent_to_email': '',
            'sent_to_phone': '',
            'shared_via': '',
            'sent_at': None,
            'status': 'draft',
            'created_by': user_id,
            'created_at': now,
            'updated_at': now,
        }
        r = sb.table('crm_deal_quotes').insert(row).execute()
        quote = (r.data or [row])[0]
        share_url = f"{request.url_root.rstrip('/')}/api/crm/deals/{deal_id}/quotation/{quote.get('id')}?token={token}"
        _crm_cache_bump()
        return jsonify({'success': True, 'quote': quote, 'share_url': share_url})

    register_crm_quote_routes(
        app,
        crm_panorama_ids=_crm_panorama_ids,
        crm_client_scope_ids=_crm_client_scope_ids,
        crm_apply_client_scope=_crm_apply_client_scope,
        crm_interest_reference_scope_user_id=_crm_interest_reference_scope_user_id,
        crm_reference_linked_ids=_crm_reference_linked_ids,
        get_contact_for_user=_get_contact_for_user,
        crm_cache_bump=_crm_cache_bump,
    )
    register_crm_contact_routes(
        app,
        crm_panorama_ids=_crm_panorama_ids,
        crm_client_scope_ids=_crm_client_scope_ids,
        crm_interest_reference_scope_user_id=_crm_interest_reference_scope_user_id,
        crm_apply_broker_referred_contact_mask=_crm_apply_broker_referred_contact_mask,
        crm_reference_linked_ids=_crm_reference_linked_ids,
        crm_cache_get=_crm_cache_get,
        crm_cache_set=_crm_cache_set,
        crm_cache_version=_crm_cache_version,
    )
    register_crm_broker_routes(
        app,
        crm_panorama_ids=_crm_panorama_ids,
        crm_client_scope_ids=_crm_client_scope_ids,
    )
    register_crm_plot_routes(
        app,
        crm_panorama_ids=_crm_panorama_ids,
        crm_cache_get=_crm_cache_get,
        crm_cache_set=_crm_cache_set,
        crm_cache_version=_crm_cache_version,
        crm_cache_bump=_crm_cache_bump,
    )
    register_crm_record_list_routes(
        app,
        crm_panorama_ids=_crm_panorama_ids,
        crm_client_scope_ids=_crm_client_scope_ids,
        crm_interest_reference_scope_user_id=_crm_interest_reference_scope_user_id,
        crm_apply_broker_interest_visibility=_crm_apply_broker_interest_visibility,
        crm_apply_broker_referred_contact_mask=_crm_apply_broker_referred_contact_mask,
        crm_reference_linked_ids=_crm_reference_linked_ids,
        crm_cache_get=_crm_cache_get,
        crm_cache_set=_crm_cache_set,
        crm_cache_version=_crm_cache_version,
    )
    register_crm_normal_routes(app)
    register_crm_lock_routes(
        app,
        crm_panorama_ids=_crm_panorama_ids,
        crm_client_scope_ids=_crm_client_scope_ids,
        crm_cache_get=_crm_cache_get,
        crm_cache_set=_crm_cache_set,
        crm_cache_version=_crm_cache_version,
        crm_cache_bump=_crm_cache_bump,
    )
    register_crm_master_routes(
        app,
        crm_client_scope_ids=_crm_client_scope_ids,
        crm_cache_bump=_crm_cache_bump,
    )

    @app.route('/api/crm/deals/<deal_id>/quotations', methods=['GET'])
    @require_auth
    def list_deal_quotations(user_id, role, deal_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        panorama_ids = _crm_panorama_ids(sb, user_id, role)
        if not panorama_ids:
            return jsonify({'error': 'Forbidden'}), 403
        client_scope_ids = _crm_client_scope_ids(sb, user_id, role)
        reference_scope_user_id = _crm_interest_reference_scope_user_id(sb, user_id, role, client_scope_ids)
        reference_interest_ids = []
        if reference_scope_user_id:
            reference_interest_ids, _reference_contact_ids = _crm_reference_linked_ids(
                sb,
                reference_scope_user_id,
                panorama_ids,
                client_ids=client_scope_ids,
            )
            if not reference_interest_ids:
                return jsonify({'error': 'Deal not found'}), 404
        drq = (
            sb.table('crm_deals')
            .select('id')
            .eq('id', str(deal_id))
        )
        drq = drq.in_('panorama_id', panorama_ids)
        if client_scope_ids is not None:
            drq = _crm_apply_client_scope(drq, client_scope_ids)
            if drq is None:
                return jsonify({'error': 'Deal not found'}), 404
        if reference_scope_user_id:
            drq = drq.in_('interest_id', reference_interest_ids)
        dr = drq.limit(1).execute()
        if not dr.data:
            return jsonify({'error': 'Deal not found'}), 404
        try:
            qr = (
                sb.table('crm_deal_quotes')
                .select('id, deal_id, contact_id, template_id, status, shared_via, sent_to_email, sent_at, created_at, updated_at')
                .eq('deal_id', str(deal_id))
                .order('created_at', desc=True)
                .limit(200)
                .execute()
            )
            rows = qr.data or []
            for row in rows:
                for k in ('created_at', 'updated_at', 'sent_at'):
                    if row.get(k):
                        row[k] = str(row[k])
                if row.get('template_id'):
                    row['template_id'] = str(row['template_id'])
            return jsonify(rows)
        except Exception as e:
            msg = str(e)
            if 'status' in msg or 'template_id' in msg:
                return jsonify({'error': 'Run db migration migration_crm_lead_assign_quote_templates.sql for quotation columns.'}), 503
            return jsonify({'error': msg}), 500

    @app.route('/api/crm/deals/<deal_id>/quotations/<quote_id>', methods=['PATCH'])
    @require_auth
    def patch_deal_quotation(user_id, role, deal_id, quote_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        panorama_ids = _crm_panorama_ids(sb, user_id, role)
        if not panorama_ids:
            return jsonify({'error': 'Forbidden'}), 403
        client_scope_ids = _crm_client_scope_ids(sb, user_id, role)
        reference_scope_user_id = _crm_interest_reference_scope_user_id(sb, user_id, role, client_scope_ids)
        reference_interest_ids = []
        if reference_scope_user_id:
            reference_interest_ids, _reference_contact_ids = _crm_reference_linked_ids(
                sb,
                reference_scope_user_id,
                panorama_ids,
                client_ids=client_scope_ids,
            )
            if not reference_interest_ids:
                return jsonify({'error': 'Deal not found'}), 404
        drq = (
            sb.table('crm_deals')
            .select('id')
            .eq('id', str(deal_id))
        )
        drq = drq.in_('panorama_id', panorama_ids)
        if client_scope_ids is not None:
            drq = _crm_apply_client_scope(drq, client_scope_ids)
            if drq is None:
                return jsonify({'error': 'Deal not found'}), 404
        if reference_scope_user_id:
            drq = drq.in_('interest_id', reference_interest_ids)
        dr = drq.limit(1).execute()
        if not dr.data:
            return jsonify({'error': 'Deal not found'}), 404
        qr = (
            sb.table('crm_deal_quotes')
            .select('id, quote_payload, status')
            .eq('id', str(quote_id))
            .eq('deal_id', str(deal_id))
            .limit(1)
            .execute()
        )
        if not qr.data:
            return jsonify({'error': 'Quote not found'}), 404
        existing = qr.data[0]
        data = request.get_json(silent=True) or {}
        upd = {}
        now = datetime.utcnow().isoformat()
        if 'status' in data:
            st = str(data.get('status') or '').strip().lower()
            if st not in ('draft', 'sent', 'accepted', 'rejected', 'superseded'):
                return jsonify({'error': 'Invalid status'}), 400
            upd['status'] = st
        if 'quote_payload' in data:
            if str(existing.get('status') or '').lower() != 'draft':
                return jsonify({'error': 'Only draft quotes can be edited'}), 400
            qp = _safe_json(data.get('quote_payload'), {})
            if not isinstance(qp, dict):
                return jsonify({'error': 'quote_payload must be an object'}), 400
            upd['quote_payload'] = qp
        if not upd:
            return jsonify({'error': 'Nothing to update'}), 400
        upd['updated_at'] = now
        sb.table('crm_deal_quotes').update(upd).eq('id', str(quote_id)).execute()
        _crm_cache_bump()
        return jsonify({'success': True})

    @app.route('/api/crm/deals/<deal_id>/quotation/<quote_id>', methods=['GET'])
    def open_deal_quote(deal_id, quote_id):
        sb = get_supabase()
        if not sb:
            return Response('Database not configured', status=503)
        token = str(request.args.get('token') or '').strip()
        if not token:
            return Response('Missing token', status=400)
        try:
            qr = (
                sb.table('crm_deal_quotes')
                .select('id, deal_id, quote_payload, share_token')
                .eq('id', str(quote_id))
                .eq('deal_id', str(deal_id))
                .eq('share_token', token)
                .limit(1)
                .execute()
            )
            if not qr.data:
                return Response('Invalid or expired quote link', status=404)
            payload = _safe_json((qr.data[0] or {}).get('quote_payload'), {})
            deal = _safe_json(payload.get('deal'), {})
            contact = _safe_json(payload.get('contact'), {})
            inputs = _safe_json(payload.get('inputs'), {})
            plots = _safe_json(deal.get('plots'), [])
            # quote_payload is user-authored JSON served on an unauthenticated
            # page, so every value must be HTML-escaped before interpolation.
            def _q(value):
                return escape(str(value if value is not None else ''))
            plot_rows = ''.join([
                '<tr>'
                f"<td>{idx+1}</td>"
                f"<td>{_q((p or {}).get('name') or '')}</td>"
                f"<td>{_q((p or {}).get('area') or '')}</td>"
                f"<td>{_q((p or {}).get('price') or '')}</td>"
                '</tr>'
                for idx, p in enumerate(plots if isinstance(plots, list) else [])
            ]) or '<tr><td colspan="4">No plots</td></tr>'
            html = f"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Quotation</title>
<style>
body {{ font-family: Arial, sans-serif; margin: 24px; color:#111827; }}
.card {{ border:1px solid #e5e7eb; border-radius:10px; padding:16px; margin-bottom:16px; }}
table {{ width:100%; border-collapse: collapse; }}
th,td {{ border:1px solid #e5e7eb; padding:8px; text-align:left; }}
h1 {{ margin:0 0 8px; font-size:22px; }}
.muted {{ color:#6b7280; }}
</style></head><body>
<h1>Quotation</h1>
<div class="card">
<div><strong>Deal:</strong> {_q(deal.get('title') or '')}</div>
<div><strong>Project:</strong> {_q(deal.get('project_name') or '')}</div>
<div><strong>Stage:</strong> {_q(deal.get('stage') or '')}</div>
<div><strong>Amount:</strong> {_q(deal.get('amount') or '')} {_q(deal.get('currency') or '')}</div>
</div>
<div class="card">
<div><strong>Contact:</strong> {_q(contact.get('full_name') or '')}</div>
<div><strong>Email:</strong> {_q(contact.get('email') or '')}</div>
<div><strong>Phone:</strong> {_q(contact.get('phone') or '')}</div>
</div>
<div class="card">
<div class="muted">Quote Inputs</div>
<pre>{_q(json.dumps(inputs, indent=2))}</pre>
</div>
<div class="card">
<table><thead><tr><th>#</th><th>Plot</th><th>Area</th><th>Price</th></tr></thead>
<tbody>{plot_rows}</tbody></table>
</div>
</body></html>"""
            return Response(html, mimetype='text/html')
        except Exception as e:
            return Response(str(e), status=500, mimetype='text/plain')

    # ----- CRM extended endpoints -----

    @app.route('/api/crm/me', methods=['GET'])
    @require_auth
    def crm_me(user_id, role):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        profile = get_profile(sb, user_id) or {}
        has_crm = False
        is_broker = False
        is_client_member = False
        client_group_name = ''
        client_group_id = ''
        client_group_names = []
        try:
            panorama_ids = _crm_panorama_ids(sb, user_id, role)
            has_crm = len(panorama_ids) > 0
        except Exception:
            normalized = str(role or '').strip().lower()
            has_crm = normalized in ('admin', 'superadmin')
        is_client_admin = False
        try:
            member_rows = (
                sb.table('client_members')
                .select('client_id, member_role')
                .eq('user_id', user_id)
                .execute()
            )
            client_ids = []
            seen_client_ids = set()
            for row in (member_rows.data or []):
                mr = _normalize_client_member_role(row.get('member_role', ''))
                if _is_broker_member_role(mr):
                    is_broker = True
                if mr == CLIENT_MEMBER_ROLE_CLIENT_ADMIN:
                    is_client_admin = True
                if mr in (
                    CLIENT_MEMBER_ROLE_CLIENT_ADMIN,
                    CLIENT_MEMBER_ROLE_CLIENT_USER,
                    CLIENT_MEMBER_ROLE_BROKER,
                ):
                    cid = str(row.get('client_id') or '').strip()
                    if cid and cid not in seen_client_ids:
                        seen_client_ids.add(cid)
                        client_ids.append(cid)
            if client_ids:
                is_client_member = True
                clients_res = (
                    sb.table('clients')
                    .select('id, name')
                    .in_('id', client_ids)
                    .order('name')
                    .execute()
                )
                for c in (clients_res.data or []):
                    name = str(c.get('name') or '').strip()
                    if name:
                        client_group_names.append(name)
                if clients_res.data:
                    first = clients_res.data[0] or {}
                    client_group_id = str(first.get('id') or '').strip()
                    client_group_name = str(first.get('name') or '').strip()
        except Exception:
            pass
        return jsonify({
            'user_id': user_id,
            'role': role,
            'org_id': profile.get('org_id'),
            'display_name': profile.get('display_name') or profile.get('email') or '',
            'has_crm_access': has_crm,
            'is_broker': is_broker,
            'is_client_admin': is_client_admin,
            'can_manage_team': bool(is_client_admin and not is_broker),
            'is_client_member': is_client_member,
            'client_group_id': client_group_id,
            'client_group_name': client_group_name,
            'client_group_names': client_group_names,
        })

    @app.route('/api/crm/panoramas/<int:panorama_id>/markers', methods=['GET'])
    @require_auth
    def list_crm_panorama_markers(user_id, role, panorama_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        pano_ids = _crm_panorama_ids(sb, user_id, role)
        if panorama_id not in pano_ids:
            return jsonify({'error': 'Not authorized for this panorama'}), 403
        cache_key = (
            'crm_panorama_markers',
            _crm_cache_version.get('v', 1),
            str(user_id),
            str(role or ''),
            int(panorama_id),
        )
        cached = _crm_cache_get(cache_key, ttl_seconds=5)
        if cached is not None:
            return jsonify(cached)
        try:
            r = sb.table('plot_markers').select('id, plot_id, name, description, status, marker_style, marker_icon, marker_color, rotation_x, rotation_y, rotation_z, longitude, latitude, linked_panorama_id, created_at').eq('plot_id', str(panorama_id)).execute()
            rows = r.data or []
            _crm_cache_set(cache_key, rows)
            return jsonify(rows)
        except Exception as e:
            msg = str(e)
            if 'plot_markers' in msg and ('does not exist' in msg.lower() or 'relation' in msg.lower()):
                return jsonify([])
            return jsonify({'error': msg}), 500

    @app.route('/api/crm/markers/<marker_id>', methods=['PUT', 'PATCH'])
    @require_auth
    def update_crm_marker(user_id, role, marker_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        data = request.get_json(silent=True) or {}
        try:
            r = sb.table('plot_markers').select('plot_id').eq('id', str(marker_id)).limit(1).execute()
            if not r.data:
                return jsonify({'error': 'Marker not found'}), 404
            panorama_id = int(r.data[0].get('plot_id', 0))
        except Exception:
            return jsonify({'error': 'Marker not found'}), 404
        pano_ids = _crm_panorama_ids(sb, user_id, role)
        if panorama_id not in pano_ids:
            return jsonify({'error': 'Not authorized'}), 403
        allowed = {'name', 'description', 'status', 'marker_icon', 'marker_color', 'rotation_x', 'rotation_y', 'rotation_z'}
        upd = {}
        for k, v in data.items():
            if k not in allowed or v is None:
                continue
            if k in ('rotation_x', 'rotation_y', 'rotation_z'):
                try:
                    upd[k] = float(v)
                except (TypeError, ValueError):
                    return jsonify({'error': f'{k} must be a number'}), 400
            else:
                upd[k] = str(v).strip()[:500]
        if not upd:
            return jsonify({'error': 'No valid fields to update'}), 400
        try:
            sb.table('plot_markers').update(upd).eq('id', str(marker_id)).execute()
            _crm_cache_bump()
            return jsonify({'success': True})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/crm/org-users', methods=['GET'])
    @require_admin
    def list_crm_org_users(user_id, role):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        profile = get_profile(sb, user_id) or {}
        org_id = profile.get('org_id')
        if not org_id:
            return jsonify([])
        try:
            r = sb.table('profiles').select('user_id, display_name, email, role').eq('org_id', org_id).execute()
            # Only return rows that have a valid user_id — orphaned or incomplete profiles are excluded
            users = [row for row in (r.data or []) if row.get('user_id') and str(row['user_id']).strip()]
            return jsonify(users)
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/crm/crm-team-users', methods=['GET'])
    @require_auth
    def list_crm_team_users(user_id, role):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        panorama_ids = _crm_panorama_ids(sb, user_id, role)
        if not panorama_ids:
            return jsonify([])
        org_ids = _crm_org_ids_for_panoramas(sb, panorama_ids)
        if not org_ids:
            return jsonify([])
        cache_key = (
            'crm_team_users',
            _crm_cache_version.get('v', 1),
            str(user_id),
            str(role or ''),
            tuple(panorama_ids),
            tuple(sorted(str(x) for x in org_ids)),
        )
        cached = _crm_cache_get(cache_key, ttl_seconds=5)
        if cached is not None:
            return jsonify(cached)
        users_out = []
        seen = set()
        try:
            r = sb.table('profiles').select('user_id, display_name, email, role').in_('org_id', org_ids).execute()
            for row in (r.data or []):
                uid = row.get('user_id')
                if not uid or str(uid) in seen:
                    continue
                seen.add(str(uid))
                users_out.append(row)
        except Exception:
            pass
        _crm_cache_set(cache_key, users_out)
        return jsonify(users_out)

    @app.route('/api/crm/quote-templates', methods=['GET'])
    @require_auth
    def list_crm_quote_templates(user_id, role):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        panorama_ids = _crm_panorama_ids(sb, user_id, role)
        if not panorama_ids:
            return jsonify([])
        org_ids = _crm_org_ids_for_panoramas(sb, panorama_ids)
        if not org_ids:
            return jsonify([])
        cache_key = (
            'crm_quote_templates',
            _crm_cache_version.get('v', 1),
            str(user_id),
            str(role or ''),
            tuple(panorama_ids),
            tuple(sorted(str(x) for x in org_ids)),
        )
        cached = _crm_cache_get(cache_key, ttl_seconds=5)
        if cached is not None:
            return jsonify(cached)
        try:
            r = sb.table('crm_quote_templates').select(
                'id, org_id, panorama_id, name, template_payload, is_default, created_at, updated_at'
            ).in_('org_id', org_ids).execute()
            rows = []
            for row in (r.data or []):
                pid = row.get('panorama_id')
                if pid is not None and int(pid) not in panorama_ids:
                    continue
                for k in ('created_at', 'updated_at'):
                    if row.get(k):
                        row[k] = str(row[k])
                rows.append(row)
            _crm_cache_set(cache_key, rows)
            return jsonify(rows)
        except Exception as e:
            msg = str(e)
            if 'crm_quote_templates' in msg and ('does not exist' in msg.lower() or 'relation' in msg.lower()):
                return jsonify({'error': 'crm_quote_templates not found. Run db migration.'}), 503
            return jsonify({'error': msg}), 500

    @app.route('/api/crm/quote-templates', methods=['POST'])
    @require_auth
    def create_crm_quote_template(user_id, role):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        panorama_ids = _crm_panorama_ids(sb, user_id, role)
        if not panorama_ids:
            return jsonify({'error': 'Forbidden'}), 403
        data = request.get_json(silent=True) or {}
        org_id = str(data.get('org_id') or '').strip()
        if not org_id:
            return jsonify({'error': 'org_id is required'}), 400
        allowed_orgs = set(_crm_org_ids_for_panoramas(sb, panorama_ids))
        if org_id not in allowed_orgs:
            return jsonify({'error': 'Invalid org_id'}), 400
        pano_raw = data.get('panorama_id')
        panorama_id = None
        if pano_raw is not None and str(pano_raw).strip() != '':
            try:
                panorama_id = int(pano_raw)
            except Exception:
                return jsonify({'error': 'Invalid panorama_id'}), 400
            if panorama_id not in panorama_ids:
                return jsonify({'error': 'Invalid panorama_id'}), 400
        name = str(data.get('name') or 'Standard').strip() or 'Standard'
        now = datetime.utcnow().isoformat()
        row = {
            'org_id': org_id,
            'panorama_id': panorama_id,
            'name': name,
            'template_payload': _safe_json(data.get('template_payload'), {}),
            'is_default': _is_truthy(data.get('is_default')),
            'created_by': user_id,
            'created_at': now,
            'updated_at': now,
        }
        try:
            r = sb.table('crm_quote_templates').insert(row).execute()
            created = (r.data or [row])[0]
            _crm_cache_bump()
            return jsonify({'success': True, 'template': created}), 201
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/crm/quote-templates/<template_id>', methods=['PATCH'])
    @require_auth
    def update_crm_quote_template(user_id, role, template_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        panorama_ids = _crm_panorama_ids(sb, user_id, role)
        if not panorama_ids:
            return jsonify({'error': 'Forbidden'}), 403
        org_ids = set(_crm_org_ids_for_panoramas(sb, panorama_ids))
        tr = (
            sb.table('crm_quote_templates')
            .select('id, org_id, panorama_id')
            .eq('id', str(template_id))
            .limit(1)
            .execute()
        )
        if not tr.data:
            return jsonify({'error': 'Not found'}), 404
        tpl = tr.data[0]
        if str(tpl.get('org_id') or '') not in org_ids:
            return jsonify({'error': 'Forbidden'}), 403
        pid = tpl.get('panorama_id')
        if pid is not None and int(pid) not in panorama_ids:
            return jsonify({'error': 'Forbidden'}), 403
        data = request.get_json(silent=True) or {}
        upd = {}
        if 'name' in data:
            upd['name'] = str(data.get('name') or '').strip()
        if 'template_payload' in data:
            upd['template_payload'] = _safe_json(data.get('template_payload'), {})
        if 'is_default' in data:
            upd['is_default'] = _is_truthy(data.get('is_default'))
        if 'panorama_id' in data:
            pr = data.get('panorama_id')
            if pr is None or str(pr).strip() == '':
                upd['panorama_id'] = None
            else:
                try:
                    p_int = int(pr)
                except Exception:
                    return jsonify({'error': 'Invalid panorama_id'}), 400
                if p_int not in panorama_ids:
                    return jsonify({'error': 'Invalid panorama_id'}), 400
                upd['panorama_id'] = p_int
        if not upd:
            return jsonify({'error': 'Nothing to update'}), 400
        upd['updated_at'] = datetime.utcnow().isoformat()
        sb.table('crm_quote_templates').update(upd).eq('id', str(template_id)).execute()
        _crm_cache_bump()
        return jsonify({'success': True})

    @app.route('/api/crm/quote-templates/<template_id>', methods=['DELETE'])
    @require_auth
    def delete_crm_quote_template(user_id, role, template_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        panorama_ids = _crm_panorama_ids(sb, user_id, role)
        if not panorama_ids:
            return jsonify({'error': 'Forbidden'}), 403
        org_ids = set(_crm_org_ids_for_panoramas(sb, panorama_ids))
        tr = (
            sb.table('crm_quote_templates')
            .select('id, org_id, panorama_id')
            .eq('id', str(template_id))
            .limit(1)
            .execute()
        )
        if not tr.data:
            return jsonify({'error': 'Not found'}), 404
        tpl = tr.data[0]
        if str(tpl.get('org_id') or '') not in org_ids:
            return jsonify({'error': 'Forbidden'}), 403
        pid = tpl.get('panorama_id')
        if pid is not None and int(pid) not in panorama_ids:
            return jsonify({'error': 'Forbidden'}), 403
        sb.table('crm_quote_templates').delete().eq('id', str(template_id)).execute()
        _crm_cache_bump()
        return jsonify({'success': True})

    # ------------------------------------------------------------------
    # Day Night Projects
    # ------------------------------------------------------------------

    register_daynight_routes(app)

    # ==================================================================
    # Floor Plan Catalogue
    # ==================================================================

    @app.route('/salestools')
    def sales_tools_page():
        return render_template(
            'floorplans.html',
            max_gallery_read_bytes=MAX_GALLERY_READ_BYTES,
            max_upload_bytes=current_app.config.get('MAX_CONTENT_LENGTH') or 0,
            **auth_ctx()
        )

    @app.route('/floorplans')
    def floorplans_page():
        qs = request.query_string.decode('utf-8').strip() if request.query_string else ''
        if qs:
            return redirect(f'/salestools?{qs}')
        return redirect('/salestools')

    @app.route('/api/floorplans/catalogues', methods=['GET'])
    @require_admin
    def api_list_fp_catalogues(user_id, role):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        catalogues = fp_list_catalogues(sb, user_id)
        workspace_id = str(request.args.get('workspace_id') or '').strip() or None
        if workspace_id:
            catalogues = [c for c in catalogues if str(c.get('workspace_id') or '') == workspace_id]
        base = (request.url_root or '').rstrip('/')
        if catalogues:
            cat_ids = [c['id'] for c in catalogues]
            counts = fp_get_item_counts(sb, cat_ids)
            previews = fp_get_item_previews(sb, cat_ids)
            for c in catalogues:
                cid = c['id']
                c['share_url'] = f"{base}/floorplans/view/{c.get('share_token', '')}"
                c['item_count'] = counts.get(cid, 0)
                c['item_names'] = previews.get(cid, [])
        return jsonify(catalogues)

    @app.route('/api/floorplans/catalogues', methods=['POST'])
    @require_admin
    def api_create_fp_catalogue(user_id, role):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        data = request.get_json(silent=True) or {}
        name = str(data.get('name') or 'Floor Plans').strip()
        workspace_id = data.get('workspace_id') or None
        if not workspace_id:
            return jsonify({'error': 'workspace_id is required'}), 400
        if fp_name_exists(sb, user_id, workspace_id, name):
            return jsonify({'error': f'A catalogue named "{name}" already exists'}), 409
        profile = get_profile(sb, user_id)
        org_id = profile.get('org_id') if profile else None
        cat = fp_create_catalogue(sb, user_id, org_id, name, workspace_id=workspace_id)
        if not cat:
            return jsonify({'error': 'Failed to create catalogue'}), 500
        base = (request.url_root or '').rstrip('/')
        cat['share_url'] = f"{base}/floorplans/view/{cat.get('share_token', '')}"
        return jsonify(cat), 201

    @app.route('/api/floorplans/catalogues/<catalogue_id>', methods=['GET'])
    @require_admin
    def api_get_fp_catalogue(user_id, role, catalogue_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        cat = fp_get_catalogue(sb, catalogue_id)
        if not cat:
            return jsonify({'error': 'Not found'}), 404
        if str(cat.get('user_id')) != str(user_id) and role != 'superadmin':
            return jsonify({'error': 'Forbidden'}), 403
        items = fp_list_items(sb, catalogue_id)
        for item in items:
            item['image_url'] = get_floorplan_s3_url(item.get('image_filename'))
        cat['items'] = items
        base = (request.url_root or '').rstrip('/')
        cat['share_url'] = f"{base}/floorplans/view/{cat.get('share_token', '')}"
        return jsonify(cat)

    @app.route('/api/floorplans/catalogues/<catalogue_id>', methods=['PATCH'])
    @require_admin
    def api_update_fp_catalogue(user_id, role, catalogue_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        cat = fp_get_catalogue(sb, catalogue_id)
        if not cat:
            return jsonify({'error': 'Not found'}), 404
        if str(cat.get('user_id')) != str(user_id) and role != 'superadmin':
            return jsonify({'error': 'Forbidden'}), 403
        data = request.get_json(silent=True) or {}
        name = str(data.get('name') or '').strip()
        if name:
            fp_update_catalogue(sb, catalogue_id, name=name)
        updated = fp_get_catalogue(sb, catalogue_id)
        return jsonify(updated)

    @app.route('/api/floorplans/catalogues/<catalogue_id>', methods=['DELETE'])
    @require_admin
    def api_delete_fp_catalogue(user_id, role, catalogue_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        cat = fp_get_catalogue(sb, catalogue_id)
        if not cat:
            return jsonify({'error': 'Not found'}), 404
        if str(cat.get('user_id')) != str(user_id) and role != 'superadmin':
            return jsonify({'error': 'Forbidden'}), 403
        # Delete all item images from S3
        items = fp_list_items(sb, catalogue_id)
        for item in items:
            delete_floorplan_from_s3(item.get('image_filename'))
        fp_delete_catalogue(sb, catalogue_id)
        return jsonify({'success': True})

    # -- Floor Plan Items --

    @app.route('/api/floorplans/catalogues/<catalogue_id>/items', methods=['GET'])
    @require_admin
    def api_list_fp_items(user_id, role, catalogue_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        cat = fp_get_catalogue(sb, catalogue_id)
        if not cat:
            return jsonify({'error': 'Catalogue not found'}), 404
        if str(cat.get('user_id')) != str(user_id) and role != 'superadmin':
            return jsonify({'error': 'Forbidden'}), 403
        items = fp_list_items(sb, catalogue_id)
        for item in items:
            item['image_url'] = get_floorplan_s3_url(item.get('image_filename'))
        return jsonify(items)

    @app.route('/api/floorplans/catalogues/<catalogue_id>/items', methods=['POST'])
    @require_admin
    def api_upload_fp_item(user_id, role, catalogue_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        cat = fp_get_catalogue(sb, catalogue_id)
        if not cat:
            return jsonify({'error': 'Catalogue not found'}), 404
        if str(cat.get('user_id')) != str(user_id) and role != 'superadmin':
            return jsonify({'error': 'Forbidden'}), 403
        name = str(request.form.get('name') or '').strip()
        if not name:
            return jsonify({'error': 'Name is required'}), 400
        f = request.files.get('file')
        if not f:
            return jsonify({'error': 'No file uploaded'}), 400
        if not allowed_file(f.filename):
            return jsonify({'error': 'Invalid file type'}), 400
        raw_bytes = f.read()
        if not raw_bytes or len(raw_bytes) > MAX_FLOORPLAN_READ_BYTES:
            return jsonify({'error': 'File too large'}), 400
        # Convert to WebP lossless (preserves transparency)
        webp_bytes, w, h = convert_floorplan_to_webp_lossless(raw_bytes)
        if not webp_bytes:
            return jsonify({'error': 'Failed to process image'}), 400
        # Generate unique filename
        filename = f"fp_{uuid.uuid4().hex[:16]}.webp"
        upload_floorplan_to_s3(filename, webp_bytes, 'image/webp')
        sort_order = fp_next_sort_order(sb, catalogue_id)
        item = fp_create_item(
            sb, catalogue_id, name, filename,
            image_width=w, image_height=h,
            file_size_bytes=len(webp_bytes),
            sort_order=sort_order,
        )
        if not item:
            return jsonify({'error': 'Failed to create item'}), 500
        item['image_url'] = get_floorplan_s3_url(filename)
        return jsonify(item), 201

    @app.route('/api/floorplans/items/<item_id>', methods=['PATCH'])
    @require_admin
    def api_update_fp_item(user_id, role, item_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        item = fp_get_item(sb, item_id)
        if not item:
            return jsonify({'error': 'Not found'}), 404
        cat = fp_get_catalogue(sb, item['catalogue_id'])
        if not cat or (str(cat.get('user_id')) != str(user_id) and role != 'superadmin'):
            return jsonify({'error': 'Forbidden'}), 403
        data = request.get_json(silent=True) or {}
        updates = {}
        if 'name' in data:
            updates['name'] = str(data['name']).strip()
        if updates:
            fp_update_item(sb, item_id, **updates)
        updated = fp_get_item(sb, item_id)
        if updated:
            updated['image_url'] = get_floorplan_s3_url(updated.get('image_filename'))
        return jsonify(updated)

    @app.route('/api/floorplans/items/<item_id>', methods=['DELETE'])
    @require_admin
    def api_delete_fp_item(user_id, role, item_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        item = fp_get_item(sb, item_id)
        if not item:
            return jsonify({'error': 'Not found'}), 404
        cat = fp_get_catalogue(sb, item['catalogue_id'])
        if not cat or (str(cat.get('user_id')) != str(user_id) and role != 'superadmin'):
            return jsonify({'error': 'Forbidden'}), 403
        delete_floorplan_from_s3(item.get('image_filename'))
        fp_delete_item(sb, item_id)
        return jsonify({'success': True})

    @app.route('/api/floorplans/catalogues/<catalogue_id>/reorder', methods=['POST'])
    @require_admin
    def api_reorder_fp_items(user_id, role, catalogue_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        cat = fp_get_catalogue(sb, catalogue_id)
        if not cat:
            return jsonify({'error': 'Catalogue not found'}), 404
        if str(cat.get('user_id')) != str(user_id) and role != 'superadmin':
            return jsonify({'error': 'Forbidden'}), 403
        data = request.get_json(silent=True) or {}
        ordered_ids = data.get('ordered_ids', [])
        if not ordered_ids or not isinstance(ordered_ids, list):
            return jsonify({'error': 'ordered_ids must be a non-empty list'}), 400
        fp_reorder_items(sb, catalogue_id, ordered_ids)
        items = fp_list_items(sb, catalogue_id)
        for item in items:
            item['image_url'] = get_floorplan_s3_url(item.get('image_filename'))
        return jsonify(items)

    # -- Public Floor Plan View --

    @app.route('/floorplans/view/<share_token>')
    def floorplans_public_view(share_token):
        sb = get_supabase()
        if not sb:
            return "Database not configured", 503
        cat = fp_get_catalogue_by_token(sb, share_token)
        if not cat:
            return "Not found", 404
        items = fp_list_items(sb, cat['id'])
        for item in items:
            item['image_url'] = get_floorplan_s3_url(item.get('image_filename'))
        # Remove items with no image URL
        items = [it for it in items if it.get('image_url')]
        if not items:
            return "No floor plans uploaded yet", 404
        return render_template('floorplans_view.html',
                               catalogue=cat,
                               items=items,
                               workspace_name=cat.get('name', 'Floor Plans'),
                               fv_style={})

    # ==================================================================
    # Building Maps
    # ==================================================================

    @app.route('/api/building-maps', methods=['GET'])
    @require_admin
    def api_list_building_maps(user_id, role):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        maps = bm_list(sb, user_id)
        base = (request.url_root or '').rstrip('/')
        for m in maps:
            m['image_url'] = get_building_map_s3_url(m.get('image_filename'))
            m['share_url'] = f"{base}/building-map/view/{m.get('share_token', '')}"
            zones = bm_list_zones(sb, m['id'])
            m['zone_count'] = len(zones)
            m['floor_count'] = len(set(z.get('floor_number', 0) for z in zones))
            if m.get('catalogue_id'):
                cat = fp_get_catalogue(sb, m['catalogue_id'])
                m['catalogue_name'] = cat.get('name', '') if cat else ''
            else:
                m['catalogue_name'] = ''
        return jsonify(maps)

    @app.route('/api/building-maps', methods=['POST'])
    @require_admin
    def api_create_building_map(user_id, role):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        name = str(request.form.get('name') or 'Building Map').strip()
        existing = bm_list(sb, user_id)
        if any(m.get('name', '').strip().lower() == name.lower() for m in existing):
            return jsonify({'error': f'A building map named "{name}" already exists'}), 409
        catalogue_id = str(request.form.get('catalogue_id') or '').strip() or None
        workspace_id = str(request.form.get('workspace_id') or '').strip() or None
        if workspace_id:
            workspace = get_workspace_by_id(sb, workspace_id)
            if not workspace:
                return jsonify({'error': 'Project not found'}), 404
            if not can_manage_workspace(sb, workspace, user_id, role):
                return jsonify({'error': 'Forbidden'}), 403
        f = request.files.get('file')
        if not f:
            return jsonify({'error': 'No file uploaded'}), 400
        if not allowed_file(f.filename):
            return jsonify({'error': 'Invalid file type'}), 400
        raw_bytes = f.read()
        if not raw_bytes or len(raw_bytes) > MAX_BUILDING_MAP_READ_BYTES:
            return jsonify({'error': 'File too large'}), 400
        jpeg_bytes, w, h = compress_building_map_image(raw_bytes)
        if not jpeg_bytes:
            return jsonify({'error': 'Failed to process image'}), 400
        filename = f"bm_{uuid.uuid4().hex[:16]}.jpg"
        upload_building_map_to_s3(filename, jpeg_bytes, 'image/jpeg')
        profile = get_profile(sb, user_id)
        org_id = profile.get('org_id') if profile else None
        bm = bm_create(sb, user_id, org_id, name, filename, w, h, catalogue_id, workspace_id=workspace_id)
        if not bm:
            return jsonify({'error': 'Failed to create building map'}), 500
        bm['image_url'] = get_building_map_s3_url(filename)
        base = (request.url_root or '').rstrip('/')
        bm['share_url'] = f"{base}/building-map/view/{bm.get('share_token', '')}"
        return jsonify(bm), 201

    @app.route('/api/building-maps/<map_id>', methods=['GET'])
    @require_admin
    def api_get_building_map(user_id, role, map_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        bm = bm_get(sb, map_id)
        if not bm:
            return jsonify({'error': 'Not found'}), 404
        if str(bm.get('user_id')) != str(user_id) and role != 'superadmin':
            return jsonify({'error': 'Forbidden'}), 403
        bm['image_url'] = get_building_map_s3_url(bm.get('image_filename'))
        zones = bm_list_zones(sb, map_id)
        bm['zones'] = zones
        base = (request.url_root or '').rstrip('/')
        bm['share_url'] = f"{base}/building-map/view/{bm.get('share_token', '')}"
        return jsonify(bm)

    @app.route('/api/building-maps/<map_id>', methods=['PATCH'])
    @require_admin
    def api_update_building_map(user_id, role, map_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        bm = bm_get(sb, map_id)
        if not bm:
            return jsonify({'error': 'Not found'}), 404
        if str(bm.get('user_id')) != str(user_id) and role != 'superadmin':
            return jsonify({'error': 'Forbidden'}), 403
        data = request.get_json(silent=True) or {}
        updates = {}
        if 'name' in data:
            updates['name'] = str(data['name']).strip()
        if 'catalogue_id' in data:
            updates['catalogue_id'] = str(data['catalogue_id']).strip() or None
        if updates:
            bm_update(sb, map_id, **updates)
        updated = bm_get(sb, map_id)
        if updated:
            updated['image_url'] = get_building_map_s3_url(updated.get('image_filename'))
        return jsonify(updated)

    @app.route('/api/building-maps/<map_id>', methods=['DELETE'])
    @require_admin
    def api_delete_building_map(user_id, role, map_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        bm = bm_get(sb, map_id)
        if not bm:
            return jsonify({'error': 'Not found'}), 404
        if str(bm.get('user_id')) != str(user_id) and role != 'superadmin':
            return jsonify({'error': 'Forbidden'}), 403
        delete_building_map_from_s3(bm.get('image_filename'))
        bm_delete(sb, map_id)
        return jsonify({'success': True})

    # -- Building Map Images --

    @app.route('/api/building-maps/<map_id>/images', methods=['GET'])
    @require_admin
    def api_list_building_map_images(user_id, role, map_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        bm = bm_get(sb, map_id)
        if not bm:
            return jsonify({'error': 'Not found'}), 404
        if str(bm.get('user_id')) != str(user_id) and role != 'superadmin':
            return jsonify({'error': 'Forbidden'}), 403
        images = bm_list_images(sb, map_id)
        for img in images:
            img['image_url'] = get_building_map_s3_url(img.get('image_filename'))
            img['zone_count'] = len(bm_list_zones_for_image(sb, img['id']))
        return jsonify(images)

    @app.route('/api/building-maps/<map_id>/images', methods=['POST'])
    @require_admin
    def api_create_building_map_image(user_id, role, map_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        bm = bm_get(sb, map_id)
        if not bm:
            return jsonify({'error': 'Not found'}), 404
        if str(bm.get('user_id')) != str(user_id) and role != 'superadmin':
            return jsonify({'error': 'Forbidden'}), 403
        name = str(request.form.get('name') or 'View').strip()
        f = request.files.get('file')
        if not f:
            return jsonify({'error': 'No file uploaded'}), 400
        if not allowed_file(f.filename):
            return jsonify({'error': 'Invalid file type'}), 400
        raw_bytes = f.read()
        if not raw_bytes or len(raw_bytes) > MAX_BUILDING_MAP_READ_BYTES:
            return jsonify({'error': 'File too large'}), 400
        jpeg_bytes, w, h = compress_building_map_image(raw_bytes)
        if not jpeg_bytes:
            return jsonify({'error': 'Failed to process image'}), 400
        filename = f"bmi_{uuid.uuid4().hex[:16]}.jpg"
        upload_building_map_to_s3(filename, jpeg_bytes, 'image/jpeg')
        sort_order = bm_next_image_sort(sb, map_id)
        img = bm_create_image(sb, map_id, name, filename, w, h, sort_order)
        if not img:
            return jsonify({'error': 'Failed to create image'}), 500
        img['image_url'] = get_building_map_s3_url(filename)
        return jsonify(img), 201

    @app.route('/api/building-map-images/<image_id>', methods=['PATCH'])
    @require_admin
    def api_update_building_map_image(user_id, role, image_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        img = bm_get_image(sb, image_id)
        if not img:
            return jsonify({'error': 'Not found'}), 404
        bm = bm_get(sb, img['building_map_id'])
        if not bm or (str(bm.get('user_id')) != str(user_id) and role != 'superadmin'):
            return jsonify({'error': 'Forbidden'}), 403
        data = request.get_json(silent=True) or {}
        updates = {}
        if 'name' in data:
            updates['name'] = str(data['name']).strip()
        if 'sort_order' in data:
            updates['sort_order'] = int(data['sort_order'])
        if updates:
            bm_update_image(sb, image_id, **updates)
        updated = bm_get_image(sb, image_id)
        if updated:
            updated['image_url'] = get_building_map_s3_url(updated.get('image_filename'))
        return jsonify(updated)

    @app.route('/api/building-map-images/<image_id>', methods=['DELETE'])
    @require_admin
    def api_delete_building_map_image(user_id, role, image_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        img = bm_get_image(sb, image_id)
        if not img:
            return jsonify({'error': 'Not found'}), 404
        bm = bm_get(sb, img['building_map_id'])
        if not bm or (str(bm.get('user_id')) != str(user_id) and role != 'superadmin'):
            return jsonify({'error': 'Forbidden'}), 403
        delete_building_map_from_s3(img.get('image_filename'))
        bm_delete_image(sb, image_id)
        return jsonify({'success': True})

    # -- Building Zones --

    @app.route('/api/building-maps/<map_id>/zones', methods=['GET'])
    @require_admin
    def api_list_building_zones(user_id, role, map_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        bm = bm_get(sb, map_id)
        if not bm:
            return jsonify({'error': 'Not found'}), 404
        if str(bm.get('user_id')) != str(user_id) and role != 'superadmin':
            return jsonify({'error': 'Forbidden'}), 403
        zones = bm_list_zones(sb, map_id)
        return jsonify(zones)

    @app.route('/api/building-maps/<map_id>/zones', methods=['POST'])
    @require_admin
    def api_create_building_zone(user_id, role, map_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        bm = bm_get(sb, map_id)
        if not bm:
            return jsonify({'error': 'Not found'}), 404
        if str(bm.get('user_id')) != str(user_id) and role != 'superadmin':
            return jsonify({'error': 'Forbidden'}), 403
        data = request.get_json(silent=True) or {}
        name = str(data.get('name') or '').strip()
        if not name:
            return jsonify({'error': 'Name is required'}), 400
        points = data.get('points', [])
        if not isinstance(points, list) or len(points) < 3:
            return jsonify({'error': 'At least 3 points required'}), 400
        floor_number = int(data.get('floor_number', 0))
        color = str(data.get('color', 'green')).strip()
        linked_panorama_id = data.get('linked_panorama_id') or None
        linked_floor_plan_item_id = data.get('linked_floor_plan_item_id') or None
        sort_order = int(data.get('sort_order', 0))
        image_id = data.get('image_id') or None
        zone = bm_create_zone(sb, map_id, name, floor_number, points, color,
                              linked_panorama_id, linked_floor_plan_item_id, sort_order,
                              image_id=image_id)
        if not zone:
            return jsonify({'error': 'Failed to create zone'}), 500
        return jsonify(zone), 201

    @app.route('/api/building-maps/<map_id>/zones/batch', methods=['POST'])
    @require_admin
    def api_batch_create_building_zones(user_id, role, map_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        bm = bm_get(sb, map_id)
        if not bm:
            return jsonify({'error': 'Not found'}), 404
        if str(bm.get('user_id')) != str(user_id) and role != 'superadmin':
            return jsonify({'error': 'Forbidden'}), 403
        data = request.get_json(silent=True) or {}
        zones_data = data.get('zones', [])
        if not isinstance(zones_data, list) or not zones_data:
            return jsonify({'error': 'zones must be a non-empty list'}), 400
        for z in zones_data:
            if not isinstance(z.get('points', []), list) or len(z.get('points', [])) < 3:
                return jsonify({'error': 'Each zone needs at least 3 points'}), 400
        created = bm_batch_create_zones(sb, map_id, zones_data)
        return jsonify(created), 201

    @app.route('/api/building-zones/<int:zone_id>', methods=['PUT'])
    @require_admin
    def api_update_building_zone(user_id, role, zone_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        zone = bm_get_zone(sb, zone_id)
        if not zone:
            return jsonify({'error': 'Not found'}), 404
        bm = bm_get(sb, zone['building_map_id'])
        if not bm or (str(bm.get('user_id')) != str(user_id) and role != 'superadmin'):
            return jsonify({'error': 'Forbidden'}), 403
        data = request.get_json(silent=True) or {}
        updates = {}
        for k in ('name', 'floor_number', 'color', 'sort_order', 'points',
                   'linked_panorama_id', 'linked_floor_plan_item_id', 'image_id'):
            if k in data:
                updates[k] = data[k]
        if updates:
            bm_update_zone(sb, zone_id, **updates)
        updated = bm_get_zone(sb, zone_id)
        return jsonify(updated)

    @app.route('/api/building-zones/<int:zone_id>', methods=['DELETE'])
    @require_admin
    def api_delete_building_zone(user_id, role, zone_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        zone = bm_get_zone(sb, zone_id)
        if not zone:
            return jsonify({'error': 'Not found'}), 404
        bm = bm_get(sb, zone['building_map_id'])
        if not bm or (str(bm.get('user_id')) != str(user_id) and role != 'superadmin'):
            return jsonify({'error': 'Forbidden'}), 403
        bm_delete_zone(sb, zone_id)
        return jsonify({'success': True})

    # -- Building Map pages --

    @app.route('/building-map/admin/<map_id>')
    def building_map_admin_page(map_id):
        return render_template('building_map_admin.html', map_id=map_id, **auth_ctx())

    @app.route('/building-map/view/<share_token>')
    def building_map_public_view(share_token):
        sb = get_supabase()
        if not sb:
            return "Database not configured", 503
        bm = bm_get_by_token(sb, share_token)
        if not bm:
            return "Not found", 404
        # Collect images for this building map
        images = bm_list_images(sb, bm['id'])
        for img in images:
            img['image_url'] = get_building_map_s3_url(img.get('image_filename'))
        # Fallback: if no images table entries, use the building map's own image
        if not images:
            images = [{
                'id': None,
                'name': bm.get('name', 'View'),
                'image_url': get_building_map_s3_url(bm.get('image_filename')),
                'image_width': bm.get('image_width', 0),
                'image_height': bm.get('image_height', 0),
            }]
        zones = bm_list_zones(sb, bm['id'])
        # Enrich zones with linked floor plan image URLs
        for z in zones:
            if z.get('linked_floor_plan_item_id'):
                fp_item = fp_get_item(sb, z['linked_floor_plan_item_id'])
                if fp_item:
                    z['linked_floor_plan_image_url'] = get_floorplan_s3_url(fp_item.get('image_filename'))
                    z['linked_floor_plan_name'] = fp_item.get('name', '')
        # Get all building maps for this user to allow switching
        all_maps = bm_list(sb, bm['user_id'])
        siblings = []
        for m in all_maps:
            siblings.append({
                'id': m['id'],
                'name': m['name'],
                'share_token': m.get('share_token', ''),
                'active': m['id'] == bm['id'],
            })
        return render_template('building_map_view.html',
                               bm=bm,
                               images=images,
                               image_url=images[0]['image_url'] if images else '',
                               zones=zones,
                               siblings=siblings)

    # -- Public API for building map data (used by customer view JS) --

    @app.route('/api/public/building-map/<share_token>')
    def api_public_building_map(share_token):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        bm = bm_get_by_token(sb, share_token)
        if not bm:
            return jsonify({'error': 'Not found'}), 404
        bm['image_url'] = get_building_map_s3_url(bm.get('image_filename'))
        zones = bm_list_zones(sb, bm['id'])
        for z in zones:
            if z.get('linked_floor_plan_item_id'):
                fp_item = fp_get_item(sb, z['linked_floor_plan_item_id'])
                if fp_item:
                    z['linked_floor_plan_image_url'] = get_floorplan_s3_url(fp_item.get('image_filename'))
                    z['linked_floor_plan_name'] = fp_item.get('name', '')
        bm['zones'] = zones
        return jsonify(bm)

    # ==================================================================
    # Sales Route Maps
    # ==================================================================

    register_sales_route_map_routes(app)

    # ==================================================================
    # Sales Flat 360 Views
    # ==================================================================

    def _resolve_sales_flat360_for_admin(sb, view_id, user_id, role):
        view = sf360_get(sb, view_id)
        if not view:
            return None, (jsonify({'error': 'Not found'}), 404)
        if str(view.get('user_id')) != str(user_id) and role != 'superadmin':
            return None, (jsonify({'error': 'Forbidden'}), 403)
        return view, None

    @app.route('/sales-flat360')
    def sales_flat360_page():
        return redirect('/salestools?tab=flat360')

    @app.route('/sales-flat360/editor/<view_id>')
    def sales_flat360_editor_page(view_id):
        return render_template('sales_flat360_editor.html', view_id=view_id, **auth_ctx())

    @app.route('/api/sales-flat360', methods=['GET'])
    @require_admin
    def api_list_sales_flat360(user_id, role):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        workspace_id = str(request.args.get('workspace_id') or '').strip() or None
        views = sf360_list(sb, user_id, workspace_id=workspace_id)
        base = (request.url_root or '').rstrip('/')
        for item in views:
            item['image_url'] = get_sales_flat360_s3_url(item.get('image_filename'))
            item['share_url'] = f"{base}/sales-flat360/view/{item.get('share_token', '')}"
        return jsonify(views)

    @app.route('/api/sales-flat360', methods=['POST'])
    @require_admin
    def api_create_sales_flat360(user_id, role):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        name = str(request.form.get('name') or 'Sales 360 View').strip() or 'Sales 360 View'
        workspace_id = str(request.form.get('workspace_id') or '').strip() or None
        if workspace_id:
            workspace = get_workspace_by_id(sb, workspace_id)
            if not workspace:
                return jsonify({'error': 'Project not found'}), 404
            if not can_manage_workspace(sb, workspace, user_id, role):
                return jsonify({'error': 'Forbidden'}), 403
        existing = sf360_list(sb, user_id)
        if any(v.get('name', '').strip().lower() == name.lower() for v in existing):
            return jsonify({'error': f'A 360 view named "{name}" already exists'}), 409
        file_obj = request.files.get('file')
        if not file_obj:
            return jsonify({'error': 'No file uploaded'}), 400
        if not allowed_file(file_obj.filename):
            return jsonify({'error': 'Invalid file type'}), 400
        raw_bytes = file_obj.read()
        if not raw_bytes or len(raw_bytes) > MAX_SALES_FLAT360_READ_BYTES:
            return jsonify({'error': 'File too large'}), 400
        jpeg_bytes, width, height = compress_sales_flat360_image(raw_bytes)
        if not jpeg_bytes:
            return jsonify({'error': 'Failed to process image'}), 400
        filename = f"sf360_{uuid.uuid4().hex[:16]}.jpg"
        upload_sales_flat360_to_s3(filename, jpeg_bytes, 'image/jpeg')
        profile = get_profile(sb, user_id)
        org_id = profile.get('org_id') if profile else None
        created = sf360_create(
            sb,
            user_id,
            org_id,
            name,
            filename,
            width,
            height,
            workspace_id=workspace_id,
        )
        if not created:
            return jsonify({'error': 'Failed to create 360 view'}), 500
        base = (request.url_root or '').rstrip('/')
        created['image_url'] = get_sales_flat360_s3_url(created.get('image_filename'))
        created['share_url'] = f"{base}/sales-flat360/view/{created.get('share_token', '')}"
        return jsonify(created), 201

    @app.route('/api/sales-flat360/<view_id>', methods=['GET'])
    @require_admin
    def api_get_sales_flat360(user_id, role, view_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        view, err = _resolve_sales_flat360_for_admin(sb, view_id, user_id, role)
        if err:
            return err
        base = (request.url_root or '').rstrip('/')
        view['image_url'] = get_sales_flat360_s3_url(view.get('image_filename'))
        view['share_url'] = f"{base}/sales-flat360/view/{view.get('share_token', '')}"
        return jsonify(view)

    @app.route('/api/sales-flat360/<view_id>', methods=['PATCH'])
    @require_admin
    def api_update_sales_flat360(user_id, role, view_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        item, err = _resolve_sales_flat360_for_admin(sb, view_id, user_id, role)
        if err:
            return err
        data = request.get_json(silent=True) or {}
        updates = {}
        if 'name' in data:
            updates['name'] = str(data.get('name') or '').strip() or item.get('name')
        if 'workspace_id' in data:
            workspace_id = str(data.get('workspace_id') or '').strip() or None
            if workspace_id:
                workspace = get_workspace_by_id(sb, workspace_id)
                if not workspace:
                    return jsonify({'error': 'Project not found'}), 404
                if not can_manage_workspace(sb, workspace, user_id, role):
                    return jsonify({'error': 'Forbidden'}), 403
            updates['workspace_id'] = workspace_id
        if updates:
            updated = sf360_update(sb, view_id, **updates)
        else:
            updated = sf360_get(sb, view_id)
        if not updated:
            return jsonify({'error': 'Not found'}), 404
        base = (request.url_root or '').rstrip('/')
        updated['image_url'] = get_sales_flat360_s3_url(updated.get('image_filename'))
        updated['share_url'] = f"{base}/sales-flat360/view/{updated.get('share_token', '')}"
        return jsonify(updated)

    @app.route('/api/sales-flat360/<view_id>', methods=['DELETE'])
    @require_admin
    def api_delete_sales_flat360(user_id, role, view_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        view, err = _resolve_sales_flat360_for_admin(sb, view_id, user_id, role)
        if err:
            return err
        delete_sales_flat360_from_s3(view.get('image_filename'))
        sf360_delete(sb, view_id)
        return jsonify({'success': True})

    @app.route('/sales-flat360/view/<share_token>')
    def sales_flat360_public_view(share_token):
        sb = get_supabase()
        if not sb:
            return "Database not configured", 503
        view = sf360_get_by_token(sb, share_token)
        if not view:
            return "Not found", 404
        view['image_url'] = get_sales_flat360_s3_url(view.get('image_filename'))
        return render_template(
            'sales_flat360_view.html',
            flat360_view=view,
            embed=(request.args.get('embed', '') == '1'),
        )

    @app.route('/customer/full-view/sales-flat360/<view_id>')
    def fv_customer_sales_flat360_view(view_id):
        sb = get_supabase()
        if not sb:
            return "Database not configured", 503
        view = sf360_get(sb, view_id)
        if not view:
            return "Not found", 404
        view['image_url'] = get_sales_flat360_s3_url(view.get('image_filename'))
        return render_template(
            'sales_flat360_view.html',
            flat360_view=view,
            embed=True,
        )

    # ===================================================================
    # EARTH VIEWS
    # ===================================================================

    @app.route('/api/earth-views', methods=['GET'])
    @require_admin
    def api_list_earth_views(user_id, role):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        workspace_id = str(request.args.get('workspace_id') or '').strip() or None
        views = ev_list(sb, user_id, workspace_id=workspace_id)
        base = (request.url_root or '').rstrip('/')
        for view in views:
            view['share_url'] = f"{base}/earth-view/view/{view.get('share_token', '')}"
            view['plot_count'] = len(ev_list_plots(sb, view['id']))
            view['marker_count'] = len(ev_list_markers(sb, view['id']))
        return jsonify(views)

    @app.route('/api/earth-views', methods=['POST'])
    @require_admin
    def api_create_earth_view(user_id, role):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        data = request.get_json(silent=True) or {}
        name = str(data.get('name') or 'Earth View').strip() or 'Earth View'
        workspace_id = str(data.get('workspace_id') or '').strip() or None
        if workspace_id:
            workspace = get_workspace_by_id(sb, workspace_id)
            if not workspace:
                return jsonify({'error': 'Project not found'}), 404
            if not can_manage_workspace(sb, workspace, user_id, role):
                return jsonify({'error': 'Forbidden'}), 403
        existing = ev_list(sb, user_id, workspace_id=workspace_id)
        if any(v.get('name', '').strip().lower() == name.lower() for v in existing):
            return jsonify({'error': f'An earth view named "{name}" already exists'}), 409
        center_lng = data.get('center_lng', 0)
        center_lat = data.get('center_lat', 20)
        zoom = data.get('zoom', 3)
        profile = get_profile(sb, user_id)
        org_id = profile.get('org_id') if profile else None
        view = ev_create(sb, user_id, org_id, name, center_lng, center_lat, zoom, workspace_id=workspace_id)
        if not view:
            return jsonify({'error': 'Failed to create earth view'}), 500
        base = (request.url_root or '').rstrip('/')
        view['share_url'] = f"{base}/earth-view/view/{view.get('share_token', '')}"
        return jsonify(view), 201

    @app.route('/api/earth-views/<view_id>', methods=['GET'])
    @require_admin
    def api_get_earth_view(user_id, role, view_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        view = ev_get(sb, view_id)
        if not view:
            return jsonify({'error': 'Not found'}), 404
        if str(view.get('user_id')) != str(user_id) and role != 'superadmin':
            return jsonify({'error': 'Forbidden'}), 403
        view['plots'] = ev_list_plots(sb, view_id)
        view['markers'] = ev_list_markers(sb, view_id)
        base = (request.url_root or '').rstrip('/')
        view['share_url'] = f"{base}/earth-view/view/{view.get('share_token', '')}"
        return jsonify(view)

    @app.route('/api/earth-views/<view_id>', methods=['PATCH'])
    @require_admin
    def api_update_earth_view(user_id, role, view_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        view = ev_get(sb, view_id)
        if not view:
            return jsonify({'error': 'Not found'}), 404
        if str(view.get('user_id')) != str(user_id) and role != 'superadmin':
            return jsonify({'error': 'Forbidden'}), 403
        data = request.get_json(silent=True) or {}
        updates = {}
        for key in ('name', 'center_lng', 'center_lat', 'zoom'):
            if key in data:
                updates[key] = data[key]
        if updates:
            ev_update(sb, view_id, **updates)
        updated = ev_get(sb, view_id)
        return jsonify(updated)

    @app.route('/api/earth-views/<view_id>', methods=['DELETE'])
    @require_admin
    def api_delete_earth_view(user_id, role, view_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        view = ev_get(sb, view_id)
        if not view:
            return jsonify({'error': 'Not found'}), 404
        if str(view.get('user_id')) != str(user_id) and role != 'superadmin':
            return jsonify({'error': 'Forbidden'}), 403
        ev_delete(sb, view_id)
        return jsonify({'success': True})

    @app.route('/api/earth-views/<view_id>/plots', methods=['GET'])
    @require_admin
    def api_list_earth_view_plots(user_id, role, view_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        view = ev_get(sb, view_id)
        if not view:
            return jsonify({'error': 'Not found'}), 404
        if str(view.get('user_id')) != str(user_id) and role != 'superadmin':
            return jsonify({'error': 'Forbidden'}), 403
        return jsonify(ev_list_plots(sb, view_id))

    @app.route('/api/earth-views/<view_id>/plots', methods=['POST'])
    @require_admin
    def api_create_earth_view_plot(user_id, role, view_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        view = ev_get(sb, view_id)
        if not view:
            return jsonify({'error': 'Not found'}), 404
        if str(view.get('user_id')) != str(user_id) and role != 'superadmin':
            return jsonify({'error': 'Forbidden'}), 403
        data = request.get_json(silent=True) or {}
        name = str(data.get('name') or '').strip()
        if not name:
            return jsonify({'error': 'Name is required'}), 400
        points = data.get('points', [])
        if not isinstance(points, list) or len(points) < 3:
            return jsonify({'error': 'At least 3 points required'}), 400
        plot = ev_create_plot(
            sb,
            view_id,
            name,
            points,
            area=str(data.get('area') or '').strip(),
            price=str(data.get('price') or '').strip(),
            status=str(data.get('status') or 'available').strip(),
            description=str(data.get('description') or '').strip(),
            color=str(data.get('color') or 'green').strip(),
            media_photo=str(data.get('media_photo') or '').strip(),
            media_video=str(data.get('media_video') or '').strip(),
            linked_panorama_id=data.get('linked_panorama_id') or None,
            sort_order=int(data.get('sort_order') or 0),
        )
        if not plot:
            return jsonify({'error': 'Failed to create plot'}), 500
        return jsonify(plot), 201

    @app.route('/api/earth-view-plots/<int:plot_id>', methods=['PUT'])
    @require_admin
    def api_update_earth_view_plot(user_id, role, plot_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        plot = ev_get_plot(sb, plot_id)
        if not plot:
            return jsonify({'error': 'Not found'}), 404
        view = ev_get(sb, plot.get('earth_view_id'))
        if not view or (str(view.get('user_id')) != str(user_id) and role != 'superadmin'):
            return jsonify({'error': 'Forbidden'}), 403
        data = request.get_json(silent=True) or {}
        updates = {}
        for key in ('name', 'area', 'price', 'status', 'description', 'color', 'media_photo',
                    'media_video', 'points', 'linked_panorama_id', 'sort_order'):
            if key in data:
                updates[key] = data[key]
        if updates:
            ev_update_plot(sb, plot_id, **updates)
        updated = ev_get_plot(sb, plot_id)
        return jsonify(updated)

    @app.route('/api/earth-view-plots/<int:plot_id>', methods=['DELETE'])
    @require_admin
    def api_delete_earth_view_plot(user_id, role, plot_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        plot = ev_get_plot(sb, plot_id)
        if not plot:
            return jsonify({'error': 'Not found'}), 404
        view = ev_get(sb, plot.get('earth_view_id'))
        if not view or (str(view.get('user_id')) != str(user_id) and role != 'superadmin'):
            return jsonify({'error': 'Forbidden'}), 403
        ev_delete_plot(sb, plot_id)
        return jsonify({'success': True})

    @app.route('/api/earth-views/<view_id>/markers', methods=['GET'])
    @require_admin
    def api_list_earth_view_markers(user_id, role, view_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        view = ev_get(sb, view_id)
        if not view:
            return jsonify({'error': 'Not found'}), 404
        if str(view.get('user_id')) != str(user_id) and role != 'superadmin':
            return jsonify({'error': 'Forbidden'}), 403
        return jsonify(ev_list_markers(sb, view_id))

    @app.route('/api/earth-views/<view_id>/markers', methods=['POST'])
    @require_admin
    def api_create_earth_view_marker(user_id, role, view_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        view = ev_get(sb, view_id)
        if not view:
            return jsonify({'error': 'Not found'}), 404
        if str(view.get('user_id')) != str(user_id) and role != 'superadmin':
            return jsonify({'error': 'Forbidden'}), 403
        data = request.get_json(silent=True) or {}
        name = str(data.get('name') or '').strip()
        if not name:
            return jsonify({'error': 'Name is required'}), 400
        if data.get('longitude') is None or data.get('latitude') is None:
            return jsonify({'error': 'longitude and latitude are required'}), 400
        marker = ev_create_marker(
            sb,
            view_id,
            name,
            data.get('longitude'),
            data.get('latitude'),
            description=str(data.get('description') or '').strip(),
            marker_color=str(data.get('marker_color') or '#4ade80').strip(),
            linked_panorama_id=data.get('linked_panorama_id') or None,
            media_photo=str(data.get('media_photo') or '').strip(),
            media_video=str(data.get('media_video') or '').strip(),
        )
        if not marker:
            return jsonify({'error': 'Failed to create marker'}), 500
        return jsonify(marker), 201

    @app.route('/api/earth-view-markers/<marker_id>', methods=['PUT'])
    @require_admin
    def api_update_earth_view_marker(user_id, role, marker_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        marker = ev_get_marker(sb, marker_id)
        if not marker:
            return jsonify({'error': 'Not found'}), 404
        view = ev_get(sb, marker.get('earth_view_id'))
        if not view or (str(view.get('user_id')) != str(user_id) and role != 'superadmin'):
            return jsonify({'error': 'Forbidden'}), 403
        data = request.get_json(silent=True) or {}
        updates = {}
        for key in ('name', 'description', 'marker_color', 'linked_panorama_id', 'media_photo',
                    'media_video', 'longitude', 'latitude'):
            if key in data:
                updates[key] = data[key]
        if updates:
            ev_update_marker(sb, marker_id, **updates)
        updated = ev_get_marker(sb, marker_id)
        return jsonify(updated)

    @app.route('/api/earth-view-markers/<marker_id>', methods=['DELETE'])
    @require_admin
    def api_delete_earth_view_marker(user_id, role, marker_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        marker = ev_get_marker(sb, marker_id)
        if not marker:
            return jsonify({'error': 'Not found'}), 404
        view = ev_get(sb, marker.get('earth_view_id'))
        if not view or (str(view.get('user_id')) != str(user_id) and role != 'superadmin'):
            return jsonify({'error': 'Forbidden'}), 403
        ev_delete_marker(sb, marker_id)
        return jsonify({'success': True})

    @app.route('/earth-view/admin/<view_id>')
    def earth_view_admin_page(view_id):
        return render_template('earth_view_admin.html', view_id=view_id, **auth_ctx())

    @app.route('/earth-view/view/<share_token>')
    def earth_view_public_view(share_token):
        sb = get_supabase()
        if not sb:
            return "Database not configured", 503
        view = ev_get_by_token(sb, share_token)
        if not view:
            return "Not found", 404
        plots = ev_list_plots(sb, view['id'])
        markers = ev_list_markers(sb, view['id'])
        all_views = ev_list(sb, view['user_id'])
        siblings = []
        for ev in all_views:
            siblings.append({
                'id': ev['id'],
                'name': ev.get('name', ''),
                'share_token': ev.get('share_token', ''),
                'active': ev['id'] == view['id'],
            })
        return render_template(
            'earth_view_customer.html',
            earth_view=view,
            plots=plots,
            markers=markers,
            siblings=siblings,
        )

    @app.route('/api/public/earth-view/<share_token>')
    def api_public_earth_view(share_token):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        view = ev_get_by_token(sb, share_token)
        if not view:
            return jsonify({'error': 'Not found'}), 404
        view['plots'] = ev_list_plots(sb, view['id'])
        view['markers'] = ev_list_markers(sb, view['id'])
        return jsonify(view)

    # ===================================================================
    # PROJECT PLANS
    # ===================================================================

    @app.route('/api/project-plans', methods=['GET'])
    @require_auth
    def api_list_project_plans(user_id, role):
        sb = get_supabase()
        plans = pp_list(sb, user_id)
        workspace_id = str(request.args.get('workspace_id') or '').strip() or None
        if workspace_id:
            plans = [p for p in plans if str(p.get('workspace_id') or '') == workspace_id]
        base = (request.url_root or '').rstrip('/')
        for p in plans:
            maps = pp_list_maps(sb, p['id'])
            p['map_count'] = len(maps)
            map_names = []
            total_zones = 0
            total_floors = 0
            for link in maps:
                bm = bm_get(sb, link.get('building_map_id'))
                if bm:
                    map_names.append(bm.get('name', ''))
                    zones = bm_list_zones(sb, bm['id'])
                    total_zones += len(zones)
                    total_floors += len(set(z.get('floor_number', 0) for z in zones))
            p['map_names'] = map_names
            p['total_zones'] = total_zones
            p['total_floors'] = total_floors
            p['share_url'] = f"{base}/project-plan/view/{p.get('share_token', '')}"
        return jsonify(plans)

    @app.route('/api/project-plans', methods=['POST'])
    @require_auth
    def api_create_project_plan(user_id, role):
        sb = get_supabase()
        data = request.get_json(force=True)
        name = data.get('name', 'Project Plan').strip() or 'Project Plan'
        existing = pp_list(sb, user_id)
        if any(p.get('name', '').strip().lower() == name.lower() for p in existing):
            return jsonify({'error': f'A project plan named "{name}" already exists'}), 409
        org_id = data.get('org_id')
        workspace_id = str(data.get('workspace_id') or '').strip() or None
        if workspace_id:
            workspace = get_workspace_by_id(sb, workspace_id)
            if not workspace:
                return jsonify({'error': 'Project not found'}), 404
            if not can_manage_workspace(sb, workspace, user_id, role):
                return jsonify({'error': 'Forbidden'}), 403
        plan = pp_create(sb, user_id, org_id, name, workspace_id=workspace_id)
        if not plan:
            return jsonify({'error': 'Failed to create project plan'}), 500
        plan['share_url'] = request.host_url.rstrip('/') + '/project-plan/view/' + plan.get('share_token', '')
        return jsonify(plan), 201

    @app.route('/api/project-plans/<plan_id>', methods=['GET'])
    @require_auth
    def api_get_project_plan(user_id, role, plan_id):
        sb = get_supabase()
        plan = pp_get(sb, plan_id)
        if not plan:
            return jsonify({'error': 'Not found'}), 404
        plan['maps'] = pp_list_maps(sb, plan_id)
        # Enrich maps with building map details
        for link in plan['maps']:
            bm = bm_get(sb, link['building_map_id'])
            if bm:
                link['building_map_name'] = bm.get('name', '')
                link['building_map_image_url'] = get_building_map_s3_url(bm.get('image_filename'))
                link['building_map_share_token'] = bm.get('share_token', '')
        plan['share_url'] = request.host_url.rstrip('/') + '/project-plan/view/' + plan.get('share_token', '')
        return jsonify(plan)

    @app.route('/api/project-plans/<plan_id>', methods=['PATCH'])
    @require_auth
    def api_update_project_plan(user_id, role, plan_id):
        sb = get_supabase()
        data = request.get_json(force=True)
        updated = pp_update(sb, plan_id, **data)
        if not updated:
            return jsonify({'error': 'Not found or no valid fields'}), 404
        return jsonify(updated)

    @app.route('/api/project-plans/<plan_id>', methods=['DELETE'])
    @require_auth
    def api_delete_project_plan(user_id, role, plan_id):
        sb = get_supabase()
        deleted = pp_delete(sb, plan_id)
        if not deleted:
            return jsonify({'error': 'Not found'}), 404
        return jsonify({'ok': True})

    # -- Plan ↔ Map linking --

    @app.route('/api/project-plans/<plan_id>/maps', methods=['GET'])
    @require_auth
    def api_list_plan_maps(user_id, role, plan_id):
        sb = get_supabase()
        maps = pp_list_maps(sb, plan_id)
        for link in maps:
            bm = bm_get(sb, link['building_map_id'])
            if bm:
                link['building_map_name'] = bm.get('name', '')
                link['building_map_image_url'] = get_building_map_s3_url(bm.get('image_filename'))
                link['building_map_share_token'] = bm.get('share_token', '')
        return jsonify(maps)

    @app.route('/api/project-plans/<plan_id>/maps', methods=['POST'])
    @require_auth
    def api_add_map_to_plan(user_id, role, plan_id):
        sb = get_supabase()
        data = request.get_json(force=True)
        building_map_id = data.get('building_map_id')
        if not building_map_id:
            return jsonify({'error': 'building_map_id required'}), 400
        sort_order = pp_next_sort(sb, plan_id)
        link = pp_add_map(sb, plan_id, building_map_id, sort_order)
        if not link:
            return jsonify({'error': 'Failed to add map'}), 500
        return jsonify(link), 201

    @app.route('/api/project-plans/<plan_id>/maps/<building_map_id>', methods=['DELETE'])
    @require_auth
    def api_remove_map_from_plan(user_id, role, plan_id, building_map_id):
        sb = get_supabase()
        pp_remove_map(sb, plan_id, building_map_id)
        return jsonify({'ok': True})

    @app.route('/api/project-plans/<plan_id>/maps/reorder', methods=['POST'])
    @require_auth
    def api_reorder_plan_maps(user_id, role, plan_id):
        sb = get_supabase()
        data = request.get_json(force=True)
        ordered_ids = data.get('ordered_map_ids', [])
        result = pp_reorder(sb, plan_id, ordered_ids)
        return jsonify(result)

    # -- Public Project Plan view --

    @app.route('/project-plan/view/<share_token>')
    def project_plan_public_view(share_token):
        sb = get_supabase()
        if not sb:
            return "Database not configured", 503
        plan = pp_get_by_token(sb, share_token)
        if not plan:
            return "Not found", 404
        links = pp_list_maps(sb, plan['id'])
        buildings = []
        for link in links:
            bm = bm_get(sb, link['building_map_id'])
            if not bm:
                continue
            bm['image_url'] = get_building_map_s3_url(bm.get('image_filename'))
            bm_zones = bm_list_zones(sb, bm['id'])
            for z in bm_zones:
                if z.get('linked_floor_plan_item_id'):
                    fp_item = fp_get_item(sb, z['linked_floor_plan_item_id'])
                    if fp_item:
                        z['linked_floor_plan_image_url'] = get_floorplan_s3_url(fp_item.get('image_filename'))
                        z['linked_floor_plan_name'] = fp_item.get('name', '')
            bm['zones'] = bm_zones
            buildings.append(bm)
        fv_style = {}
        workspace_id = str((plan or {}).get('workspace_id') or '').strip()
        if workspace_id:
            fv_cfg = fv_get_config(sb, workspace_id)
            if fv_cfg and isinstance(fv_cfg.get('style'), dict):
                fv_style = fv_cfg.get('style')
        return render_template('project_plan_view.html',
                               plan=plan,
                               buildings=buildings,
                               fv_style=fv_style)

    # ==================================================================
    # Galleries
    # ==================================================================
    register_asset_routes(app)
    register_gallery_routes(app)

    # ==================================================================
    # Page Access Tokens
    # ==================================================================
    register_page_access_routes(app)

    # ==================================================================
    # Shared Filter Resource Lists
    # ==================================================================
    register_resource_filters_routes(app)

    # ==================================================================
    # User Access Management
    # ==================================================================
    register_uam_routes(app)

    # ==================================================================
    # Full View Creator
    # ==================================================================

    register_full_view_routes(app)
