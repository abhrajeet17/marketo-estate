"""Panorama, plot and marker media: upload flows (direct-to-storage and local), rename rules, page tokens."""
import io

import pytest

import app.config as app_config
import app.services.storage_service as storage
from world import jpeg_bytes, png_bytes
from test_route_variants import _wav_bytes


def _local_storage(monkeypatch):
    monkeypatch.setattr(app_config, 'SUPABASE_S3_BUCKET', '')


# ---------------------------------------------------------------- panorama upload
def test_direct_upload_flow_creates_panorama_and_thumbnail(world):
    w = world
    r = w.post('/api/panoramas/upload-url', as_='admin', json={'original_filename': 'drone.jpg', 'name': 'Drone 1',
                                                               'size_bytes': 1000})
    assert r.status_code == 200
    ticket = r.get_json()
    assert ticket['upload_url'].startswith('https://storage.test/')
    w.s3.objects[storage.panorama_object_key(ticket['filename'])] = {'body': jpeg_bytes(512, 256), 'content_type': 'image/jpeg'}
    r = w.client.post('/api/panoramas', headers=w.headers('admin'), data={
        'name': 'Drone 1', 'is_360': 'true', 'workspace_id': w.ws2['id'], 'width': '512', 'height': '-5',
        'filename': ticket['filename'], 'upload_token': ticket['upload_token'], 'original_filename': 'drone.jpg'})
    assert r.status_code == 201, r.get_data(as_text=True)
    created = r.get_json()
    assert created['is_360'] is True and created['height'] == 0
    row = w.db.one('panoramas', id=created['id'])
    assert row['workspace_id'] == w.ws2['id'] and row['org_id'] == w.org['id']
    # First 360 panorama of a project becomes its main panorama; a thumbnail is stored.
    assert w.db.one('workspaces', id=w.ws2['id'])['main_panorama_id'] == created['id']
    assert storage.panorama_thumb_object_key(ticket['filename']) in w.s3.objects


@pytest.mark.parametrize('payload,status', [
    ({}, 400),
    ({'original_filename': 'notes.txt'}, 400),
    ({'original_filename': 'blob', 'content_type': 'image/png'}, 200),
    ({'original_filename': 'a.jpg', 'size_bytes': 10 ** 12}, 413),
    ({'original_filename': 'a.jpg', 'name': 'x' * 300}, 200),
])
def test_upload_url_validation(world, payload, status):
    assert world.post('/api/panoramas/upload-url', as_='admin', json=payload).status_code == status


def test_upload_url_needs_storage(world, monkeypatch):
    _local_storage(monkeypatch)
    assert world.post('/api/panoramas/upload-url', as_='admin', json={'original_filename': 'a.jpg'}).status_code == 503


def test_direct_upload_rejections(world):
    w = world
    ticket = w.post('/api/panoramas/upload-url', as_='admin', json={'original_filename': 'a.jpg'}).get_json()
    base = {'filename': ticket['filename'], 'upload_token': ticket['upload_token']}
    post = lambda data, who='admin': w.client.post('/api/panoramas', headers=w.headers(who), data=data)  # noqa: E731
    assert post({'upload_token': 'x'}).status_code == 400                       # no filename
    assert post({'filename': 'a.jpg'}).status_code == 400                       # no token
    assert post({'filename': 'a.txt', 'upload_token': 'x'}).status_code == 400  # bad type
    assert post({'filename': ticket['filename'], 'upload_token': 'garbage'}).status_code == 400
    assert post(base, who='super').status_code == 403                           # token issued to someone else
    assert post(base).status_code == 400                                        # object never uploaded
    w.s3.objects[storage.panorama_object_key(ticket['filename'])] = {'body': jpeg_bytes(), 'content_type': 'image/jpeg'}
    assert post({**base, 'workspace_id': w.foreign_ws['id']}).status_code == 403
    assert post({**base, 'workspace_id': '00000000-0000-0000-0000-000000000000'}).status_code == 404


