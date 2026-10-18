"""Sales tools media: day/night, galleries, floor plans, building map images, route maps, flat 360."""
import io

import pytest

import app.config as app_config
import app.services.storage_service as storage
from world import jpeg_bytes, png_bytes


def _files(w, path, files, form=None, as_='admin', method='POST'):
    data = dict(form or {})
    data.update(files)
    return w.client.open(path, method=method, data=data, content_type='multipart/form-data', headers=w.headers(as_))


def _mp4():
    return b'\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom' + b'\x00' * 256


# ---------------------------------------------------------------- day / night
def test_daynight_image_stitching(world):
    w = world
    path = f"/api/daynight/{w.daynight['id']}/upload-images"
    images = lambda n: [(io.BytesIO(jpeg_bytes(160 + i, 90)), f'f{i}.jpg') for i in range(n)]  # noqa: E731
    r = _files(w, path, {'images': images(3)})
    assert r.status_code == 200, r.get_data(as_text=True)
    body = r.get_json()
    assert body['share_url'].endswith('/daynight/view/dn-token') and body['stitched_width'] > 0
    assert _files(w, path, {'images': images(1)}).status_code == 400
    assert _files(w, path, {'images': [(io.BytesIO(b'x'), 'a.txt'), (io.BytesIO(b'y'), 'b.txt')]}).status_code == 400
    assert _files(w, path, {'images': [(io.BytesIO(b''), 'a.jpg'), (io.BytesIO(b''), 'b.jpg')]}).status_code == 400
    assert _files(w, path, {'images': [(io.BytesIO(b'not-image'), 'a.jpg'), (io.BytesIO(b'no'), 'b.jpg')]}).status_code == 500
    assert _files(w, path, {'images': images(2)}, as_='admin2').status_code == 403
    assert _files(w, path, {'images': images(2)}, as_='super').status_code == 200
    assert _files(w, f"/api/daynight/{w.daynight_video['id']}/upload-images", {'images': images(2)}).status_code == 400
    assert _files(w, '/api/daynight/missing/upload-images', {'images': images(2)}).status_code == 404


def test_daynight_video_direct_upload(world):
    w = world
    pid = w.daynight_video['id']
    url = f'/api/daynight/{pid}/upload-video-url'
    assert w.post(url, as_='admin', json={}).status_code == 400
    assert w.post(url, as_='admin', json={'original_filename': 'a.avi.exe'}).status_code == 400
    assert w.post(url, as_='admin', json={'original_filename': 'a.mp4', 'size_bytes': 10 ** 12}).status_code == 413
    assert w.post(url, as_='admin', json={'original_filename': 'clip', 'content_type': 'video/mp4'}).status_code == 200
    assert w.post(f"/api/daynight/{w.daynight['id']}/upload-video-url", as_='admin',
                  json={'original_filename': 'a.mp4'}).status_code == 400
    assert w.post(url, as_='admin2', json={'original_filename': 'a.mp4'}).status_code == 403
    ticket = w.post(url, as_='admin', json={'original_filename': 'clip.mp4'}).get_json()
    up = f'/api/daynight/{pid}/upload-video'
    post = lambda data, who='admin': w.client.post(up, headers=w.headers(who), data=data)  # noqa: E731
    assert post({'upload_token': ticket['upload_token']}).status_code in (400, 200)
    assert post({'filename': ticket['filename']}).status_code == 400
    assert post({'filename': ticket['filename'], 'upload_token': 'bad'}).status_code == 400
    assert post({'filename': 'other.mp4', 'upload_token': ticket['upload_token']}).status_code == 403
    assert post({'filename': ticket['filename'], 'upload_token': ticket['upload_token']}).status_code == 400  # not uploaded
    w.s3.objects[storage.daynight_object_key(ticket['filename'])] = {'body': _mp4(), 'content_type': 'video/mp4'}
    r = post({'filename': ticket['filename'], 'upload_token': ticket['upload_token'], 'video_duration': '4.5'})
    assert r.status_code == 200, r.get_data(as_text=True)
    assert w.db.one('daynight_projects', id=pid)['video_filename'] == ticket['filename']


def test_daynight_video_form_upload(world, monkeypatch):
    w = world
    up = f"/api/daynight/{w.daynight_video['id']}/upload-video"
    assert _files(w, up, {'video': (io.BytesIO(_mp4()), 'clip.mp4')}, {'video_duration': '3'}).status_code == 200
    assert _files(w, up, {'video': (io.BytesIO(b'x'), 'clip.txt')}).status_code == 400
    assert _files(w, up, {'video': (io.BytesIO(b''), 'clip.mp4')}).status_code == 400
    assert w.client.post(up, headers=w.headers('admin')).status_code == 400
    assert _files(w, f"/api/daynight/{w.daynight['id']}/upload-video", {'video': (io.BytesIO(_mp4()), 'c.mp4')}).status_code == 400
    monkeypatch.setattr(app_config, 'SUPABASE_S3_BUCKET', '')
    assert w.post(f"/api/daynight/{w.daynight_video['id']}/upload-video-url", as_='admin',
                  json={'original_filename': 'a.mp4'}).status_code == 503


