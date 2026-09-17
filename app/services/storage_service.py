"""
S3/Storage: client, object keys, signed URLs, thumbnails, upload/delete.
No Flask dependency; callers pass config or use app.config.
"""
import io
import os
import tempfile
import time

from PIL import Image

try:
    import boto3
    from botocore.config import Config as BotoConfig
    from botocore.exceptions import ClientError as BotoClientError
except Exception:
    boto3 = None
    BotoConfig = None
    BotoClientError = None

from app import config as app_config

RESAMPLE_LANCZOS = Image.Resampling.LANCZOS if hasattr(Image, 'Resampling') else Image.LANCZOS
EXIF_ORIENTATION_TAG = 274

_s3_client = None
_s3_signed_url_cache = {}


def _s3_tls_verify_setting():
    """TLS verify for boto3 S3 (Supabase storage). Matches app/core/database.py SUPABASE_SSL_VERIFY."""
    if os.environ.get('SUPABASE_SSL_VERIFY', 'true').lower() in ('false', '0', 'no'):
        return False
    ca = os.environ.get('SUPABASE_S3_CA_BUNDLE', '').strip()
    if ca and os.path.isfile(ca):
        return ca
    return True

PANORAMA_THUMB_MAX_DIMENSION = 400
PANORAMA_THUMB_JPEG_QUALITY = 82
MAX_PANORAMA_THUMB_READ_BYTES = int(os.environ.get('MAX_PANORAMA_THUMB_READ_BYTES', str(20 * 1024 * 1024)))  # 20MB
MAX_PANORAMA_OPTIMIZED_READ_BYTES = int(os.environ.get('MAX_PANORAMA_OPTIMIZED_READ_BYTES', str(50 * 1024 * 1024)))  # 50MB
MAX_DAYNIGHT_IMAGE_READ_BYTES = int(os.environ.get('MAX_DAYNIGHT_IMAGE_READ_BYTES', str(50 * 1024 * 1024)))  # 50MB per image
DAYNIGHT_STITCH_JPEG_QUALITY = 92
MARKER_IMAGE_MAX_DIMENSION = 1200
MARKER_IMAGE_THUMB_SIZE = 200
MARKER_IMAGE_JPEG_QUALITY = 85


def use_s3():
    return bool(app_config.SUPABASE_S3_BUCKET)


def get_s3_client():
    global _s3_client
    if not use_s3():
        return None
    if not boto3:
        return None
    if not app_config.SUPABASE_S3_ENDPOINT or not app_config.SUPABASE_S3_REGION:
        return None
    if not app_config.SUPABASE_S3_BUCKET:
        return None
    if not app_config.SUPABASE_S3_ACCESS_KEY_ID or not app_config.SUPABASE_S3_SECRET_ACCESS_KEY:
        return None
    if _s3_client is None:
        kwargs = {
            'service_name': 's3',
            'endpoint_url': app_config.SUPABASE_S3_ENDPOINT,
            'region_name': app_config.SUPABASE_S3_REGION,
            'aws_access_key_id': app_config.SUPABASE_S3_ACCESS_KEY_ID,
            'aws_secret_access_key': app_config.SUPABASE_S3_SECRET_ACCESS_KEY,
        }
        verify = _s3_tls_verify_setting()
        if verify is not True:
            kwargs['verify'] = verify
        if BotoConfig:
            kwargs['config'] = BotoConfig(
                signature_version='s3v4',
                s3={'addressing_style': 'path'},
                connect_timeout=5,
                read_timeout=120,
                retries={'max_attempts': 6, 'mode': 'standard'},
            )
        _s3_client = boto3.client(**kwargs)
    return _s3_client


def panorama_object_key(filename):
    safe_name = os.path.basename(filename or '').strip()
    if app_config.SUPABASE_S3_PANORAMA_PREFIX:
        return f"{app_config.SUPABASE_S3_PANORAMA_PREFIX}/{safe_name}"
    return safe_name


def panorama_thumb_object_key(filename):
    base = os.path.basename(filename or '').strip()
    if not base:
        return None
    name, ext = os.path.splitext(base)
    thumb_name = f"{name}_thumb.jpg"
    if app_config.SUPABASE_S3_PANORAMA_PREFIX:
        return f"{app_config.SUPABASE_S3_PANORAMA_PREFIX}/{thumb_name}"
    return thumb_name


def generate_panorama_thumb_bytes(raw_bytes):
    if not raw_bytes or len(raw_bytes) > MAX_PANORAMA_THUMB_READ_BYTES:
        return None
    try:
        img = Image.open(io.BytesIO(raw_bytes))
        img = img.convert('RGB')
    except Exception:
        return None
    w, h = img.size
    if w == 0 or h == 0:
        return None
    if max(w, h) <= PANORAMA_THUMB_MAX_DIMENSION:
        tw, th = w, h
    else:
        ratio = PANORAMA_THUMB_MAX_DIMENSION / float(max(w, h))
        tw = max(1, int(w * ratio))
        th = max(1, int(h * ratio))
    img_thumb = img.resize((tw, th), RESAMPLE_LANCZOS)
    buf = io.BytesIO()
    try:
        img_thumb.save(buf, 'JPEG', quality=PANORAMA_THUMB_JPEG_QUALITY, optimize=True, progressive=True)
    except Exception:
        return None
    return buf.getvalue()


def panorama_optimized_object_key(filename):
    base = os.path.basename(filename or '').strip()
    if not base:
        return None
    name, _ext = os.path.splitext(base)
    opt_name = f"{name}_optimized.jpg"
    if app_config.SUPABASE_S3_PANORAMA_PREFIX:
        return f"{app_config.SUPABASE_S3_PANORAMA_PREFIX}/{opt_name}"
    return opt_name


def generate_panorama_optimized_bytes(raw_bytes):
    if not raw_bytes or len(raw_bytes) > MAX_PANORAMA_OPTIMIZED_READ_BYTES:
        return None
    try:
        img = Image.open(io.BytesIO(raw_bytes))
    except Exception:
        return None
    w, h = img.size
    if w == 0 or h == 0:
        return None
    try:
        exif = img.getexif()
        orientation = exif.get(EXIF_ORIENTATION_TAG)
        if orientation == 3:
            img = img.rotate(180, expand=True)
        elif orientation == 6:
            img = img.rotate(270, expand=True)
        elif orientation == 8:
            img = img.rotate(90, expand=True)
    except Exception:
        pass
    img = img.convert('RGB')
    buf = io.BytesIO()
    try:
        img.save(buf, 'JPEG', quality='keep', optimize=True, progressive=True)
    except Exception:
        try:
            buf = io.BytesIO()
            img.save(buf, 'JPEG', quality=95, optimize=True, progressive=True, subsampling='keep')
        except Exception:
            try:
                buf = io.BytesIO()
                img.save(buf, 'JPEG', quality=95, optimize=True, progressive=True)
            except Exception:
                return None
    result = buf.getvalue()
    if len(result) >= len(raw_bytes):
        return None
    return result


