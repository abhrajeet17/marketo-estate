"""Sign-in paths beyond the local HS256 token: Supabase Auth lookup, Clerk RS256 (header and cookies),
token/profile caches and profile creation."""
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

import app.core.auth as auth

ISSUER = 'https://clerk.example.test'


@pytest.fixture
def rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _clerk_token(key, sub='clerk-user', iss=ISSUER, exp_in=600):
    now = int(time.time())
    return jwt.encode({'sub': sub, 'iss': iss, 'iat': now, 'exp': now + exp_in}, key, algorithm='RS256')


class _JWKS:
    def __init__(self, key):
        self.key = key.public_key()

    def get_signing_key_from_jwt(self, _token):
        return self


@pytest.fixture
def clerk(world, monkeypatch, rsa_key):
    monkeypatch.setattr(auth, 'CLERK_ISSUER', ISSUER)
    monkeypatch.setattr(auth, '_CLERK_JWKS_CLIENT', _JWKS(rsa_key))
    world.db.add('profiles', user_id='clerk-user', role='admin', display_name='Clerk Admin')
    return rsa_key


def test_clerk_bearer_token(world, clerk):
    r = world.client.get('/api/crm/me', headers={'Authorization': 'Bearer ' + _clerk_token(clerk)})
    assert r.status_code == 200


def test_clerk_cookie_token(world, clerk):
    token = _clerk_token(clerk)
    for name, value in (('__session', token), ('__clerk_db_jwt', token)):
        world.client.set_cookie(name, value)
        assert world.client.get('/api/crm/me').status_code == 200
        world.client.delete_cookie(name)
    world.client.set_cookie('__session', 'not-a-jwt')
    assert world.client.get('/api/crm/me').status_code == 401


def test_clerk_rejects_bad_tokens(world, clerk, rsa_key):
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    for token in (_clerk_token(other), _clerk_token(clerk, exp_in=-60), _clerk_token(clerk, iss='https://evil.test')):
        assert world.client.get('/api/crm/me', headers={'Authorization': 'Bearer ' + token}).status_code == 401


def test_clerk_jwks_url_resolution(monkeypatch):
    monkeypatch.setattr(auth, 'CLERK_JWKS_URL', 'https://jwks.test/keys')
    assert auth._get_clerk_jwks_url() == 'https://jwks.test/keys'
    monkeypatch.setattr(auth, 'CLERK_JWKS_URL', '')
    monkeypatch.setattr(auth, 'CLERK_ISSUER', ISSUER + '/')
    assert auth._get_clerk_jwks_url() == ISSUER + '/.well-known/jwks.json'
    monkeypatch.setattr(auth, 'CLERK_ISSUER', '')
    assert auth._get_clerk_jwks_url() is None
    monkeypatch.setattr(auth, '_CLERK_JWKS_CLIENT', None)
    assert auth._get_clerk_jwks_client() is None
    monkeypatch.setattr(auth, 'CLERK_ISSUER', ISSUER)
    client = auth._get_clerk_jwks_client()  # builds a PyJWKClient without fetching
    assert client is not None
    monkeypatch.setattr(auth, '_CLERK_JWKS_CLIENT', None)
    monkeypatch.setattr(auth, 'PyJWKClient', lambda *a, **k: (_ for _ in ()).throw(ValueError('x')))
    assert auth._get_clerk_jwks_client() is None


def test_verify_clerk_without_config(monkeypatch):
    monkeypatch.setattr(auth, 'CLERK_ISSUER', '')
    monkeypatch.setattr(auth, 'CLERK_JWKS_URL', '')
    assert auth._verify_clerk_token('') is None
    assert auth._verify_clerk_token('a.b.c') is None
    monkeypatch.setattr(auth, '_CLERK_JWKS_CLIENT', None)
    hinted = jwt.encode({'sub': 'x', 'iss': 'https://my.clerk.accounts.dev'}, 'k' * 32, algorithm='HS256')
    assert auth._verify_clerk_token(hinted) is None


class _HttpxResponse:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload

    def json(self):
        return self._payload


class _Httpx:
    def __init__(self, status, payload):
        self.calls = 0
        self.response = _HttpxResponse(status, payload)

    def get(self, *_a, **_k):
        self.calls += 1
        return self.response


