"""
Times every GET API route of the app and fails any route slower than the budget.

    cd app-backend
    python -m pytest tests/perf -q                    # all routes, report in tests/perf/reports/
    PERF_BUDGET_MS=300 PERF_SAMPLES=5 python -m pytest tests/perf -q
    python -m pytest tests/perf -q -k crm             # one area

Routes are discovered from the Flask URL map, so new GET routes are picked up automatically.
Each route is called once cold (caches empty for that route), then PERF_SAMPLES times warm; the
warm median is checked against PERF_BUDGET_MS. The per-request query and storage-call counts
come from the Server-Timing header added by app/core/perf.py.
"""
import re
import statistics
import time

import pytest

from conftest import BUDGET_MS, LOCAL_RTT, PROD_RTT_MS, ROLE_ORDER, SAMPLES, record_result

# Query strings some endpoints require (filled from the `ids` fixture).
EXTRA_QUERY = {
    '/api/public/full-view': {'workspace_id'},
    '/api/full-view/config': {'workspace_id'},
}
EXCLUDED = set()


def _discover_routes():
    import os
    import sys
    from conftest import BACKEND_DIR
    sys.path.insert(0, BACKEND_DIR)
    os.environ.setdefault('PERF_SERVER_TIMING', 'true')
    from app import app
    rules = sorted({r.rule for r in app.url_map.iter_rules()
                    if 'GET' in r.methods and r.rule.startswith('/api/') and r.rule not in EXCLUDED})
    return rules


ROUTES = _discover_routes()


def _resolve(rule, ids):
    path = rule
    for arg in re.findall(r'<(?:[a-z]+:)?([a-z_]+)>', rule):
        value = None
        for (prefix, name), v in ((k, v) for k, v in ids.items() if isinstance(k, tuple)):
            if name == arg and rule.startswith(prefix):
                value = v
        if value is None:
            value = ids.get(arg)
        if value is None:
            return None, f'no data for <{arg}>'
        path = re.sub(r'<(?:[a-z]+:)?%s>' % arg, str(value), path, count=1)
    query = {k: ids[k] for k in EXTRA_QUERY.get(rule, ()) if ids.get(k)}
    if query:
        path += '?' + '&'.join(f'{k}={v}' for k, v in query.items())
    return path, None


def _server_timing(resp):
    out = {}
    for part in (resp.headers.get('Server-Timing') or '').split(','):
        bits = [b.strip() for b in part.split(';')]
        if not bits or not bits[0]:
            continue
        entry = {'dur': 0.0, 'n': 0}
        for b in bits[1:]:
            if b.startswith('dur='):
                entry['dur'] = float(b[4:])
            elif b.startswith('desc='):
                m = re.match(r'desc="(\d+)', b)
                entry['n'] = int(m.group(1)) if m else 0
        out[bits[0]] = entry
    return out


def _call(client, path, headers):
    start = time.perf_counter()
    resp = client.get(path, headers=headers)
    resp.get_data()  # drain streamed bodies so their time is counted
    return (time.perf_counter() - start) * 1000.0, resp


@pytest.mark.parametrize('rule', ROUTES)
def test_api_timing(rule, client, ids, auth_headers):
    path, reason = _resolve(rule, ids)
    if not path:
        record_result({'rule': rule, 'skipped': reason})
        pytest.skip(reason)

    # Measure as the first role the route lets in (public routes: no token needed).
    chosen = None
    for role in ROLE_ORDER + (None,):
        if role not in auth_headers:
            continue
        cold_ms, resp = _call(client, path, auth_headers[role])
        if resp.status_code not in (401, 403):
            chosen = (role, cold_ms, resp)
            break
    if chosen is None:
        record_result({'rule': rule, 'skipped': 'every role got 401/403'})
        pytest.skip('every role got 401/403')
    role, cold_ms, resp = chosen
    headers = auth_headers[role]

    samples, timings = [], []
    for _ in range(SAMPLES):
        ms, resp = _call(client, path, headers)
        samples.append(ms)
        timings.append(_server_timing(resp))
    warm_ms = statistics.median(samples)
    last = timings[samples.index(sorted(samples)[len(samples) // 2])]
    db_n = last.get('db', {}).get('n', 0) + last.get('auth', {}).get('n', 0)
    s3_n = last.get('s3', {}).get('n', 0)
    app_ms = last.get('app', {}).get('dur', 0.0)
    io_ms = last.get('io', {}).get('dur', 0.0)
    depth = io_ms / LOCAL_RTT['ms'] if LOCAL_RTT['ms'] else 0.0
    row = {
        'rule': rule, 'path': path, 'role': role or 'public', 'status': resp.status_code,
        'cold_ms': cold_ms, 'warm_ms': warm_ms,
        'db_n': db_n, 'db_ms': last.get('db', {}).get('dur', 0.0) + last.get('auth', {}).get('dur', 0.0),
        's3_n': s3_n, 's3_ms': last.get('s3', {}).get('dur', 0.0), 'app_ms': app_ms,
        'io_ms': io_ms, 'depth': depth, 'prod_ms': app_ms + depth * PROD_RTT_MS,
    }
    from app.core.perf import TRACE_ENABLED, current_trace
    if TRACE_ENABLED:
        row['trace'] = current_trace()  # calls made by the last sample (PERF_TRACE=1)
    record_result(row)

    assert resp.status_code < 500, f'{path} -> {resp.status_code}: {resp.get_data(as_text=True)[:200]}'
    assert warm_ms <= BUDGET_MS, (
        f'{path} took {warm_ms:.0f}ms (budget {BUDGET_MS:.0f}ms): '
        f'{db_n} DB queries + {s3_n} storage calls, {io_ms:.0f}ms waiting on I/O '
        f'(~{depth:.1f} sequential round-trips), python {app_ms:.0f}ms'
    )
