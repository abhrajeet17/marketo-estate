import os
import uuid
from urllib.parse import urlsplit

from flask import current_app, jsonify, make_response, render_template, request
from werkzeug.utils import secure_filename

from app.core.auth import get_profile, require_admin
from app.core.database import get_supabase
from app.services.building_map_service import get_building_map as bm_get, list_zones as bm_list_zones
from app.services.daynight_service import get_daynight_project as dn_get
from app.services.floorplan_service import (
    get_catalogue as fp_get_catalogue,
    get_item as fp_get_item,
    list_items as fp_list_items,
)
from app.services.full_view_service import (
    create_config as fv_create_config,
    create_tab as fv_create_tab,
    delete_tab as fv_delete_tab,
    get_config_for_workspace as fv_get_config,
    get_config_with_tabs as fv_get_config_with_tabs,
    list_tabs as fv_list_tabs,
    reorder_tabs as fv_reorder_tabs,
    update_config as fv_update_config,
    update_tab as fv_update_tab,
)
from app.services.gallery_service import get_gallery as gal_get, list_items as gal_list_items
from app.services.project_plan_service import get_project_plan as pp_get, list_plan_maps as pp_list_maps
from app.services.sales_route_map_service import get_sales_map as srm_get
from app.services.storage_service import (
    get_building_map_s3_url,
    get_daynight_s3_url,
    get_floorplan_s3_url,
    get_gallery_s3_url,
    probe_image_dimensions,
    read_uploaded_file_bytes,
    upload_panorama_to_s3,
    use_s3,
)
from app.services.workspace_service import get_workspace_by_id, get_workspace_id_by_share_endpoint

from .shared import auth_ctx, is_truthy, json_payload


def _normalize_embedded_link_url(raw_url):
    url = str(raw_url or '').strip()
    if not url:
        raise ValueError('URL is required')
    if url.startswith('//'):
        url = 'https:' + url
    elif url.startswith('/'):
        return url
    elif not urlsplit(url).scheme:
        url = 'https://' + url

    parsed = urlsplit(url)
    if parsed.scheme.lower() not in {'http', 'https'} or not parsed.netloc:
        raise ValueError('URL must use http:// or https://')
    return url


def _normalize_link_tab_payload(data):
    payload = dict(data or {})
    if str(payload.get('tab_type') or '').strip().lower() != 'link':
        return payload

    content_data = payload.get('content_data')
    if not isinstance(content_data, dict):
        raise ValueError('content_data must be a JSON object')
    normalized_content = dict(content_data)
    normalized_content['url'] = _normalize_embedded_link_url(content_data.get('url'))
    payload['content_data'] = normalized_content
    return payload


def _render_fv_customer_shell(
    workspace_id,
    *,
    shell_base_path=None,
    is_editor=False,
    editor_preview_mode='',
    extra_template_ctx=None,
):
    sb = get_supabase()
    if not sb:
        return "Database not configured", 503
    ws = get_workspace_by_id(sb, workspace_id)
    if not ws:
        return "Project not found", 404
    fv_config = fv_get_config_with_tabs(sb, workspace_id) if not is_editor else None
    if is_editor:
        config = fv_get_config(sb, workspace_id)
        tabs = fv_list_tabs(sb, config['id']) if config else []
        fv_config = dict(config or {})
        fv_config['tabs'] = tabs
    init_type = request.args.get('type', '').strip() or None
    init_ref = request.args.get('ref', '').strip() or None
    fv_style = {}
    if fv_config and isinstance(fv_config.get('style'), dict):
        fv_style = fv_config.get('style')
    if not shell_base_path and not is_editor:
        shell_base_path = f"/customer/full-view/{workspace_id}"
    elif not shell_base_path and is_editor:
        shell_base_path = f"/customer/full-view/edit/{workspace_id}"
    template_ctx = {
        'workspace_id': workspace_id,
        'workspace_name': ws.get('name', ''),
        'fv_config': fv_config,
        'fv_style': fv_style,
        'is_editor': is_editor,
        'editor_preview_mode': editor_preview_mode,
        'init_type': init_type,
        'init_ref': init_ref,
        'shell_base_path': shell_base_path,
    }
    if is_editor:
        template_ctx.update(auth_ctx())
    if extra_template_ctx:
        template_ctx.update(extra_template_ctx)
    return render_template('customer_fullview.html', **template_ctx)


