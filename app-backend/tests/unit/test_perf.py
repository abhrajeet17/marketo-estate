import re

from app.core import perf
from app.core.concurrency import run_parallel


def test_wall_time_is_union_of_spans():
    assert perf._wall_ms([]) == 0
    assert round(perf._wall_ms([(0.0, 0.1)])) == 100
    # Overlapping calls count once; the gap between groups does not count.
    assert round(perf._wall_ms([(0.0, 0.1), (0.05, 0.15), (0.3, 0.4)])) == 250


def test_record_outside_a_request_is_ignored():
    perf.record('db', 12.0)  # must not raise


def test_parallel_reads_are_attributed_to_the_request():
    token = perf._current.set(perf._new_stats())
    try:
        run_parallel(lambda: perf.record('db', 5.0), lambda: perf.record('db', 7.0), lambda: perf.record('s3', 1.0))
        stats = perf._current.get()
        assert stats['db_n'] == 2 and stats['db_ms'] == 12.0 and stats['s3_n'] == 1
    finally:
        perf._current.reset(token)


def test_server_timing_header_on_responses(client):
    resp = client.get('/login')
    header = resp.headers.get('Server-Timing', '')
    for part in ('db;', 'auth;', 's3;', 'io;', 'app;', 'total;'):
        assert part in header
    assert re.search(r'db;desc="0 queries"', header)
