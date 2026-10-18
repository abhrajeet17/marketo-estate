"""
More passes over every route, each from a different angle:

* GET with filter / search / paging query strings
* writes with an empty body (validation paths)
* writes as multipart uploads carrying real image, audio and video bytes (upload paths)

As in test_route_sweep.py, nothing may crash. Every pass runs in a fresh in-memory world.
"""
import io

import pytest

from test_route_sweep import EXTERNAL, _rules, generic_body, resolve
from world import jpeg_bytes, png_bytes

WRITE_RULES = [(r, m) for r, m in _rules() if m != 'GET' and (r, m) not in EXTERNAL]
GET_RULES = [(r, m) for r, m in _rules() if m == 'GET']


def _query(world):
    w = world
    return {
        'workspace_id': w.ws['id'], 'q': 'a', 'status': 'available', 'panorama_id': w.pano['id'], 'embed': '1',
        'type': 'image', 'sort': 'name', 'dir': 'desc', 'size': 'thumb', 'page': '2', 'per_page': '5', 'limit': '5',
        'client_id': w.client_group['id'], 'preview': '1', 'tab': 'leads', 'scope': 'all', 'lightweight': '1',
        'include_empty_shared': '1', 'include_disabled': '1', 'days': '30', 'city': 'Pune', 'autocreate': '1',
        'org_id': w.org['id'], 'project_id': w.daynight['id'], 'target_user_id': w.users['user'], 'unlinked': '1',
    }


@pytest.mark.parametrize('rule,method', GET_RULES, ids=lambda v: str(v))
def test_get_with_query_strings(world, rule, method):
    path = resolve(world, rule)
    failures = []
    for role in ('admin', 'super', 'client_admin', 'broker', 'user'):
        try:
            resp = world.get(path, as_=role, query_string=_query(world))
        except Exception as exc:
            failures.append(f'{role}: {type(exc).__name__}: {exc}')
            continue
        if resp.status_code >= 500:
            failures.append(f'{role}: HTTP {resp.status_code} {resp.get_data(as_text=True)[:300]}')
    assert not failures, f'GET {path}\n' + '\n'.join(failures)


@pytest.mark.parametrize('rule,method', WRITE_RULES, ids=lambda v: str(v))
def test_write_with_empty_and_odd_bodies(world, rule, method):
    path = resolve(world, rule)
    failures = []
    bodies = ({}, {'name': '', 'email': 'not-an-email', 'status': 'bogus', 'points': 'nope'}, None)
    for body in bodies:
        for role in ('admin', 'super'):
            try:
                if body is None:
                    resp = world.open(method, path, as_=role, data='not json', headers={'Content-Type': 'text/plain'})
                else:
                    resp = world.open(method, path, as_=role, json=body)
            except Exception as exc:
                failures.append(f'{role} {body!r}: {type(exc).__name__}: {exc}')
                continue
            if resp.status_code >= 500:
                failures.append(f'{role} {body!r}: HTTP {resp.status_code} {resp.get_data(as_text=True)[:300]}')
    assert not failures, f'{method} {path}\n' + '\n'.join(failures)


def _wav_bytes():
    import struct
    frames = b'\x00\x00' * 800
    header = b'RIFF' + struct.pack('<I', 36 + len(frames)) + b'WAVEfmt ' + struct.pack('<IHHIIHH', 16, 1, 1, 8000, 16000, 2, 16)
    return header + b'data' + struct.pack('<I', len(frames)) + frames


@pytest.mark.parametrize('rule,method', [(r, m) for r, m in WRITE_RULES if m in ('POST', 'PUT', 'PATCH')],
                         ids=lambda v: str(v))
def test_multipart_uploads(world, rule, method):
    path = resolve(world, rule)
    form = {k: (str(v) if not isinstance(v, (list, dict)) else __import__('json').dumps(v))
            for k, v in generic_body(world).items()}
    form.update({'is_360': 'true', 'width': '256', 'height': '128', 'media_type': 'images'})
    failures = []
    for variant in ('png', 'jpeg'):
        data = dict(form)
        image = png_bytes(64, 32) if variant == 'png' else jpeg_bytes(256, 128)
        name = 'photo.png' if variant == 'png' else 'pano.jpg'
        data['file'] = (io.BytesIO(image), name)
        data['images'] = [(io.BytesIO(jpeg_bytes(128, 64)), 'a.jpg'), (io.BytesIO(jpeg_bytes(128, 64)), 'b.jpg')]
        data['voiceover'] = (io.BytesIO(_wav_bytes()), 'voice.wav')
        data['audio'] = (io.BytesIO(_wav_bytes()), 'audio.wav')
        data['video'] = (io.BytesIO(b'\x00\x00\x00\x18ftypmp42' + b'\x00' * 64), 'clip.mp4')
        try:
            resp = world.client.open(path, method=method, data=data, content_type='multipart/form-data',
                                     headers=world.headers('admin'))
        except Exception as exc:
            failures.append(f'{variant}: {type(exc).__name__}: {exc}')
            continue
        if resp.status_code >= 500:
            failures.append(f'{variant}: HTTP {resp.status_code} {resp.get_data(as_text=True)[:300]}')
    assert not failures, f'{method} {path}\n' + '\n'.join(failures)
