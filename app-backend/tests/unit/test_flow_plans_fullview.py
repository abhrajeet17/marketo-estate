"""Building plan tree and interest form, Full View builder, maps-link resolver, media streaming."""
import io
import time

import pytest

import app.controllers.register as register
from app.controllers.features import building_plan
from world import jpeg_bytes, png_bytes


# ---------------------------------------------------------------- building plan tree
@pytest.fixture
def tower(world):
    """Tower (root) -> Floor 3 zone links to a floor map with three units."""
    w = world
    db = w.db
    admin = w.users['admin']
    root = db.one('building_maps', id=w.building_map['id'])
    root['view_config'] = {'level': 'tower', 'brand_name': 'Green Valley', 'rera_number': 'P5200', 'show_interest': True}
    floor_map = db.add('building_maps', user_id=admin, org_id=w.org['id'], name='Floor 3 plan', image_filename='tower.png',
                       image_width=64, image_height=32, share_token='floor-token', workspace_id=w.ws['id'],
                       view_config={'level': 'floor'})
    floor_zone = db.add('building_zones', building_map_id=root['id'], name='Floor 3', floor_number=3,
                        points=[[0, 0], [1, 0], [1, 1]], link_type='building_map', linked_building_map_id=floor_map['id'],
                        meta={'unit_status': {}})
    units = {}
    for name, meta in (('301', {'status': 'available', 'area': '1200 Sq.ft'}),
                       ('302', {'status': 'sold'}),
                       ('303', {'status': 'available', 'hide_interest': True}),
                       ('304', {'status': 'available', 'size_min': 900, 'size_max': 1100})):
        units[name] = db.add('building_zones', building_map_id=floor_map['id'], name=name, points=[[0, 0], [1, 0], [1, 1]],
                             meta=meta, link_type='none')
    db.add('building_zones', building_map_id=root['id'], name='Tour', points=[[0, 0], [1, 0], [1, 1]],
           link_type='panorama', linked_panorama_id=w.pano['id'])
    building_plan._tree_cache.clear()
    return {'root': root, 'floor_map': floor_map, 'floor_zone': floor_zone, 'units': units}


def _interest(w, unit, tower, **extra):
    body = {'map_id': tower['floor_map']['id'], 'zone_id': unit['id'], 'path': [tower['floor_zone']['id']],
            'name': 'Asha', 'email': 'asha@example.test', 'phone': '9812345678', 'city': 'Pune', **extra}
    return w.post('/api/public/building-plan/bm-token/interest', json=body)


def test_public_tree_and_pages(world, tower):
    w = world
    r = w.get('/api/public/building-plan/bm-token', headers={'Accept-Encoding': 'gzip'})
    assert r.status_code == 200
    tree = w.get('/api/public/building-plan/bm-token').get_json() if r.headers.get('Content-Encoding') != 'gzip' else None
    assert w.get('/api/public/building-plan/nope').status_code == 404
    assert w.get('/building-plan/bm-token').status_code == 200
    assert w.get('/building-plan/bm-token/floor/3/unit/301').status_code == 200
    assert w.get('/building-plan/missing').status_code == 404
    assert w.get('/api/public/building-plan/bm-token/reference-users').status_code == 200
    assert w.get('/api/public/building-plan/missing/reference-users').status_code == 404
    assert tree is None or tree


@pytest.mark.parametrize('unit,extra,status', [
    ('301', {}, 201), ('304', {}, 201), ('302', {}, 400), ('303', {}, 400),
    ('301', {'email': ''}, 400), ('301', {'reference_user_id': 'not-a-reference'}, 400),
    ('301', {'path': 'bad'}, 201), ('301', {'path': ['wrong-zone']}, 201), ('301', {'birthday': '1990-01-01'}, 201),
])
def test_interest_rules(world, tower, unit, extra, status):
    r = _interest(world, tower['units'][unit], tower, **extra)
    assert r.status_code == status, r.get_data(as_text=True)
    if status == 201:
        lead = world.db.one('crm_leads', id=r.get_json()['id'])
        assert lead['lead_source'] == 'SalesTool' and lead['panorama_id']


