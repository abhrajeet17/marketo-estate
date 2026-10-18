import gzip

import pytest

from app.core import static_assets

JS = '/static/js/sidebar.js'


def _brotli():
    return pytest.importorskip('brotli')


def test_gzip_when_brotli_not_accepted(client):
    resp = client.get(JS, headers={'Accept-Encoding': 'gzip'})
    assert resp.status_code == 200
    assert resp.headers['Content-Encoding'] == 'gzip'
    assert b'msProjects' in gzip.decompress(resp.data)
    assert resp.headers['Vary'] == 'Accept-Encoding'


def test_brotli_preferred(client):
    brotli = _brotli()
    resp = client.get(JS, headers={'Accept-Encoding': 'gzip, br'})
    assert resp.headers['Content-Encoding'] == 'br'
    assert b'msProjects' in brotli.decompress(resp.data)


def test_compression_is_lossless(client):
    plain = client.get(JS, headers={'Accept-Encoding': 'identity'})
    packed = client.get(JS, headers={'Accept-Encoding': 'gzip'})
    assert 'Content-Encoding' not in plain.headers
    assert gzip.decompress(packed.data) == plain.data


def test_conditional_request_returns_304(client):
    first = client.get(JS, headers={'Accept-Encoding': 'gzip'})
    etag = first.headers['ETag']
    again = client.get(JS, headers={'Accept-Encoding': 'gzip', 'If-None-Match': etag})
    assert again.status_code == 304


def test_deploy_token_marks_file_immutable(client, flask_app):
    import re
    found = re.search(r'sidebar\.js\?v=([^"&]+)', client.get('/dashboard').get_data(as_text=True))
    assert found, 'pages must reference sidebar.js with the deploy token'
    token = found.group(1)
    resp = client.get(f'{JS}?v={token}', headers={'Accept-Encoding': 'gzip'})
    assert resp.headers['Cache-Control'] == static_assets.IMMUTABLE_CACHE_CONTROL


def test_dashboard_modules_are_never_cached_stale(client):
    resp = client.get('/static/js/dashboard/main.js', headers={'Accept-Encoding': 'gzip'})
    assert resp.status_code == 200
    assert 'immutable' not in resp.headers.get('Cache-Control', '')


def test_path_traversal_is_rejected(client):
    assert client.get('/static/../app.py').status_code == 404
    assert client.get('/static/js/..%2F..%2F..%2Fapp-backend%2Fapp.py').status_code == 404


def test_missing_file_404(client):
    assert client.get('/static/js/does-not-exist.js', headers={'Accept-Encoding': 'gzip'}).status_code == 404


def test_images_are_not_recompressed(client):
    resp = client.get('/static/Marketostate/Marketostate%20Favicon.svg', headers={'Accept-Encoding': 'gzip'})
    assert resp.status_code == 200
    # SVG is text and gets compressed; raster images never do.
    assert resp.headers.get('Content-Encoding') in (None, 'gzip')