def test_supabase_auth_lookup_and_token_cache(world, monkeypatch):
    uid = world.users['admin']
    fake = _Httpx(200, {'id': uid})
    monkeypatch.setattr(auth, 'SUPABASE_URL', 'https://fake.supabase.test')
    monkeypatch.setattr(auth, 'SUPABASE_ANON_KEY', 'anon')
    monkeypatch.setattr(auth, '_get_httpx_client', lambda: fake)
    now = int(time.time())
    es256_like = jwt.encode({'sub': uid, 'exp': now + 300}, 'another-secret-key-of-32-bytes!!!', algorithm='HS256')
    for _ in range(3):
        assert world.client.get('/api/crm/me', headers={'Authorization': 'Bearer ' + es256_like}).status_code == 200
    assert fake.calls == 1  # later requests hit the token cache
    fake.response = _HttpxResponse(200, {'user': {'id': uid}})
    no_exp = 'a.' + 'e30' + '.c'  # payload "{}"
    assert world.client.get('/api/crm/me', headers={'Authorization': 'Bearer ' + no_exp}).status_code == 200
    fake.response = _HttpxResponse(401, {})
    assert world.client.get('/api/crm/me', headers={'Authorization': 'Bearer x.y.z'}).status_code == 401
    monkeypatch.setattr(auth, '_get_httpx_client', lambda: (_ for _ in ()).throw(RuntimeError('down')))
    assert world.client.get('/api/crm/me', headers={'Authorization': 'Bearer q.w.e'}).status_code == 401


def test_token_cache_expiry_and_cap(monkeypatch):
    auth._TOKEN_CACHE.clear()
    auth._token_cache_set('garbage-token', 'u1')
    assert auth._token_cache_get('garbage-token') == 'u1'
    past = jwt.encode({'exp': int(time.time()) - 5}, 'k' * 32, algorithm='HS256')
    auth._token_cache_set(past, 'u2')
    assert auth._token_cache_get(past) is None
    monkeypatch.setattr(auth, '_TOKEN_CACHE_MAX', 1)
    auth._token_cache_set('t1', 'a')
    auth._token_cache_set('t2', 'b')
    auth._token_cache_set('t3', 'c')
    assert len(auth._TOKEN_CACHE) <= 3


def test_profile_cache(monkeypatch):
    auth._PROFILE_CACHE.clear()
    assert auth._profile_cache_get('') == (None, False)
    auth._profile_cache_set('', {'x': 1})
    auth._profile_cache_set('u', {'role': 'admin'})
    assert auth._profile_cache_get('u') == ({'role': 'admin'}, True)
    auth._PROFILE_CACHE['u']['ts'] = 0
    assert auth._profile_cache_get('u') == (None, False)
    monkeypatch.setattr(auth, '_PROFILE_CACHE_MAX', 0)
    auth._profile_cache_set('a', {})
    auth._profile_cache_set('b', {})
    assert len(auth._PROFILE_CACHE) == 1


def test_profile_created_and_synced_on_first_request(world):
    w = world
    uid = 'brand-new-user'
    w.db.auth_users[uid] = {'id': uid, 'email': 'fresh@example.test', 'user_metadata': {'display_name': 'Fresh'}}
    r = w.client.get('/api/crm/me', headers={'Authorization': 'Bearer ' + w.token(uid)})
    assert r.status_code == 200
    profile = w.db.one('profiles', user_id=uid)
    assert profile and profile['role'] == 'user'
    # A profile without a name is filled from the auth record.
    w.db.one('profiles', user_id=w.users['user'])['display_name'] = ''
    auth._profile_cache_invalidate(w.users['user'])
    w.get('/api/crm/me', as_='user')
    assert w.db.one('profiles', user_id=w.users['user'])['display_name'] == 'User'


def test_profile_sync_edge_cases(world):
    sb = world.db
    auth._sync_profile_display_name_from_auth(sb, 'missing-user')  # auth lookup fails: ignored
    sb.auth_users['blank'] = {'id': 'blank', 'email': None, 'user_metadata': {}}
    auth._sync_profile_display_name_from_auth(sb, 'blank')
    sb.fail_tables['profiles'] = 'down'
    assert auth.ensure_profile(sb, 'someone', 'user', existing_profile={})['user_id'] == 'someone'


def test_requests_without_database(world, monkeypatch):
    import app.core.database as database
    monkeypatch.setattr(database, 'SUPABASE_URL', '')
    with world.app.test_request_context(headers={'Authorization': 'Bearer ' + world.token('admin')}):
        assert auth.get_current_user() == (world.users['admin'], 'user')
        assert auth.get_current_user() == (world.users['admin'], 'user')  # memoised per request


def test_profile_lookup_failure_is_not_cached(world):
    auth._PROFILE_CACHE.clear()
    world.db.fail_at, world.db.fail_persist, world.db.call_index = 1, True, 0
    assert auth.get_profile(world.db, world.users['admin']) is None  # fails even after the retry
    world.db.fail_at, world.db.fail_persist = None, False
    assert auth.get_profile(world.db, world.users['admin'])['role'] == 'admin'
    assert auth.get_profile(world.db, 'nobody') is None
