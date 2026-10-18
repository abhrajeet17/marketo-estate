"""
End-to-end tests in Google Chrome (Playwright), against the real app and the Supabase project in .env.

    python -m pytest tests/e2e -q                 # headless Chrome; starts the app on :5055 if needed
    E2E_HEADED=1 python -m pytest tests/e2e -q    # watch it run
    E2E_BASE_URL=http://localhost:5000 ...        # use a server you already run
    E2E_WRITE=1 ...                               # also run the create/rename/delete flows

Sign-in: a short-lived token is signed locally with SUPABASE_JWT_SECRET for the first platform
admin (the backend accepts it), and put in the browser's storage the way the login page does.
Supabase's own REST API rejects such tokens, so the few direct supabase-js reads (editor
markers) fail with PGRST301 under this login; they are ignored.

Read-only by default. E2E_WRITE=1 tests only touch records they create (named "[e2e] …") and
delete them again, even when the test fails.
"""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
import uuid

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(os.path.dirname(HERE))
PERF_DIR = os.path.join(os.path.dirname(HERE), 'perf')
REPORT_DIR = os.path.join(HERE, 'reports')
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

DEFAULT_PORT = int(os.environ.get('E2E_PORT', '5055'))
HEADED = os.environ.get('E2E_HEADED', '').lower() in ('1', 'true', 'yes')
WRITE = os.environ.get('E2E_WRITE', '').lower() in ('1', 'true', 'yes')
# Console noise that is not an app error: expected 4xx answers and the test-login limitation.
IGNORED_CONSOLE = ('status of 401', 'status of 403', 'status of 404', 'PGRST301')
IGNORED_HOSTS = ('googletagmanager', 'google-analytics', 'doubleclick', 'clarity.ms')
MEDIA_EXTENSIONS = ('.mp4', '.webm', '.mov', '.mp3', '.m4a', '.ogg', '.wav')


def pytest_configure(config):
    config.addinivalue_line('markers', 'write: creates and deletes its own test records (E2E_WRITE=1)')


def pytest_collection_modifyitems(config, items):
    if WRITE:
        return
    skip = pytest.mark.skip(reason='write flow: set E2E_WRITE=1 to run')
    for item in items:
        if 'write' in item.keywords:
            item.add_marker(skip)


# ── Server ──────────────────────────────────────────────────────────────────
def _listening(port):
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(('127.0.0.1', port)) == 0


@pytest.fixture(scope='session')
def base_url():
    configured = os.environ.get('E2E_BASE_URL', '').rstrip('/')
    if configured:
        yield configured
        return
    url = f'http://127.0.0.1:{DEFAULT_PORT}'
    proc = None
    if not _listening(DEFAULT_PORT):
        os.makedirs(REPORT_DIR, exist_ok=True)
        log = open(os.path.join(REPORT_DIR, 'server.log'), 'w', encoding='utf-8')
        env = dict(os.environ, PORT=str(DEFAULT_PORT))
        proc = subprocess.Popen([sys.executable, 'app.py'], cwd=BACKEND_DIR, env=env, stdout=log, stderr=subprocess.STDOUT)
        deadline = time.time() + 60
        while time.time() < deadline:
            try:
                if urllib.request.urlopen(url + '/login', timeout=3).status == 200:
                    break
            except Exception:
                time.sleep(0.5)
        else:
            proc.terminate()
            pytest.exit(f'app did not start on {url} (see tests/e2e/reports/server.log)', returncode=3)
    yield url
    if proc:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


# ── Data and sign-in ────────────────────────────────────────────────────────
@pytest.fixture(scope='session')
def sb():
    from app import app  # noqa: F401  (loads .env)
    from app.core.database import get_supabase
    client = get_supabase()
    if not client:
        pytest.skip('Supabase is not configured (.env)')
    return client


def _perf_helpers():
    """tests/perf/conftest.py (owner and id lookups), loaded under its own module name."""
    import importlib.util
    if 'perf_helpers' not in sys.modules:
        spec = importlib.util.spec_from_file_location('perf_helpers', os.path.join(PERF_DIR, 'conftest.py'))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        sys.modules['perf_helpers'] = module
    return sys.modules['perf_helpers']


@pytest.fixture(scope='session')
def owner_id(sb):
    return _perf_helpers().load_owner_id(sb)


@pytest.fixture(scope='session')
def ids(sb, owner_id):
    return _perf_helpers().load_ids(sb, owner_id)


@pytest.fixture(scope='session')
def token(owner_id):
    import jwt
    from app.config import SUPABASE_JWT_SECRET
    now = int(time.time())
    return jwt.encode({'sub': owner_id, 'role': 'authenticated', 'iat': now, 'exp': now + 3 * 3600},
                      SUPABASE_JWT_SECRET, algorithm='HS256')


@pytest.fixture(scope='session')
def api(base_url, token):
    """Small JSON client for the running app, signed in as the test admin."""
    import requests

    class Api:
        def __init__(self):
            self.session = requests.Session()
            self.session.headers['Authorization'] = f'Bearer {token}'

        def get(self, path, **kw):
            r = self.session.get(base_url + path, timeout=60, **kw)
            r.raise_for_status()
            return r.json()

        def request(self, method, path, **kw):
            return self.session.request(method, base_url + path, timeout=60, **kw)

    return Api()


@pytest.fixture(scope='session')
def projects(api):
    """Projects as the selection page lists them (owned, or shared and holding panoramas)."""
    data = api.get('/api/dashboard')
    with_panos = {str(p['workspace_id']) for p in data['panoramas'] if p.get('workspace_id')}
    listed = [p for p in data['projects'] if (p.get('access_type') or 'owner') == 'owner' or str(p['id']) in with_panos]
    assert listed, 'the test admin needs at least one project'
    return {'all': listed, 'panoramas': data['panoramas']}


