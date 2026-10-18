"""Every page of the product opens in Chrome without errors (admin pages signed in, customer pages as a visitor)."""
import pytest


def _pages(sb, ids, owner_id):
    import importlib.util
    import os
    import sys
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    spec = importlib.util.spec_from_file_location('ui_smoke_pages', os.path.join(here, 'perf', 'ui_smoke.py'))
    module = importlib.util.module_from_spec(spec)
    sys.modules['ui_smoke_pages'] = module
    spec.loader.exec_module(module)
    return module.build_pages(sb, ids, owner_id)


@pytest.fixture(scope='module')
def page_list(sb, ids, owner_id):
    return _pages(sb, ids, owner_id)


@pytest.fixture(scope='module')
def page_tokens(api, page_list):
    """Editor pages need a short-lived page token from the running server."""
    edit = next((p.split('/')[-1].split('?')[0] for p, _w in page_list if p.startswith('/admin/3d/')), None)
    tokens = {}
    for mode in ('admin', 'client'):
        resp = api.request('POST', f'/api/panoramas/{edit}/page-token', json={'mode': mode})
        tokens[mode] = (resp.json() if resp.ok else {}).get('token', '')
    return tokens


def test_page_list_is_complete(page_list):
    paths = [p for p, _w in page_list]
    for required in ('/projectselection', '/dashboard', '/salestools', '/building-plans', '/full-view', '/crm', '/login'):
        assert required in paths
    assert len(paths) >= 40


def pytest_generate_tests(metafunc):
    if 'page_index' in metafunc.fixturenames:
        metafunc.parametrize('page_index', range(48))


def test_page_opens_cleanly(open_page, page_list, page_tokens, main_project, page_index):
    if page_index >= len(page_list):
        pytest.skip('fewer pages in this database')
    path, who = page_list[page_index]
    path = path.replace('{admin}', page_tokens['admin']).replace('{client}', page_tokens['client'])
    page, watch = open_page(path, active=main_project if who == 'admin' else None, signed_in=(who == 'admin'),
                            wait='load')
    try:
        page.wait_for_load_state('networkidle', timeout=15000)
    except Exception:
        pass  # pages streaming video never go idle; errors below still count
    page.wait_for_timeout(800)
    status = page.evaluate("performance.getEntriesByType('navigation')[0]?.responseStatus || 200")
    assert status < 400, f'{path} -> HTTP {status}'
    assert '/login' not in page.url or path == '/login', f'{path} sent a signed-in admin to login'
    watch.assert_clean()
