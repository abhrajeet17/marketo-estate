"""
Static asset delivery with compress-once caching.

Flask-Compress re-compresses every static response on every request. Here each compressible
file is compressed once per process (keyed by path + mtime, so edits are picked up) and the
encoded bytes are reused. Responses already carry Content-Encoding, so Flask-Compress leaves
them alone. Files are never altered on disk.
"""
import gzip
import mimetypes
import os
import threading

from flask import Response, current_app, request, send_from_directory
from werkzeug.security import safe_join

try:
    import brotli
except ImportError:
    brotli = None

COMPRESSIBLE_TYPES = {
    'text/html', 'text/css', 'text/xml', 'text/plain', 'application/json',
    'application/javascript', 'text/javascript', 'image/svg+xml', 'application/xml',
}
MIN_COMPRESS_BYTES = 500
MAX_COMPRESS_BYTES = 8 * 1024 * 1024
CACHE_BUDGET_BYTES = 48 * 1024 * 1024
IMMUTABLE_CACHE_CONTROL = 'public, max-age=31536000, immutable'

_cache = {}
_cache_bytes = 0
_lock = threading.Lock()


def _accepted_encoding():
    accept = request.headers.get('Accept-Encoding', '').lower()
    if brotli is not None and 'br' in accept:
        return 'br'
    if 'gzip' in accept:
        return 'gzip'
    return None


def _encode(data, encoding):
    if encoding == 'br':
        return brotli.compress(data, quality=9)
    return gzip.compress(data, compresslevel=9, mtime=0)


def _encoded_bytes(path, stat, encoding):
    global _cache_bytes
    key = (path, encoding)
    with _lock:
        hit = _cache.get(key)
    if hit and hit[0] == stat.st_mtime_ns:
        return hit[1]
    with open(path, 'rb') as f:
        data = f.read()
    encoded = _encode(data, encoding)
    with _lock:
        old = _cache.pop(key, None)
        if old:
            _cache_bytes -= len(old[1])
        if _cache_bytes + len(encoded) > CACHE_BUDGET_BYTES:
            _cache.clear()
            _cache_bytes = 0
        _cache[key] = (stat.st_mtime_ns, encoded)
        _cache_bytes += len(encoded)
    return encoded


def send_static_file(root, filename, max_age=None, immutable=False):
    """Serve `filename` from `root`, precompressed when the client accepts it.

    `immutable` marks a request whose ?v= is the current deploy token: such a URL names one
    exact build of the file, so browsers may keep it for a year.
    """
    path = safe_join(root, filename)
    mimetype = mimetypes.guess_type(filename)[0] or 'application/octet-stream'
    encoding = _accepted_encoding() if mimetype in COMPRESSIBLE_TYPES else None
    try:
        stat = os.stat(path) if path else None
    except OSError:
        stat = None
    if not encoding or not stat or not (MIN_COMPRESS_BYTES <= stat.st_size <= MAX_COMPRESS_BYTES):
        resp = send_from_directory(root, filename, max_age=max_age)
        if immutable and resp.status_code == 200:
            resp.headers['Cache-Control'] = IMMUTABLE_CACHE_CONTROL
        return resp

    resp = Response(_encoded_bytes(path, stat, encoding), mimetype=mimetype)
    resp.headers['Content-Encoding'] = encoding
    resp.headers['Vary'] = 'Accept-Encoding'
    resp.set_etag(f'{stat.st_mtime_ns:x}-{stat.st_size:x}-{encoding}')
    resp.last_modified = int(stat.st_mtime)
    age = current_app.get_send_file_max_age(filename) if max_age is None else max_age
    if immutable:
        resp.headers['Cache-Control'] = IMMUTABLE_CACHE_CONTROL
    elif age:
        resp.cache_control.public = True
        resp.cache_control.max_age = age
    else:
        resp.cache_control.no_cache = True
    return resp.make_conditional(request)