def upload_panorama_optimized_to_s3(filename, opt_bytes):
    if not opt_bytes:
        return
    client = get_s3_client()
    if not client:
        return
    key = panorama_optimized_object_key(filename)
    if not key:
        return
    try:
        client.put_object(
            Bucket=app_config.SUPABASE_S3_BUCKET,
            Key=key,
            Body=opt_bytes,
            ContentType='image/jpeg',
        )
    except Exception:
        pass


def get_panorama_optimized_s3_url(filename):
    client = get_s3_client()
    if not client or not filename:
        return None
    key = panorama_optimized_object_key(filename)
    if not key:
        return None
    now = time.time()
    cached = _s3_signed_url_cache.get(key)
    if cached:
        url, expires_at = cached
        if url and expires_at and now < (expires_at - 30):
            return url
    try:
        client.head_object(Bucket=app_config.SUPABASE_S3_BUCKET, Key=key)
    except Exception:
        return None
    url = client.generate_presigned_url(
        ClientMethod='get_object',
        Params={'Bucket': app_config.SUPABASE_S3_BUCKET, 'Key': key},
        ExpiresIn=app_config.SUPABASE_S3_SIGNED_URL_TTL,
    )
    try:
        _s3_signed_url_cache[key] = (url, now + float(app_config.SUPABASE_S3_SIGNED_URL_TTL))
    except Exception:
        pass
    return url


def upload_panorama_thumb_to_s3(filename, thumb_bytes):
    if not thumb_bytes:
        return
    client = get_s3_client()
    if not client:
        return
    key = panorama_thumb_object_key(filename)
    if not key:
        return
    try:
        client.put_object(
            Bucket=app_config.SUPABASE_S3_BUCKET,
            Key=key,
            Body=thumb_bytes,
            ContentType='image/jpeg',
        )
    except Exception:
        pass


def get_panorama_thumb_s3_url(filename):
    client = get_s3_client()
    if not client or not filename:
        return None
    key = panorama_thumb_object_key(filename)
    if not key:
        return None
    try:
        client.head_object(Bucket=app_config.SUPABASE_S3_BUCKET, Key=key)
    except Exception:
        return None
    return client.generate_presigned_url(
        ClientMethod='get_object',
        Params={'Bucket': app_config.SUPABASE_S3_BUCKET, 'Key': key},
        ExpiresIn=app_config.SUPABASE_S3_SIGNED_URL_TTL,
    )


def plot_object_key(filename):
    safe_name = os.path.basename(filename or '').strip()
    if app_config.SUPABASE_S3_PLOT_PREFIX:
        return f"{app_config.SUPABASE_S3_PLOT_PREFIX}/{safe_name}"
    return safe_name


def marker_object_key(filename):
    safe_name = os.path.basename(filename or '').strip()
    if app_config.SUPABASE_S3_MARKER_PREFIX:
        return f"{app_config.SUPABASE_S3_MARKER_PREFIX}/{safe_name}"
    return safe_name


def marker_thumb_object_key(filename):
    base = os.path.basename(filename or '').strip()
    if not base:
        return None
    name, ext = os.path.splitext(base)
    thumb_name = f"{name}_thumb.jpg"
    if app_config.SUPABASE_S3_MARKER_PREFIX:
        return f"{app_config.SUPABASE_S3_MARKER_PREFIX}/{thumb_name}"
    return thumb_name


def compress_marker_image(raw_bytes):
    if not raw_bytes:
        return None
    try:
        img = Image.open(io.BytesIO(raw_bytes))
        img = img.convert('RGB')
    except Exception:
        return None
    w, h = img.size
    if w == 0 or h == 0:
        return None
    if max(w, h) > MARKER_IMAGE_MAX_DIMENSION:
        ratio = MARKER_IMAGE_MAX_DIMENSION / float(max(w, h))
        new_w = max(1, int(w * ratio))
        new_h = max(1, int(h * ratio))
        img_full = img.resize((new_w, new_h), RESAMPLE_LANCZOS)
    else:
        img_full = img
    if max(img_full.size) > MARKER_IMAGE_THUMB_SIZE:
        ratio = MARKER_IMAGE_THUMB_SIZE / float(max(img_full.size))
        tw = max(1, int(img_full.size[0] * ratio))
        th = max(1, int(img_full.size[1] * ratio))
        img_thumb = img_full.resize((tw, th), RESAMPLE_LANCZOS)
    else:
        img_thumb = img_full
    buf_full = io.BytesIO()
    buf_thumb = io.BytesIO()
    try:
        img_full.save(buf_full, 'JPEG', quality=MARKER_IMAGE_JPEG_QUALITY, optimize=True)
        img_thumb.save(buf_thumb, 'JPEG', quality=MARKER_IMAGE_JPEG_QUALITY, optimize=True)
    except Exception:
        return None
    return buf_full.getvalue(), buf_thumb.getvalue()


def upload_panorama_to_s3(filename, raw_bytes, content_type):
    client = get_s3_client()
    if not client:
        missing = []
        if not boto3:
            missing.append('boto3')
        if not app_config.SUPABASE_S3_ENDPOINT:
            missing.append('SUPABASE_S3_ENDPOINT')
        if not app_config.SUPABASE_S3_BUCKET:
            missing.append('SUPABASE_S3_BUCKET')
        hint = f" Missing: {', '.join(missing)}" if missing else ''
        raise RuntimeError(f'Supabase S3 is not fully configured.{hint}')
    key = panorama_object_key(filename)
    if hasattr(raw_bytes, 'read'):
        try:
            raw_bytes.seek(0)
        except Exception:
            pass
        if hasattr(client, 'upload_fileobj'):
            client.upload_fileobj(
                raw_bytes,
                app_config.SUPABASE_S3_BUCKET,
                key,
                ExtraArgs={'ContentType': content_type},
            )
            return
    client.put_object(
        Bucket=app_config.SUPABASE_S3_BUCKET,
        Key=key,
        Body=raw_bytes,
        ContentType=content_type,
    )


