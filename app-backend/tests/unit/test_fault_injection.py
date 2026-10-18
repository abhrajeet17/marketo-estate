"""
Failure handling: every route keeps working when a database query or the storage service fails.

For each route the test first counts how many queries a normal admin call makes, then repeats the
call once per query with that query failing (once, then from that point on), with a generic
error and with a "missing column" error that the legacy-schema fallbacks look for. A last pass
takes storage offline. The response may be an error, but the handler must not crash with a
secondary exception: only the injected error itself may escape.
"""
import pytest
from botocore.exceptions import EndpointConnectionError
from postgrest.exceptions import APIError

from test_route_sweep import EXTERNAL, _rules, generic_body, resolve

MAX_POINTS = 30
SCHEMA_MESSAGE = ('column "workspace_id" org_id image_filename voiceover_filename audio_filename label_longitude '
                  'label_latitude start_view use_animated_icons share_token client_member_id media_photo '
                  'linked_panorama_id main_panorama_id is_published view_config custom_fields does not exist '
                  'relation schema cache PGRST204 42703 42P01')

INJECTED = (APIError, EndpointConnectionError)


def _call(world, method, path, body):
    try:
        return world.open(method, path, as_='admin', json=body), None
    except INJECTED as exc:  # the injected failure surfacing unhandled is tolerated
        return None, exc
    except Exception as exc:  # anything else is a bug in the error handling
        return None, exc


@pytest.mark.parametrize('rule,method', [rm for rm in _rules() if rm not in EXTERNAL], ids=lambda v: str(v))
def test_route_survives_failures(make_world, rule, method):
    world = make_world()
    path = resolve(world, rule)
    body = generic_body(world) if method != 'GET' else None
    world.db.call_index = 0
    _call(world, method, path, body)
    total = min(world.db.call_index, MAX_POINTS)
    secondary = []
    plans = [(k, persist, msg) for k in range(1, total + 1) for persist in (False, True)
             for msg in (('injected database failure', 'XX000'), (SCHEMA_MESSAGE, '42703'))]
    for k, persist, (message, code) in plans:
        w = make_world()
        path = resolve(w, rule)
        body = generic_body(w) if method != 'GET' else None
        w.db.call_index = 0
        w.db.fail_at, w.db.fail_persist, w.db.fail_message, w.db.fail_code = k, persist, message, code
        _resp, exc = _call(w, method, path, body)
        if exc is not None and not isinstance(exc, INJECTED):
            secondary.append(f'query {k} {"onwards" if persist else "once"} ({code}): {type(exc).__name__}: {exc}')
    w = make_world()
    path = resolve(w, rule)
    w.s3.broken = True
    _resp, exc = _call(w, method, path, generic_body(w) if method != 'GET' else None)
    if exc is not None and not isinstance(exc, INJECTED):
        secondary.append(f'storage offline: {type(exc).__name__}: {exc}')
    assert not secondary, f'{method} {path}\n' + '\n'.join(secondary[:10])
