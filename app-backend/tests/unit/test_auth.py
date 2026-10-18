"""Authentication and role checks, and an anonymous sweep over every API route."""
import re
import time

import jwt
import pytest
from flask import Flask

PUBLIC_API_PREFIXES = (
    '/api/public/', '/api/customer/', '/api/portal/public', '/api/share/', '/api/invite',
    '/api/client-invites/public', '/api/health',
)
# Public by design although outside the prefixes above (read by the public customer 3D page).
PUBLIC_API_ROUTES = {'/api/workspaces/<workspace_id>/customer-view-config'}


SECRET = 'unit-test-secret-at-least-32-bytes!!'


def _token(secret, sub='user-1', **extra):
    now = int(time.time())
    return jwt.encode({'sub': sub, 'role': 'authenticated', 'iat': now, 'exp': now + 600, **extra}, secret, algorithm='HS256')


@pytest.fixture
def guarded_app(offline_auth, fake_sb, monkeypatch):
    """A tiny app using the real decorators, with profiles served from memory."""
    auth = offline_auth
    profiles = [
        {'user_id': 'admin-1', 'role': 'admin', 'display_name': 'A'},
        {'user_id': 'super-1', 'role': 'superadmin', 'display_name': 'S'},
        {'user_id': 'user-1', 'role': 'user', 'display_name': 'U'},
    ]
    monkeypatch.setattr(auth, 'get_supabase', lambda: fake_sb({'profiles': profiles}))
    monkeypatch.setattr(auth, 'SUPABASE_JWT_SECRET', SECRET)
    auth._profile_cache_invalidate('admin-1')
    auth._profile_cache_invalidate('super-1')
    auth._profile_cache_invalidate('user-1')

    app = Flask('guarded')

    @app.route('/any')
    @auth.require_auth
    def any_user(user_id, role):
        return {'user': user_id, 'role': role}

    @app.route('/admin')
    @auth.require_admin
    def admin_only(user_id, role):
        return {'ok': True}

    @app.route('/super')
    @auth.require_superadmin
    def super_only(user_id, role):
        return {'ok': True}

    return app.test_client()


def _get(client, path, sub=None, secret=SECRET, raw=None):
    headers = {}
    if raw is not None:
        headers['Authorization'] = raw
    elif sub:
        headers['Authorization'] = 'Bearer ' + _token(secret, sub)
    return client.get(path, headers=headers)


def test_missing_token_is_401(guarded_app):
    for path in ('/any', '/admin', '/super'):
        assert _get(guarded_app, path).status_code == 401


def test_garbage_and_foreign_tokens_are_401(guarded_app):
    assert _get(guarded_app, '/any', raw='Bearer not-a-jwt').status_code == 401
    assert _get(guarded_app, '/any', sub='admin-1', secret='another-secret-that-is-32-bytes-long').status_code == 401


def test_expired_token_is_401(guarded_app):
    old = jwt.encode({'sub': 'admin-1', 'exp': int(time.time()) - 10}, SECRET, algorithm='HS256')
    assert _get(guarded_app, '/any', raw='Bearer ' + old).status_code == 401


def test_role_is_read_from_profile_not_token(guarded_app):
    # A user cannot promote themselves by putting a role claim in the token.
    forged = _token(SECRET, 'user-1', app_role='superadmin', user_role='admin')
    assert _get(guarded_app, '/admin', raw='Bearer ' + forged).status_code == 403
    assert _get(guarded_app, '/any', sub='user-1').get_json() == {'user': 'user-1', 'role': 'user'}


def test_role_gates(guarded_app):
    assert _get(guarded_app, '/admin', sub='user-1').status_code == 403
    assert _get(guarded_app, '/admin', sub='admin-1').status_code == 200
    assert _get(guarded_app, '/admin', sub='super-1').status_code == 200
    assert _get(guarded_app, '/super', sub='admin-1').status_code == 403
    assert _get(guarded_app, '/super', sub='super-1').status_code == 200


def _fill(rule):
    path = rule.rule
    for conv, name in re.findall(r'<(?:(\w+):)?(\w+)>', path):
        value = '1' if conv in ('int',) else '00000000-0000-0000-0000-000000000000'
        path = re.sub(r'<(?:\w+:)?' + name + '>', value, path, count=1)
    return path


def test_every_private_api_route_rejects_anonymous_calls(flask_app, offline_auth, monkeypatch):
    """No data API is reachable without signing in (public share/customer routes excepted)."""
    import app.core.database as database
    monkeypatch.setattr(database, 'get_supabase', lambda: None)
    client = flask_app.test_client()
    leaks = []
    checked = 0
    for rule in flask_app.url_map.iter_rules():
        if not rule.rule.startswith('/api/') or rule.rule.startswith(PUBLIC_API_PREFIXES) or rule.rule in PUBLIC_API_ROUTES:
            continue
        for method in sorted((rule.methods or set()) - {'HEAD', 'OPTIONS'}):
            path = _fill(rule)
            resp = client.open(path, method=method, json={} if method != 'GET' else None)
            checked += 1
            # 401/403 = rejected; 400/404/405 = refused before any data; 503 = no database.
            if resp.status_code not in (400, 401, 403, 404, 405, 503):
                leaks.append(f'{method} {rule.rule} -> {resp.status_code}')
    assert checked > 200
    assert not leaks, 'API routes answered without auth:\n' + '\n'.join(leaks)


def test_no_duplicate_routes(flask_app):
    seen = {}
    dupes = []
    for rule in flask_app.url_map.iter_rules():
        for method in (rule.methods or set()) - {'HEAD', 'OPTIONS'}:
            key = (rule.rule, method)
            if key in seen:
                dupes.append(key)
            seen[key] = rule.endpoint
    assert not dupes