def read_uploaded_file_bytes(file_storage, max_bytes):
    if not file_storage:
        return b''
    stream = getattr(file_storage, 'stream', None) or file_storage
    try:
        stream.seek(0)
    except Exception:
        pass
    cap = int(max_bytes) if max_bytes else 0
    if cap > 0:
        data = stream.read(cap + 1)
        if data and len(data) > cap:
            raise ValueError('file_too_large')
        return data or b''
    return stream.read() or b''


def buffer_uploaded_file(file_storage, max_bytes, chunk_size=1024 * 1024):
    if not file_storage:
        return None, 0
    stream = getattr(file_storage, 'stream', None) or file_storage
    try:
        stream.seek(0)
    except Exception:
        pass
    cap = int(max_bytes) if max_bytes else 0
    spool_limit = 8 * 1024 * 1024
    if cap > 0:
        spool_limit = max(1024 * 1024, min(spool_limit, cap))
    staged = tempfile.SpooledTemporaryFile(max_size=spool_limit)
    total = 0
    try:
        while True:
            chunk = stream.read(chunk_size)
            if not chunk:
                break
            total += len(chunk)
            if cap > 0 and total > cap:
                raise ValueError('file_too_large')
            staged.write(chunk)
        staged.seek(0)
        return staged, total
    except Exception:
        try:
            staged.close()
        except Exception:
            pass
        raise


def get_panorama_s3_url(filename):
    client = get_s3_client()
    if not client:
        return None
    key = panorama_object_key(filename)
    now = time.time()
    cached = _s3_signed_url_cache.get(key)
    if cached:
        url, expires_at = cached
        if url and expires_at and now < (expires_at - 30):
            return url
    try:
        client.head_object(Bucket=app_config.SUPABASE_S3_BUCKET, Key=key)
    except Exception:
        return None
    url = client.generate_presigned_url(
        ClientMethod='get_object',
        Params={'Bucket': app_config.SUPABASE_S3_BUCKET, 'Key': key},
        ExpiresIn=app_config.SUPABASE_S3_SIGNED_URL_TTL,
    )
    try:
        _s3_signed_url_cache[key] = (url, now + float(app_config.SUPABASE_S3_SIGNED_URL_TTL))
    except Exception:
        pass
    return url


def delete_panorama_from_s3(filename):
    client = get_s3_client()
    if not client:
        return
    try:
        client.delete_object(Bucket=app_config.SUPABASE_S3_BUCKET, Key=panorama_object_key(filename))
    except Exception:
        pass


def get_plot_s3_url(filename):
    client = get_s3_client()
    if not client or not filename:
        return None
    key = plot_object_key(filename)
    try:
        client.head_object(Bucket=app_config.SUPABASE_S3_BUCKET, Key=key)
    except Exception:
        return None
    return client.generate_presigned_url(
        ClientMethod='get_object',
        Params={'Bucket': app_config.SUPABASE_S3_BUCKET, 'Key': key},
        ExpiresIn=app_config.SUPABASE_S3_SIGNED_URL_TTL,
    )


def get_marker_s3_url(filename):
    client = get_s3_client()
    if not client or not filename:
        return None
    key = marker_object_key(filename)
    try:
        client.head_object(Bucket=app_config.SUPABASE_S3_BUCKET, Key=key)
    except Exception:
        return None
    return client.generate_presigned_url(
        ClientMethod='get_object',
        Params={'Bucket': app_config.SUPABASE_S3_BUCKET, 'Key': key},
        ExpiresIn=app_config.SUPABASE_S3_SIGNED_URL_TTL,
    )


def delete_plot_from_s3(filename):
    client = get_s3_client()
    if not client or not filename:
        return
    try:
        client.delete_object(Bucket=app_config.SUPABASE_S3_BUCKET, Key=plot_object_key(filename))
    except Exception:
        pass


def delete_marker_from_s3(filename):
    client = get_s3_client()
    if not client or not filename:
        return
    try:
        client.delete_object(Bucket=app_config.SUPABASE_S3_BUCKET, Key=marker_object_key(filename))
    except Exception:
        pass


def voiceover_object_key(filename):
    safe_name = os.path.basename(filename or '').strip()
    if app_config.SUPABASE_S3_VOICEOVER_PREFIX:
        return f"{app_config.SUPABASE_S3_VOICEOVER_PREFIX}/{safe_name}"
    return safe_name


def get_voiceover_s3_url(filename):
    client = get_s3_client()
    if not client or not filename:
        return None
    key = voiceover_object_key(filename)
    try:
        client.head_object(Bucket=app_config.SUPABASE_S3_BUCKET, Key=key)
    except Exception:
        return None
    return client.generate_presigned_url(
        ClientMethod='get_object',
        Params={'Bucket': app_config.SUPABASE_S3_BUCKET, 'Key': key},
        ExpiresIn=app_config.SUPABASE_S3_SIGNED_URL_TTL,
    )


def delete_voiceover_from_s3(filename):
    client = get_s3_client()
    if not client or not filename:
        return
    try:
        client.delete_object(Bucket=app_config.SUPABASE_S3_BUCKET, Key=voiceover_object_key(filename))
    except Exception:
        pass


def panorama_audio_object_key(filename):
    safe_name = os.path.basename(filename or '').strip()
    if app_config.SUPABASE_S3_PANORAMA_AUDIO_PREFIX:
        return f"{app_config.SUPABASE_S3_PANORAMA_AUDIO_PREFIX}/{safe_name}"
    return safe_name


def get_panorama_audio_s3_url(filename):
    client = get_s3_client()
    if not client or not filename:
        return None
    key = panorama_audio_object_key(filename)
    try:
        client.head_object(Bucket=app_config.SUPABASE_S3_BUCKET, Key=key)
    except Exception:
        return None
    return client.generate_presigned_url(
        ClientMethod='get_object',
        Params={'Bucket': app_config.SUPABASE_S3_BUCKET, 'Key': key},
        ExpiresIn=app_config.SUPABASE_S3_SIGNED_URL_TTL,
    )


def delete_panorama_audio_from_s3(filename):
    client = get_s3_client()
    if not client or not filename:
        return
    try:
        client.delete_object(Bucket=app_config.SUPABASE_S3_BUCKET, Key=panorama_audio_object_key(filename))
    except Exception:
        pass


MAX_PANORAMA_AUDIO_BYTES = 20 * 1024 * 1024


