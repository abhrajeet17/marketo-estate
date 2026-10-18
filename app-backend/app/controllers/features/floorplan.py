"""
Floorplan routes (moved out of register.py).
"""

import uuid

from flask import current_app, jsonify, redirect, render_template, request

from app.core.auth import get_profile, require_admin
from app.core.concurrency import run_parallel
from app.core.database import get_supabase
from app.services.floorplan_service import catalogue_name_exists as fp_name_exists, create_catalogue as fp_create_catalogue, create_item as fp_create_item, delete_catalogue as fp_delete_catalogue, delete_item as fp_delete_item, get_catalogue as fp_get_catalogue, get_catalogue_by_token as fp_get_catalogue_by_token, get_item as fp_get_item, get_item_counts as fp_get_item_counts, get_item_previews as fp_get_item_previews, get_next_sort_order as fp_next_sort_order, list_catalogues as fp_list_catalogues, list_items as fp_list_items, reorder_items as fp_reorder_items, update_catalogue as fp_update_catalogue, update_item as fp_update_item
from app.services.storage_service import MAX_FLOORPLAN_READ_BYTES, MAX_GALLERY_READ_BYTES, convert_floorplan_to_webp_lossless, delete_floorplan_from_s3, get_floorplan_s3_url, upload_floorplan_to_s3

from .building_plan import sign_many as _sign_many
from .shared import allowed_file, auth_ctx


def register_floorplan_routes(app):
    @app.route('/salestools')
    def sales_tools_page():
        if request.args.get('tab') == 'building-maps':
            return redirect('/building-plans')
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
            counts, previews = run_parallel(
                lambda: fp_get_item_counts(sb, cat_ids),
                lambda: fp_get_item_previews(sb, cat_ids),
                strict=True,
            )
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
        urls = _sign_many(get_floorplan_s3_url, [it.get('image_filename') for it in items], verify=False)
        for item in items:
            item['image_url'] = urls.get(item.get('image_filename'))
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
