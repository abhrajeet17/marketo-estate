"""
Media delivery: panorama files (/uploads) and plot / marker images.

Bytes are never re-encoded here. Objects in storage are either redirected to (signed URL) or
streamed through in small chunks, so a large image never sits whole in worker memory.
"""

from flask import Response, current_app, jsonify, redirect, request, send_from_directory, stream_with_context

from app.config import SUPABASE_S3_BUCKET, SUPABASE_S3_SIGNED_URL_TTL
from app.core.auth import require_auth
from app.core.database import get_supabase
from app.services.panorama_service import get_panorama_by_id, get_panorama_with_access
from app.services.storage_service import (
    MAX_PANORAMA_OPTIMIZED_READ_BYTES,
    ensure_panorama_thumb,
    generate_panorama_optimized_bytes,
    get_panorama_optimized_s3_url,
    get_panorama_s3_url,
    get_panorama_thumb_s3_url,
    get_s3_client,
    marker_object_key,
    marker_thumb_object_key,
    panorama_object_key,
    plot_object_key,
    signed_url_reuse_seconds,
    upload_panorama_optimized_to_s3,
)

STREAM_CHUNK_BYTES = 64 * 1024
MEDIA_CACHE_CONTROL = 'private, max-age=900'


def _read_object(client, key, max_bytes):
    obj = client.get_object(Bucket=SUPABASE_S3_BUCKET, Key=key)
    body = obj.get('Body')
    if not body:
        return b''
    try:
        return body.read(max_bytes)
    finally:
        try:
            body.close()
        except Exception:
            pass


def stream_s3_object(client, key, fallback_content_type='image/jpeg'):
    """Stream a storage object to the client unchanged.

    Returns None when the object is missing. Honours If-None-Match so a browser revalidating
    an image it already holds gets a 304 instead of the whole file again.
    """
    params = {'Bucket': SUPABASE_S3_BUCKET, 'Key': key}
    if_none_match = request.headers.get('If-None-Match')
    if if_none_match:
        params['IfNoneMatch'] = if_none_match
    try:
        obj = client.get_object(**params)
    except Exception as exc:
        status = ((getattr(exc, 'response', None) or {}).get('ResponseMetadata') or {}).get('HTTPStatusCode')
        if if_none_match and status == 304:
            resp = Response(status=304)
            resp.headers['ETag'] = if_none_match
            resp.headers['Cache-Control'] = MEDIA_CACHE_CONTROL
            return resp
        return None
    body = obj.get('Body')

    def generate():
        try:
            if body:
                for chunk in body.iter_chunks(STREAM_CHUNK_BYTES):
                    yield chunk
        finally:
            try:
                if body:
                    body.close()
            except Exception:
                pass

    resp = Response(stream_with_context(generate()), mimetype=str(obj.get('ContentType') or fallback_content_type))
    if obj.get('ContentLength') is not None:
        resp.headers['Content-Length'] = str(obj['ContentLength'])
    if obj.get('ETag'):
        resp.headers['ETag'] = obj['ETag']
    resp.headers['Cache-Control'] = MEDIA_CACHE_CONTROL
    return resp


def _signed_redirect(url):
    resp = redirect(url, code=302)
    # Never let the browser keep the redirect longer than the signed URL stays valid.
    resp.headers['Cache-Control'] = f'private, max-age={signed_url_reuse_seconds()}'
    return resp


def _fetch_plot_image_row(sb, plot_id):
    # The owning panorama comes embedded (plots.panorama_id FK) so the existence / owner check
    # needs no second round-trip.
    try:
        return sb.table('plots').select('panorama_id, image_filename, image_content_type, panoramas(id, user_id)').eq('id', plot_id).limit(1).execute()
    except Exception:
        pass
    try:
        return sb.table('plots').select('panorama_id, image_filename, image_content_type').eq('id', plot_id).limit(1).execute()
    except Exception as e:
        if 'image_content_type' in str(e).lower():
            return sb.table('plots').select('panorama_id, image_filename').eq('id', plot_id).limit(1).execute()
        raise


def _fetch_marker_image_row(sb, marker_id):
    return sb.table('plot_markers').select('id, plot_id, image_filename').eq('id', marker_id).limit(1).execute()


