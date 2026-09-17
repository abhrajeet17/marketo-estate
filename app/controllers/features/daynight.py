import os
import uuid
from datetime import datetime

from flask import current_app, jsonify, render_template, request
from itsdangerous import BadSignature, SignatureExpired
from werkzeug.utils import secure_filename

from app import config as app_config
from app.config import (
    ALLOWED_EXTENSIONS,
    ALLOWED_VIDEO_EXTENSIONS,
    MAX_DAYNIGHT_VIDEO_BYTES,
    SUPABASE_S3_BUCKET,
    SUPABASE_S3_UPLOAD_URL_TTL,
    VIDEO_CONTENT_TYPES,
)
from app.core.auth import get_profile, require_admin
from app.core.database import get_supabase
from app.core.serializers import daynight_upload_serializer
from app.services.daynight_service import (
    create_daynight_project as dn_create,
    delete_daynight_project as dn_delete,
    get_daynight_project as dn_get,
    get_daynight_project_by_token as dn_get_by_token,
    list_daynight_projects as dn_list,
    update_daynight_project as dn_update,
)
from app.services.storage_service import (
    MAX_DAYNIGHT_IMAGE_READ_BYTES,
    buffer_uploaded_file,
    daynight_object_key,
    delete_daynight_from_s3,
    get_daynight_s3_url,
    get_s3_client,
    read_uploaded_file_bytes,
    stitch_images_horizontally,
    upload_daynight_to_s3,
    use_s3,
)
from app.services.workspace_service import can_manage_workspace, get_workspace_by_id

from .shared import auth_ctx, detect_video_ext_from_content_type


