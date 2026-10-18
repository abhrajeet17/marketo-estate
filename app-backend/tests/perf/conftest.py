"""
Fixtures for the API timing suite.

The suite runs the real Flask app in-process against the Supabase project configured in .env
and only ever issues GET requests, so no data is created, changed or deleted.

Auth: a short-lived HS256 token is signed locally with SUPABASE_JWT_SECRET for an existing
profile (the backend accepts these), so no password is needed. Path parameters are filled with
real ids read from the database.
"""
import json
import os
import time
from datetime import datetime, timezone

import pytest

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REPORT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'reports')

BUDGET_MS = float(os.environ.get('PERF_BUDGET_MS', '500'))
SAMPLES = max(1, int(os.environ.get('PERF_SAMPLES', '3')))
# Round-trip to the database from production (e.g. Heroku us-east -> Supabase ap-south-1 is
# ~230ms). Used to project production latency from the measured query count.
PROD_RTT_MS = float(os.environ.get('PERF_PROD_RTT_MS', '230'))
LOCAL_RTT = {'ms': None}
ROLE_ORDER = ('admin', 'superadmin', 'broker', 'user')

_results = []


@pytest.fixture(scope='session')
def app():
    import sys
    sys.path.insert(0, BACKEND_DIR)
    from app import app as flask_app
    from app.core.database import get_supabase
    if not get_supabase():
        pytest.skip('Supabase is not configured (.env)')
    return flask_app


@pytest.fixture(scope='session')
def client(app):
    return app.test_client()


@pytest.fixture(scope='session')
def sb(app):
    from app.core.database import get_supabase
    sb = get_supabase()
    LOCAL_RTT['ms'] = measure_rtt(sb)
    return sb


def measure_rtt(sb, samples=7):
    """Median round-trip of a trivial query from this machine to the database, in ms."""
    import statistics
    times = []
    for _ in range(samples):
        start = time.perf_counter()
        sb.table('organizations').select('id').limit(1).execute()
        times.append((time.perf_counter() - start) * 1000.0)
    return statistics.median(times)


def _sign_token(user_id):
    import jwt
    from app.config import SUPABASE_JWT_SECRET
    now = int(time.time())
    return jwt.encode({'sub': str(user_id), 'role': 'authenticated', 'iat': now, 'exp': now + 900},
                      SUPABASE_JWT_SECRET, algorithm='HS256')


@pytest.fixture(scope='session')
def auth_headers(sb):
    from app.config import SUPABASE_JWT_SECRET
    if not SUPABASE_JWT_SECRET:
        pytest.skip('SUPABASE_JWT_SECRET is required to sign test tokens')
    return load_auth_headers(sb)


def load_auth_headers(sb):
    """{role: headers} for one existing profile per role, best-connected profile first."""
    profiles = sb.table('profiles').select('user_id, role, org_id').execute().data or []
    owned = {}
    for row in sb.table('panoramas').select('user_id').execute().data or []:
        owned[row['user_id']] = owned.get(row['user_id'], 0) + 1
    headers = {}
    for p in sorted(profiles, key=lambda p: -owned.get(p['user_id'], 0)):
        role = p.get('role') or 'user'
        if role not in headers:
            headers[role] = {'Authorization': f"Bearer {_sign_token(p['user_id'])}"}
    headers[None] = {}
    return headers


def _first(sb, table, column='id', where=None, order=None):
    try:
        q = sb.table(table).select(column)
        for col, op in (where or {}).items():
            q = q.not_.is_(col, 'null') if op == 'not_null' else q.eq(col, op)
        if order:
            q = q.order(order, desc=True)
        rows = q.limit(1).execute().data or []
        return str(rows[0][column]) if rows and rows[0].get(column) is not None else None
    except Exception:
        return None


@pytest.fixture(scope='session')
def owner_id(sb):
    return load_owner_id(sb)


def load_owner_id(sb):
    """The admin (or else any) profile owning the most panoramas: tests read its resources."""
    roles = {p['user_id']: p.get('role') for p in sb.table('profiles').select('user_id, role').execute().data or []}
    owned = {}
    for row in sb.table('panoramas').select('user_id').execute().data or []:
        owned[row['user_id']] = owned.get(row['user_id'], 0) + 1
    ranked = sorted(owned, key=lambda u: (roles.get(u) not in ('admin', 'superadmin'), -owned[u]))
    return ranked[0] if ranked else None