@pytest.fixture(scope='session')
def main_project(projects):
    """The listed project with the most panoramas: the richest page for checks."""
    def count(p):
        return sum(1 for x in projects['panoramas'] if str(x.get('workspace_id')) == str(p['id']))
    return max(projects['all'], key=count)


def session_script(owner_id, token, active=None):
    from app.config import SUPABASE_URL
    ref = SUPABASE_URL.split('//', 1)[-1].split('.', 1)[0]
    now = int(time.time())
    items = {
        f'sb-{ref}-auth-token': {
            'access_token': token, 'token_type': 'bearer', 'expires_in': 3600, 'expires_at': now + 3 * 3600,
            'refresh_token': 'e2e', 'user': {'id': owner_id, 'aud': 'authenticated', 'role': 'authenticated'},
        },
        'marketostate_auth_session_v1': {'access_token': token, 'refresh_token': 'e2e', 'expires_at': now + 3 * 3600, 'user': {'id': owner_id}},
        'dashboard-sidebar-collapsed': '1',
    }
    sets = ''.join(f'localStorage.setItem({json.dumps(k)}, {json.dumps(v if isinstance(v, str) else json.dumps(v))});' for k, v in items.items())
    # Only on the first page of a context, so tests can change the active project afterwards.
    active_js = ''
    if active:
        value = json.dumps(json.dumps({'id': str(active['id']), 'name': active.get('name', '')}))
        active_js = f"if (!sessionStorage.getItem('e2e_init')) {{ localStorage.setItem({json.dumps(f'ms_active_project_v1:{owner_id}')}, {value}); }}"
    else:
        active_js = f"if (!sessionStorage.getItem('e2e_init')) {{ localStorage.removeItem({json.dumps(f'ms_active_project_v1:{owner_id}')}); }}"
    return f"try {{ {sets} {active_js} sessionStorage.setItem('e2e_init', '1'); }} catch (e) {{}}"


# ── Browser ─────────────────────────────────────────────────────────────────
@pytest.fixture(scope='session')
def browser():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        try:
            b = pw.chromium.launch(channel='chrome', headless=not HEADED)
        except Exception:
            # Google Chrome is not installed: Playwright's bundled Chromium (playwright install chromium).
            b = pw.chromium.launch(headless=not HEADED)
        yield b
        b.close()


class PageWatch:
    """Collects uncaught errors, console errors, failed requests and API calls of a page."""

    def __init__(self, page, base_url):
        self.page = page
        self.base_url = base_url
        self.errors = []
        self.api_calls = []
        page.on('pageerror', lambda e: self.errors.append(f'Uncaught: {e}'))
        page.on('console', self._console)
        page.on('requestfailed', self._failed)
        page.on('response', self._response)

    def _console(self, msg):
        if msg.type == 'error' and not any(x in msg.text for x in IGNORED_CONSOLE):
            self.errors.append(f'console: {msg.text[:300]}')

    def _failed(self, req):
        path = req.url.split('?', 1)[0].lower()
        if any(h in req.url for h in IGNORED_HOSTS):
            return
        if 'ERR_ABORTED' in str(req.failure) and (path.endswith(MEDIA_EXTENSIONS) or req.resource_type in ('media', 'image', 'fetch')):
            return  # navigations and <video>/<img> cancel their own requests
        self.errors.append(f'request failed: {req.method} {req.url[:160]} ({req.failure})')

    def _response(self, resp):
        if resp.url.startswith(self.base_url) and '/api/' in resp.url:
            self.api_calls.append((resp.request.method, resp.url[len(self.base_url):], resp.status))
            if resp.status >= 500:
                self.errors.append(f'API {resp.status}: {resp.request.method} {resp.url[len(self.base_url):][:160]}')

    def assert_clean(self):
        assert not self.errors, 'page problems:\n' + '\n'.join(self.errors[:20])


@pytest.fixture
def open_page(browser, base_url, owner_id, token, request):
    """open_page(path, active=project|None, signed_in=True, viewport=(w, h)) -> (page, watch)."""
    contexts = []

    def _open(path, active=None, signed_in=True, viewport=(1440, 900), wait='networkidle'):
        ctx = browser.new_context(viewport={'width': viewport[0], 'height': viewport[1]},
                                  permissions=['clipboard-read', 'clipboard-write'])
        if signed_in:
            ctx.add_init_script(session_script(owner_id, token, active))
        contexts.append(ctx)
        page = ctx.new_page()
        page.set_default_timeout(20000)
        watch = PageWatch(page, base_url)
        request.node._e2e_pages = getattr(request.node, '_e2e_pages', []) + [page]
        page.goto(base_url + path, wait_until=wait, timeout=60000)
        return page, watch

    yield _open
    for ctx in contexts:
        ctx.close()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if report.when == 'call' and report.failed:
        os.makedirs(REPORT_DIR, exist_ok=True)
        for i, page in enumerate(getattr(item, '_e2e_pages', [])):
            try:
                name = ''.join(c if c.isalnum() else '_' for c in item.nodeid.split('::', 1)[-1])[:120]
                page.screenshot(path=os.path.join(REPORT_DIR, f'FAIL_{name}_{i}.png'), full_page=True)
            except Exception:
                pass


@pytest.fixture
def unique_name():
    return f'[e2e] {time.strftime("%H%M%S")}-{uuid.uuid4().hex[:4]}'