def probe_image_dimensions(stream):
    """Return (width, height) without full decode."""
    try:
        stream.seek(0)
    except Exception:
        pass
    with Image.open(stream) as img:
        width, height = img.size
        try:
            exif = img.getexif()
            orientation = exif.get(EXIF_ORIENTATION_TAG)
            if orientation in (5, 6, 7, 8):
                width, height = height, width
        except Exception:
            pass
    return int(width or 0), int(height or 0)


# ---------------------------------------------------------------------------
# Day Night project helpers
# ---------------------------------------------------------------------------

def daynight_object_key(filename):
    safe_name = os.path.basename(filename or '').strip()
    if app_config.SUPABASE_S3_DAYNIGHT_PREFIX:
        return f"{app_config.SUPABASE_S3_DAYNIGHT_PREFIX}/{safe_name}"
    return safe_name


def upload_daynight_to_s3(filename, raw_bytes, content_type):
    client = get_s3_client()
    if not client:
        raise RuntimeError('S3 not configured')
    key = daynight_object_key(filename)
    if hasattr(raw_bytes, 'read'):
        try:
            raw_bytes.seek(0)
        except Exception:
            pass
        if hasattr(client, 'upload_fileobj'):
            client.upload_fileobj(
                raw_bytes,
                app_config.SUPABASE_S3_BUCKET,
                key,
                ExtraArgs={'ContentType': content_type},
            )
            return
    client.put_object(
        Bucket=app_config.SUPABASE_S3_BUCKET,
        Key=key,
        Body=raw_bytes,
        ContentType=content_type,
    )


def get_daynight_s3_url(filename):
    client = get_s3_client()
    if not client or not filename:
        return None
    key = daynight_object_key(filename)
    now = time.time()
    cached = _s3_signed_url_cache.get(key)
    if cached:
        url, expires_at = cached
        if url and expires_at and now < (expires_at - 30):
            return url
    try:
        client.head_object(Bucket=app_config.SUPABASE_S3_BUCKET, Key=key)
    except Exception:
        return None
    url = client.generate_presigned_url(
        ClientMethod='get_object',
        Params={'Bucket': app_config.SUPABASE_S3_BUCKET, 'Key': key},
        ExpiresIn=app_config.SUPABASE_S3_SIGNED_URL_TTL,
    )
    try:
        _s3_signed_url_cache[key] = (url, now + float(app_config.SUPABASE_S3_SIGNED_URL_TTL))
    except Exception:
        pass
    return url


def delete_daynight_from_s3(filename):
    client = get_s3_client()
    if not client or not filename:
        return
    try:
        client.delete_object(Bucket=app_config.SUPABASE_S3_BUCKET, Key=daynight_object_key(filename))
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Floor Plan helpers (WebP lossless for transparent PNGs)
# ---------------------------------------------------------------------------

FLOORPLAN_MAX_DIMENSION = 2400
MAX_FLOORPLAN_READ_BYTES = int(os.environ.get('MAX_FLOORPLAN_READ_BYTES', str(30 * 1024 * 1024)))  # 30MB


def floorplan_object_key(filename):
    safe_name = os.path.basename(filename or '').strip()
    if app_config.SUPABASE_S3_FLOORPLAN_PREFIX:
        return f"{app_config.SUPABASE_S3_FLOORPLAN_PREFIX}/{safe_name}"
    return safe_name


def convert_floorplan_to_webp_lossless(raw_bytes):
    """Convert uploaded image to WebP lossless, preserving transparency.
    Returns (webp_bytes, width, height) or (None, 0, 0).
    """
    if not raw_bytes or len(raw_bytes) > MAX_FLOORPLAN_READ_BYTES:
        return None, 0, 0
    try:
        img = Image.open(io.BytesIO(raw_bytes))
    except Exception:
        return None, 0, 0
    # Handle EXIF orientation
    try:
        exif = img.getexif()
        orientation = exif.get(EXIF_ORIENTATION_TAG)
        if orientation == 3:
            img = img.rotate(180, expand=True)
        elif orientation == 6:
            img = img.rotate(270, expand=True)
        elif orientation == 8:
            img = img.rotate(90, expand=True)
    except Exception:
        pass
    # Preserve alpha channel (RGBA) for background-removed images
    if img.mode not in ('RGBA', 'LA', 'PA'):
        img = img.convert('RGBA')
    else:
        img = img.convert('RGBA')
    w, h = img.size
    # Scale down if needed
    if max(w, h) > FLOORPLAN_MAX_DIMENSION:
        ratio = FLOORPLAN_MAX_DIMENSION / float(max(w, h))
        w = max(1, int(w * ratio))
        h = max(1, int(h * ratio))
        img = img.resize((w, h), RESAMPLE_LANCZOS)
    buf = io.BytesIO()
    try:
        img.save(buf, 'WEBP', lossless=True, quality=100, method=6)
    except Exception:
        return None, 0, 0
    return buf.getvalue(), w, h


def upload_floorplan_to_s3(filename, raw_bytes, content_type='image/webp'):
    client = get_s3_client()
    if not client:
        raise RuntimeError('S3 not configured')
    key = floorplan_object_key(filename)
    client.put_object(
        Bucket=app_config.SUPABASE_S3_BUCKET,
        Key=key,
        Body=raw_bytes,
        ContentType=content_type,
    )


def get_floorplan_s3_url(filename):
    client = get_s3_client()
    if not client or not filename:
        return None
    key = floorplan_object_key(filename)
    now = time.time()
    cached = _s3_signed_url_cache.get(key)
    if cached:
        url, expires_at = cached
        if url and expires_at and now < (expires_at - 30):
            return url
    try:
        client.head_object(Bucket=app_config.SUPABASE_S3_BUCKET, Key=key)
    except Exception:
        return None
    url = client.generate_presigned_url(
        ClientMethod='get_object',
        Params={'Bucket': app_config.SUPABASE_S3_BUCKET, 'Key': key},
        ExpiresIn=app_config.SUPABASE_S3_SIGNED_URL_TTL,
    )
    try:
        _s3_signed_url_cache[key] = (url, now + float(app_config.SUPABASE_S3_SIGNED_URL_TTL))
    except Exception:
        pass
    return url


def delete_floorplan_from_s3(filename):
    client = get_s3_client()
    if not client or not filename:
        return
    try:
        client.delete_object(Bucket=app_config.SUPABASE_S3_BUCKET, Key=floorplan_object_key(filename))
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Building Map helpers (optimised JPEG for building photos/panoramas)
# ---------------------------------------------------------------------------