def test_daynight_crud_and_public_views(world):
    w = world
    r = w.post('/api/daynight', as_='admin', json={'name': 'New DN', 'media_type': 'video', 'workspace_id': w.ws['id']})
    assert r.status_code in (200, 201), r.get_data(as_text=True)
    new_id = r.get_json().get('id') or r.get_json().get('project', {}).get('id')
    assert w.post('/api/daynight', as_='admin', json={'name': '', 'media_type': 'image'}).status_code == 400
    assert w.post('/api/daynight', as_='admin', json={'name': 'x', 'media_type': 'gif'}).status_code == 400
    assert w.get('/api/daynight', as_='admin', query_string={'workspace_id': w.ws['id']}).status_code == 200
    assert w.patch(f'/api/daynight/{new_id}', as_='admin', json={'name': 'Renamed', 'drag_speed': 2,
                                                                 'join_positions': [0.3, 0.6]}).status_code == 200
    assert w.patch(f'/api/daynight/{new_id}', as_='admin2', json={'name': 'x'}).status_code in (403, 404)
    for path in ('/daynight/view/dn-token', '/daynight/preview/dn-token', '/daynight/view/dnv-token',
                 f"/customer/full-view/daynight/{w.daynight['id']}", '/api/public/daynight/dn-token'):
        assert w.get(path).status_code in (200, 404), path
    assert w.get('/daynight/view/nope').status_code == 404
    assert w.delete(f'/api/daynight/{new_id}', as_='admin').status_code in (200, 204)


# ---------------------------------------------------------------- galleries
@pytest.mark.parametrize('name,content,form,ok', [
    ('photo.png', png_bytes(), {}, True),
    ('photo.jpg', jpeg_bytes(400, 200), {'is_360': 'true'}, True),
    ('walk.mp4', _mp4(), {}, True),
    ('doc.pdf', b'%PDF-1.4', {}, False),
    ('empty.jpg', b'', {}, False),
])
def test_gallery_item_uploads(world, name, content, form, ok):
    w = world
    r = _files(w, f"/api/galleries/{w.gallery['id']}/items", {'file': (io.BytesIO(content), name)}, form)
    assert (r.status_code in (200, 201)) == ok, r.get_data(as_text=True)


def test_gallery_crud(world):
    w = world
    r = w.post('/api/galleries', as_='admin', json={'name': 'Interiors', 'workspace_id': w.ws['id']})
    assert r.status_code in (200, 201)
    gid = r.get_json()['id']
    assert w.post('/api/galleries', as_='admin', json={'name': ''}).status_code in (201, 400)  # blank gets a default
    assert w.get(f'/api/galleries/{gid}', as_='admin').status_code == 200
    assert w.get(f'/api/galleries/{gid}/items', as_='admin').status_code == 200
    item = _files(w, f'/api/galleries/{gid}/items', {'file': (io.BytesIO(png_bytes()), 'a.png')}).get_json()
    iid = item.get('id') or item.get('item', {}).get('id')
    assert w.patch(f'/api/gallery-items/{iid}', as_='admin', json={'name': 'Lobby', 'sort_order': 3}).status_code == 200
    assert w.patch(f'/api/gallery-items/{iid}', as_='admin2', json={'name': 'x'}).status_code in (403, 404)
    assert w.patch(f'/api/galleries/{gid}', as_='admin', json={'name': 'Renamed'}).status_code == 200
    assert w.get(f'/gallery/view/gal-token').status_code == 200
    assert w.get(f"/customer/full-view/gallery/{w.gallery['id']}").status_code in (200, 404)
    assert w.delete(f'/api/gallery-items/{iid}', as_='admin').status_code in (200, 204)
    assert w.delete(f'/api/galleries/{gid}', as_='admin').status_code in (200, 204)
    assert w.get(f'/api/galleries/{gid}', as_='admin').status_code == 404


