"""
Per-request performance accounting.

Counts and times every Supabase HTTP call (PostgREST + Auth) and storage (S3) call made while
serving a request, then reports them:

- `Server-Timing` response header (Chrome DevTools > Network > Timing shows the breakdown);
- one log line for any request slower than PERF_SLOW_MS (default 500), so production logs
  name the slow endpoints and whether the time went to the database, storage or Python.

Calls made outside a request (background threads) are not attributed to anything.
"""
import contextvars
import logging
import os
import threading
import time

import httpx
from flask import g, request

logger = logging.getLogger('app.perf')
_lock = threading.Lock()

SLOW_REQUEST_MS = float(os.environ.get('PERF_SLOW_MS', '500'))
SERVER_TIMING_ENABLED = os.environ.get('PERF_SERVER_TIMING', 'true').lower() not in ('0', 'false', 'no')
# Keep the list of individual calls per request (g._perf_trace) for diagnosis; off in production.
TRACE_ENABLED = os.environ.get('PERF_TRACE', '').lower() in ('1', 'true', 'yes')


# The current request's counters. A context variable (not flask.g) so that reads fanned out to
# worker threads by app.core.concurrency.run_parallel are still attributed to the request.
_current = contextvars.ContextVar('perf_stats', default=None)


def _new_stats():
    return {'db_n': 0, 'db_ms': 0.0, 'auth_n': 0, 'auth_ms': 0.0, 's3_n': 0, 's3_ms': 0.0, 'trace': [], 'spans': []}


def _wall_ms(spans):
    """Length of the union of (start, end) spans: I/O time on the critical path, in ms.

    Parallel calls overlap, so this (not the per-call sum) is what the request waited for.
    """
    total, cur_start, cur_end = 0.0, None, None
    for start, end in sorted(spans):
        if cur_end is None or start > cur_end:
            if cur_end is not None:
                total += cur_end - cur_start
            cur_start, cur_end = start, end
        else:
            cur_end = max(cur_end, end)
    if cur_end is not None:
        total += cur_end - cur_start
    return total * 1000.0


def record(kind, elapsed_ms, label=None):
    stats = _current.get()
    if stats is None:
        return
    end = time.perf_counter()
    with _lock:
        stats[f'{kind}_n'] += 1
        stats[f'{kind}_ms'] += elapsed_ms
        stats['spans'].append((end - elapsed_ms / 1000.0, end))
        if TRACE_ENABLED:
            stats['trace'].append((kind, label, round(elapsed_ms, 1)))


def current_trace():
    stats = _current.get()
    return list(stats['trace']) if stats else []


class TimingTransport(httpx.BaseTransport):
    """httpx transport wrapper that records each Supabase round-trip on the current request."""

    def __init__(self, inner):
        self._inner = inner

    def handle_request(self, req):
        start = time.perf_counter()
        try:
            return self._inner.handle_request(req)
        finally:
            kind = 'auth' if req.url.path.startswith('/auth/') else 'db'
            label = f'{req.method} {req.url.path}?{req.url.query.decode()[:300]}' if TRACE_ENABLED else None
            record(kind, (time.perf_counter() - start) * 1000.0, label)

    def close(self):
        self._inner.close()


def instrument_boto_client(client):
    """Record every storage API call (HEAD/GET/PUT...) made through a boto3 client."""
    def before(**kwargs):
        context = kwargs.get('context')
        if context is not None:
            context['_perf_start'] = time.perf_counter()

    def after(**kwargs):
        context = kwargs.get('context') or {}
        start = context.get('_perf_start')
        if start is not None:
            label = kwargs.get('event_name', '').rsplit('.', 1)[-1] if TRACE_ENABLED else None
            record('s3', (time.perf_counter() - start) * 1000.0, label)

    client.meta.events.register('before-call.s3', before)
    client.meta.events.register('after-call.s3', after)
    return client


def init_app(app):
    @app.before_request
    def _perf_start():
        g._perf_t0 = time.perf_counter()
        g._perf_token = _current.set(_new_stats())

    @app.after_request
    def _perf_report(response):
        t0 = getattr(g, '_perf_t0', None)
        if t0 is None:
            return response
        total_ms = (time.perf_counter() - t0) * 1000.0
        s = _current.get() or _new_stats()
        io_ms = _wall_ms(s['spans'])
        if SERVER_TIMING_ENABLED:
            # db/auth/s3 durations are per-call sums (parallel calls overlap); io is the wall time
            # the request spent waiting on them, app the rest (Python).
            response.headers['Server-Timing'] = ', '.join([
                f'db;desc="{s["db_n"]} queries";dur={s["db_ms"]:.1f}',
                f'auth;desc="{s["auth_n"]} calls";dur={s["auth_ms"]:.1f}',
                f's3;desc="{s["s3_n"]} calls";dur={s["s3_ms"]:.1f}',
                f'io;desc="wall";dur={io_ms:.1f}',
                f'app;desc="python";dur={max(0.0, total_ms - io_ms):.1f}',
                f'total;dur={total_ms:.1f}',
            ])
        if total_ms >= SLOW_REQUEST_MS and not request.path.startswith('/static/'):
            logger.warning(
                'slow request %s %s -> %s in %.0fms (io wait %.0fms; db %d/%.0fms, auth %d/%.0fms, s3 %d/%.0fms)',
                request.method, request.path, response.status_code, total_ms, io_ms,
                s['db_n'], s['db_ms'], s['auth_n'], s['auth_ms'], s['s3_n'], s['s3_ms'],
            )
        return response
