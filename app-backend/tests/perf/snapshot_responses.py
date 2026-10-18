"""
Record every GET API response so a refactor can be checked for identical output.

    python tests/perf/snapshot_responses.py before.json
    ... change code ...
    python tests/perf/snapshot_responses.py after.json
    python tests/perf/snapshot_responses.py --compare before.json after.json

Uses the same routes, ids and roles as the timing suite (read-only GETs). Values that differ on
every call (signed-URL signatures, short-lived tokens, server timestamps) are normalised.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

VOLATILE_QUERY = re.compile(r'([?&](X-Amz-[A-Za-z-]+|Signature|Expires|token|sig)=)[^&"\s]*')
VOLATILE_KEYS = {'expires_at_epoch', 'server_time', 'generated_at', 'access_token', 'page_token', 'upload_token'}


def _normalise(value):
    if isinstance(value, dict):
        return {k: ('<volatile>' if k in VOLATILE_KEYS else _normalise(v)) for k, v in sorted(value.items())}
    if isinstance(value, list):
        return [_normalise(v) for v in value]
    if isinstance(value, str):
        return VOLATILE_QUERY.sub(r'\1<sig>', value)
    return value


def snapshot():
    import conftest
    from test_api_timings import ROUTES, _resolve
    from app import app
    from app.core.database import get_supabase

    sb = get_supabase()
    client = app.test_client()
    ids = conftest.load_ids(sb, conftest.load_owner_id(sb))
    headers = conftest.load_auth_headers(sb)
    out = {}
    for rule in ROUTES:
        path, reason = _resolve(rule, ids)
        if not path:
            continue
        for role in conftest.ROLE_ORDER + (None,):
            if role not in headers:
                continue
            resp = client.get(path, headers=headers[role])
            if resp.status_code in (401, 403):
                continue
            body = resp.get_data()
            if resp.is_json:
                payload = _normalise(resp.get_json(silent=True))
            else:
                payload = {'content_type': resp.mimetype, 'bytes': len(body),
                           'location': VOLATILE_QUERY.sub(r'\1<sig>', resp.headers.get('Location', ''))}
            out[rule] = {'path': path, 'role': role or 'public', 'status': resp.status_code, 'body': payload}
            break
    return out


def compare(a_path, b_path):
    a = json.load(open(a_path, encoding='utf-8'))
    b = json.load(open(b_path, encoding='utf-8'))
    diffs = 0
    for rule in sorted(set(a) | set(b)):
        if a.get(rule) != b.get(rule):
            diffs += 1
            ra, rb = a.get(rule) or {}, b.get(rule) or {}
            print(f'DIFF {rule}: status {ra.get("status")} -> {rb.get("status")}')
            sa = json.dumps(ra.get('body'), sort_keys=True)
            sb_ = json.dumps(rb.get('body'), sort_keys=True)
            i = next((k for k in range(min(len(sa), len(sb_))) if sa[k] != sb_[k]), min(len(sa), len(sb_)))
            print(f'   before: ...{sa[max(0, i - 80):i + 120]}')
            print(f'   after:  ...{sb_[max(0, i - 80):i + 120]}')
    print(f'{len(set(a) | set(b))} routes compared, {diffs} differ')
    return diffs


if __name__ == '__main__':
    if sys.argv[1:2] == ['--compare']:
        sys.exit(1 if compare(sys.argv[2], sys.argv[3]) else 0)
    data = snapshot()
    with open(sys.argv[1], 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=1, sort_keys=True)
    print(f'{len(data)} responses written to {sys.argv[1]}')
