"""
Browser smoke test: open every page of the app in headless Chromium (as the admin and as a
public visitor), and report JavaScript errors, failed requests and the timing of every API
call each page makes.

    pip install playwright && python -m playwright install chromium
    python tests/perf/ui_smoke.py [http://127.0.0.1:5055]     # app must already be running

Read-only: pages are only loaded, nothing is clicked or submitted. Report:
tests/perf/reports/ui_smoke.md (+ .json). Exit code 1 when any page has an error.
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

BASE = (sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:5055').rstrip('/')
BUDGET_MS = float(os.environ.get('PERF_BUDGET_MS', '500'))
SETTLE_MS = 1500
# Requests that fail for reasons unrelated to the app (third-party trackers, map tiles...).
IGNORED_HOSTS = ('googletagmanager', 'google-analytics', 'doubleclick', 'clarity.ms')
# Expected 401/403/404 API answers (e.g. a broker-only endpoint refusing an admin) are listed per
# call in the report; the browser's generic console line for them is not an error of its own.
EXPECTED_STATUS_CONSOLE = ('status of 401', 'status of 403', 'status of 404')
# The test signs in with a token signed by the legacy JWT secret, which the backend accepts but
# Supabase's own REST API (used directly by some pages via supabase-js) does not. Those calls fail
# only under this test login; they are reported as notes, not errors.
TEST_LOGIN_LIMITATION = ('PGRST301',)
MEDIA_EXTENSIONS = ('.mp4', '.webm', '.mov', '.mp3', '.m4a', '.ogg', '.wav')


def _is_benign_failure(request):
    # <video>/<audio> elements cancel their own range/preload requests: not an error.
    path = request.url.split('?', 1)[0].lower()
    return 'ERR_ABORTED' in str(request.failure) and path.endswith(MEDIA_EXTENSIONS)


def _share_tokens(sb):
    def first(table, column='share_token'):
        try:
            rows = sb.table(table).select(column).not_.is_(column, 'null').limit(1).execute().data or []
            return rows[0][column] if rows else None
        except Exception:
            return None
    endpoint = first('workspace_share_endpoints', 'endpoint')
    return {
        'gallery': first('galleries'),
        'daynight': first('daynight_projects'),
        'sales_map': first('sales_route_maps'),
        'flat360': first('sales_flat360_views'),
        'catalogue': first('floor_plan_catalogues'),
        'plan': first('project_plans'),
        'building_map': first('building_maps'),
        'earth_view': first('earth_views'),
        'endpoint': endpoint,
    }


def build_pages(sb, ids, owner_id):
    t = _share_tokens(sb)
    pano, ws = ids.get('panorama_id'), ids.get('workspace_id')
    # The editor (admin mode) only opens for the panorama's owner.
    owned = sb.table('panoramas').select('id').eq('user_id', owner_id).limit(1).execute().data or []
    edit_pano = owned[0]['id'] if owned else pano
    admin = [
        '/projectselection', '/dashboard', '/crm', '/salestools', '/building-plans', '/full-view', '/daynight',
        '/sales-route-maps', '/sales-flat360', '/user-management', '/organizations',
        '/client-management', '/projects', '/portal', '/explore',
        f'/admin/{edit_pano}?pt={{admin}}', f'/admin/3d/{edit_pano}?pt={{admin}}',
        f'/client/{edit_pano}?pt={{client}}', f'/client/3d/{edit_pano}?pt={{client}}',
        f'/customer/edit/{ws}', f'/customer/full-view/edit/{ws}',
        f"/building-map/admin/{ids.get(('/api/building-maps', 'map_id'))}",
        f"/earth-view/admin/{ids.get(('/api/earth-views', 'view_id'))}",
        f"/sales-route-maps/editor/{ids.get(('/api/sales-maps', 'map_id'))}",
        f"/sales-flat360/editor/{ids.get(('/api/sales-flat360', 'view_id'))}",
    ]
    public = [
        '/login', f'/customer/{pano}', f'/customer/3d/{pano}', f'/customer/full-view/{ws}',
        f"/customer/full-view/floor-plan/{ids.get('catalogue_id')}",
        f"/customer/full-view/gallery/{ids.get('gallery_id')}",
        f"/customer/full-view/project-plan/{ids.get('plan_id')}",
        f"/customer/full-view/sales-map/{ids.get(('/api/sales-maps', 'map_id'))}",
        f"/customer/full-view/daynight/{ids.get('project_id')}",
    ]
    for key, route in (('gallery', '/gallery/view/{}'), ('daynight', '/daynight/view/{}'),
                       ('sales_map', '/sales-route-map/view/{}'), ('flat360', '/sales-flat360/view/{}'),
                       ('catalogue', '/floorplans/view/{}'), ('plan', '/project-plan/view/{}'),
                       ('building_map', '/building-plan/{}'), ('earth_view', '/earth-view/view/{}'),
                       ('endpoint', '/panoview/{}')):
        if t.get(key):
            public.append(route.format(t[key]))
    return [(p, 'admin') for p in admin if 'None' not in p] + [(p, 'public') for p in public if 'None' not in p]


def _session_script(user_id, token, workspace_id=None):
    from app.config import SUPABASE_URL
    ref = SUPABASE_URL.split('//', 1)[-1].split('.', 1)[0]
    now = int(time.time())
    session = {
        'access_token': token, 'token_type': 'bearer', 'expires_in': 3600, 'expires_at': now + 3600,
        'refresh_token': 'ui-smoke', 'user': {'id': user_id, 'aud': 'authenticated', 'role': 'authenticated'},
    }
    cached = {'access_token': token, 'refresh_token': 'ui-smoke', 'expires_at': now + 3600, 'user': {'id': user_id}}
    items = {f'sb-{ref}-auth-token': session, 'marketostate_auth_session_v1': cached}
    # Workspace pages show the active project (picked on /projectselection); without one they redirect there.
    if workspace_id:
        items[f'ms_active_project_v1:{user_id}'] = {'id': str(workspace_id), 'name': ''}
    sets = ''.join(f'localStorage.setItem({json.dumps(k)}, {json.dumps(json.dumps(v))});' for k, v in items.items())
    return f'try {{ {sets} }} catch (e) {{}}'


def run():
    import conftest
    import jwt
    from playwright.sync_api import sync_playwright
    from app import app  # noqa: F401  (loads .env)
    from app.config import SUPABASE_JWT_SECRET
    from app.core.database import get_supabase

    sb = get_supabase()
    owner = conftest.load_owner_id(sb)
    ids = conftest.load_ids(sb, owner)
    now = int(time.time())
    token = jwt.encode({'sub': owner, 'role': 'authenticated', 'iat': now, 'exp': now + 3600}, SUPABASE_JWT_SECRET, algorithm='HS256')
    pages = build_pages(sb, ids, owner)
    # Editor pages need a short-lived page token, issued by the running server (it is signed with
    # that process's secret key) the same way the dashboard requests it.
    import requests
    page_tokens = {}
    edit_pano = next((p.split('/')[-1].split('?')[0] for p, _w in pages if p.startswith('/admin/3d/')), ids.get('panorama_id'))
    for mode in ('admin', 'client'):
        resp = requests.post(f'{BASE}/api/panoramas/{edit_pano}/page-token', json={'mode': mode},
                             headers={'Authorization': f'Bearer {token}'}, timeout=30)
        page_tokens[mode] = (resp.json() if resp.ok else {}).get('token', '')
    pages = [(p.replace('{admin}', page_tokens['admin']).replace('{client}', page_tokens['client']), who) for p, who in pages]
    results = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for path, who in pages:
            ctx = browser.new_context(viewport={'width': 1440, 'height': 900})
            if who == 'admin':
                ctx.add_init_script(_session_script(owner, token, ids.get('workspace_id')))
            page = ctx.new_page()
            errors, failed, apis, notes = [], [], [], []

            def on_console(m):
                if m.type != 'error' or any(x in m.text for x in EXPECTED_STATUS_CONSOLE):
                    return
                (notes if any(x in m.text for x in TEST_LOGIN_LIMITATION) else errors).append(m.text[:300])
            page.on('console', on_console)
            page.on('pageerror', lambda e: errors.append(f'Uncaught: {str(e)[:300]}'))
            page.on('requestfailed', lambda r: not any(h in r.url for h in IGNORED_HOSTS) and not _is_benign_failure(r)
                    and failed.append(f'{r.method} {r.url[:160]} ({r.failure})'))

            def on_response(resp):
                url = resp.url
                if url.startswith(BASE) and '/api/' in url:
                    timing = resp.request.timing
                    ms = timing.get('responseEnd', -1)
                    st = resp.headers.get('server-timing', '')
                    apis.append({'url': url[len(BASE):][:140], 'status': resp.status, 'ms': round(ms, 1), 'server_timing': st})
                    if resp.status >= 500 or (resp.status >= 400 and resp.status not in (401, 403, 404)):
                        failed.append(f'{resp.request.method} {url[len(BASE):][:140]} -> {resp.status}')
            page.on('response', on_response)

            start = time.perf_counter()
            status = None
            try:
                nav = page.goto(BASE + path, wait_until='networkidle', timeout=45000)
                status = nav.status if nav else None
                page.wait_for_timeout(SETTLE_MS)
            except Exception as e:
                errors.append(f'Navigation: {str(e)[:200]}')
            if status and status >= 400:
                errors.append(f'Page returned HTTP {status}')
            load_ms = (time.perf_counter() - start) * 1000.0
            results.append({'path': path, 'as': who, 'status': status, 'load_ms': round(load_ms),
                            'errors': errors, 'failed': failed, 'apis': apis, 'notes': notes,
                            'final_url': page.url[len(BASE):] if page.url.startswith(BASE) else page.url})
            print(f"{'OK ' if not errors and not failed else 'ERR'} {who:6} {path.split('?pt=')[0][:70]:70} {status} {load_ms:6.0f}ms apis={len(apis)} slow={sum(a['ms'] > BUDGET_MS for a in apis)}")
            ctx.close()
        browser.close()

    os.makedirs(os.path.join(HERE, 'reports'), exist_ok=True)
    with open(os.path.join(HERE, 'reports', 'ui_smoke.json'), 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=1)
    lines = ['# UI smoke test', '', f'{BASE}, {len(results)} pages. API budget {BUDGET_MS:.0f} ms.', '',
             '| Page | As | Status | Load ms | API calls | Slowest API ms | Errors |', '|---|---|---|---|---|---|---|']
    for r in results:
        slowest = max((a['ms'] for a in r['apis']), default=0)
        lines.append(f"| `{r['path'].split('?pt=')[0]}` | {r['as']} | {r['status']} | {r['load_ms']} | {len(r['apis'])} | {slowest:.0f} | {len(r['errors']) + len(r['failed'])} |")
    bad = [r for r in results if r['errors'] or r['failed']]
    noted = [r for r in results if r['notes']]
    if noted:
        lines += ['', '## Notes (test-login limitation, not app errors)', '']
        for r in noted:
            lines.append(f"- `{r['path'].split('?pt=')[0]}`: " + '; '.join(sorted(set(r['notes'])))[:300])
    if bad:
        lines += ['', '## Errors', '']
        for r in bad:
            lines.append(f"### `{r['path'].split('?pt=')[0]}` ({r['as']})")
            lines += [f'- {e}' for e in r['errors'] + r['failed']]
    with open(os.path.join(HERE, 'reports', 'ui_smoke.md'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    print(f'{len(results)} pages, {len(bad)} with errors')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(run())
