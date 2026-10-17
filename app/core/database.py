"""
Supabase client (service role).
"""
import os
import time

from app.config import SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY

_sb_client = None
_httpx_client = None

_TRANSIENT_SUPABASE_TOKENS = (
    'connectionterminated',
    'connection terminated',
    'connection closed',
    'server closed the connection',
    'stream error',
    'eof',
    'timeout',
    'timed out',
    'temporarily unavailable',
    'cannot send a request, as the client has been closed',
)


def is_transient_supabase_error(error):
    message = str(error or '').lower()
    return any(token in message for token in _TRANSIENT_SUPABASE_TOKENS)


def _get_httpx_client():
    """Lazy httpx client for Auth API."""
    global _httpx_client
    if _httpx_client is None:
        verify = os.environ.get('SUPABASE_SSL_VERIFY', 'true').lower() not in ('false', '0', 'no')
        import httpx
        _httpx_client = httpx.Client(verify=verify, timeout=10)
    return _httpx_client


def reset_supabase_client():
    """Drop cached Supabase client; do not close sessions used by in-flight requests."""
    global _sb_client
    _sb_client = None


def require_supabase():
    sb = get_supabase()
    if not sb:
        raise RuntimeError('Database not configured')
    return sb


def with_supabase_retry(fn, attempts=2, sleep_seconds=0.18):
    last_error = None
    total_attempts = max(1, int(attempts or 1))
    for index in range(total_attempts):
        try:
            return fn()
        except Exception as error:
            last_error = error
            if not is_transient_supabase_error(error) or index >= total_attempts - 1:
                raise
            reset_supabase_client()
            time.sleep(sleep_seconds)
    if last_error is not None:
        raise last_error


def get_supabase():
    """Lazy Supabase client (service role)."""
    global _sb_client
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        return None
    if _sb_client is None:
        try:
            import httpx
            from supabase import create_client
            from supabase.lib.client_options import SyncClientOptions
            verify = os.environ.get('SUPABASE_SSL_VERIFY', 'true').lower() not in ('false', '0', 'no')
            # HTTP/1.1 connection pool instead of the default single HTTP/2 connection: request
            # threads share this client, and concurrent streams on one HTTP/2 connection were
            # being terminated (ConnectionTerminated -> random 403/500s). A pool gives each
            # in-flight query its own kept-alive connection.
            http = httpx.Client(
                http2=False,
                verify=verify,
                timeout=httpx.Timeout(30.0, connect=10.0),
                limits=httpx.Limits(max_connections=64, max_keepalive_connections=32, keepalive_expiry=60),
            )
            options = SyncClientOptions(httpx_client=http)
            _sb_client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, options=options)
        except Exception:
            return None
    return _sb_client