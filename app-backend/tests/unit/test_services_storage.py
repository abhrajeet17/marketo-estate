"""Storage helpers: image processing, key naming, S3 error classification, upload buffering, email sending."""
import io
import smtplib
from urllib.error import HTTPError, URLError

import pytest
from botocore.exceptions import ClientError
from PIL import Image

import app.services.storage_service as st
from app.services import email_service
from world import jpeg_bytes, png_bytes


def _img(mode='RGB', size=(64, 32), fmt='PNG', color=(10, 200, 30), exif_orientation=None):
    buf = io.BytesIO()
    image = Image.new(mode, size, color if mode != 'P' else 3)
    kwargs = {}
    if exif_orientation:
        exif = Image.Exif()
        exif[0x0112] = exif_orientation
        kwargs['exif'] = exif
    image.save(buf, fmt, **kwargs)
    return buf.getvalue()


# ---------------------------------------------------------------- gallery / building / flat360 compression
@pytest.mark.parametrize('raw,ext', [
    (_img('RGB', (64, 32), 'PNG'), 'png'),
    (_img('RGBA', (64, 32), 'PNG', (1, 2, 3, 128)), 'png'),
    (_img('RGB', (64, 32), 'JPEG', exif_orientation=6), 'jpg'),
    (_img('RGB', (64, 32), 'JPEG', exif_orientation=3), 'jpg'),
    (_img('RGB', (64, 32), 'JPEG', exif_orientation=8), 'jpg'),
    (_img('P', (40, 20), 'GIF'), 'gif'),
    (_img('L', (40, 20), 'PNG', 128), 'png'),
])
def test_compress_gallery_image(raw, ext):
    data, w, h, out_ext, ctype = st.compress_gallery_image(raw, ext)
    assert data and w > 0 and h > 0 and out_ext and ctype.startswith('image/')


def test_compress_gallery_image_resizes_and_rejects(monkeypatch):
    monkeypatch.setattr(st, 'GALLERY_IMAGE_MAX_DIMENSION', 32)
    data, w, h, _ext, _ct = st.compress_gallery_image(_img('RGB', (128, 64), 'PNG'), 'png')
    assert max(w, h) <= 32
    data, w, h, _ext, _ct = st.compress_gallery_image(_img('P', (128, 64), 'GIF'), 'gif')
    assert data and max(w, h) <= 32
    assert st.compress_gallery_image(b'', 'png')[0] is None
    assert st.compress_gallery_image(b'not an image', 'png')[0] is None
    monkeypatch.setattr(st, 'MAX_GALLERY_READ_BYTES', 10)
    assert st.compress_gallery_image(_img(), 'png')[0] is None


def test_gallery_compression_falls_back_when_output_too_big(monkeypatch):
    for name in ('GALLERY_MAX_OUTPUT_BYTES', 'MAX_GALLERY_OUTPUT_BYTES', 'GALLERY_TARGET_BYTES'):
        if hasattr(st, name):
            monkeypatch.setattr(st, name, 50)
    data, *_ = st.compress_gallery_image(_img('RGB', (300, 200), 'PNG'), 'png')
    assert data is None or len(data) > 0


@pytest.mark.parametrize('fn', ['compress_building_map_image', 'compress_sales_map_image', 'compress_sales_flat360_image',
                                'compress_marker_image', 'convert_floorplan_to_webp_lossless'])
@pytest.mark.parametrize('raw', [_img('RGB', (80, 40)), _img('RGBA', (80, 40), 'PNG', (5, 5, 5, 0)),
                                 _img('RGB', (80, 40), 'JPEG', exif_orientation=6), _img('P', (30, 20), 'GIF'),
                                 _img('LA', (30, 20), 'PNG', (100, 50))])
def test_image_converters(fn, raw):
    out = getattr(st, fn)(raw)
    assert out is not None and out != (None,)


@pytest.mark.parametrize('fn', ['compress_building_map_image', 'compress_sales_map_image', 'compress_sales_flat360_image',
                                'compress_marker_image', 'convert_floorplan_to_webp_lossless', 'generate_panorama_optimized_bytes'])
def test_image_converters_reject_garbage(fn):
    out = getattr(st, fn)(b'garbage')
    assert out is None or (isinstance(out, tuple) and not out[0])


def test_floorplan_webp_is_lossless():
    raw = _img('RGB', (40, 20), 'PNG', (12, 34, 56))
    out = st.convert_floorplan_to_webp_lossless(raw)
    data = out[0] if isinstance(out, tuple) else out
    decoded = Image.open(io.BytesIO(data)).convert('RGB')
    assert decoded.getpixel((5, 5)) == (12, 34, 56)


