import uuid

from flask import current_app, jsonify, render_template, request

from app.core.auth import get_profile, require_admin
from app.core.database import get_supabase
from app.services.gallery_service import (
    create_gallery as gal_create,
    create_item as gal_create_item,
    delete_gallery as gal_delete,
    delete_item as gal_delete_item,
    get_gallery as gal_get,
    get_gallery_by_token as gal_get_by_token,
    get_item as gal_get_item,
    get_next_sort_order as gal_next_sort_order,
    list_galleries as gal_list,
    list_items as gal_list_items,
    reorder_items as gal_reorder_items,
    update_gallery as gal_update,
    update_item as gal_update_item,
)
from app.services.storage_service import (
    ALLOWED_GALLERY_IMAGE_EXT,
    ALLOWED_GALLERY_VIDEO_EXT,
    GALLERY_MAX_SAFE_UPLOAD_BYTES,
    MAX_GALLERY_READ_BYTES,
    buffer_uploaded_file,
    compress_gallery_image,
    delete_gallery_from_s3,
    get_gallery_s3_url,
    read_uploaded_file_bytes,
    upload_gallery_to_s3,
)
from app.services.workspace_service import can_manage_workspace, get_workspace_by_id

from .shared import is_truthy


def register_gallery_routes(app):
    @app.route('/api/galleries', methods=['GET'])
    @require_admin
    def api_list_galleries(user_id, role):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        workspace_id = str(request.args.get('workspace_id') or '').strip() or None
        galleries = gal_list(sb, user_id, workspace_id=workspace_id)
        base = (request.url_root or '').rstrip('/')
        for g in galleries:
            g['share_url'] = f"{base}/gallery/view/{g.get('share_token', '')}"
            items = gal_list_items(sb, g['id'])
            g['item_count'] = len(items)
            g['item_names'] = [it.get('name', '') for it in items[:5]]
            g['image_count'] = sum(1 for it in items if it.get('media_type') == 'image')
            g['video_count'] = sum(1 for it in items if it.get('media_type') == 'video')
        return jsonify(galleries)

    @app.route('/api/galleries', methods=['POST'])
    @require_admin
    def api_create_gallery(user_id, role):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        data = request.get_json(silent=True) or {}
        name = str(data.get('name') or 'Gallery').strip()
        workspace_id = str(data.get('workspace_id') or '').strip() or None
        if workspace_id:
            workspace = get_workspace_by_id(sb, workspace_id)
            if not workspace:
                return jsonify({'error': 'Project not found'}), 404
            if not can_manage_workspace(sb, workspace, user_id, role):
                return jsonify({'error': 'Forbidden'}), 403
        existing = gal_list(sb, user_id, workspace_id=workspace_id)
        if any(g.get('name', '').strip().lower() == name.lower() for g in existing):
            return jsonify({'error': f'A gallery named "{name}" already exists'}), 409
        profile = get_profile(sb, user_id)
        org_id = profile.get('org_id') if profile else None
        gal = gal_create(sb, user_id, org_id, name, workspace_id=workspace_id)
        if not gal:
            return jsonify({'error': 'Failed to create gallery'}), 500
        base = (request.url_root or '').rstrip('/')
        gal['share_url'] = f"{base}/gallery/view/{gal.get('share_token', '')}"
        return jsonify(gal), 201

    @app.route('/api/galleries/<gallery_id>', methods=['GET'])
    @require_admin
    def api_get_gallery(user_id, role, gallery_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        gal = gal_get(sb, gallery_id)
        if not gal:
            return jsonify({'error': 'Not found'}), 404
        if str(gal.get('user_id')) != str(user_id) and role != 'superadmin':
            return jsonify({'error': 'Forbidden'}), 403
        items = gal_list_items(sb, gallery_id)
        for item in items:
            item['media_url'] = get_gallery_s3_url(item.get('filename'))
        gal['items'] = items
        base = (request.url_root or '').rstrip('/')
        gal['share_url'] = f"{base}/gallery/view/{gal.get('share_token', '')}"
        return jsonify(gal)

    @app.route('/api/galleries/<gallery_id>', methods=['PATCH'])
    @require_admin
    def api_update_gallery(user_id, role, gallery_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        gal = gal_get(sb, gallery_id)
        if not gal or (str(gal.get('user_id')) != str(user_id) and role != 'superadmin'):
            return jsonify({'error': 'Forbidden'}), 403
        data = request.get_json(silent=True) or {}
        name = data.get('name')
        if name:
            gal_update(sb, gallery_id, name=name)
        updated = gal_get(sb, gallery_id)
        return jsonify(updated)

    @app.route('/api/galleries/<gallery_id>', methods=['DELETE'])
    @require_admin
    def api_delete_gallery(user_id, role, gallery_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        gal = gal_get(sb, gallery_id)
        if not gal or (str(gal.get('user_id')) != str(user_id) and role != 'superadmin'):
            return jsonify({'error': 'Forbidden'}), 403
        items = gal_list_items(sb, gallery_id)
        for item in items:
            delete_gallery_from_s3(item.get('filename'))
        gal_delete(sb, gallery_id)
        return jsonify({'success': True})

    @app.route('/api/galleries/<gallery_id>/items', methods=['GET'])
    @require_admin
    def api_list_gallery_items(user_id, role, gallery_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        gal = gal_get(sb, gallery_id)
        if not gal or (str(gal.get('user_id')) != str(user_id) and role != 'superadmin'):
            return jsonify({'error': 'Forbidden'}), 403
        items = gal_list_items(sb, gallery_id)
        for item in items:
            item['media_url'] = get_gallery_s3_url(item.get('filename'))
        return jsonify(items)

    @app.route('/api/galleries/<gallery_id>/items', methods=['POST'])
    @require_admin
    def api_upload_gallery_item(user_id, role, gallery_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        gal = gal_get(sb, gallery_id)
        if not gal or (str(gal.get('user_id')) != str(user_id) and role != 'superadmin'):
            return jsonify({'error': 'Forbidden'}), 403
        name = request.form.get('name', '').strip() or 'Media'
        raw_is_360 = request.form.get('is_360')
        f = request.files.get('file')
        if not f or not f.filename:
            return jsonify({'error': 'No file provided'}), 400
        ext = f.filename.rsplit('.', 1)[-1].lower() if '.' in f.filename else ''
        is_video = ext in ALLOWED_GALLERY_VIDEO_EXT
        is_image = ext in ALLOWED_GALLERY_IMAGE_EXT
        if not is_video and not is_image:
            return jsonify({'error': f'Invalid file type. Allowed: {", ".join(ALLOWED_GALLERY_IMAGE_EXT | ALLOWED_GALLERY_VIDEO_EXT)}'}), 400
        max_cfg = int(current_app.config.get('MAX_CONTENT_LENGTH') or 0)
        max_allowed = int(MAX_GALLERY_READ_BYTES)
        if max_cfg > 0:
            max_allowed = min(max_allowed, max_cfg)
        declared_size = int(request.content_length or 0)
        declared_limit = max_allowed + (1024 * 1024)
        if max_allowed > 0 and declared_size and declared_size > declared_limit:
            max_mb = max(1, int(max_allowed / (1024 * 1024)))
            return jsonify({'error': f'File too large (max {max_mb}MB)'}), 413

        # Safe target: match Supabase bucket limit (currently 50MB).
        # Source files can be larger (up to MAX_GALLERY_READ_BYTES); images are losslessly resized + WebP-compressed.
        MAX_SAFE_S3_UPLOAD = int(GALLERY_MAX_SAFE_UPLOAD_BYTES)

        staged_stream = None
        filename = ''
        try:
            if is_image:
                raw_bytes = read_uploaded_file_bytes(f, max_allowed)
                if not raw_bytes:
                    return jsonify({'error': 'No file provided'}), 400
                processed, w, h, out_ext, out_content_type = compress_gallery_image(raw_bytes, source_ext=ext)
                if not processed:
                    return jsonify({'error': 'Failed to process image'}), 400
                if len(processed) > MAX_SAFE_S3_UPLOAD:
                    max_mb = max(1, MAX_SAFE_S3_UPLOAD // (1024 * 1024))
                    return jsonify({'error': f'Image is too large even after processing (max {max_mb}MB). Please use a smaller or lower-resolution file.'}), 413
                filename = f"gal_{uuid.uuid4().hex[:16]}.{out_ext or 'webp'}"
                upload_gallery_to_s3(filename, processed, out_content_type or 'image/webp')
                file_size = len(processed)
            else:
                content_types = {'mp4': 'video/mp4', 'webm': 'video/webm', 'mov': 'video/quicktime'}
                filename = f"gal_{uuid.uuid4().hex[:16]}.{ext}"
                staged_stream, file_size = buffer_uploaded_file(f, max_allowed)
                if not staged_stream or file_size <= 0:
                    return jsonify({'error': 'No file provided'}), 400
                if file_size > MAX_SAFE_S3_UPLOAD:
                    max_mb = max(1, MAX_SAFE_S3_UPLOAD // (1024 * 1024))
                    return jsonify({'error': f'Video is too large for storage (max {max_mb}MB). Please use a smaller video or compress it first.'}), 413
                upload_gallery_to_s3(filename, staged_stream, content_types.get(ext, 'video/mp4'))
                w, h = 0, 0
        except ValueError:
            max_mb = max(1, int(max_allowed / (1024 * 1024)))
            return jsonify({'error': f'File too large (max {max_mb}MB)'}), 413
        except RuntimeError as e:
            msg = str(e) or 'Upload failed'
            code = 503 if 'not configured' in msg.lower() else 502
            return jsonify({'error': msg}), code
        except Exception as e:
            current_app.logger.exception('Gallery upload failed unexpectedly: %s', e)
            return jsonify({
                'error': 'Upload failed while processing or storing the file. Please retry. If this keeps happening, try a smaller file.'
            }), 500
        finally:
            if staged_stream:
                try:
                    staged_stream.close()
                except Exception:
                    pass

        if is_image:
            if raw_is_360 is not None and str(raw_is_360).strip() != '':
                is_360 = is_truthy(raw_is_360)
            else:
                is_360 = False
        else:
            is_360 = False

        sort_order = gal_next_sort_order(sb, gallery_id)
        try:
            item = gal_create_item(
                sb, gallery_id, name, filename,
                media_type='video' if is_video else 'image',
                media_width=w, media_height=h,
                file_size_bytes=file_size,
                sort_order=sort_order,
                is_360=is_360,
            )
        except Exception as e:
            current_app.logger.exception('Gallery item DB create failed: %s', e)
            if filename:
                delete_gallery_from_s3(filename)
            return jsonify({'error': 'File uploaded but metadata save failed. Please retry.'}), 500
        if not item:
            if filename:
                delete_gallery_from_s3(filename)
            return jsonify({'error': 'Failed to create item'}), 500
        item['media_url'] = get_gallery_s3_url(filename)
        return jsonify(item), 201

    @app.route('/api/gallery-items/<item_id>', methods=['PATCH'])
    @require_admin
    def api_update_gallery_item(user_id, role, item_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        item = gal_get_item(sb, item_id)
        if not item:
            return jsonify({'error': 'Not found'}), 404
        gal = gal_get(sb, item['gallery_id'])
        if not gal or (str(gal.get('user_id')) != str(user_id) and role != 'superadmin'):
            return jsonify({'error': 'Forbidden'}), 403
        data = request.get_json(silent=True) or {}
        updates = {}
        if 'name' in data:
            updates['name'] = str(data['name']).strip()
        if 'is_360' in data:
            updates['is_360'] = is_truthy(data.get('is_360'))
        if updates:
            gal_update_item(sb, item_id, **updates)
        updated = gal_get_item(sb, item_id)
        if updated:
            updated['media_url'] = get_gallery_s3_url(updated.get('filename'))
        return jsonify(updated)

    @app.route('/api/gallery-items/<item_id>', methods=['DELETE'])
    @require_admin
    def api_delete_gallery_item(user_id, role, item_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        item = gal_get_item(sb, item_id)
        if not item:
            return jsonify({'error': 'Not found'}), 404
        gal = gal_get(sb, item['gallery_id'])
        if not gal or (str(gal.get('user_id')) != str(user_id) and role != 'superadmin'):
            return jsonify({'error': 'Forbidden'}), 403
        delete_gallery_from_s3(item.get('filename'))
        gal_delete_item(sb, item_id)
        return jsonify({'success': True})

    @app.route('/api/galleries/<gallery_id>/reorder', methods=['POST'])
    @require_admin
    def api_reorder_gallery_items(user_id, role, gallery_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        gal = gal_get(sb, gallery_id)
        if not gal or (str(gal.get('user_id')) != str(user_id) and role != 'superadmin'):
            return jsonify({'error': 'Forbidden'}), 403
        data = request.get_json(silent=True) or {}
        ordered_ids = data.get('ordered_ids')
        if not ordered_ids or not isinstance(ordered_ids, list):
            return jsonify({'error': 'ordered_ids must be a non-empty list'}), 400
        gal_reorder_items(sb, gallery_id, ordered_ids)
        items = gal_list_items(sb, gallery_id)
        for item in items:
            item['media_url'] = get_gallery_s3_url(item.get('filename'))
        return jsonify(items)

    @app.route('/gallery/view/<share_token>')
    def gallery_public_view(share_token):
        sb = get_supabase()
        if not sb:
            return "Database not configured", 503
        gal = gal_get_by_token(sb, share_token)
        if not gal:
            return "Not found", 404
        items = gal_list_items(sb, gal['id'])
        for item in items:
            item['media_url'] = get_gallery_s3_url(item.get('filename'))
        items = [it for it in items if it.get('media_url')]
        if not items:
            return "No media uploaded yet", 404
        return render_template(
            'gallery_view.html',
            gallery=gal,
            items=items,
            fv_style={},
        )