def test_direct_upload_too_large_is_deleted(world):
    w = world
    ticket = w.post('/api/panoramas/upload-url', as_='admin', json={'original_filename': 'a.jpg'}).get_json()
    key = storage.panorama_object_key(ticket['filename'])
    w.s3.objects[key] = {'body': b'x' * 50000, 'content_type': 'image/jpeg'}
    w.app.config['MAX_CONTENT_LENGTH'], old = 20000, w.app.config['MAX_CONTENT_LENGTH']
    try:
        r = w.client.post('/api/panoramas', headers=w.headers('admin'),
                          data={'filename': ticket['filename'], 'upload_token': ticket['upload_token']})
    finally:
        w.app.config['MAX_CONTENT_LENGTH'] = old
    assert r.status_code == 413 and key not in w.s3.objects


def test_storage_mode_requires_direct_upload(world):
    r = world.upload('/api/panoramas', filename='pano.jpg', content=jpeg_bytes())
    assert r.status_code == 400 and 'upload-url' in r.get_json()['error']


def test_local_upload_mode(world, monkeypatch):
    _local_storage(monkeypatch)
    w = world
    r = w.upload('/api/panoramas', filename='pano.jpg', content=jpeg_bytes(),
                 extra={'name': 'Local', 'is_360': 'true', 'workspace_id': w.ws['id']})
    assert r.status_code == 201, r.get_data(as_text=True)
    assert (w.uploads / r.get_json()['filename']).exists()
    assert w.upload('/api/panoramas', filename='', content=b'x').status_code == 400
    assert w.upload('/api/panoramas', filename='virus.exe', content=b'x').status_code == 400
    # Database insert fails: the stored file is removed again.
    w.db.fail_tables['panoramas'] = 'insert failed'
    before = set(p.name for p in w.uploads.iterdir())
    assert w.upload('/api/panoramas', filename='p2.jpg', content=jpeg_bytes()).status_code == 500
    assert set(p.name for p in w.uploads.iterdir()) == before
    w.db.fail_tables.clear()
    assert w.client.post('/api/panoramas', headers=w.headers('admin'),
                         data={'filename': 'a.jpg', 'upload_token': 't'}).status_code == 503


def test_non_admin_cannot_upload(world):
    assert world.upload('/api/panoramas', as_='user').status_code == 403
    assert world.upload('/api/panoramas', as_=None).status_code == 401


# ---------------------------------------------------------------- rename / settings
@pytest.mark.parametrize('body,status', [
    ({'name': 'Renamed'}, 200),
    ({'name': ''}, 400),
    ({'name': 'x' * 121}, 400),
    ({}, 400),
    ({'use_animated_icons': True}, 200),
    ({'use_animated_icons': 'yes'}, 200),
    ({'start_view': {'longitude': 10, 'latitude': 5, 'zoom': 2}}, 200),
    ({'start_view': {'longitude': 10}}, 400),
    ({'start_view': {'longitude': 'a', 'latitude': 'b'}}, 400),
    ({'start_view': False}, 200),
    ({'start_view': None}, 400),
    ({'start_view': 'east'}, 400),
])
def test_rename_and_settings(world, body, status):
    r = world.patch(f"/api/panoramas/{world.pano['id']}", as_='admin', json=body)
    assert r.status_code == status, r.get_data(as_text=True)


def test_rename_permissions(world):
    w = world
    assert w.patch(f"/api/panoramas/{w.pano['id']}", as_='user', json={'name': 'x'}).status_code == 403
    assert w.patch(f"/api/panoramas/{w.foreign_pano['id']}", as_='admin', json={'name': 'x'}).status_code == 404
    assert w.patch('/api/panoramas/999999', as_='admin', json={'name': 'x'}).status_code == 404
    r = w.put(f"/api/panoramas/{w.pano['id']}", as_='admin', json={'name': 'New name'})
    assert r.status_code == 200 and w.db.one('panoramas', id=w.pano['id'])['name'] == 'New name'


