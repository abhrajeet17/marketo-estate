import os
import time
import statistics
from typing import Dict, List, Tuple

import requests


BASE_URL = os.environ.get("CRM_BENCH_BASE_URL", "http://127.0.0.1:5000").rstrip("/")
TOKEN = os.environ.get("CRM_BENCH_TOKEN", "").strip()
ITERATIONS = int(os.environ.get("CRM_BENCH_ITERATIONS", "12"))
TIMEOUT_SECONDS = float(os.environ.get("CRM_BENCH_TIMEOUT", "8"))


def _headers() -> Dict[str, str]:
    h = {"Accept": "application/json"}
    if TOKEN:
        h["Authorization"] = f"Bearer {TOKEN}"
    return h


def _ms(seconds: float) -> float:
    return round(seconds * 1000.0, 2)


def _stats(samples: List[float]) -> Tuple[float, float, float]:
    if not samples:
        return 0.0, 0.0, 0.0
    p50 = statistics.median(samples)
    p95_idx = max(0, min(len(samples) - 1, int(len(samples) * 0.95) - 1))
    p95 = sorted(samples)[p95_idx]
    return _ms(min(samples)), _ms(p50), _ms(p95)


def benchmark(path: str) -> Dict[str, object]:
    url = f"{BASE_URL}{path}"
    samples: List[float] = []
    ok = 0
    fail = 0
    last_status = None

    for _ in range(ITERATIONS):
        start = time.perf_counter()
        try:
            resp = requests.get(url, headers=_headers(), timeout=TIMEOUT_SECONDS)
            elapsed = time.perf_counter() - start
            samples.append(elapsed)
            last_status = resp.status_code
            if 200 <= resp.status_code < 300:
                ok += 1
            else:
                fail += 1
        except Exception:
            elapsed = time.perf_counter() - start
            samples.append(elapsed)
            fail += 1

    mn, p50, p95 = _stats(samples)
    return {
        "path": path,
        "ok": ok,
        "fail": fail,
        "status": last_status,
        "min_ms": mn,
        "p50_ms": p50,
        "p95_ms": p95,
    }


def main():
    paths = [
        "/api/crm/me",
        "/api/crm/panoramas",
        "/api/buy-interests?page=1&limit=10",
        "/api/crm/contacts?include_counts=1&page=1&limit=10",
        "/api/crm/deals?page=1&limit=10",
        "/api/crm/plots?page=1&limit=10",
        "/api/crm/crm-team-users",
        "/api/crm/quote-templates",
        "/api/crm/lockable-plots",
    ]
    print(f"CRM benchmark base={BASE_URL} iterations={ITERATIONS}")
    if not TOKEN:
        print("WARNING: CRM_BENCH_TOKEN is not set; authenticated endpoints may return 401.")
    print("-" * 90)
    for path in paths:
        r = benchmark(path)
        print(
            f"{r['path']:<40} status={str(r['status']):<4} "
            f"ok={r['ok']:<3} fail={r['fail']:<3} "
            f"min={r['min_ms']:>7}ms p50={r['p50_ms']:>7}ms p95={r['p95_ms']:>7}ms"
        )


if __name__ == "__main__":
    main()