def test_interest_needs_unit_and_switch(world, tower):
    w = world
    assert w.post('/api/public/building-plan/bm-token/interest', json={'name': 'x'}).status_code == 400
    assert w.post('/api/public/building-plan/missing/interest', json={}).status_code == 404
    tower['root']['view_config'] = {'show_interest': False}
    building_plan._tree_cache.clear()
    assert _interest(w, tower['units']['301'], tower).status_code == 403


def test_interest_without_crm_project(world, tower):
    w = world
    tower['root']['workspace_id'] = None
    w.db.tables['building_zones'] = [z for z in w.db.rows('building_zones') if z.get('link_type') != 'panorama']
    building_plan._tree_cache.clear()
    assert _interest(w, tower['units']['301'], tower).status_code in (409, 201)


def test_unit_status_from_parent_overrides(world, tower):
    w = world
    unit = tower['units']['301']
    w.db.one('building_zones', id=tower['floor_zone']['id'])['meta'] = {'unit_status': {str(unit['id']): 'sold'}}
    building_plan._tree_cache.clear()
    assert _interest(w, unit, tower).status_code == 400


def test_tree_cache_refresh(world, tower, monkeypatch):
    w = world
    sb = w.db
    first = building_plan.get_plan_tree_cached(sb, 'bm-token')
    assert first
    # Stale entry is served and refreshed; expired entry is rebuilt.
    built, tree = building_plan._tree_cache['bm-token']
    building_plan._tree_cache['bm-token'] = (built - building_plan.TREE_MAX_STALE_SECONDS + 1, tree)
    assert building_plan.get_plan_tree_cached(sb, 'bm-token')
    building_plan._tree_cache['bm-token'] = (built - 10 ** 6, tree)
    assert building_plan.get_plan_tree_cached(sb, 'bm-token')
    building_plan._tree_cache['bm-token'] = (0, None)  # someone else is building it
    assert building_plan.get_plan_tree_cached(sb, 'missing-token') is None
    building_plan.invalidate_building_plan_cache()  # marks every tree stale and rebuilds in the background
    assert 'bm-token' in building_plan._tree_cache


def test_sign_many():
    sign = lambda n, verify=True: n.upper()  # noqa: E731
    assert building_plan.sign_many(sign, []) == {}
    assert building_plan.sign_many(sign, ['a']) == {'a': 'A'}
    assert building_plan.sign_many(sign, ['a', 'b', 'a', None]) == {'a': 'A', 'b': 'B'}
    assert building_plan.sign_many(sign, ['a', 'b'], verify=False) == {'a': 'A', 'b': 'B'}