# ---------------------------------------------------------------- audio & voice-over
def test_panorama_audio(world, monkeypatch):
    w = world
    path = f"/api/panoramas/{w.pano['id']}/audio"
    assert w.upload(path, field='audio', filename='a.wav', content=_wav_bytes()).status_code == 200
    assert w.db.one('panoramas', id=w.pano['id'])['audio_filename']
    assert w.upload(path, field='audio', filename='b.wav', content=_wav_bytes()).status_code == 200  # replaces
    assert w.upload(path, field='audio', filename='a.txt', content=b'x').status_code == 400
    assert w.upload(path, field='audio', filename='a.mp3', content=b'').status_code == 400
    assert w.client.post(path, headers=w.headers('admin')).status_code == 400
    assert w.upload(path, field='audio', filename='a.wav', content=_wav_bytes(), as_='user').status_code == 403
    assert w.upload('/api/panoramas/999999/audio', field='audio', filename='a.wav', content=_wav_bytes()).status_code == 404
    assert w.delete(path, as_='admin').status_code == 200
    assert not w.db.one('panoramas', id=w.pano['id'])['audio_filename']
    assert w.delete(path, as_='user').status_code == 403
    _local_storage(monkeypatch)
    assert w.upload(path, field='audio', filename='a.wav', content=_wav_bytes()).status_code == 503


def test_marker_voiceover(world, monkeypatch):
    w = world
    path = f"/api/markers/{w.marker['id']}/voiceover"
    assert w.get(path, as_='admin').status_code == 200  # seeded voice-over
    r = w.upload(path, field='voiceover', filename='v.wav', content=_wav_bytes())
    assert r.status_code == 200, r.get_data(as_text=True)
    assert w.get(path, as_='admin').status_code == 200
    assert w.get(f"/api/public/markers/{w.marker['id']}/voiceover").status_code in (200, 302, 404)
    assert w.upload(path, field='voiceover', filename='v.doc', content=b'x').status_code == 400
    assert w.upload(path, field='voiceover', filename='v.wav', content=b'').status_code == 400
    assert w.client.post(path, headers=w.headers('admin')).status_code == 400
    assert w.upload('/api/markers/nope/voiceover', field='voiceover', filename='v.wav', content=_wav_bytes()).status_code == 404
    bad = w.db.add('plot_markers', plot_id='', name='Broken')
    assert w.upload(f"/api/markers/{bad['id']}/voiceover", field='voiceover', filename='v.wav',
                    content=_wav_bytes()).status_code == 400
    bad2 = w.db.add('plot_markers', plot_id='abc', name='Broken')
    assert w.upload(f"/api/markers/{bad2['id']}/voiceover", field='voiceover', filename='v.wav',
                    content=_wav_bytes()).status_code == 400
    assert w.upload(path, field='voiceover', filename='v.wav', content=_wav_bytes(), as_='stranger').status_code == 403
    _local_storage(monkeypatch)
    assert w.upload(path, field='voiceover', filename='v.wav', content=_wav_bytes()).status_code == 503


# ---------------------------------------------------------------- plot & marker images
@pytest.mark.parametrize('kind', ['plot', 'marker'])
def test_image_direct_upload_flow(world, kind):
    w = world
    target = w.plot['id'] if kind == 'plot' else w.marker['id']
    base = f'/api/{kind}s/{target}/image'
    assert w.post(base + '/upload-url', as_='admin', json={}).status_code == 400
    assert w.post(base + '/upload-url', as_='admin', json={'original_filename': 'a.bmp'}).status_code == 400
    assert w.post(base + '/upload-url', as_='admin', json={'original_filename': 'a.png', 'size_bytes': 10 ** 10}).status_code == 413
    assert w.post(base + '/upload-url', as_='admin', json={'original_filename': 'x', 'content_type': 'image/webp'}).status_code == 200
    ticket = w.post(base + '/upload-url', as_='admin', json={'original_filename': 'a.png'}).get_json()
    assert ticket.get('upload_token'), ticket
    post = lambda data, who='admin': w.client.post(base, headers=w.headers(who), data=data)  # noqa: E731
    assert post({}).status_code == 400
    assert post({'filename': ticket['filename']}).status_code == 400
    assert post({'filename': ticket['filename'], 'upload_token': 'junk'}).status_code in (400, 403)
    assert post({'filename': 'other.png', 'upload_token': ticket['upload_token']}).status_code in (400, 403)
    assert post({'filename': ticket['filename'], 'upload_token': ticket['upload_token']}).status_code in (400, 404)
    key_fn = storage.plot_object_key if kind == 'plot' else storage.marker_object_key
    w.s3.objects[key_fn(ticket['filename'])] = {'body': png_bytes(), 'content_type': 'image/png'}
    r = post({'filename': ticket['filename'], 'upload_token': ticket['upload_token']})
    assert r.status_code == 200, r.get_data(as_text=True)
    assert post({'filename': ticket['filename'], 'upload_token': ticket['upload_token']}, who='super').status_code in (403, 404)