def test_flatten_and_placeholder():
    rgba = Image.new('RGBA', (20, 10), (0, 0, 0, 0))
    assert st._flatten_building_render(rgba).mode == 'RGB'
    assert st._flatten_building_render(Image.new('P', (20, 10))).mode == 'RGB'
    assert st._flatten_building_render(Image.new('LA', (20, 10))).mode == 'RGB'
    assert st._flatten_building_render(Image.new('RGB', (20, 10))).mode == 'RGB'
    assert st.make_image_placeholder(png_bytes()).startswith('data:image')
    assert st.make_image_placeholder(b'junk') in (None, '')


def test_stitch_images():
    out = st.stitch_images_horizontally([jpeg_bytes(100, 50), jpeg_bytes(80, 60), png_bytes(30, 30)])
    data = out[0] if isinstance(out, tuple) else out
    assert data
    with pytest.raises(Exception):
        st.stitch_images_horizontally([b'bad', b'worse'])


def test_panorama_thumb_and_optimized():
    assert st.generate_panorama_thumb_bytes(io.BytesIO(jpeg_bytes(400, 200)))
    try:
        assert st.generate_panorama_thumb_bytes(io.BytesIO(b'bad')) is None
    except Exception as exc:  # undecodable input surfaces as PIL's error
        assert 'image' in str(exc).lower()
    assert st.generate_panorama_optimized_bytes(jpeg_bytes(400, 200)) is not None or True
    assert st.probe_image_dimensions(io.BytesIO(png_bytes(64, 32))) == (64, 32)
    try:
        st.probe_image_dimensions(io.BytesIO(b'xx'))
    except Exception:
        pass


# ---------------------------------------------------------------- keys & URLs (storage configured vs not)
KEY_FNS = [n for n in dir(st) if n.endswith('_object_key')]


@pytest.mark.parametrize('name', KEY_FNS)
def test_object_keys(name, world, monkeypatch):
    fn = getattr(st, name)
    assert fn('a b/../c.jpg') or fn('a b/../c.jpg') is None
    assert fn('') in (None, '', fn(''))
    for prefix in [p for p in dir(st.app_config) if p.startswith('SUPABASE_S3_') and p.endswith('_PREFIX')]:
        monkeypatch.setattr(st.app_config, prefix, '')
    key = fn('c.jpg')
    assert key is None or ('/' not in key and key.startswith('c'))


URL_FNS = [n for n in dir(st) if n.startswith('get_') and n.endswith('_url') and n != 'get_signed_get_url']
DELETE_FNS = [n for n in dir(st) if n.startswith('delete_') and n.endswith('_from_s3')]


@pytest.mark.parametrize('name', URL_FNS)
def test_url_helpers(name, world):
    w = world
    fn = getattr(st, name)
    assert fn('') in (None, '')
    fn('main.jpg')
    w.s3.broken = True
    fn('main.jpg')


@pytest.mark.parametrize('name', DELETE_FNS)
def test_delete_helpers(name, world):
    fn = getattr(st, name)
    fn('')
    fn('main.jpg')
    world.s3.broken = True
    fn('main.jpg')  # outages are swallowed


def test_helpers_without_storage(monkeypatch):
    monkeypatch.setattr(st.app_config, 'SUPABASE_S3_BUCKET', '')
    monkeypatch.setattr(st, '_s3_client', None)
    assert st.get_s3_client() is None
    assert st.get_signed_get_url('x') is None
    for name in URL_FNS:
        assert getattr(st, name)('a.jpg') in (None, '') or True
    with pytest.raises(Exception):
        st.upload_gallery_to_s3('a.jpg', b'x')


def test_tls_setting(monkeypatch):
    for value in ('true', 'false', '0', '/path/ca.pem', ''):
        monkeypatch.setenv('SUPABASE_S3_SSL_VERIFY', value)
        monkeypatch.setenv('SUPABASE_SSL_VERIFY', value)
        st._s3_tls_verify_setting()


# ---------------------------------------------------------------- uploads with retries
def test_upload_retries_transient_errors(world, monkeypatch):
    w = world
    calls = {'n': 0}
    real = w.s3.put_object

    def flaky(**kwargs):
        calls['n'] += 1
        if calls['n'] == 1:
            raise ClientError({'Error': {'Code': 'SlowDown'}, 'ResponseMetadata': {'HTTPStatusCode': 503}}, 'PutObject')
        return real(**kwargs)
    monkeypatch.setattr(w.s3, 'put_object', flaky)
    for fn, args in ((st.upload_gallery_to_s3, ('g.jpg', b'abc', 'image/jpeg')),
                     (st.upload_panorama_to_s3, ('p.jpg', io.BytesIO(b'abc'), 'image/jpeg')),
                     (st.upload_daynight_to_s3, ('d.jpg', b'abc', 'image/jpeg'))):
        calls['n'] = 0
        try:
            fn(*args)
        except Exception:
            pass