BUILDING_MAP_MAX_DIMENSION = 4096
BUILDING_MAP_JPEG_QUALITY = 92
MAX_BUILDING_MAP_READ_BYTES = int(os.environ.get('MAX_BUILDING_MAP_READ_BYTES', str(50 * 1024 * 1024)))  # 50MB
MAX_SALES_MAP_READ_BYTES = int(os.environ.get('MAX_SALES_MAP_READ_BYTES', str(50 * 1024 * 1024)))  # 50MB
MAX_SALES_FLAT360_READ_BYTES = int(os.environ.get('MAX_SALES_FLAT360_READ_BYTES', str(80 * 1024 * 1024)))  # 80MB
SALES_FLAT360_MAX_DIMENSION = int(os.environ.get('SALES_FLAT360_MAX_DIMENSION', '8192'))
SALES_FLAT360_JPEG_QUALITY = int(os.environ.get('SALES_FLAT360_JPEG_QUALITY', '92'))


def building_map_object_key(filename):
    safe_name = os.path.basename(filename or '').strip()
    if app_config.SUPABASE_S3_BUILDING_MAP_PREFIX:
        return f"{app_config.SUPABASE_S3_BUILDING_MAP_PREFIX}/{safe_name}"
    return safe_name


def compress_building_map_image(raw_bytes):
    """Compress building photo to optimised progressive JPEG.
    Returns (jpeg_bytes, width, height) or (None, 0, 0).
    """
    if not raw_bytes or len(raw_bytes) > MAX_BUILDING_MAP_READ_BYTES:
        return None, 0, 0
    try:
        img = Image.open(io.BytesIO(raw_bytes))
    except Exception:
        return None, 0, 0
    # Handle EXIF orientation
    try:
        exif = img.getexif()
        orientation = exif.get(EXIF_ORIENTATION_TAG)
        if orientation == 3:
            img = img.rotate(180, expand=True)
        elif orientation == 6:
            img = img.rotate(270, expand=True)
        elif orientation == 8:
            img = img.rotate(90, expand=True)
    except Exception:
        pass
    img = img.convert('RGB')
    w, h = img.size
    if max(w, h) > BUILDING_MAP_MAX_DIMENSION:
        ratio = BUILDING_MAP_MAX_DIMENSION / float(max(w, h))
        w = max(1, int(w * ratio))
        h = max(1, int(h * ratio))
        img = img.resize((w, h), RESAMPLE_LANCZOS)
    buf = io.BytesIO()
    try:
        img.save(buf, 'JPEG', quality=BUILDING_MAP_JPEG_QUALITY, optimize=True, progressive=True)
    except Exception:
        return None, 0, 0
    return buf.getvalue(), w, h


def upload_building_map_to_s3(filename, raw_bytes, content_type='image/jpeg'):
    client = get_s3_client()
    if not client:
        raise RuntimeError('S3 not configured')
    key = building_map_object_key(filename)
    client.put_object(
        Bucket=app_config.SUPABASE_S3_BUCKET,
        Key=key,
        Body=raw_bytes,
        ContentType=content_type,
    )


def get_building_map_s3_url(filename):
    client = get_s3_client()
    if not client or not filename:
        return None
    key = building_map_object_key(filename)
    now = time.time()
    cached = _s3_signed_url_cache.get(key)
    if cached:
        url, expires_at = cached
        if url and expires_at and now < (expires_at - 30):
            return url
    try:
        client.head_object(Bucket=app_config.SUPABASE_S3_BUCKET, Key=key)
    except Exception:
        return None
    url = client.generate_presigned_url(
        ClientMethod='get_object',
        Params={'Bucket': app_config.SUPABASE_S3_BUCKET, 'Key': key},
        ExpiresIn=app_config.SUPABASE_S3_SIGNED_URL_TTL,
    )
    try:
        _s3_signed_url_cache[key] = (url, now + float(app_config.SUPABASE_S3_SIGNED_URL_TTL))
    except Exception:
        pass
    return url


def delete_building_map_from_s3(filename):
    client = get_s3_client()
    if not client or not filename:
        return
    try:
        client.delete_object(Bucket=app_config.SUPABASE_S3_BUCKET, Key=building_map_object_key(filename))
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Sales Route Map helpers (optimised JPEG for 2D map image uploads)
# ---------------------------------------------------------------------------

def sales_map_object_key(filename):
    safe_name = os.path.basename(filename or '').strip()
    if app_config.SUPABASE_S3_SALES_MAP_PREFIX:
        return f"{app_config.SUPABASE_S3_SALES_MAP_PREFIX}/{safe_name}"
    return safe_name


def compress_sales_map_image(raw_bytes):
    """Compress sales-route map image to optimised progressive JPEG."""
    if not raw_bytes or len(raw_bytes) > MAX_SALES_MAP_READ_BYTES:
        return None, 0, 0
    return compress_building_map_image(raw_bytes)


def upload_sales_map_to_s3(filename, raw_bytes, content_type='image/jpeg'):
    client = get_s3_client()
    if not client:
        raise RuntimeError('S3 not configured')
    key = sales_map_object_key(filename)
    client.put_object(
        Bucket=app_config.SUPABASE_S3_BUCKET,
        Key=key,
        Body=raw_bytes,
        ContentType=content_type,
    )


def get_sales_map_s3_url(filename):
    client = get_s3_client()
    if not client or not filename:
        return None
    key = sales_map_object_key(filename)
    now = time.time()
    cached = _s3_signed_url_cache.get(key)
    if cached:
        url, expires_at = cached
        if url and expires_at and now < (expires_at - 30):
            return url
    try:
        client.head_object(Bucket=app_config.SUPABASE_S3_BUCKET, Key=key)
    except Exception:
        return None
    url = client.generate_presigned_url(
        ClientMethod='get_object',
        Params={'Bucket': app_config.SUPABASE_S3_BUCKET, 'Key': key},
        ExpiresIn=app_config.SUPABASE_S3_SIGNED_URL_TTL,
    )
    try:
        _s3_signed_url_cache[key] = (url, now + float(app_config.SUPABASE_S3_SIGNED_URL_TTL))
    except Exception:
        pass
    return url


def delete_sales_map_from_s3(filename):
    client = get_s3_client()
    if not client or not filename:
        return
    try:
        client.delete_object(Bucket=app_config.SUPABASE_S3_BUCKET, Key=sales_map_object_key(filename))
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Sales Flat 360 helpers (optimised JPEG for horizontal drag viewer strips)
# ---------------------------------------------------------------------------