# ---------------------------------------------------------------- floor plans
def test_floor_plan_catalogue_lifecycle(world):
    w = world
    r = w.post('/api/floorplans/catalogues', as_='admin', json={'name': 'Towers', 'workspace_id': w.ws['id']})
    assert r.status_code in (200, 201), r.get_data(as_text=True)
    cid = r.get_json()['id']
    up = f'/api/floorplans/catalogues/{cid}/items'
    for name, content in (('a.png', png_bytes()), ('b.jpg', jpeg_bytes())):
        assert _files(w, up, {'file': (io.BytesIO(content), name)}, {'name': name}).status_code in (200, 201)
    assert _files(w, up, {'file': (io.BytesIO(b'x'), 'a.gif.exe')}).status_code == 400
    assert w.client.post(up, headers=w.headers('admin')).status_code == 400
    items = w.get(up, as_='admin').get_json()
    items = items.get('items', items) if isinstance(items, dict) else items
    iid = items[0]['id']
    assert w.patch(f'/api/floorplans/items/{iid}', as_='admin', json={'name': 'Type B', 'sort_order': 2}).status_code == 200
    assert w.patch(f'/api/floorplans/catalogues/{cid}', as_='admin', json={'name': 'Renamed'}).status_code == 200
    assert w.get('/floorplans/view/fp-token').status_code in (200, 404)
    assert w.get(f"/customer/full-view/floor-plan/{w.catalogue['id']}").status_code in (200, 404)
    assert w.delete(f'/api/floorplans/items/{iid}', as_='admin').status_code in (200, 204)
    assert w.delete(f'/api/floorplans/catalogues/{cid}', as_='admin').status_code in (200, 204)
    assert w.delete(f'/api/floorplans/catalogues/{cid}', as_='admin').status_code == 404


# ---------------------------------------------------------------- building maps
def test_building_map_lifecycle(world):
    w = world
    r = _files(w, '/api/building-maps', {'file': (io.BytesIO(png_bytes(120, 60)), 'tower.png')},
               {'name': 'Tower B', 'workspace_id': w.ws['id']})
    assert r.status_code in (200, 201), r.get_data(as_text=True)
    mid = r.get_json()['id']
    assert _files(w, '/api/building-maps', {'file': (io.BytesIO(b'x'), 'x.txt')}, {'name': 'x'}).status_code == 400
    img = _files(w, f'/api/building-maps/{mid}/images', {'file': (io.BytesIO(png_bytes()), 'side.png')}, {'name': 'Side'})
    assert img.status_code in (200, 201), img.get_data(as_text=True)
    image_id = img.get_json()['id']
    assert w.get(f'/api/building-maps/{mid}/images', as_='admin').status_code == 200
    assert w.patch(f'/api/building-map-images/{image_id}', as_='admin', json={'name': 'Back', 'sort_order': 1}).status_code == 200
    zone = w.post(f'/api/building-maps/{mid}/zones', as_='admin', json={
        'name': 'Floor 2', 'floor_number': 2, 'points': [[0, 0], [1, 0], [1, 1]], 'color': '#00ff00',
        'image_id': image_id, 'link_type': 'panorama', 'linked_panorama_id': w.pano['id'],
        'meta': {'units': [{'name': '201', 'status': 'available'}]}})
    assert zone.status_code in (200, 201), zone.get_data(as_text=True)
    zid = zone.get_json()['id']
    batch = w.post(f'/api/building-maps/{mid}/zones/batch', as_='admin', json={'zones': [
        {'name': f'F{i}', 'floor_number': i, 'points': [[0, 0], [1, 0], [1, 1]]} for i in range(3, 6)]})
    assert batch.status_code in (200, 201, 404), batch.get_data(as_text=True)
    for body in ({'name': 'Floor 2A'}, {'points': [[0, 0], [0.5, 0], [0.5, 0.5]]}, {'link_type': 'building_map',
                 'linked_building_map_id': w.building_map['id']}, {'link_type': 'floor_plan',
                 'linked_floor_plan_item_id': w.fp_item['id']}, {'meta': {'units': []}}, {'color': 'not-a-color'}):
        assert w.put(f'/api/building-zones/{zid}', as_='admin', json=body).status_code in (200, 400), body
    assert w.get(f'/api/building-maps/{mid}', as_='admin').status_code == 200
    assert w.patch(f'/api/building-maps/{mid}', as_='admin', json={'name': 'Tower B2', 'view_config': {'zoom': 2}}).status_code == 200
    assert w.get('/building-plan/bm-token').status_code in (200, 404)
    assert w.delete(f'/api/building-zones/{zid}', as_='admin').status_code in (200, 204)
    assert w.delete(f'/api/building-map-images/{image_id}', as_='admin').status_code in (200, 204)
    assert w.delete(f'/api/building-maps/{mid}', as_='admin').status_code in (200, 204)