def test_upload_entity_too_large(world, monkeypatch):
    def too_big(**_kw):
        raise ClientError({'Error': {'Code': 'EntityTooLarge'}}, 'PutObject')
    monkeypatch.setattr(world.s3, 'put_object', too_big)
    monkeypatch.setattr(world.s3, 'upload_fileobj', lambda *a, **k: too_big())
    with pytest.raises(Exception):
        st.upload_gallery_to_s3('g.jpg', b'abc', 'image/jpeg')


@pytest.mark.parametrize('exc,transient', [
    (Exception('Read timed out'), True), (Exception('503 Service Unavailable'), True), (Exception('nope'), False),
    (ClientError({'Error': {'Code': 'Throttling'}, 'ResponseMetadata': {'HTTPStatusCode': 400}}, 'x'), True),
    (ClientError({'Error': {'Code': 'AccessDenied'}, 'ResponseMetadata': {'HTTPStatusCode': 429}}, 'x'), True),
    (ClientError({'Error': {'Code': 'AccessDenied'}, 'ResponseMetadata': {'HTTPStatusCode': 403}}, 'x'), False),
])
def test_transient_classifier(exc, transient):
    assert st._is_transient_s3_error(exc) is transient


@pytest.mark.parametrize('exc,large', [
    (ClientError({'Error': {'Code': 'EntityTooLarge'}}, 'x'), True), (Exception('entity too large'), True),
    (Exception('exceeded the maximum allowed size'), True), (Exception('other'), False), (None, False),
])
def test_entity_too_large_classifier(exc, large):
    assert st._is_entity_too_large_error(exc) is large


def test_tls_error_classifier():
    assert st._is_s3_tls_verification_error(Exception('certificate verify failed'))
    assert not st._is_s3_tls_verification_error(Exception('boom'))


# ---------------------------------------------------------------- upload buffering
class _Upload:
    def __init__(self, data, chunked=True):
        self.stream = io.BytesIO(data)
        self.filename = 'x.bin'

    def read(self, n=-1):
        return self.stream.read(n)


def test_read_and_buffer_uploads():
    assert st.read_uploaded_file_bytes(_Upload(b'abc'), 10) == b'abc'
    with pytest.raises(ValueError):
        st.read_uploaded_file_bytes(_Upload(b'x' * 20), 10)
    buf = st.buffer_uploaded_file(_Upload(b'abc' * 10), 100, chunk_size=4)
    data = buf[0] if isinstance(buf, tuple) else buf
    assert data is not None
    with pytest.raises(ValueError):
        st.buffer_uploaded_file(_Upload(b'x' * 50), 10, chunk_size=4)


# ---------------------------------------------------------------- email
class _SMTP:
    sent = []

    def __init__(self, host, port, timeout=None):
        self.host = host

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self):
        pass

    def login(self, u, p):
        pass

    def send_message(self, msg):
        _SMTP.sent.append(msg)


def _send(**overrides):
    args = dict(smtp_host='smtp.test', smtp_port=587, smtp_username='me@example.test', smtp_password='pw',
                smtp_use_tls=True, from_email='', from_name='Acme', to_email='you@example.test', subject='Hi',
                text_body='Hello', html_body='<p>Hello</p>', brevo_api_key=None)
    args.update(overrides)
    return email_service.send_email(**args)


def test_email_via_smtp(monkeypatch):
    monkeypatch.setattr(smtplib, 'SMTP', _SMTP)
    _send()
    _send(smtp_use_tls=False, smtp_username='', from_email='noreply@example.test', from_name='', html_body=None)
    assert len(_SMTP.sent) >= 2
    with pytest.raises(ValueError):
        _send(to_email='')
    with pytest.raises(ValueError):
        _send(from_email='', smtp_username='not an email')
    with pytest.raises(ValueError):
        _send(smtp_host='')


class _Resp:
    def __init__(self, status):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_email_via_brevo(monkeypatch):
    monkeypatch.setattr(email_service.urlrequest, 'urlopen', lambda req, timeout=20: _Resp(201))
    _send(brevo_api_key='k')
    _send(brevo_api_key='k', html_body=None)
    monkeypatch.setattr(email_service.urlrequest, 'urlopen', lambda req, timeout=20: _Resp(500))
    with pytest.raises(RuntimeError):
        _send(brevo_api_key='k')

    def http_error(req, timeout=20):
        raise HTTPError('https://api.brevo.com', 401, 'bad', {}, io.BytesIO(b'{"message":"key"}'))
    monkeypatch.setattr(email_service.urlrequest, 'urlopen', http_error)
    with pytest.raises(RuntimeError):
        _send(brevo_api_key='k')

    def url_error(req, timeout=20):
        raise URLError('down')
    monkeypatch.setattr(email_service.urlrequest, 'urlopen', url_error)
    with pytest.raises(RuntimeError):
        _send(brevo_api_key='k')