def sales_flat360_object_key(filename):
    safe_name = os.path.basename(filename or '').strip()
    if app_config.SUPABASE_S3_SALES_FLAT360_PREFIX:
        return f"{app_config.SUPABASE_S3_SALES_FLAT360_PREFIX}/{safe_name}"
    return safe_name


def compress_sales_flat360_image(raw_bytes):
    """Compress flat-360 strip image to optimised progressive JPEG.
    Returns (jpeg_bytes, width, height) or (None, 0, 0).
    """
    if not raw_bytes or len(raw_bytes) > MAX_SALES_FLAT360_READ_BYTES:
        return None, 0, 0
    try:
        img = Image.open(io.BytesIO(raw_bytes))
    except Exception:
        return None, 0, 0
    try:
        exif = img.getexif()
        orientation = exif.get(EXIF_ORIENTATION_TAG)
        if orientation == 3:
            img = img.rotate(180, expand=True)
        elif orientation == 6:
            img = img.rotate(270, expand=True)
        elif orientation == 8:
            img = img.rotate(90, expand=True)
    except Exception:
        pass
    img = img.convert('RGB')
    w, h = img.size
    if max(w, h) > SALES_FLAT360_MAX_DIMENSION:
        ratio = SALES_FLAT360_MAX_DIMENSION / float(max(w, h))
        w = max(1, int(w * ratio))
        h = max(1, int(h * ratio))
        img = img.resize((w, h), RESAMPLE_LANCZOS)
    buf = io.BytesIO()
    try:
        img.save(buf, 'JPEG', quality=SALES_FLAT360_JPEG_QUALITY, optimize=True, progressive=True)
    except Exception:
        return None, 0, 0
    return buf.getvalue(), w, h


def upload_sales_flat360_to_s3(filename, raw_bytes, content_type='image/jpeg'):
    client = get_s3_client()
    if not client:
        raise RuntimeError('S3 not configured')
    key = sales_flat360_object_key(filename)
    client.put_object(
        Bucket=app_config.SUPABASE_S3_BUCKET,
        Key=key,
        Body=raw_bytes,
        ContentType=content_type,
    )


def get_sales_flat360_s3_url(filename):
    client = get_s3_client()
    if not client or not filename:
        return None
    key = sales_flat360_object_key(filename)
    now = time.time()
    cached = _s3_signed_url_cache.get(key)
    if cached:
        url, expires_at = cached
        if url and expires_at and now < (expires_at - 30):
            return url
    try:
        client.head_object(Bucket=app_config.SUPABASE_S3_BUCKET, Key=key)
    except Exception:
        return None
    url = client.generate_presigned_url(
        ClientMethod='get_object',
        Params={'Bucket': app_config.SUPABASE_S3_BUCKET, 'Key': key},
        ExpiresIn=app_config.SUPABASE_S3_SIGNED_URL_TTL,
    )
    try:
        _s3_signed_url_cache[key] = (url, now + float(app_config.SUPABASE_S3_SIGNED_URL_TTL))
    except Exception:
        pass
    return url


def delete_sales_flat360_from_s3(filename):
    client = get_s3_client()
    if not client or not filename:
        return
    try:
        client.delete_object(Bucket=app_config.SUPABASE_S3_BUCKET, Key=sales_flat360_object_key(filename))
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Gallery helpers (images + videos)
# ---------------------------------------------------------------------------

MAX_GALLERY_READ_BYTES = int(os.environ.get('MAX_GALLERY_READ_BYTES', str(100 * 1024 * 1024)))  # allow large source uploads (e.g. 80MB); images are compressed down to SAFE limit

ALLOWED_GALLERY_IMAGE_EXT = {'png', 'jpg', 'jpeg', 'webp', 'gif'}
ALLOWED_GALLERY_VIDEO_EXT = {'mp4', 'webm', 'mov'}
GALLERY_IMAGE_CONTENT_TYPES = {
    'png': 'image/png',
    'jpg': 'image/jpeg',
    'jpeg': 'image/jpeg',
    'webp': 'image/webp',
    'gif': 'image/gif',
}
GALLERY_IMAGE_MAX_DIMENSION = int(os.environ.get('GALLERY_IMAGE_MAX_DIMENSION', '2400'))
GALLERY_JPEG_QUALITY = int(os.environ.get('GALLERY_JPEG_QUALITY', '88'))
GALLERY_WEBP_QUALITY = int(os.environ.get('GALLERY_WEBP_QUALITY', '90'))
# Supabase bucket limit is 50MB. Allow larger source uploads (e.g. 80MB) but ensure final delivered <= ~50MB.
GALLERY_MAX_DELIVERED_IMAGE_BYTES = int(os.environ.get('GALLERY_MAX_DELIVERED_IMAGE_BYTES', str(48 * 1024 * 1024)))
GALLERY_MAX_SAFE_UPLOAD_BYTES = int(os.environ.get('GALLERY_MAX_SAFE_UPLOAD_BYTES', str(50 * 1024 * 1024)))  # match Supabase storage limit (images compressed, videos as-is)
GALLERY_UPLOAD_RETRY_ATTEMPTS = max(1, int(os.environ.get('GALLERY_UPLOAD_RETRY_ATTEMPTS', '3')))
GALLERY_UPLOAD_RETRY_BASE_DELAY_SEC = max(0.1, float(os.environ.get('GALLERY_UPLOAD_RETRY_BASE_DELAY_SEC', '0.6')))


def gallery_object_key(filename):
    safe_name = os.path.basename(filename or '').strip()
    if app_config.SUPABASE_S3_GALLERY_PREFIX:
        return f"{app_config.SUPABASE_S3_GALLERY_PREFIX}/{safe_name}"
    return safe_name