@pytest.fixture(scope='session')
def ids(sb, owner_id):
    return load_ids(sb, owner_id)


def load_ids(sb, owner_id):
    """Real ids for every path parameter, keyed by (route prefix, parameter name)."""
    def owned(table, column='id', where=None):
        return _first(sb, table, column, dict(where or {}, user_id=owner_id)) or _first(sb, table, column, where)

    main_ws = owned('workspaces', 'id', {'main_panorama_id': 'not_null'})
    pano = owned('workspaces', 'main_panorama_id', {'main_panorama_id': 'not_null'}) or owned('panoramas')
    quote = sb.table('crm_deal_quotes').select('id, deal_id').limit(1).execute().data or []
    return {
        'panorama_id': pano,
        'workspace_id': main_ws or owned('workspaces'),
        'plot_id': _first(sb, 'plots', 'id', {'image_filename': 'not_null'}) or _first(sb, 'plots'),
        'marker_id': _first(sb, 'plot_markers', 'id', {'image_filename': 'not_null'}) or _first(sb, 'plot_markers'),
        'client_id': _first(sb, 'clients'),
        'catalogue_id': owned('floor_plan_catalogues'),
        'gallery_id': owned('galleries'),
        'deal_id': str(quote[0]['deal_id']) if quote else _first(sb, 'crm_deals'),
        'quote_id': str(quote[0]['id']) if quote else None,
        'lead_id': _first(sb, 'crm_leads'),
        'project_id': owned('daynight_projects'),
        'plan_id': owned('project_plans'),
        'invite_token': _first(sb, 'client_team_invites', 'invite_token'),
        ('/api/building-maps', 'map_id'): owned('building_maps'),
        ('/api/sales-maps', 'map_id'): owned('sales_route_maps'),
        ('/api/earth-views', 'view_id'): owned('earth_views'),
        ('/api/sales-flat360', 'view_id'): owned('sales_flat360_views'),
        ('/api/public/building-map', 'share_token'): owned('building_maps', 'share_token', {'share_token': 'not_null'}),
        ('/api/public/earth-view', 'share_token'): owned('earth_views', 'share_token', {'share_token': 'not_null'}),
        ('/api/public/building-plan', 'token'): owned('project_plans', 'share_token', {'share_token': 'not_null'}),
    }


def record_result(row):
    _results.append(row)


def pytest_sessionfinish(session, exitstatus):
    if not _results:
        return
    os.makedirs(REPORT_DIR, exist_ok=True)
    rows = sorted(_results, key=lambda r: -(r.get('warm_ms') or 0))
    stamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    with open(os.path.join(REPORT_DIR, 'api_timings.json'), 'w', encoding='utf-8') as f:
        json.dump({'generated': stamp, 'budget_ms': BUDGET_MS, 'prod_rtt_ms': PROD_RTT_MS,
                   'local_rtt_ms': LOCAL_RTT['ms'], 'results': rows}, f, indent=2)
    lines = [
        f'# API timings ({stamp})', '',
        f'Budget {BUDGET_MS:.0f} ms. Local database round-trip {LOCAL_RTT["ms"] or 0:.0f} ms. '
        '"Round-trips" = I/O wait / local round-trip (sequential depth). '
        f'"Prod est." = Python ms + round-trips x {PROD_RTT_MS:.0f} ms.', '',
        '| Route | Role | Status | Cold ms | Warm ms | DB queries | S3 calls | I/O wait ms | Round-trips | Python ms | Prod est. ms |',
        '|---|---|---|---|---|---|---|---|---|---|---|',
    ]
    for r in rows:
        if r.get('skipped'):
            continue
        lines.append('| `{path}` | {role} | {status} | {cold_ms:.0f} | {warm_ms:.0f} | {db_n} | {s3_n} | {io_ms:.0f} | {depth:.1f} | {app_ms:.0f} | {prod_ms:.0f} |'.format(**r))
    skipped = [r for r in rows if r.get('skipped')]
    if skipped:
        lines += ['', '## Not measured', ''] + [f"- `{r['rule']}`: {r['skipped']}" for r in skipped]
    with open(os.path.join(REPORT_DIR, 'api_timings.md'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
