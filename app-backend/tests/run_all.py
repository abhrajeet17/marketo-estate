"""
Run every test suite in order and write one summary. Use before every deployment (see TEST.md).

    python tests/run_all.py              # unit + API + end-to-end (Chrome)
    python tests/run_all.py --quick      # unit + end-to-end, skip the API timing suite
    python tests/run_all.py --write      # also run the create/rename/delete browser flows
    python tests/run_all.py --headed     # show the Chrome window
    python tests/run_all.py --base-url http://localhost:5000   # test a server you already run

Exit code 0 only when every suite passed. Summary: tests/reports/summary.md, JUnit XML per
suite next to it, failure screenshots in tests/e2e/reports/.
"""
import argparse
import os
import subprocess
import sys
import time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(HERE)
REPORT_DIR = os.path.join(HERE, 'reports')

SUITES = [
    # (key, title, pytest target)
    ('unit', 'Backend unit tests (offline)', 'tests/unit'),
    ('api', 'API tests: every GET route, no 5xx, under the time budget', 'tests/perf'),
    ('e2e', 'End-to-end in Google Chrome', 'tests/e2e'),
]


def run_suite(key, target, env):
    junit = os.path.join(REPORT_DIR, f'{key}.xml')
    cmd = [sys.executable, '-m', 'pytest', target, '-q', '-rfEs', '-p', 'no:cacheprovider', f'--junitxml={junit}']
    start = time.time()
    proc = subprocess.run(cmd, cwd=BACKEND_DIR, env=env, capture_output=True, text=True, encoding='utf-8', errors='replace')
    elapsed = time.time() - start
    output = proc.stdout + proc.stderr
    lines = [l for l in output.splitlines() if l.strip()]
    tally = next((l.strip('= ') for l in reversed(lines) if (' passed' in l or ' failed' in l or ' error' in l) and ' in ' in l), '')
    failures = [l for l in lines if l.startswith(('FAILED', 'ERROR'))]
    with open(os.path.join(REPORT_DIR, f'{key}.log'), 'w', encoding='utf-8') as f:
        f.write(output)
    # pytest exit code 5 = nothing collected (e.g. database not configured): not a pass.
    return {'ok': proc.returncode == 0, 'code': proc.returncode, 'tally': tally or f'exit code {proc.returncode}',
            'failures': failures, 'seconds': elapsed}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--quick', action='store_true', help='skip the API timing suite')
    parser.add_argument('--write', action='store_true', help='run browser flows that create and delete test records')
    parser.add_argument('--headed', action='store_true', help='show the Chrome window')
    parser.add_argument('--base-url', help='test an already running server instead of starting one')
    parser.add_argument('--only', choices=[s[0] for s in SUITES], action='append', help='run only these suites')
    args = parser.parse_args()

    os.makedirs(REPORT_DIR, exist_ok=True)
    env = dict(os.environ, PYTHONIOENCODING='utf-8')
    if args.write:
        env['E2E_WRITE'] = '1'
    if args.headed:
        env['E2E_HEADED'] = '1'
    if args.base_url:
        env['E2E_BASE_URL'] = args.base_url.rstrip('/')

    chosen = [s for s in SUITES if (not args.only or s[0] in args.only) and not (args.quick and s[0] == 'api')]
    results = []
    for key, title, target in chosen:
        print(f'▶ {title} …', flush=True)
        result = run_suite(key, target, env)
        results.append((key, title, result))
        print(f"  {'PASS' if result['ok'] else 'FAIL'}  {result['tally']}  ({result['seconds']:.0f}s)", flush=True)
        for line in result['failures'][:15]:
            print(f'    {line}')

    ok = all(r['ok'] for _k, _t, r in results)
    lines = [
        '# Test run summary', '',
        f"{datetime.now():%Y-%m-%d %H:%M}  ·  {'**ALL PASSED**' if ok else '**FAILED**'}"
        f"{'  ·  write flows on' if args.write else ''}", '',
        '| Suite | Result | Tests | Time |', '|---|---|---|---|',
    ]
    for key, title, r in results:
        lines.append(f"| {title} | {'✅ pass' if r['ok'] else '❌ fail'} | {r['tally']} | {r['seconds']:.0f}s |")
    failed = [(t, r) for _k, t, r in results if r['failures']]
    if failed:
        lines += ['', '## Failures', '']
        for title, r in failed:
            lines.append(f'### {title}')
            lines += [f'- `{l}`' for l in r['failures']]
    lines += ['', 'Logs: `tests/reports/<suite>.log` · JUnit: `tests/reports/<suite>.xml` · '
                  'Screenshots of failed browser tests: `tests/e2e/reports/` · '
                  'API timings: `tests/perf/reports/api_timings.md`']
    with open(os.path.join(REPORT_DIR, 'summary.md'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    print(f"\n{'ALL PASSED' if ok else 'FAILED'} — summary: tests/reports/summary.md")
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
