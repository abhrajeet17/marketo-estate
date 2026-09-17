"""
Auth: JWT verification, profiles, decorators.
"""
from functools import wraps
from datetime import datetime
import time

from flask import request, jsonify, g

from app.config import (
    SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_JWT_SECRET,
    CLERK_ISSUER, CLERK_JWKS_URL
)
from app.core.database import get_supabase, _get_httpx_client

try:
    import jwt
except ImportError:
    jwt = None

try:
    from jwt import PyJWKClient
except Exception:
    PyJWKClient = None

_PROFILE_CACHE = {}
_PROFILE_CACHE_TTL_SECONDS = 8
_PROFILE_CACHE_MAX = 2000


def _profile_cache_get(user_id):
    key = str(user_id or '').strip()
    if not key:
        return None, False
    row = _PROFILE_CACHE.get(key)
    if not row:
        return None, False
    if (time.time() - float(row.get('ts') or 0)) > _PROFILE_CACHE_TTL_SECONDS:
        _PROFILE_CACHE.pop(key, None)
        return None, False
    return row.get('data'), True


def _profile_cache_set(user_id, profile):
    key = str(user_id or '').strip()
    if not key:
        return
    if len(_PROFILE_CACHE) > _PROFILE_CACHE_MAX:
        _PROFILE_CACHE.clear()
    _PROFILE_CACHE[key] = {'ts': time.time(), 'data': profile}


def _profile_cache_invalidate(user_id):
    key = str(user_id or '').strip()
    if key:
        _PROFILE_CACHE.pop(key, None)


def _get_clerk_jwks_url(issuer=None):
    if CLERK_JWKS_URL:
        return CLERK_JWKS_URL
    base = (CLERK_ISSUER or issuer or '').strip()
    if base:
        return base.rstrip('/') + '/.well-known/jwks.json'
    return None


_CLERK_JWKS_CLIENT = None


def _get_clerk_jwks_client():
    global _CLERK_JWKS_CLIENT
    if _CLERK_JWKS_CLIENT is not None:
        return _CLERK_JWKS_CLIENT
    url = _get_clerk_jwks_url()
    if not url or not jwt or not PyJWKClient:
        return None
    try:
        _CLERK_JWKS_CLIENT = PyJWKClient(url, cache_keys=True)
    except Exception:
        _CLERK_JWKS_CLIENT = None
    return _CLERK_JWKS_CLIENT


def _verify_clerk_token(token):
    """Verify Clerk JWT (from Authorization or __session cookie) and return user sub or None."""
    if not token or not jwt:
        return None
    # Fast path: only proceed if we have clerk config or the token claims 'clerk'
    try:
        unverified = jwt.decode(token, options={'verify_signature': False, 'verify_exp': False})
        iss = str(unverified.get('iss') or '').lower()
        has_clerk_hint = 'clerk' in iss
    except Exception:
        has_clerk_hint = False

    if not has_clerk_hint and not (CLERK_ISSUER or CLERK_JWKS_URL):
        return None

    jwks_client = _get_clerk_jwks_client()
    if not jwks_client:
        return None

    try:
        signing_key = jwks_client.get_signing_key_from_jwt(token)
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=['RS256'],
            issuer=CLERK_ISSUER or None,
            options={
                'verify_aud': False,
                'verify_exp': True,
                'verify_iss': bool(CLERK_ISSUER),
            }
        )
        user_id = payload.get('sub')
        return str(user_id) if user_id else None
    except Exception:
        return None


def _get_clerk_token_from_cookies():
    """Extract Clerk session token from common Clerk cookies."""
    # __session is the primary one used by Clerk's getToken()
    for name in ('__session', '__clerk_db_jwt', 'clerk_session', '__session_9SSEJt-J'):
        val = request.cookies.get(name)
        if val:
            # Clerk sometimes stores as raw JWT or may be urlencoded - take the first plausible JWT
            if isinstance(val, str) and val.count('.') >= 2:
                return val.strip()
            # Some cookies might be compound; try splitting
            parts = str(val).split(';')[0].strip()
            if parts.count('.') >= 2:
                return parts
    return None