def register_daynight_routes(app):
    secret_key = app.secret_key or app_config.SECRET_KEY

    @app.route('/daynight')
    def daynight_page():
        return render_template(
            'daynight.html',
            max_daynight_video_bytes=MAX_DAYNIGHT_VIDEO_BYTES,
            max_upload_bytes=current_app.config.get('MAX_CONTENT_LENGTH') or 0,
            **auth_ctx(),
        )

    @app.route('/api/daynight', methods=['GET'])
    @require_admin
    def api_list_daynight(user_id, role):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        workspace_id = str(request.args.get('workspace_id') or '').strip() or None
        projects = dn_list(sb, user_id, workspace_id=workspace_id)
        base = (request.url_root or '').rstrip('/')
        for project in projects:
            project['share_url'] = f"{base}/daynight/view/{project.get('share_token', '')}"
            if project.get('media_type') == 'image' and project.get('stitched_filename'):
                project['media_url'] = get_daynight_s3_url(project['stitched_filename'])
            elif project.get('media_type') == 'video' and project.get('video_filename'):
                project['media_url'] = get_daynight_s3_url(project['video_filename'])
            else:
                project['media_url'] = None
            project['preview_url'] = f"{base}/daynight/preview/{project.get('share_token', '')}"
        return jsonify(projects)

    @app.route('/api/daynight', methods=['POST'])
    @require_admin
    def api_create_daynight(user_id, role):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        data = request.get_json(silent=True) or {}
        name = str(data.get('name') or '').strip()
        media_type = str(data.get('media_type') or '').strip()
        workspace_id = str(data.get('workspace_id') or '').strip() or None
        if not name:
            return jsonify({'error': 'Name is required'}), 400
        if media_type not in ('image', 'video'):
            return jsonify({'error': 'media_type must be image or video'}), 400
        if workspace_id:
            workspace = get_workspace_by_id(sb, workspace_id)
            if not workspace:
                return jsonify({'error': 'Project not found'}), 404
            if not can_manage_workspace(sb, workspace, user_id, role):
                return jsonify({'error': 'Forbidden'}), 403
        profile = get_profile(sb, user_id)
        org_id = profile.get('org_id') if profile else None
        project = dn_create(sb, user_id, org_id, name, media_type, workspace_id=workspace_id)
        if not project:
            return jsonify({'error': 'Failed to create project'}), 500
        project['share_url'] = f"{(request.url_root or '').rstrip('/')}/daynight/view/{project.get('share_token', '')}"
        return jsonify(project), 201

    @app.route('/api/daynight/<project_id>', methods=['GET'])
    @require_admin
    def api_get_daynight(user_id, role, project_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        project = dn_get(sb, project_id)
        if not project:
            return jsonify({'error': 'Not found'}), 404
        if str(project.get('user_id')) != str(user_id) and role != 'superadmin':
            return jsonify({'error': 'Forbidden'}), 403
        media_url = None
        if project.get('media_type') == 'image' and project.get('stitched_filename'):
            media_url = get_daynight_s3_url(project['stitched_filename'])
        elif project.get('media_type') == 'video' and project.get('video_filename'):
            media_url = get_daynight_s3_url(project['video_filename'])
        project['media_url'] = media_url
        project['share_url'] = f"{(request.url_root or '').rstrip('/')}/daynight/view/{project.get('share_token', '')}"
        return jsonify(project)

    @app.route('/api/daynight/<project_id>', methods=['PATCH'])
    @require_admin
    def api_update_daynight(user_id, role, project_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        project = dn_get(sb, project_id)
        if not project:
            return jsonify({'error': 'Not found'}), 404
        if str(project.get('user_id')) != str(user_id) and role != 'superadmin':
            return jsonify({'error': 'Forbidden'}), 403
        data = request.get_json(silent=True) or {}
        updates = {}
        if 'name' in data:
            name = str(data.get('name') or '').strip()
            if not name:
                return jsonify({'error': 'Name is required'}), 400
            updates['name'] = name
        if not updates:
            return jsonify({'error': 'No supported fields provided'}), 400
        updated = dn_update(sb, project_id, **updates)
        if not updated:
            return jsonify({'error': 'Update failed'}), 500
        updated['share_url'] = f"{(request.url_root or '').rstrip('/')}/daynight/view/{updated.get('share_token', '')}"
        updated['preview_url'] = f"{(request.url_root or '').rstrip('/')}/daynight/preview/{updated.get('share_token', '')}"
        if updated.get('media_type') == 'image' and updated.get('stitched_filename'):
            updated['media_url'] = get_daynight_s3_url(updated['stitched_filename'])
        elif updated.get('media_type') == 'video' and updated.get('video_filename'):
            updated['media_url'] = get_daynight_s3_url(updated['video_filename'])
        else:
            updated['media_url'] = None
        return jsonify(updated)

    @app.route('/api/daynight/<project_id>/upload-images', methods=['POST'])
    @require_admin
    def api_daynight_upload_images(user_id, role, project_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        project = dn_get(sb, project_id)
        if not project:
            return jsonify({'error': 'Not found'}), 404
        if str(project.get('user_id')) != str(user_id) and role != 'superadmin':
            return jsonify({'error': 'Forbidden'}), 403
        if project.get('media_type') != 'image':
            return jsonify({'error': 'Project media_type is not image'}), 400
        files = request.files.getlist('images')
        if not files or len(files) < 2:
            return jsonify({'error': 'At least 2 images required'}), 400
        image_bytes_list = []
        source_names = []
        for f in files:
            ext = (f.filename or '').rsplit('.', 1)[-1].lower() if f.filename else ''
            if ext not in ALLOWED_EXTENSIONS:
                return jsonify({'error': f'Invalid image type: {f.filename}'}), 400
            try:
                raw = read_uploaded_file_bytes(f, MAX_DAYNIGHT_IMAGE_READ_BYTES)
            except ValueError:
                max_mb = max(1, int(MAX_DAYNIGHT_IMAGE_READ_BYTES / (1024 * 1024)))
                return jsonify({'error': f'Image too large: {f.filename} (max {max_mb}MB each)'}), 413
            if not raw:
                return jsonify({'error': f'Empty file: {f.filename}'}), 400
            image_bytes_list.append(raw)
            source_names.append(f.filename or 'unknown')
        try:
            stitched_bytes, join_positions, width, height = stitch_images_horizontally(image_bytes_list)
        except Exception as e:
            current_app.logger.exception('Day/night image stitching failed for project %s', project_id)
            return jsonify({'error': f'Stitching failed: {str(e)}'}), 500
        filename = f"dn_{project_id}_{uuid.uuid4().hex[:8]}.jpg"
        old_fn = project.get('stitched_filename')
        try:
            upload_daynight_to_s3(filename, stitched_bytes, 'image/jpeg')
        except Exception as e:
            current_app.logger.exception('Day/night image upload failed for project %s', project_id)
            return jsonify({'error': f'Upload failed: {str(e)}'}), 500
        updated = dn_update(
            sb,
            project_id,
            stitched_filename=filename,
            stitched_width=width,
            stitched_height=height,
            join_positions=join_positions,
            source_images=source_names,
        )
        if not updated:
            delete_daynight_from_s3(filename)
            return jsonify({'error': 'Failed to save upload metadata'}), 500
        if old_fn and old_fn != filename:
            delete_daynight_from_s3(old_fn)
        updated['media_url'] = get_daynight_s3_url(filename)
        updated['share_url'] = f"{(request.url_root or '').rstrip('/')}/daynight/view/{updated.get('share_token', '')}"
        return jsonify(updated or {'success': True})

    @app.route('/api/daynight/<project_id>/upload-video-url', methods=['POST'])
    @require_admin
    def api_daynight_upload_video_url(user_id, role, project_id):
        if not use_s3():
            return jsonify({'error': 'Supabase S3 is not configured'}), 503
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        project = dn_get(sb, project_id)
        if not project:
            return jsonify({'error': 'Not found'}), 404
        if str(project.get('user_id')) != str(user_id) and role != 'superadmin':
            return jsonify({'error': 'Forbidden'}), 403
        if project.get('media_type') != 'video':
            return jsonify({'error': 'Project media_type is not video'}), 400
        payload = request.get_json(silent=True) or request.form or {}
        original_filename = str(payload.get('original_filename') or payload.get('filename') or '').strip()
        if not original_filename:
            return jsonify({'error': 'original_filename is required'}), 400
        try:
            size_bytes = int(payload.get('size_bytes') or payload.get('size') or 0)
        except Exception:
            size_bytes = 0
        if size_bytes and size_bytes > MAX_DAYNIGHT_VIDEO_BYTES:
            max_mb = max(1, int(MAX_DAYNIGHT_VIDEO_BYTES / (1024 * 1024)))
            return jsonify({'error': f'Video too large (max {max_mb}MB)'}), 413
        content_type_hint = str(payload.get('content_type') or '').split(';', 1)[0].lower().strip()
        ext = original_filename.rsplit('.', 1)[-1].lower() if '.' in original_filename else ''
        if ext not in ALLOWED_VIDEO_EXTENSIONS and content_type_hint:
            ext = detect_video_ext_from_content_type(content_type_hint)
        if ext not in ALLOWED_VIDEO_EXTENSIONS:
            return jsonify({'error': f'Invalid video type. Allowed: {", ".join(sorted(ALLOWED_VIDEO_EXTENSIONS))}'}), 400
        content_type = VIDEO_CONTENT_TYPES.get(ext, content_type_hint or 'video/mp4')
        client = get_s3_client()
        if not client:
            return jsonify({'error': 'Supabase S3 is not fully configured'}), 503
        safe_name = secure_filename(str(project.get('name') or 'daynight').strip()) or 'daynight'
        filename = f"dn_{project_id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{safe_name}_{uuid.uuid4().hex[:8]}.{ext}"
        key = daynight_object_key(filename)
        try:
            upload_url = client.generate_presigned_url(
                ClientMethod='put_object',
                Params={'Bucket': SUPABASE_S3_BUCKET, 'Key': key, 'ContentType': content_type},
                ExpiresIn=int(SUPABASE_S3_UPLOAD_URL_TTL),
            )
        except Exception as e:
            current_app.logger.exception('Failed to generate day/night video upload URL for project %s', project_id)
            return jsonify({'error': str(e)}), 500
        token = daynight_upload_serializer(secret_key).dumps({
            'user_id': str(user_id),
            'project_id': str(project_id),
            'filename': filename,
            'content_type': content_type,
        })
        return jsonify({
            'filename': filename,
            'upload_url': upload_url,
            'upload_token': token,
            'content_type': content_type,
            'max_bytes': MAX_DAYNIGHT_VIDEO_BYTES,
            'expires_in': int(SUPABASE_S3_UPLOAD_URL_TTL),
        })

    @app.route('/api/daynight/<project_id>/upload-video', methods=['POST'])
    @require_admin
    def api_daynight_upload_video(user_id, role, project_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        project = dn_get(sb, project_id)
        if not project:
            return jsonify({'error': 'Not found'}), 404
        if str(project.get('user_id')) != str(user_id) and role != 'superadmin':
            return jsonify({'error': 'Forbidden'}), 403
        if project.get('media_type') != 'video':
            return jsonify({'error': 'Project media_type is not video'}), 400

        form_payload = request.form or {}
        direct_filename = os.path.basename(str(form_payload.get('filename') or '').strip())
        upload_token = str(form_payload.get('upload_token') or '').strip()
        old_fn = project.get('video_filename')
        filename = ''
        staged_file = None
        uploaded_object_exists = False

        try:
            if direct_filename or upload_token:
                if not direct_filename:
                    return jsonify({'error': 'filename is required'}), 400
                if not upload_token:
                    return jsonify({'error': 'upload_token is required'}), 400
                if not use_s3():
                    return jsonify({'error': 'Supabase S3 is not configured'}), 503
                try:
                    signed = daynight_upload_serializer(secret_key).loads(
                        upload_token,
                        max_age=int(SUPABASE_S3_UPLOAD_URL_TTL),
                    )
                except SignatureExpired:
                    return jsonify({'error': 'upload_token expired; request a new upload URL'}), 400
                except BadSignature:
                    return jsonify({'error': 'Invalid upload_token'}), 400
                if (
                    str(signed.get('user_id')) != str(user_id)
                    or str(signed.get('project_id')) != str(project_id)
                    or str(signed.get('filename')) != direct_filename
                ):
                    return jsonify({'error': 'Invalid upload_token'}), 403
                ext = direct_filename.rsplit('.', 1)[-1].lower() if '.' in direct_filename else ''
                if ext not in ALLOWED_VIDEO_EXTENSIONS:
                    return jsonify({'error': f'Invalid video type. Allowed: {", ".join(sorted(ALLOWED_VIDEO_EXTENSIONS))}'}), 400
                client = get_s3_client()
                if not client:
                    return jsonify({'error': 'Supabase S3 is not fully configured'}), 503
                try:
                    head = client.head_object(Bucket=SUPABASE_S3_BUCKET, Key=daynight_object_key(direct_filename))
                except Exception:
                    return jsonify({'error': 'Uploaded file not found; please retry'}), 400
                size_bytes = int((head or {}).get('ContentLength') or 0)
                if size_bytes > MAX_DAYNIGHT_VIDEO_BYTES:
                    delete_daynight_from_s3(direct_filename)
                    max_mb = max(1, int(MAX_DAYNIGHT_VIDEO_BYTES / (1024 * 1024)))
                    return jsonify({'error': f'Video too large (max {max_mb}MB)'}), 413
                filename = direct_filename
                uploaded_object_exists = True
            else:
                f = request.files.get('video')
                if not f:
                    return jsonify({'error': 'No video file provided'}), 400
                ext = (f.filename or '').rsplit('.', 1)[-1].lower() if f.filename else ''
                content_type_hint = str(getattr(f, 'content_type', '') or getattr(f, 'mimetype', '') or '').split(';', 1)[0].lower().strip()
                if ext not in ALLOWED_VIDEO_EXTENSIONS and content_type_hint:
                    ext = detect_video_ext_from_content_type(content_type_hint)
                if ext not in ALLOWED_VIDEO_EXTENSIONS:
                    return jsonify({'error': f'Invalid video type. Allowed: {", ".join(sorted(ALLOWED_VIDEO_EXTENSIONS))}'}), 400
                content_type = VIDEO_CONTENT_TYPES.get(ext, content_type_hint or 'video/mp4')
                try:
                    staged_file, size_bytes = buffer_uploaded_file(f, MAX_DAYNIGHT_VIDEO_BYTES)
                except ValueError:
                    max_mb = max(1, int(MAX_DAYNIGHT_VIDEO_BYTES / (1024 * 1024)))
                    return jsonify({'error': f'Video too large (max {max_mb}MB)'}), 413
                if size_bytes <= 0 or not staged_file:
                    return jsonify({'error': 'Empty file'}), 400
                filename = f"dn_{project_id}_{uuid.uuid4().hex[:8]}.{ext}"
                upload_daynight_to_s3(filename, staged_file, content_type)
                uploaded_object_exists = True

            updated = dn_update(sb, project_id, video_filename=filename)
            if not updated:
                if uploaded_object_exists and filename and filename != old_fn:
                    delete_daynight_from_s3(filename)
                return jsonify({'error': 'Failed to save upload metadata'}), 500
            if old_fn and old_fn != filename:
                delete_daynight_from_s3(old_fn)
            updated['media_url'] = get_daynight_s3_url(filename)
            updated['share_url'] = f"{(request.url_root or '').rstrip('/')}/daynight/view/{updated.get('share_token', '')}"
            return jsonify(updated)
        except Exception as e:
            current_app.logger.exception('Day/night video upload failed for project %s', project_id)
            if uploaded_object_exists and filename and filename != old_fn:
                delete_daynight_from_s3(filename)
            return jsonify({'error': f'Upload failed: {str(e)}'}), 500
        finally:
            if staged_file:
                try:
                    staged_file.close()
                except Exception:
                    pass

    @app.route('/api/daynight/<project_id>', methods=['DELETE'])
    @require_admin
    def api_delete_daynight(user_id, role, project_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        project = dn_get(sb, project_id)
        if not project:
            return jsonify({'error': 'Not found'}), 404
        if str(project.get('user_id')) != str(user_id) and role != 'superadmin':
            return jsonify({'error': 'Forbidden'}), 403
        if project.get('stitched_filename'):
            delete_daynight_from_s3(project['stitched_filename'])
        if project.get('video_filename'):
            delete_daynight_from_s3(project['video_filename'])
        dn_delete(sb, project_id)
        return jsonify({'success': True})

    @app.route('/daynight/preview/<share_token>')
    def daynight_preview_page(share_token):
        sb = get_supabase()
        if not sb:
            return "Database not configured", 503
        project = dn_get_by_token(sb, share_token)
        if not project:
            return "Not found", 404
        media_url = None
        if project.get('media_type') == 'image' and project.get('stitched_filename'):
            media_url = get_daynight_s3_url(project['stitched_filename'])
        elif project.get('media_type') == 'video' and project.get('video_filename'):
            media_url = get_daynight_s3_url(project['video_filename'])
        if not media_url:
            return "Media not yet uploaded", 404
        return render_template(
            'daynight_preview.html',
            project=project,
            media_url=media_url,
            media_type=project.get('media_type'),
            stitched_width=project.get('stitched_width', 0),
            stitched_height=project.get('stitched_height', 0),
            drag_speed=project.get('drag_speed') or 80,
            **auth_ctx(),
        )

    @app.route('/api/daynight/<project_id>/settings', methods=['POST'])
    @require_admin
    def api_daynight_save_settings(user_id, role, project_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        project = dn_get(sb, project_id)
        if not project:
            return jsonify({'error': 'Not found'}), 404
        if str(project.get('user_id')) != str(user_id) and role != 'superadmin':
            return jsonify({'error': 'Forbidden'}), 403
        data = request.get_json(silent=True) or {}
        drag_speed = data.get('drag_speed')
        if drag_speed is not None:
            try:
                drag_speed = float(drag_speed)
                if drag_speed < 10 or drag_speed > 500:
                    return jsonify({'error': 'drag_speed must be between 10 and 500'}), 400
            except (ValueError, TypeError):
                return jsonify({'error': 'Invalid drag_speed'}), 400
            dn_update(sb, project_id, drag_speed=drag_speed)
        updated = dn_get(sb, project_id)
        return jsonify(updated or {'success': True})

    @app.route('/daynight/view/<share_token>')
    def daynight_customer_view(share_token):
        sb = get_supabase()
        if not sb:
            return "Database not configured", 503
        project = dn_get_by_token(sb, share_token)
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
        )