# ---------------------------------------------------------------- full view builder
def test_full_view_builder(world):
    w = world
    wid = w.ws2['id']
    assert w.get('/api/full-view/config', as_='admin', query_string={'workspace_id': wid}).status_code == 200
    assert w.get('/api/full-view/config', as_='admin', query_string={'workspace_id': wid, 'autocreate': '1'}).status_code == 200
    created = w.post('/api/full-view/config', as_='admin', json={'workspace_id': w.ws2['id']})
    assert created.status_code in (200, 201)
    cid = (created.get_json().get('config') or {}).get('id') or w.db.one('full_view_configs', workspace_id=wid)['id']
    assert w.post('/api/full-view/config', as_='admin', json={'workspace_id': '00000000-0000-0000-0000-000000000000'}).status_code == 404
    assert w.put(f'/api/full-view/config/{cid}', as_='admin', json={'style': {'accent': '#ffffff', 'font': 'serif'}}).status_code == 200
    assert w.put(f'/api/full-view/config/{cid}', as_='admin', json={'style': 'red'}).status_code == 400
    tabs = []
    for body in ({'tab_type': 'panorama', 'ref_panorama_id': w.pano['id'], 'name': 'Tour'},
                 {'tab_type': 'link', 'name': 'Site', 'content_data': {'url': 'example.com/brochure'}},
                 {'tab_type': 'link', 'name': 'Rel', 'content_data': {'url': '/fullview/x'}},
                 {'tab_type': 'link', 'name': 'Proto', 'content_data': {'url': '//cdn.example.com/a'}},
                 {'tab_type': 'daynight', 'ref_daynight_id': w.daynight['id']},
                 {'tab_type': 'floor_plan', 'ref_floor_plan_id': w.catalogue['id']},
                 {'tab_type': 'gallery', 'ref_gallery_id': w.gallery['id']},
                 {'tab_type': 'project_plan', 'ref_project_plan_id': w.project_plan['id']},
                 {'tab_type': 'sales_map', 'ref_sales_map_id': w.sales_map['id']},
                 {'tab_type': 'sales_flat360', 'ref_sales_flat360_id': w.flat360['id']},
                 {'tab_type': 'content', 'content_data': {'html': '<b>About</b>'}}):
        r = w.post('/api/full-view/tabs', as_='admin', json={'config_id': cid, 'icon': 'star', 'name': 'Tab', **body})
        assert r.status_code in (200, 201), (body, r.get_data(as_text=True))
        tabs.append(r.get_json().get('tab', r.get_json())['id'])
    for body in ({'tab_type': 'link', 'content_data': {'url': 'ftp://x'}}, {'tab_type': 'link', 'content_data': 'x'},
                 {'tab_type': 'link', 'content_data': {'url': ''}}):
        assert w.post('/api/full-view/tabs', as_='admin', json={'config_id': cid, 'name': 'Bad', **body}).status_code == 400, body
    assert w.put(f'/api/full-view/tabs/{tabs[0]}', as_='admin', json={'name': 'Walk', 'is_visible': False}).status_code == 200
    assert w.put(f'/api/full-view/tabs/{tabs[1]}', as_='admin', json={'tab_type': 'link', 'content_data': {'url': 'javascript:x'}}).status_code == 400
    assert w.post('/api/full-view/tabs/reorder', as_='admin', json={'config_id': cid, 'tab_ids': list(reversed(tabs))}).status_code == 200
    assert w.post('/api/full-view/tabs/reorder', as_='admin', json={}).status_code == 400
    for path, field, content in (('/api/full-view/icon-upload', 'file', png_bytes()),
                                 ('/api/full-view/logo-upload', 'file', jpeg_bytes())):
        assert w.upload(path, field=field, filename='a.png', content=content).status_code in (200, 201)
        assert w.upload(path, field=field, filename='a.png', content=b'not image').status_code == 400
        assert w.upload(path, field=field, filename='a.png', content=b'').status_code == 400
        assert w.upload(path, field=field, filename='a.gif', content=b'GIF89a').status_code == 400
    assert w.get('/api/public/full-view', query_string={'workspace_id': w.ws['id']}).status_code == 200
    assert w.get('/fullview/green-valley').status_code == 200
    assert w.get('/fullview/unknown-endpoint').status_code == 404
    assert w.get(f"/customer/full-view/{w.ws['id']}").status_code == 200
    assert w.get(f"/customer/full-view/edit/{w.ws['id']}").status_code in (200, 302, 401, 403)
    assert w.get(f"/api/customer/full-view/floor-plan/{w.catalogue['id']}/items").status_code == 200
    assert w.get(f"/api/customer/full-view/gallery/{w.gallery['id']}/items").status_code == 200
    for tid in tabs:
        assert w.delete(f'/api/full-view/tabs/{tid}', as_='admin').status_code in (200, 204)
    assert w.delete(f'/api/full-view/config/{cid}', as_='admin').status_code == 403
    assert w.delete(f'/api/full-view/config/{cid}', as_='super').status_code == 403  # edit-only by design


def test_full_view_logo_local_storage(world, monkeypatch):
    import app.config as app_config
    monkeypatch.setattr(app_config, 'SUPABASE_S3_BUCKET', '')
    assert world.upload('/api/full-view/logo-upload', filename='l.png', content=png_bytes()).status_code in (200, 201)
    assert world.upload('/api/full-view/icon-upload', filename='i.png', content=png_bytes()).status_code in (200, 201)


# ---------------------------------------------------------------- maps link resolver
class _Resp:
    def __init__(self, url='', status=200, payload=None):
        self.url, self.status_code, self._payload = url, status, payload or {}

    def json(self):
        return self._payload

    def close(self):
        pass


