import contextvars
import threading
import time

import pytest

from app.core.concurrency import outcome, run_parallel


def test_results_keep_call_order():
    def slow(value, delay):
        return lambda: (time.sleep(delay), value)[1]
    assert run_parallel(slow('a', 0.05), slow('b', 0.0), slow('c', 0.02)) == ['a', 'b', 'c']


def test_reads_actually_overlap():
    start = time.perf_counter()
    run_parallel(*[lambda: time.sleep(0.1) for _ in range(4)])
    assert time.perf_counter() - start < 0.3


def test_failure_is_none_by_default():
    def boom():
        raise ValueError('x')
    assert run_parallel(lambda: 1, boom) == [1, None]


def test_strict_reraises_first_failure_after_all_finish():
    finished = []

    def late():
        time.sleep(0.05)
        finished.append('late')
        return 'ok'

    def boom():
        raise KeyError('first')

    with pytest.raises(KeyError):
        run_parallel(boom, late, strict=True)
    assert finished == ['late']


def test_single_read_runs_inline():
    caller = threading.get_ident()
    assert run_parallel(lambda: threading.get_ident()) == [caller]


def test_outcome_defers_errors_until_get():
    def boom():
        raise RuntimeError('denied')
    ok, failed = run_parallel(outcome(lambda: 5), outcome(boom))
    assert ok.get() == 5
    with pytest.raises(RuntimeError):
        failed.get()


def test_context_variables_follow_reads_into_threads():
    var = contextvars.ContextVar('request_id', default=None)
    var.set('req-1')
    assert run_parallel(lambda: var.get(), lambda: var.get()) == ['req-1', 'req-1']