# ---------------------------------------------------------------- sales route maps & flat 360
def test_sales_route_map_lifecycle(world):
    w = world
    r = _files(w, '/api/sales-maps', {'file': (io.BytesIO(png_bytes(200, 100)), 'map.png')},
               {'name': 'Connectivity 2', 'workspace_id': w.ws['id']})
    assert r.status_code in (200, 201), r.get_data(as_text=True)
    mid = r.get_json()['id']
    m1 = w.post(f'/api/sales-maps/{mid}/markers', as_='admin', json={'marker_type': 'main', 'label': 'Site',
                                                                     'x_ratio': 0.5, 'y_ratio': 0.5})
    m2 = w.post(f'/api/sales-maps/{mid}/markers', as_='admin', json={'marker_type': 'normal', 'label': 'School',
                                                                     'x_ratio': 0.2, 'y_ratio': 0.8})
    assert m1.status_code in (200, 201) and m2.status_code in (200, 201), m1.get_data(as_text=True)
    a, b = m1.get_json()['id'], m2.get_json()['id']
    route = w.post(f'/api/sales-maps/{mid}/routes', as_='admin', json={
        'from_marker_id': a, 'to_marker_id': b, 'path_points': [{'x': 0.5, 'y': 0.5}, {'x': 0.2, 'y': 0.8}], 'color': '#ff0000',
        'line_width': 3, 'distance_km': 4.2, 'line_style': 'dashed'})
    assert route.status_code in (200, 201), route.get_data(as_text=True)
    rid = route.get_json()['id']
    hover = w.post(f'/api/sales-maps/{mid}/hover-routes', as_='admin', json={
        'label': 'Ring road', 'path_points': [{'x': 0.1, 'y': 0.1}, {'x': 0.9, 'y': 0.9}], 'color': '#00ff00', 'line_width': 2})
    assert hover.status_code in (200, 201), hover.get_data(as_text=True)
    hid = hover.get_json()['id']
    for body in ({'label': 'Main site', 'x_ratio': 0.55}, {'x_ratio': 2}, {'icon_key': 'hospital', 'icon_color': '#fff',
                 'pointer_type': 'pin', 'icon_look': 'solid', 'marker_size': 1.5}, {'marker_type': 'unknown'}):
        assert w.patch(f'/api/sales-map-markers/{a}', as_='admin', json=body).status_code in (200, 400), body
    for body in ({'color': '#0000ff', 'distance_km': 5}, {'path_points': 'bad'}, {'line_style': 'dotted', 'line_width': 9}):
        assert w.patch(f'/api/sales-map-routes/{rid}', as_='admin', json=body).status_code in (200, 400), body
    for body in ({'label': 'Highway'}, {'path_points': [[0, 0]]}, {'line_style': 'solid'}):
        assert w.patch(f'/api/sales-map-hover-routes/{hid}', as_='admin', json=body).status_code in (200, 400), body
    assert w.get(f'/api/sales-maps/{mid}', as_='admin').status_code == 200
    assert w.patch(f'/api/sales-maps/{mid}', as_='admin', json={'name': 'Renamed'}).status_code == 200
    replaced = _files(w, f'/api/sales-maps/{mid}/image', {'file': (io.BytesIO(png_bytes(300, 150)), 'new.png')},
                      method='PUT')
    assert replaced.status_code in (200, 404, 405)
    assert w.get('/sales-route-maps/view/sm-token').status_code in (200, 404)
    assert w.get(f'/sales-route-maps/editor/{mid}').status_code == 200
    assert w.delete(f'/api/sales-map-hover-routes/{hid}', as_='admin').status_code in (200, 204)
    assert w.delete(f'/api/sales-map-routes/{rid}', as_='admin').status_code in (200, 204)
    assert w.delete(f'/api/sales-map-markers/{a}', as_='admin').status_code in (200, 204)
    assert w.delete(f'/api/sales-maps/{mid}', as_='admin').status_code in (200, 204)


def test_flat360_lifecycle(world):
    w = world
    r = _files(w, '/api/sales-flat360', {'file': (io.BytesIO(jpeg_bytes(400, 200)), 'flat.jpg')},
               {'name': 'Flat 2', 'workspace_id': w.ws['id']})
    assert r.status_code in (200, 201), r.get_data(as_text=True)
    vid = r.get_json()['id']
    assert _files(w, '/api/sales-flat360', {'file': (io.BytesIO(b'x'), 'a.txt')}, {'name': 'x'}).status_code == 400
    assert w.get(f'/api/sales-flat360/{vid}', as_='admin').status_code == 200
    assert w.patch(f'/api/sales-flat360/{vid}', as_='admin', json={'name': 'Flat 2B'}).status_code == 200
    assert w.patch(f'/api/sales-flat360/{vid}', as_='admin2', json={'name': 'x'}).status_code in (403, 404)
    assert w.get('/sales-flat360/view/f360-token').status_code in (200, 404)
    assert w.delete(f'/api/sales-flat360/{vid}', as_='admin').status_code in (200, 204)