def compress_gallery_image(raw_bytes, source_ext=''):
    """Resize (if needed) + lossless WebP re-encode for gallery images.

    Allows large source files (e.g. 80MB) while producing a final asset
    that fits Supabase's 50MB bucket limit. Uses lossless WebP after
    downscaling. Falls back to lower resolution or mild lossy only if
    absolutely necessary. GIFs are passed through (or re-encoded if resized).

    Returns (bytes, width, height, out_ext, out_content_type)
    or (None, 0, 0, '', '').
    """
    if not raw_bytes or len(raw_bytes) > MAX_GALLERY_READ_BYTES:
        return None, 0, 0, '', ''
    src_ext = str(source_ext or '').strip().lower().lstrip('.')
    try:
        img = Image.open(io.BytesIO(raw_bytes))
    except Exception:
        return None, 0, 0, '', ''
    w, h = img.size
    if w <= 0 or h <= 0:
        return None, 0, 0, '', ''

    # EXIF orientation
    try:
        exif = img.getexif()
        orientation = exif.get(EXIF_ORIENTATION_TAG)
        if orientation == 3:
            img = img.rotate(180, expand=True)
        elif orientation == 6:
            img = img.rotate(270, expand=True)
        elif orientation == 8:
            img = img.rotate(90, expand=True)
    except Exception:
        pass

    # Recompute after possible rotation
    w, h = img.size
    orig_w, orig_h = w, h

    # Resize if oversized
    if max(w, h) > GALLERY_IMAGE_MAX_DIMENSION:
        ratio = GALLERY_IMAGE_MAX_DIMENSION / float(max(w, h))
        new_w = max(1, int(w * ratio))
        new_h = max(1, int(h * ratio))
        img = img.resize((new_w, new_h), RESAMPLE_LANCZOS)
        w, h = img.size

    fmt = str(getattr(img, 'format', '') or '').strip().lower()
    is_gif = (src_ext == 'gif') or (fmt == 'gif')

    if is_gif:
        # Keep GIF as-is (passthrough original bytes to preserve animation if any)
        out_ext = 'gif'
        out_ct = 'image/gif'
        # Re-encode only if we resized (compare against original pre-resize dims)
        did_resize = (orig_w != w or orig_h != h)
        if did_resize:
            try:
                buf = io.BytesIO()
                save_img = img
                if img.mode not in ('P', 'RGBA', 'RGB'):
                    save_img = img.convert('RGBA')
                save_img.save(buf, 'GIF', optimize=True)
                out_bytes = buf.getvalue()
                return out_bytes, w, h, out_ext, out_ct
            except Exception:
                return None, 0, 0, '', ''
        return raw_bytes, w, h, out_ext, out_ct

    # For static images: use **lossless WebP** (user request) + resize.
    # Resize alone gives huge wins. Lossless WebP from an 80MB source can easily drop to <50MB
    # while preserving full quality (no generation loss).
    # Preserve alpha when present.
    has_alpha = img.mode in ('RGBA', 'LA', 'PA', 'P') and 'transparency' in (img.info or {})
    try:
        if has_alpha or img.mode == 'RGBA':
            img = img.convert('RGBA')
        else:
            img = img.convert('RGB')
    except Exception:
        pass

    target = GALLERY_MAX_DELIVERED_IMAGE_BYTES

    def _encode_lossless(current_img):
        b = io.BytesIO()
        current_img.save(b, 'WEBP', lossless=True, method=6)
        return b.getvalue()

    def _encode_lossy(current_img, q):
        b = io.BytesIO()
        current_img.save(b, 'WEBP', quality=q, method=6, lossless=False)
        return b.getvalue()

    try:
        current_img = img
        out_bytes = _encode_lossless(current_img)
        out_w, out_h = current_img.size

        # If still over the Supabase 50MB limit (very rare after 2400px), further downscale while staying lossless
        max_dim = GALLERY_IMAGE_MAX_DIMENSION
        while len(out_bytes) > target and max_dim > 700:
            max_dim = int(max_dim * 0.82)
            if max(current_img.size) <= max_dim:
                break
            ratio = max_dim / float(max(current_img.size))
            new_w = max(1, int(current_img.width * ratio))
            new_h = max(1, int(current_img.height * ratio))
            current_img = current_img.resize((new_w, new_h), RESAMPLE_LANCZOS)
            out_bytes = _encode_lossless(current_img)
            out_w, out_h = current_img.size
            if len(out_bytes) <= target:
                break

        # Absolute last resort: switch to lossy only if we still can't fit under limit losslessly
        if len(out_bytes) > target:
            for q in (85, 78, 70):
                candidate = _encode_lossy(current_img, q)
                if len(candidate) <= target or len(candidate) < len(out_bytes):
                    out_bytes = candidate
                if len(out_bytes) <= target:
                    break

        return out_bytes, out_w, out_h, 'webp', 'image/webp'
    except Exception:
        # JPEG fallback (lossy)
        try:
            if img.mode != 'RGB':
                img = img.convert('RGB')
            buf = io.BytesIO()
            img.save(buf, 'JPEG', quality=GALLERY_JPEG_QUALITY, optimize=True, progressive=True)
            out_bytes = buf.getvalue()
            if len(out_bytes) > target:
                for q in (82, 75, 68):
                    try:
                        buf = io.BytesIO()
                        img.save(buf, 'JPEG', quality=q, optimize=True, progressive=True)
                        candidate = buf.getvalue()
                        if len(candidate) < len(out_bytes):
                            out_bytes = candidate
                        if len(out_bytes) <= target:
                            break
                    except Exception:
                        pass
            return out_bytes, img.size[0], img.size[1], 'jpg', 'image/jpeg'
        except Exception:
            return None, 0, 0, '', ''


def _is_s3_tls_verification_error(exc):
    try:
        from botocore.exceptions import SSLError as BotoSSLError
        if isinstance(exc, BotoSSLError):
            return True
    except Exception:
        pass
    msg = (str(exc) or '').lower()
    return 'certificate verify failed' in msg or 'ssl' in msg and 'cert' in msg


def _is_transient_s3_error(exc):
    msg = (str(exc) or '').lower()
    markers = (
        'timed out',
        'timeout',
        'temporar',
        'service unavailable',
        'slowdown',
        'throttl',
        'too many requests',
        'requesttimeout',
        'internalerror',
        'connection',
        'connection reset',
        'connection aborted',
        'connection refused',
        'connection closed',
        'broken pipe',
        'reset by peer',
        'bad gateway',
        'gateway timeout',
        '503',
        '504',
    )
    if any(m in msg for m in markers):
        return True
    try:
        response = getattr(exc, 'response', None) or {}
        meta = response.get('ResponseMetadata') or {}
        status = int(meta.get('HTTPStatusCode') or 0)
        if status in (408, 429, 500, 502, 503, 504):
            return True
        err = response.get('Error') or {}
        code = str(err.get('Code') or '').strip().lower()
        if code in {
            'slowdown',
            'throttling',
            'requesttimeout',
            'requesttimeoutexception',
            'internalerror',
            'serviceunavailable',
            'unavailable',
            'gatewaytimeout',
        }:
            return True
    except Exception:
        pass
    return False