def _marker_image_response(client, image_filename):
    if request.args.get('size') == 'thumb':
        thumb_key = marker_thumb_object_key(image_filename)
        if thumb_key:
            resp = stream_s3_object(client, thumb_key)
            if resp is not None:
                return resp
    resp = stream_s3_object(client, marker_object_key(image_filename))
    if resp is None:
        return jsonify({'error': 'Image not found'}), 404
    return resp


def register_media_routes(app):
    @app.route('/uploads/<filename>')
    def uploaded_file(filename):
        size = request.args.get('size', '').strip().lower()
        use_thumb = size == 'thumb'
        use_optimized = size == 'optimized'
        opt_cache_ttl = max(int(SUPABASE_S3_SIGNED_URL_TTL), 3600)
        if use_thumb:
            thumb_url = get_panorama_thumb_s3_url(filename)
            if thumb_url:
                return _signed_redirect(thumb_url)
            # Missing thumbnail (older or very large uploads): build it once from the original.
            try:
                thumb_bytes = ensure_panorama_thumb(filename)
            except Exception:
                thumb_bytes = None
            if thumb_bytes:
                return Response(thumb_bytes, mimetype='image/jpeg', headers={'Cache-Control': 'private, max-age=86400'})
        if use_optimized:
            opt_url = get_panorama_optimized_s3_url(filename)
            if opt_url:
                return _signed_redirect(opt_url)
            client = get_s3_client()
            if client:
                try:
                    data = _read_object(client, panorama_object_key(filename), MAX_PANORAMA_OPTIMIZED_READ_BYTES)
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
            return _signed_redirect(s3_url)
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

    @app.route('/api/public/plots/<int:plot_id>/image', methods=['GET'])
    def public_get_plot_image(plot_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        try:
            pl = _fetch_plot_image_row(sb, plot_id)
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
        if panorama_id is None or not (row.get('panoramas') or get_panorama_by_id(sb, panorama_id)):
            return jsonify({'error': 'Not found'}), 404
        image_filename = row.get('image_filename') or ''
        if not image_filename:
            return jsonify({'error': 'No image'}), 404
        client = get_s3_client()
        if not client:
            return jsonify({'error': 'Supabase S3 is not configured'}), 503
        resp = stream_s3_object(client, plot_object_key(image_filename), row.get('image_content_type') or 'image/jpeg')
        if resp is None:
            return jsonify({'error': 'Image not found'}), 404
        return resp

    @app.route('/api/plots/<int:plot_id>/image', methods=['GET'])
    @require_auth
    def get_plot_image(user_id, role, plot_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        try:
            pl = _fetch_plot_image_row(sb, plot_id)
            if not pl.data or len(pl.data) == 0:
                return jsonify({'error': 'Plot not found'}), 404
            row = pl.data[0]
            panorama_id = row['panorama_id']
        except Exception as e:
            msg = str(e).lower()
            if 'image_filename' in msg and ('does not exist' in msg or 'column' in msg):
                return jsonify({'error': 'image_filename column missing. Run db/schema.sql in Supabase SQL Editor.'}), 503
            return jsonify({'error': 'Not found'}), 404
        owner = str((row.get('panoramas') or {}).get('user_id') or '') == str(user_id)
        if not owner:
            panorama, _ = get_panorama_with_access(sb, panorama_id, user_id)
            if not panorama:
                return jsonify({'error': 'Forbidden'}), 403
        image_filename = row.get('image_filename') or ''
        if not image_filename:
            return jsonify({'error': 'No image'}), 404
        client = get_s3_client()
        if not client:
            return jsonify({'error': 'Supabase S3 is not configured'}), 503
        resp = stream_s3_object(client, plot_object_key(image_filename), row.get('image_content_type') or 'image/jpeg')
        if resp is None:
            return jsonify({'error': 'Image not found'}), 404
        return resp

    @app.route('/api/public/markers/<marker_id>/image', methods=['GET'])
    def public_get_marker_image(marker_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        try:
            r = _fetch_marker_image_row(sb, marker_id)
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
        return _marker_image_response(client, image_filename)

    @app.route('/api/markers/<marker_id>/image', methods=['GET'])
    @require_auth
    def get_marker_image(user_id, role, marker_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        try:
            r = _fetch_marker_image_row(sb, marker_id)
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
        return _marker_image_response(client, image_filename)