def register_full_view_routes(app):
    @app.route('/full-view')
    def full_view_page():
        return render_template('full_view_admin.html', **auth_ctx())

    @app.route('/api/full-view/config', methods=['GET'])
    @require_admin
    def api_fv_get_config(user_id, role):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        workspace_id = request.args.get('workspace_id', '').strip()
        autocreate = is_truthy(request.args.get('autocreate'))
        if not workspace_id:
            return jsonify({'error': 'workspace_id is required'}), 400
        config = fv_get_config(sb, workspace_id)
        if not config and autocreate:
            ws = get_workspace_by_id(sb, workspace_id)
            if not ws:
                return jsonify({'error': 'Project not found'}), 404
            profile = get_profile(sb, user_id)
            org_id = (profile or {}).get('org_id')
            config = fv_create_config(sb, workspace_id, user_id, org_id)
        if not config:
            return jsonify({'config': None, 'tabs': []})
        tabs = fv_list_tabs(sb, config['id'])
        return jsonify({'config': config, 'tabs': tabs})

    @app.route('/api/full-view/config', methods=['POST'])
    @require_admin
    def api_fv_create_config(user_id, role):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        data = json_payload()
        workspace_id = (data.get('workspace_id') or '').strip()
        if not workspace_id:
            return jsonify({'error': 'workspace_id is required'}), 400
        ws = get_workspace_by_id(sb, workspace_id)
        if not ws:
            return jsonify({'error': 'Project not found'}), 404
        existing = fv_get_config(sb, workspace_id)
        if existing:
            return jsonify({'config': existing})
        profile = get_profile(sb, user_id)
        org_id = (profile or {}).get('org_id')
        config = fv_create_config(sb, workspace_id, user_id, org_id)
        if not config:
            return jsonify({'error': 'Failed to create config'}), 500
        return jsonify({'config': config}), 201

    @app.route('/api/full-view/config/<config_id>', methods=['PUT'])
    @require_admin
    def api_fv_update_config(user_id, role, config_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        data = request.get_json(silent=True) or {}
        if 'style' in data and not isinstance(data.get('style'), dict):
            return jsonify({'error': 'style must be a JSON object'}), 400
        updated = fv_update_config(sb, config_id, **data)
        return jsonify({'config': updated})

    @app.route('/api/full-view/config/<config_id>', methods=['DELETE'])
    @require_admin
    def api_fv_delete_config(user_id, role, config_id):
        # Global Full View config is edit-only to prevent accidental resets.
        return jsonify({'error': 'Global Full View config is edit-only and cannot be deleted.'}), 403

    @app.route('/api/full-view/icon-upload', methods=['POST'])
    @require_admin
    def api_fv_upload_icon(user_id, role):
        file_storage = request.files.get('file')
        if not file_storage or not getattr(file_storage, 'filename', ''):
            return jsonify({'error': 'Icon file is required'}), 400

        original_name = secure_filename(file_storage.filename or '')
        ext = os.path.splitext(original_name)[1].lower()
        allowed_types = {
            '.png': 'image/png',
            '.webp': 'image/webp',
        }
        if ext not in allowed_types:
            return jsonify({'error': 'Only transparent PNG or WebP icons are supported'}), 400

        try:
            width, height = probe_image_dimensions(file_storage.stream)
        except Exception:
            return jsonify({'error': 'Uploaded file is not a valid image'}), 400
        if not width or not height:
            return jsonify({'error': 'Uploaded file is not a valid image'}), 400

        max_bytes = 5 * 1024 * 1024
        try:
            raw = read_uploaded_file_bytes(file_storage, max_bytes)
        except ValueError:
            return jsonify({'error': 'Icon file is too large. Max size is 5 MB'}), 413
        if not raw:
            return jsonify({'error': 'Uploaded icon is empty'}), 400

        workspace_hint = secure_filename((request.form.get('workspace_id') or '').strip())[:40]
        prefix = f'fv_icon_{workspace_hint}_' if workspace_hint else 'fv_icon_'
        filename = f"{prefix}{uuid.uuid4().hex}{ext}"

        try:
            if use_s3():
                upload_panorama_to_s3(filename, raw, allowed_types[ext])
            else:
                local_path = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
                with open(local_path, 'wb') as f:
                    f.write(raw)
        except Exception as e:
            return jsonify({'error': str(e)}), 500

        return jsonify({
            'filename': filename,
            'url': '/uploads/' + filename,
            'width': int(width),
            'height': int(height),
        }), 201

    @app.route('/api/full-view/logo-upload', methods=['POST'])
    @require_admin
    def api_fv_upload_logo(user_id, role):
        file_storage = request.files.get('file')
        if not file_storage or not getattr(file_storage, 'filename', ''):
            return jsonify({'error': 'Logo file is required'}), 400

        original_name = secure_filename(file_storage.filename or '')
        ext = os.path.splitext(original_name)[1].lower()
        allowed_types = {
            '.png': 'image/png',
            '.webp': 'image/webp',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
        }
        if ext not in allowed_types:
            return jsonify({'error': 'Only PNG, JPG, JPEG, or WebP logos are supported'}), 400

        try:
            width, height = probe_image_dimensions(file_storage.stream)
        except Exception:
            return jsonify({'error': 'Uploaded file is not a valid image'}), 400
        if not width or not height:
            return jsonify({'error': 'Uploaded file is not a valid image'}), 400

        max_bytes = 5 * 1024 * 1024
        try:
            raw = read_uploaded_file_bytes(file_storage, max_bytes)
        except ValueError:
            return jsonify({'error': 'Logo file is too large. Max size is 5 MB'}), 413
        if not raw:
            return jsonify({'error': 'Uploaded logo is empty'}), 400

        workspace_hint = secure_filename((request.form.get('workspace_id') or '').strip())[:40]
        prefix = f'fv_logo_{workspace_hint}_' if workspace_hint else 'fv_logo_'
        filename = f"{prefix}{uuid.uuid4().hex}{ext}"

        try:
            if use_s3():
                upload_panorama_to_s3(filename, raw, allowed_types[ext])
            else:
                local_path = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
                with open(local_path, 'wb') as f:
                    f.write(raw)
        except Exception as e:
            return jsonify({'error': str(e)}), 500

        return jsonify({
            'filename': filename,
            'url': '/uploads/' + filename,
            'width': int(width),
            'height': int(height),
        }), 201

    @app.route('/api/full-view/tabs', methods=['POST'])
    @require_admin
    def api_fv_create_tab(user_id, role):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        try:
            data = _normalize_link_tab_payload(json_payload())
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400
        config_id = (data.get('config_id') or '').strip()
        workspace_id = (data.get('workspace_id') or '').strip()
        icon = (data.get('icon') or 'ph:house').strip()
        name = (data.get('name') or '').strip()
        tab_type = (data.get('tab_type') or '360_pano').strip()
        smap = None
        if tab_type == 'sales_map':
            ref_sales_map_id = (data.get('ref_sales_map_id') or '').strip()
            if ref_sales_map_id:
                smap = srm_get(sb, ref_sales_map_id)
                if not workspace_id:
                    workspace_id = str((smap or {}).get('workspace_id') or '').strip()
                if not name:
                    name = str((smap or {}).get('name') or '').strip() or 'Sales Route Map'
        if not config_id and workspace_id:
            cfg = fv_get_config(sb, workspace_id)
            if not cfg:
                ws = get_workspace_by_id(sb, workspace_id)
                if ws:
                    profile = get_profile(sb, user_id)
                    org_id = (profile or {}).get('org_id')
                    cfg = fv_create_config(sb, workspace_id, user_id, org_id)
            config_id = str((cfg or {}).get('id') or '').strip()
        if not config_id:
            return jsonify({'error': 'config_id is required'}), 400
        if not name:
            return jsonify({'error': 'name is required'}), 400
        kwargs = {
            'is_visible': data.get('is_visible', True),
            'sort_order': data.get('sort_order', 0),
            'content_data': data.get('content_data') or {},
            'ref_panorama_id': data.get('ref_panorama_id'),
            'ref_daynight_id': data.get('ref_daynight_id'),
            'ref_floor_plan_id': data.get('ref_floor_plan_id'),
            'ref_gallery_id': data.get('ref_gallery_id'),
            'ref_project_plan_id': data.get('ref_project_plan_id'),
            'ref_sales_map_id': data.get('ref_sales_map_id'),
            'ref_sales_flat360_id': data.get('ref_sales_flat360_id'),
        }
        tab = fv_create_tab(sb, config_id, icon, name, tab_type, **kwargs)
        if not tab:
            return jsonify({'error': 'Failed to create tab'}), 500
        return jsonify({'tab': tab}), 201

    @app.route('/api/full-view/tabs/<tab_id>', methods=['PUT'])
    @require_admin
    def api_fv_update_tab(user_id, role, tab_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        try:
            data = _normalize_link_tab_payload(json_payload())
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400
        updated = fv_update_tab(sb, tab_id, **data)
        return jsonify({'tab': updated})

    @app.route('/api/full-view/tabs/<tab_id>', methods=['DELETE'])
    @require_admin
    def api_fv_delete_tab(user_id, role, tab_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        fv_delete_tab(sb, tab_id)
        return jsonify({'success': True})

    @app.route('/api/full-view/tabs/reorder', methods=['POST'])
    @require_admin
    def api_fv_reorder_tabs(user_id, role):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        data = json_payload()
        config_id = (data.get('config_id') or '').strip()
        tab_ids = data.get('tab_ids') or []
        if not config_id or not tab_ids:
            return jsonify({'error': 'config_id and tab_ids are required'}), 400
        fv_reorder_tabs(sb, config_id, tab_ids)
        return jsonify({'success': True})

    @app.route('/api/customer/full-view/floor-plan/<catalogue_id>/items', methods=['GET'])
    def api_customer_fv_fp_items(catalogue_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        cat = fp_get_catalogue(sb, catalogue_id)
        if not cat:
            return jsonify({'error': 'Not found'}), 404
        items = fp_list_items(sb, catalogue_id)
        for item in items:
            fn = item.get('image_filename') or item.get('filename')
            item['image_url'] = get_floorplan_s3_url(fn) if fn else None
        return jsonify({'items': items})

    @app.route('/api/customer/full-view/gallery/<gallery_id>/items', methods=['GET'])
    def api_customer_fv_gallery_items(gallery_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        gal = gal_get(sb, gallery_id)
        if not gal:
            return jsonify({'error': 'Not found'}), 404
        items = gal_list_items(sb, gallery_id)
        for item in items:
            item['media_url'] = get_gallery_s3_url(item.get('filename'))
        return jsonify({'items': items})

    @app.route('/api/public/full-view', methods=['GET'])
    def api_public_fv_config():
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        workspace_id = request.args.get('workspace_id', '').strip()
        if not workspace_id:
            return jsonify({'error': 'workspace_id is required'}), 400
        result = fv_get_config_with_tabs(sb, workspace_id)
        if not result:
            return jsonify({'config': None, 'tabs': []})
        tabs = result.pop('tabs', [])
        return jsonify({'config': result, 'tabs': tabs})

    @app.route('/fullview/<endpoint>')
    def fv_customer_share_view(endpoint):
        sb = get_supabase()
        if not sb:
            return "Database not configured", 503
        workspace_id = get_workspace_id_by_share_endpoint(sb, endpoint)
        if not workspace_id:
            return "Project not found", 404
        fv_config = fv_get_config(sb, workspace_id)
        if fv_config and not fv_config.get('is_active'):
            return "Full View is not available", 404
        shell_base_path = (request.path or f'/fullview/{endpoint}').rstrip('/') or f'/fullview/{endpoint}'
        rendered = _render_fv_customer_shell(
            workspace_id,
            shell_base_path=shell_base_path,
        )
        if isinstance(rendered, tuple):
            return rendered
        response = make_response(rendered)
        response.headers['Cache-Control'] = 'no-store, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        return response

    @app.route('/customer/full-view/<workspace_id>')
    def fv_customer_shell(workspace_id):
        return _render_fv_customer_shell(workspace_id)

    @app.route('/customer/full-view/edit/<workspace_id>')
    def fv_customer_shell_editor(workspace_id):
        editor_preview_mode = request.args.get('preview', '').strip().lower() or ''
        return _render_fv_customer_shell(
            workspace_id,
            is_editor=True,
            editor_preview_mode=editor_preview_mode,
        )

    @app.route('/customer/full-view/floor-plan/<catalogue_id>')
    def fv_customer_floorplan_view(catalogue_id):
        sb = get_supabase()
        if not sb:
            return "Database not configured", 503
        cat = fp_get_catalogue(sb, catalogue_id)
        if not cat:
            return "Not found", 404
        items = fp_list_items(sb, catalogue_id)
        for item in items:
            item['image_url'] = get_floorplan_s3_url(item.get('image_filename'))
        items = [it for it in items if it.get('image_url')]
        workspace_id = (request.args.get('workspace_id') or '').strip() or None
        fv_style = {}
        if workspace_id:
            fv_cfg = fv_get_config(sb, workspace_id)
            style_blob = (fv_cfg or {}).get('style')
            if isinstance(style_blob, dict):
                fv_style = style_blob
        return render_template(
            'floorplans_view.html',
            catalogue=cat,
            items=items,
            workspace_name=cat.get('name', 'Floor Plans'),
            fv_style=fv_style,
            fv_config=None,
        )

    @app.route('/customer/full-view/gallery/<gallery_id>')
    def fv_customer_gallery_view(gallery_id):
        sb = get_supabase()
        if not sb:
            return "Database not configured", 503
        gal = gal_get(sb, gallery_id)
        if not gal:
            return "Not found", 404
        items = gal_list_items(sb, gallery_id)
        for item in items:
            item['media_url'] = get_gallery_s3_url(item.get('filename'))
        items = [it for it in items if it.get('media_url')]
        workspace_id = (request.args.get('workspace_id') or '').strip() or None
        fv_style = {}
        if workspace_id:
            fv_cfg = fv_get_config(sb, workspace_id)
            style_blob = (fv_cfg or {}).get('style')
            if isinstance(style_blob, dict):
                fv_style = style_blob
        return render_template(
            'gallery_view.html',
            gallery=gal,
            items=items,
            fv_style=fv_style,
            fv_config=None,
        )

    @app.route('/customer/full-view/daynight/<project_id>')
    def fv_customer_daynight_view(project_id):
        sb = get_supabase()
        if not sb:
            return "Database not configured", 503
        project = dn_get(sb, project_id)
        if not project:
            return "Not found", 404
        media_url = None
        if project.get('media_type') == 'image' and project.get('stitched_filename'):
            media_url = get_daynight_s3_url(project['stitched_filename'])
        elif project.get('media_type') == 'video' and project.get('video_filename'):
            media_url = get_daynight_s3_url(project['video_filename'])
        if not media_url:
            return "Media not yet uploaded", 404
        preview_mode = request.args.get('preview', '').strip().lower() or ''
        return render_template(
            'daynight_view.html',
            project=project,
            media_url=media_url,
            media_type=project.get('media_type'),
            stitched_width=project.get('stitched_width', 0),
            stitched_height=project.get('stitched_height', 0),
            drag_speed=project.get('drag_speed') or 80,
            preview_mode=preview_mode,
            fv_config=None,
        )

    @app.route('/customer/full-view/project-plan/<plan_id>')
    def fv_customer_project_plan_view(plan_id):
        sb = get_supabase()
        if not sb:
            return "Database not configured", 503
        plan = pp_get(sb, plan_id)
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
        return render_template(
            'project_plan_view.html',
            plan=plan,
            buildings=buildings,
            fv_config=None,
            fv_style=fv_style,
        )