@pytest.mark.parametrize('kind', ['plot', 'marker'])
def test_image_form_upload_rules(world, kind, monkeypatch):
    w = world
    target = w.plot['id'] if kind == 'plot' else w.marker['id']
    base = f'/api/{kind}s/{target}/image'
    assert w.upload(base, filename='a.png').status_code == 200
    assert w.upload(base, filename='b.jpg', content=jpeg_bytes(), method='PUT').status_code == 200  # replaces old
    # Existing rule: an unknown content type is stored as .jpg rather than rejected.
    assert w.upload(base, filename='a.exe', content=b'MZ').status_code == 200
    assert w.client.post(base, headers=w.headers('admin'), content_type='multipart/form-data',
                         data={'file': (io.BytesIO(b'x'), 'noext')}).status_code in (200, 400)
    assert w.upload(base, filename='', content=b'').status_code == 400
    assert w.upload(base, filename='a.png', content=b'not an image').status_code in (200, 400)
    assert w.upload(base, filename='a.png', as_='stranger').status_code in (403, 404)
    assert w.get(base, as_='admin').status_code in (200, 302)
    missing = f'/api/{kind}s/{"999999" if kind == "plot" else "nope"}/image'
    assert w.upload(missing, filename='a.png').status_code == 404
    w.s3.broken = True
    assert w.upload(base, filename='a.png').status_code >= 400
    w.s3.broken = False
    _local_storage(monkeypatch)
    assert w.upload(base, filename='a.png').status_code == 503


# ---------------------------------------------------------------- page tokens & editor pages
@pytest.mark.parametrize('mode,who,status', [('admin', 'admin', 200), ('client', 'admin', 200),
                                             ('client', 'user', 403), ('admin', 'user', 403),
                                             ('client', 'client_admin', 200), ('bogus', 'admin', 400),
                                             ('client', 'stranger', 404)])
def test_page_token_rules(world, mode, who, status):
    r = world.post(f"/api/panoramas/{world.pano['id']}/page-token", as_=who, json={'mode': mode})
    assert r.status_code == status, r.get_data(as_text=True)


@pytest.mark.parametrize('page,mode', [('/admin/{id}', 'admin'), ('/admin/3d/{id}', 'admin'),
                                       ('/client/{id}', 'client'), ('/client/3d/{id}', 'client')])
def test_editor_pages_need_a_valid_page_token(world, page, mode):
    w = world
    path = page.format(id=w.pano['id'])
    assert w.get(path).status_code == 403
    assert w.get(path + '?pt=garbage').status_code == 403
    token = w.post(f"/api/panoramas/{w.pano['id']}/page-token", as_='admin', json={'mode': mode}).get_json()['token']
    r = w.get(f'{path}?pt={token}')
    assert r.status_code == 200, r.get_data(as_text=True)[:300]
    # A token for another panorama or mode is refused.
    other = w.post(f"/api/panoramas/{w.pano2['id']}/page-token", as_='admin', json={'mode': mode}).get_json()['token']
    assert w.get(f'{path}?pt={other}').status_code == 403
    w.db.tables['panoramas'] = [p for p in w.db.tables['panoramas'] if p['id'] != w.pano['id']]
    assert w.get(f'{path}?pt={token}').status_code in (403, 404)


def test_expired_page_token(world, monkeypatch):
    w = world
    token = w.post(f"/api/panoramas/{w.pano['id']}/page-token", as_='admin', json={'mode': 'admin'}).get_json()['token']
    import itsdangerous.timed
    real = itsdangerous.timed.TimestampSigner.get_timestamp
    monkeypatch.setattr(itsdangerous.timed.TimestampSigner, 'get_timestamp', lambda self: real(self) + 10 ** 7)
    assert w.get(f"/admin/{w.pano['id']}?pt={token}").status_code == 403


def test_admin_3d_without_project(world):
    w = world
    token = w.post(f"/api/panoramas/{w.unlinked_pano['id']}/page-token", as_='admin',
                   json={'mode': 'admin'}).get_json()['token']
    assert w.get(f"/admin/3d/{w.unlinked_pano['id']}?pt={token}").status_code == 200