def _is_entity_too_large_error(exc):
    """Detect S3 EntityTooLarge (or equivalent) regardless of exact exception shape."""
    if not exc:
        return False
    try:
        # Check via botocore ClientError response
        if BotoClientError and isinstance(exc, BotoClientError):
            resp = getattr(exc, 'response', None) or {}
            err = resp.get('Error') or {}
            code = str(err.get('Code') or '').lower()
            if 'entity' in code and 'large' in code:
                return True
    except Exception:
        pass

    try:
        full = str(exc)
        fl = full.lower()
        if 'entitytoolarge' in fl or 'entity_too_large' in fl or 'entity too large' in fl:
            return True
        if 'exceeded the maximum allowed size' in fl:
            return True
        # Also catch the common boto message pattern
        if 'an error occurred (entitytoolarge)' in fl:
            return True
    except Exception:
        pass
    return False


def upload_gallery_to_s3(filename, raw_bytes, content_type='image/jpeg'):
    client = get_s3_client()
    if not client:
        raise RuntimeError('S3 not configured')
    key = gallery_object_key(filename)
    last_error = None

    # Prefer upload_fileobj (uses boto3 transfer manager + multipart for larger objects).
    # This avoids single PutObject limits on some storage backends.
    # Wrap plain bytes in BytesIO so the high-level uploader is always used.
    upload_stream = raw_bytes
    if not hasattr(upload_stream, 'read'):
        try:
            upload_stream = io.BytesIO(raw_bytes)
        except Exception:
            # Fall back to direct body if wrapping fails
            upload_stream = raw_bytes

    for attempt in range(1, GALLERY_UPLOAD_RETRY_ATTEMPTS + 1):
        try:
            if hasattr(upload_stream, 'read') and hasattr(client, 'upload_fileobj'):
                try:
                    upload_stream.seek(0)
                except Exception:
                    pass
                client.upload_fileobj(
                    upload_stream,
                    app_config.SUPABASE_S3_BUCKET,
                    key,
                    ExtraArgs={'ContentType': content_type},
                )
                return
            # Direct put only as last resort (for very small or non-seekable)
            client.put_object(
                Bucket=app_config.SUPABASE_S3_BUCKET,
                Key=key,
                Body=raw_bytes,
                ContentType=content_type,
            )
            return
        except Exception as e:
            if _is_s3_tls_verification_error(e):
                raise RuntimeError(
                    'Storage upload failed: TLS certificate verification error. '
                    'Set SUPABASE_SSL_VERIFY=false for local dev behind a proxy, or SUPABASE_S3_CA_BUNDLE '
                    'to a PEM file with your corporate root CA, then restart the app.'
                ) from None
            last_error = e
            if attempt < GALLERY_UPLOAD_RETRY_ATTEMPTS and _is_transient_s3_error(e):
                time.sleep(GALLERY_UPLOAD_RETRY_BASE_DELAY_SEC * (2 ** (attempt - 1)))
                continue
            break

    msg = (str(last_error) or '').lower()
    if _is_transient_s3_error(last_error):
        raise RuntimeError('Storage upload was temporarily unavailable after retries. Please retry.') from None
    if 'timed out' in msg or 'timeout' in msg:
        raise RuntimeError('Storage upload timed out. Please retry; for videos, try a smaller file if possible.') from None
    if 'connection' in msg or 'endpoint' in msg or 'temporar' in msg or 'unavailable' in msg:
        raise RuntimeError('Storage upload connection failed. Please check network/storage availability and retry.') from None

    # Specific handling for storage provider object size limits (e.g. Supabase S3 EntityTooLarge)
    if _is_entity_too_large_error(last_error):
        raise RuntimeError(
            'Storage upload failed: The file exceeds the maximum size allowed by the storage provider (EntityTooLarge). '
            'Try a smaller file (videos: shorten or compress first), lower image resolution, '
            'or increase the "Maximum file size" limit on the bucket in your Supabase Storage settings.'
        ) from None

    raise RuntimeError(f'Storage upload failed: {str(last_error) or "unknown error"}') from None


def get_gallery_s3_url(filename):
    client = get_s3_client()
    if not client or not filename:
        return None
    key = gallery_object_key(filename)
    now = time.time()
    cached = _s3_signed_url_cache.get(key)
    if cached:
        url, expires_at = cached
        if url and expires_at and now < (expires_at - 30):
            return url
    try:
        client.head_object(Bucket=app_config.SUPABASE_S3_BUCKET, Key=key)
    except Exception:
        return None
    url = client.generate_presigned_url(
        ClientMethod='get_object',
        Params={'Bucket': app_config.SUPABASE_S3_BUCKET, 'Key': key},
        ExpiresIn=app_config.SUPABASE_S3_SIGNED_URL_TTL,
    )
    try:
        _s3_signed_url_cache[key] = (url, now + float(app_config.SUPABASE_S3_SIGNED_URL_TTL))
    except Exception:
        pass
    return url


def delete_gallery_from_s3(filename):
    client = get_s3_client()
    if not client or not filename:
        return
    try:
        client.delete_object(Bucket=app_config.SUPABASE_S3_BUCKET, Key=gallery_object_key(filename))
    except Exception:
        pass


def stitch_images_horizontally(image_bytes_list):
    """Join images left-to-right into one long JPEG.
    Returns (stitched_bytes, join_positions, total_width, height).
    """
    images = []
    for b in image_bytes_list:
        img = Image.open(io.BytesIO(b))
        try:
            exif = img.getexif()
            orientation = exif.get(EXIF_ORIENTATION_TAG)
            if orientation == 3:
                img = img.rotate(180, expand=True)
            elif orientation == 6:
                img = img.rotate(270, expand=True)
            elif orientation == 8:
                img = img.rotate(90, expand=True)
        except Exception:
            pass
        images.append(img.convert('RGB'))

    max_height = max(img.height for img in images)

    scaled = []
    for img in images:
        if img.height != max_height:
            ratio = max_height / img.height
            new_w = max(1, int(img.width * ratio))
            img = img.resize((new_w, max_height), RESAMPLE_LANCZOS)
        scaled.append(img)

    total_width = sum(img.width for img in scaled)
    canvas = Image.new('RGB', (total_width, max_height))

    join_positions = []
    x_offset = 0
    for i, img in enumerate(scaled):
        canvas.paste(img, (x_offset, 0))
        x_offset += img.width
        if i < len(scaled) - 1:
            join_positions.append(x_offset)

    buf = io.BytesIO()
    canvas.save(buf, 'JPEG', quality=DAYNIGHT_STITCH_JPEG_QUALITY, optimize=True, progressive=True)
    return buf.getvalue(), join_positions, total_width, max_height