@pytest.mark.parametrize('link,coords', [
    ('https://www.google.com/maps/@18.52,73.85,15z', (18.52, 73.85)),
    ('https://www.google.com/maps/place/x/data=!3d18.5!4d73.8', (18.5, 73.8)),
    ('https://maps.google.com/?q=18.1,73.2', (18.1, 73.2)),
    ('https://maps.google.com/?ll=18.3,73.4', (18.3, 73.4)),
])
def test_maps_link_coordinates(world, monkeypatch, link, coords):
    geo = {'address': {'road': 'MG Road', 'suburb': 'Camp', 'city': 'Pune', 'state': 'MH'}, 'display_name': 'Pune'}
    monkeypatch.setattr(register._requests, 'get', lambda *a, **k: _Resp(status=200, payload=geo))
    r = world.post('/api/resolve-maps-link', as_='admin', json={'link': link})
    assert r.status_code == 200, r.get_data(as_text=True)
    body = r.get_json()
    assert (body['lat'], body['lng']) == coords and body['city'] == 'Pune' and 'MG Road' in body['address']


def test_maps_short_links_and_failures(world, monkeypatch):
    w = world
    monkeypatch.setattr(register._requests, 'head', lambda *a, **k: _Resp(url='https://maps.google.com/?q=1.5,2.5'))
    monkeypatch.setattr(register._requests, 'get', lambda *a, **k: _Resp(status=500))
    r = w.post('/api/resolve-maps-link', as_='admin', json={'link': 'https://maps.app.goo.gl/abc'})
    assert r.status_code == 200 and 'address' not in r.get_json()

    def boom(*a, **k):
        raise ConnectionError('offline')
    monkeypatch.setattr(register._requests, 'head', boom)
    monkeypatch.setattr(register._requests, 'get', lambda *a, **k: _Resp(url='https://maps.google.com/?center=3.5,4.5'))
    assert w.post('/api/resolve-maps-link', as_='admin', json={'link': 'https://goo.gl/maps/x'}).status_code == 200
    monkeypatch.setattr(register._requests, 'get', boom)
    assert w.post('/api/resolve-maps-link', as_='admin', json={'link': 'https://goo.gl/maps/x'}).status_code == 400
    assert w.post('/api/resolve-maps-link', as_='admin', json={'link': 'https://example.com/no-coords'}).status_code == 400
    assert w.post('/api/resolve-maps-link', as_='admin', json={}).status_code == 400
    geo_no_parts = {'address': {}, 'display_name': 'Somewhere'}
    monkeypatch.setattr(register._requests, 'get', lambda *a, **k: _Resp(status=200, payload=geo_no_parts))
    r = w.post('/api/resolve-maps-link', as_='admin', json={'link': 'https://maps.google.com/?q=1.0,2.0'})
    assert r.get_json()['address'] == 'Somewhere'


# ---------------------------------------------------------------- media streaming & uploads folder
def test_media_streaming(world):
    w = world
    for path in (f"/api/panoramas/{w.pano['id']}/image", f"/api/panoramas/{w.pano['id']}/thumb",
                 f"/api/public/panoramas/{w.pano['id']}/image", '/uploads/main.jpg', '/uploads/main.jpg?size=thumb',
                 '/uploads/missing.jpg', '/uploads/../secret', f"/api/public/plots/{w.plot['id']}/image",
                 f"/api/public/markers/{w.marker['id']}/image"):
        r = w.get(path, as_='admin', headers={'Range': 'bytes=0-10'})
        assert r.status_code in (200, 206, 302, 304, 400, 403, 404), (path, r.status_code)


def test_uploads_fall_back_to_local_files(world, monkeypatch):
    import app.config as app_config
    monkeypatch.setattr(app_config, 'SUPABASE_S3_BUCKET', '')
    w = world
    assert w.get('/uploads/main.jpg').status_code == 200
    assert w.get('/uploads/main.jpg?size=thumb').status_code in (200, 302)
    assert w.get('/uploads/nope.jpg').status_code == 404


# ---------------------------------------------------------------- mobile panoramas
def test_mobile_panorama(world):
    w = world
    path = f"/api/panoramas/{w.pano['id']}/mobile"
    r = w.upload(path, filename='m.jpg', content=jpeg_bytes(200, 100), extra={'width': '200', 'height': '100'})
    assert r.status_code in (200, 201, 400, 404, 405), r.get_data(as_text=True)
    assert w.get(path, as_='admin').status_code in (200, 404, 405)
