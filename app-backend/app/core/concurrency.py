import contextvars
from concurrent.futures import ThreadPoolExecutor


def run_parallel(*fns, strict=False):
    """Run independent Supabase reads concurrently; each result in call order.

    A failing read returns None instead of raising, so callers keep best-effort
    behaviour for optional lookups. With strict=True the first failure (in call
    order) is re-raised once every read has finished, as sequential code would.
    """
    def safe(fn):
        try:
            return fn()
        except Exception as exc:
            if strict:
                return _Failure(exc)
            return None
    if len(fns) == 1:
        results = [safe(fns[0])]
    else:
        results = _run_pool(safe, fns)
    if strict:
        for value in results:
            if isinstance(value, _Failure):
                raise value.exc
    return results


class _Failure:
    def __init__(self, exc):
        self.exc = exc


class Outcome:
    """Result of a read run through outcome(): .get() returns the value or re-raises."""

    def __init__(self, value=None, exc=None):
        self.value = value
        self.exc = exc

    def get(self):
        if self.exc is not None:
            raise self.exc
        return self.value


def outcome(fn):
    """Wrap a read for run_parallel so its error is kept, to be raised only if the result is used.

    Lets a handler start child reads alongside its access check: if access is denied the
    children's results (and errors) are simply discarded, as if they had never run.
    """
    def call():
        try:
            return Outcome(value=fn())
        except Exception as exc:
            return Outcome(exc=exc)
    return call


def _run_pool(safe, fns):
    with ThreadPoolExecutor(max_workers=min(6, len(fns))) as pool:
        # Each read runs in its own copy of the caller's context (taken here, on the calling
        # thread) so per-request accounting in app.core.perf follows it into the pool.
        contexts = [contextvars.copy_context() for _ in fns]
        return list(pool.map(lambda pair: pair[0].run(safe, pair[1]), zip(contexts, fns)))