def get_current_user():
    """
    From Authorization: Bearer <jwt> or Clerk __session cookie.
    Tries Supabase first (for legacy), then Clerk JWT.
    Returns (user_id, role) or (None, None).
    """
    cached_ctx = getattr(g, '_auth_user_ctx', None)
    if cached_ctx is not None:
        return cached_ctx

    header_token = None
    auth = request.headers.get('Authorization') or request.headers.get('authorization')
    if auth and auth.lower().startswith('bearer '):
        header_token = auth[7:].strip() or None

    user_id = None

    # 1. Try Supabase path on the Authorization header token (existing behavior)
    if header_token:
        if SUPABASE_JWT_SECRET and jwt:
            try:
                payload = jwt.decode(header_token, SUPABASE_JWT_SECRET, algorithms=['HS256'])
                user_id = payload.get('sub')
            except Exception:
                pass
        if not user_id and SUPABASE_URL and SUPABASE_ANON_KEY:
            try:
                client = _get_httpx_client()
                r = client.get(
                    f'{SUPABASE_URL}/auth/v1/user',
                    headers={'apikey': SUPABASE_ANON_KEY, 'Authorization': f'Bearer {header_token}'},
                )
                if r.status_code == 200:
                    data = r.json()
                    user_id = (data.get('id') or data.get('user', {}).get('id'))
            except Exception:
                pass

    # 2. If no user_id yet, try Clerk verification on the header token (allows sending Clerk token as Bearer)
    if not user_id and header_token:
        user_id = _verify_clerk_token(header_token)

    # 3. If still nothing, try Clerk session cookie (supports curl -b with Clerk cookies)
    if not user_id:
        cookie_token = _get_clerk_token_from_cookies()
        if cookie_token:
            user_id = _verify_clerk_token(cookie_token)

    if not user_id:
        g._auth_user_ctx = (None, None)
        return g._auth_user_ctx

    sb = get_supabase()
    if not sb:
        g._auth_profile = None
        g._auth_user_ctx = (user_id, 'user')
        return g._auth_user_ctx

    profile = get_profile(sb, user_id)
    g._auth_profile = profile
    role = (profile or {}).get('role', 'user')
    g._auth_user_ctx = (user_id, role)
    return g._auth_user_ctx


def get_profile(sb, user_id):
    """Fetch profile row for user_id."""
    cached, hit = _profile_cache_get(user_id)
    if hit:
        return cached
    try:
        r = sb.table('profiles').select('*').eq('user_id', user_id).limit(1).execute()
        if r.data and len(r.data) > 0:
            row = r.data[0]
            _profile_cache_set(user_id, row)
            return row
    except Exception:
        pass
    _profile_cache_set(user_id, None)
    return None


def _sync_profile_display_name_from_auth(sb, user_id):
    """Backfill profile display_name and email from Supabase Auth user_metadata."""
    try:
        resp = sb.auth.admin.get_user_by_id(str(user_id))
        user = getattr(resp, 'user', resp)
        if not user:
            return
        meta = getattr(user, 'user_metadata', None) or {}
        display_name = (meta.get('display_name') or '').strip() or None
        email = (getattr(user, 'email', None) or '').strip() or None
        if not display_name and not email:
            return
        upd = {'updated_at': datetime.utcnow().isoformat()}
        if display_name is not None:
            upd['display_name'] = display_name
        if email is not None:
            upd['email'] = email
        sb.table('profiles').update(upd).eq('user_id', user_id).execute()
    except Exception:
        pass


def ensure_profile(sb, user_id, role='user', existing_profile=None):
    """Insert or update profile with role."""
    existing = existing_profile if existing_profile is not None else get_profile(sb, user_id)
    if existing:
        if not (existing.get('display_name') or '').strip():
            _sync_profile_display_name_from_auth(sb, user_id)
            existing = get_profile(sb, user_id) or existing
        return existing
    try:
        sb.table('profiles').upsert(
            {'user_id': user_id, 'role': role},
            on_conflict='user_id'
        ).execute()
    except Exception:
        try:
            sb.table('profiles').insert({'user_id': user_id, 'role': role}).execute()
        except Exception:
            pass
    _profile_cache_invalidate(user_id)
    return get_profile(sb, user_id) or {'user_id': user_id, 'role': role}


def require_auth(f):
    """Decorator: require valid JWT; inject (user_id, role) as first args."""
    @wraps(f)
    def wrapped(*args, **kwargs):
        user_id, role = get_current_user()
        if not user_id:
            return jsonify({'error': 'Unauthorized'}), 401
        sb = get_supabase()
        if sb:
            existing_profile = getattr(g, '_auth_profile', None)
            if existing_profile is None:
                existing_profile = get_profile(sb, user_id)
            ensure_profile(sb, user_id, role or 'user', existing_profile=existing_profile)
        return f(user_id, role, *args, **kwargs)
    return wrapped


def require_admin(f):
    """Decorator: require auth and role admin."""
    @wraps(f)
    def wrapped(*args, **kwargs):
        user_id, role = get_current_user()
        if not user_id:
            return jsonify({'error': 'Unauthorized'}), 401
        if role not in ('admin', 'superadmin'):
            return jsonify({'error': 'Forbidden'}), 403
        return f(user_id, role, *args, **kwargs)
    return wrapped


def require_superadmin(f):
    """Decorator: require auth and role superadmin."""
    @wraps(f)
    def wrapped(*args, **kwargs):
        user_id, role = get_current_user()
        if not user_id:
            return jsonify({'error': 'Unauthorized'}), 401
        if role != 'superadmin':
            return jsonify({'error': 'Forbidden'}), 403
        return f(user_id, role, *args, **kwargs)
    return wrapped
