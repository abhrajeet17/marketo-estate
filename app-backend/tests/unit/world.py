"""
A seeded, in-memory MarketoState world for route-level unit tests.

`World` installs FakeSupabase/FakeS3 in place of the real clients, signs tokens for the seeded
users and offers request helpers (`w.get('/api/x', as_='admin')`). Every id is generated here,
so tests never depend on, or touch, real data.
"""
import functools
import io
import time
import uuid

import jwt

from fakedb import FakeS3, FakeSupabase

SECRET = 'unit-test-secret-at-least-32-bytes!!'
MP4_BYTES = bytes(3) + bytes([24]) + b'ftypmp42' + bytes(64)


@functools.lru_cache(maxsize=None)
def png_bytes(width=64, height=32, color=(200, 120, 40)):
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', (width, height), color).save(buf, 'PNG')
    return buf.getvalue()


@functools.lru_cache(maxsize=None)
def jpeg_bytes(width=128, height=64, color=(30, 120, 200)):
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', (width, height), color).save(buf, 'JPEG', quality=90)
    return buf.getvalue()


def _finished(resp):
    """Read streamed bodies to the end so stream_with_context pops its request context now,
    not later during garbage collection (which would pop whatever request runs then)."""
    resp.get_data()
    resp.close()
    return resp


class World:
    def __init__(self, app, monkeypatch, tmp_path):
        self.app = app
        self.client = app.test_client()
        raw_open = self.client.open
        self.client.open = lambda *a, **k: _finished(raw_open(*a, **k))  # get/post/... all go through open
        self.db = FakeSupabase()
        self.s3 = FakeS3()
        self.sent_emails = []
        self.tmp = tmp_path
        self._install(monkeypatch)
        self._seed()

    # ------------------------------------------------------------------ setup
    def _install(self, mp):
        import app.config as app_config
        import app.core.auth as auth
        import app.core.database as database
        import app.services.storage_service as storage

        mp.setattr(time, 'sleep', lambda *_a, **_k: None)  # retry back-off is instant in unit tests
        mp.setattr(database, 'SUPABASE_URL', 'https://fake.supabase.test')
        mp.setattr(app_config, 'SUPABASE_URL', 'https://fake.supabase.test')
        mp.setattr(app_config, 'SUPABASE_SERVICE_ROLE_KEY', 'service-role-test')
        mp.setattr(database, 'SUPABASE_SERVICE_ROLE_KEY', 'service-role-test')
        mp.setattr(database, '_sb_client', self.db)
        import supabase
        mp.setattr(supabase, 'create_client', lambda *_a, **_k: self.db)  # admin user routes build their own
        mp.setattr(database, 'reset_supabase_client', lambda: None)
        mp.setattr(auth, 'reset_supabase_client', lambda: None)
        mp.setattr(auth, 'SUPABASE_URL', '')
        mp.setattr(auth, 'CLERK_ISSUER', '')
        mp.setattr(auth, 'CLERK_JWKS_URL', '')
        mp.setattr(auth, 'SUPABASE_JWT_SECRET', SECRET)
        auth._TOKEN_CACHE.clear()
        auth._PROFILE_CACHE.clear()

        for name, value in (('SUPABASE_S3_BUCKET', 'test-bucket'), ('SUPABASE_S3_ENDPOINT', 'https://s3.test'),
                            ('SUPABASE_S3_REGION', 'test-1'), ('SUPABASE_S3_ACCESS_KEY_ID', 'key'),
                            ('SUPABASE_S3_SECRET_ACCESS_KEY', 'secret')):
            mp.setattr(app_config, name, value)
        mp.setattr(storage, '_s3_client', self.s3)
        storage._s3_signed_url_cache.clear()

        uploads = self.tmp / f'uploads-{uuid.uuid4().hex[:8]}'
        uploads.mkdir(parents=True)
        mp.setattr(app_config, 'UPLOAD_FOLDER', str(uploads))
        mp.setitem(self.app.config, 'UPLOAD_FOLDER', str(uploads))
        self.uploads = uploads

        def fake_send(*args, **kwargs):
            self.sent_emails.append({'args': args, **kwargs})
            return True
        import app.services.email_service as email_service
        mp.setattr(email_service, 'send_email', fake_send)
        for module in ('app.controllers.features.crm_quotes', 'app.controllers.features.uam.shared'):
            mod = __import__(module, fromlist=['send_smtp_email'])
            if hasattr(mod, 'send_smtp_email'):
                mp.setattr(mod, 'send_smtp_email', fake_send)

        from app.services.portal_identity_service import invalidate_portal_identity
        invalidate_portal_identity()
        from app.controllers.features import building_plan
        building_plan._tree_cache.clear()
        building_plan._tree_refreshing.clear()
        # Rebuild plan trees inline: a background thread could outlive this test and touch the next one.
        mp.setattr(building_plan, '_refresh_in_background', building_plan._rebuild_tree)

    def _seed(self):
        db = self.db
        self.org = db.add('organizations', name='Acme Developers', accent_color='#ffaa00')
        self.org2 = db.add('organizations', name='Other Org')
        self.users = {}
        for key, role, org in (('super', 'superadmin', self.org), ('admin', 'admin', self.org),
                               ('admin2', 'admin', self.org2), ('broker', 'broker', self.org),
                               ('user', 'user', self.org), ('client_admin', 'user', self.org),
                               ('member', 'user', self.org), ('stranger', 'user', None)):
            uid = str(uuid.uuid4())
            email = f'{key}@example.test'
            db.add('profiles', user_id=uid, role=role, display_name=key.title(), email=email,
                   org_id=org['id'] if org else None)
            db.auth_users[uid] = {'id': uid, 'email': email, 'user_metadata': {'display_name': key.title()},
                                  'created_at': '2026-01-01T00:00:00+00:00', 'email_confirmed_at': '2026-01-01T00:00:00+00:00'}
            self.users[key] = uid
        admin = self.users['admin']
        self.client_group = db.add('clients', org_id=self.org['id'], name='Sunrise Homes', created_by=admin)
        self.client_admin_member = db.add('client_members', client_id=self.client_group['id'],
                                          user_id=self.users['client_admin'], member_role='client_admin', invited_by=admin)
        self.client_member = db.add('client_members', client_id=self.client_group['id'],
                                    user_id=self.users['member'], member_role='client_user', invited_by=admin)
        self.broker_member = db.add('client_members', client_id=self.client_group['id'],
                                    user_id=self.users['broker'], member_role='broker', invited_by=admin)

        self.ws = db.add('workspaces', user_id=admin, org_id=self.org['id'], name='Green Valley',
                         location_city='Pune', location_state='MH', is_published=True,
                         location_lat=18.5, location_lng=73.8, amenities=['Clubhouse'])
        self.ws2 = db.add('workspaces', user_id=admin, org_id=self.org['id'], name='Blue Ridge')
        self.foreign_ws = db.add('workspaces', user_id=self.users['admin2'], org_id=self.org2['id'], name='Foreign')

        self.pano = db.add('panoramas', user_id=admin, org_id=self.org['id'], workspace_id=self.ws['id'],
                           name='Main Drone', filename='main.jpg', original_filename='main.jpg',
                           width=4096, height=2048, is_360=True)
        self.pano2 = db.add('panoramas', user_id=admin, org_id=self.org['id'], workspace_id=self.ws['id'],
                            name='Gate', filename='gate.jpg', width=2000, height=1000, is_360=False)
        self.unlinked_pano = db.add('panoramas', user_id=admin, org_id=self.org['id'], workspace_id=None,
                                    name='Loose', filename='loose.jpg', width=4096, height=2048)
        self.foreign_pano = db.add('panoramas', user_id=self.users['admin2'], org_id=self.org2['id'],
                                   workspace_id=self.foreign_ws['id'], name='Foreign Pano', filename='f.jpg')
        db.tables['workspaces'][0]['main_panorama_id'] = self.pano['id']
        self.ws['main_panorama_id'] = self.pano['id']
        import app.services.storage_service as st
        for name, data in (('main.jpg', jpeg_bytes(256, 128)), ('gate.jpg', jpeg_bytes()), ('loose.jpg', jpeg_bytes())):
            self.s3.objects[st.panorama_object_key(name)] = {'body': data, 'content_type': 'image/jpeg'}
            (self.uploads / name).write_bytes(data)
        for key_fn, name in ((st.plot_object_key, 'plot.jpg'), (st.marker_object_key, 'marker.jpg'),
                             (st.voiceover_object_key, 'voice.wav'), (st.panorama_audio_object_key, 'pano_audio.wav')):
            self.s3.objects[key_fn(name)] = {'body': jpeg_bytes(), 'content_type': 'application/octet-stream'}

        self.plot = db.add('plots', panorama_id=self.pano['id'], name='A-1', area='1200', price='42L',
                           status='available', color='#00ff00', points=[[0.1, 0.2], [0.2, 0.2], [0.2, 0.3]])
        self.plot_sold = db.add('plots', panorama_id=self.pano['id'], name='A-2', status='sold', points=[])
        self.marker = db.add('plot_markers', plot_id=str(self.pano['id']), name='Clubhouse', longitude=10.0,
                             latitude=5.0, marker_style='pin', status='available', link_mode='none',
                             image_filename='marker.jpg', voiceover_filename='voice.wav')
        db.add('plot_markers', plot_id=str(self.pano['id']), name='Gate link', longitude=20.0, latitude=1.0,
               marker_style='nav', link_mode='panorama', linked_panorama_id=self.pano2['id'])
        db.tables['plots'][0].update({'image_filename': 'plot.jpg', 'media_photo': 'https://img.test/p.jpg',
                                      'label_longitude': 1.0, 'label_latitude': 2.0, 'linked_panorama_id': self.pano2['id']})
        db.tables['panoramas'][0].update({'audio_filename': 'pano_audio.wav', 'start_view': {'longitude': 1, 'latitude': 2},
                                          'use_animated_icons': True})

        db.add('workspace_access', workspace_id=self.ws['id'], user_id=self.users['user'], access_type='view',
               granted_by=admin)
        db.add('panorama_access', panorama_id=self.pano['id'], user_id=self.users['user'], access_type='view',
               granted_by=admin)
        db.add('workspace_access', workspace_id=self.ws['id'], user_id=self.users['member'], access_type='view',
               granted_by=admin, client_member_id=self.client_member['id'])
        db.add('plot_lock_access', panorama_id=self.pano['id'], user_id=self.users['broker'], granted_by=admin,
               org_id=self.org['id'])
        # Richer access: client-group grants for the broker and client admin, editor/client panorama grants.
        db.add('workspace_access', workspace_id=self.ws['id'], user_id=self.users['broker'], access_type='client',
               granted_by=admin, client_member_id=self.broker_member['id'])
        db.add('workspace_access', workspace_id=self.ws['id'], user_id=self.users['client_admin'], access_type='client',
               granted_by=admin, client_member_id=self.client_admin_member['id'])
        db.add('panorama_access', panorama_id=self.pano2['id'], user_id=self.users['client_admin'], access_type='client',
               granted_by=admin, client_member_id=self.client_admin_member['id'])
        db.add('panorama_access', panorama_id=self.pano2['id'], user_id=self.users['member'], access_type='editor',
               granted_by=admin, client_member_id=self.client_member['id'])
        db.add('workspace_access', workspace_id=self.ws2['id'], user_id=self.users['admin2'], access_type='editor',
               granted_by=admin)
        db.add('mobile_panoramas', user_id=admin, org_id=self.org['id'], workspace_id=self.ws['id'],
               panorama_parent_id=self.pano['id'], name='Mobile', filename='mobile.jpg', width=2048, height=1024)
        db.add('workspace_share_endpoints', workspace_id=self.ws['id'], endpoint='green-valley', created_by=admin)

        self.catalogue = db.add('floor_plan_catalogues', workspace_id=self.ws['id'], user_id=admin,
                                org_id=self.org['id'], name='Villas', share_token='fp-token')
        self.fp_item = db.add('floor_plan_items', catalogue_id=self.catalogue['id'], name='Type A',
                              image_filename='fp_a.png', image_width=64, image_height=32)
        self.gallery = db.add('galleries', user_id=admin, org_id=self.org['id'], name='Amenities',
                              share_token='gal-token', workspace_id=self.ws['id'])
        self.gallery_item = db.add('gallery_items', gallery_id=self.gallery['id'], name='Pool', media_type='image',
                                   filename='pool.png', media_width=64, media_height=32)
        self.daynight = db.add('daynight_projects', user_id=admin, org_id=self.org['id'], name='Dusk',
                               media_type='image', stitched_filename='dn.jpg', stitched_width=256,
                               stitched_height=64, share_token='dn-token', workspace_id=self.ws['id'],
                               join_positions=[0.5], source_images=['a.jpg', 'b.jpg'], drag_speed=1)
        self.daynight_video = db.add('daynight_projects', user_id=admin, org_id=self.org['id'], name='Dusk video',
                                     media_type='video', video_filename='dn.mp4', share_token='dnv-token',
                                     workspace_id=self.ws['id'])
        self.building_map = db.add('building_maps', user_id=admin, org_id=self.org['id'], name='Tower A',
                                   image_filename='tower.png', image_width=64, image_height=32,
                                   share_token='bm-token', workspace_id=self.ws['id'], view_config={})
        self.zone = db.add('building_zones', building_map_id=self.building_map['id'], name='Floor 1',
                           floor_number=1, color='#ff0000', points=[[0, 0], [1, 0], [1, 1]],
                           linked_floor_plan_item_id=self.fp_item['id'], link_type='floor_plan')
        self.project_plan = db.add('project_plans', user_id=admin, org_id=self.org['id'], name='Master Plan',
                                   share_token='pp-token', workspace_id=self.ws['id'])
        db.add('project_plan_maps', project_plan_id=self.project_plan['id'], building_map_id=self.building_map['id'])
        self.earth_view = db.add('earth_views', user_id=admin, org_id=self.org['id'], name='Site Globe',
                                 share_token='ev-token', center_lng=73.8, center_lat=18.5, zoom=14,
                                 workspace_id=self.ws['id'])
        db.add('earth_view_plots', earth_view_id=self.earth_view['id'], name='P1', status='available',
               points=[[73.8, 18.5], [73.81, 18.5], [73.81, 18.51]])
        db.add('earth_view_markers', earth_view_id=self.earth_view['id'], name='Gate', longitude=73.8, latitude=18.5)
        self.sales_map = db.add('sales_route_maps', user_id=admin, org_id=self.org['id'], workspace_id=self.ws['id'],
                                name='Connectivity', image_filename='map.png', image_width=64, image_height=32,
                                share_token='sm-token')
        m1 = db.add('sales_route_map_markers', map_id=self.sales_map['id'], marker_type='main', label='Site',
                    x_ratio=0.5, y_ratio=0.5)
        m2 = db.add('sales_route_map_markers', map_id=self.sales_map['id'], marker_type='normal', label='Airport',
                    x_ratio=0.1, y_ratio=0.1)
        db.add('sales_route_map_routes', map_id=self.sales_map['id'], from_marker_id=m1['id'], to_marker_id=m2['id'],
               path_points=[{'x': 0.5, 'y': 0.5}, {'x': 0.1, 'y': 0.1}], color='#fff', line_width=3, distance_km=12)
        db.add('sales_route_map_hover_routes', map_id=self.sales_map['id'], label='Highway',
               path_points=[{'x': 0.2, 'y': 0.2}, {'x': 0.3, 'y': 0.3}], color='#0f0', line_width=2)
        self.flat360 = db.add('sales_flat360_views', user_id=admin, org_id=self.org['id'], workspace_id=self.ws['id'],
                              name='Flat 360', image_filename='flat.jpg', image_width=256, image_height=128,
                              share_token='f360-token')
        self.fv_config = db.add('full_view_configs', workspace_id=self.ws['id'], org_id=self.org['id'], user_id=admin,
                                is_active=True, style={'accent': '#ffaa00'})
        db.add('full_view_tabs', config_id=self.fv_config['id'], icon='pano', name='Tour', tab_type='panorama',
               ref_panorama_id=self.pano['id'], sort_order=0, is_visible=True)
        db.add('full_view_tabs', config_id=self.fv_config['id'], icon='info', name='About', tab_type='content',
               content_data={'html': '<p>Hi</p>'}, sort_order=1, is_visible=True)

        import app.services.storage_service as st
        stored = ((st.floorplan_object_key, 'fp_a.png', png_bytes()), (st.gallery_object_key, 'pool.png', png_bytes()),
                  (st.building_map_object_key, 'tower.png', png_bytes()), (st.sales_map_object_key, 'map.png', png_bytes()),
                  (st.sales_flat360_object_key, 'flat.jpg', jpeg_bytes(256, 128)),
                  (st.daynight_object_key, 'dn.jpg', jpeg_bytes(256, 64)),
                  (st.daynight_object_key, 'dn.mp4', MP4_BYTES))
        for key_fn, name, data in stored:
            content_type = 'video/mp4' if name.endswith('.mp4') else ('image/png' if name.endswith('.png') else 'image/jpeg')
            self.s3.objects[key_fn(name)] = {'body': data, 'content_type': content_type}
            (self.uploads / name).write_bytes(data)

        self.lead = db.add('crm_leads', record_status='lead', org_id=self.org['id'], client_id=self.client_group['id'],
                           panorama_id=self.pano['id'], submitted_by=self.users['broker'],
                           reference_user_id=self.users['broker'], reference_user_role='broker',
                           customer_name='Riya Sharma', customer_email='riya@example.test',
                           customer_phone='+91 98765 43210', email_norm='riya@example.test', phone_norm='919876543210',
                           lead_status='new', lead_source='tour', plots=[{'id': self.plot['id'], 'name': 'A-1'}],
                           custom_fields={'budget': '50L', 'visits': 3, 'vip': True})
        self.interest = db.add('buy_interests', panorama_id=self.pano['id'], submitted_by=self.users['user'],
                               customer_name='Arjun', customer_email='arjun@example.test', customer_phone='9999999999',
                               plots=[{'id': self.plot['id']}], status='new', client_id=self.client_group['id'])
        self.contact = db.add('crm_contacts', org_id=self.org['id'], panorama_id=self.pano['id'], full_name='Meera',
                              email='meera@example.test', phone='8888888888', created_by=admin,
                              client_id=self.client_group['id'])
        self.deal = db.add('crm_deals', org_id=self.org['id'], panorama_id=self.pano['id'], contact_id=self.contact['id'],
                           title='Plot A-1', stage='negotiation', amount='4200000', currency='INR',
                           plots=[{'id': self.plot['id']}], created_by=admin, client_id=self.client_group['id'])
        self.quote_template = db.add('crm_quote_templates', org_id=self.org['id'], panorama_id=self.pano['id'],
                                     name='Default', template_payload={'rows': []}, is_default=True, created_by=admin)
        self.deal_lead = db.add('crm_leads', record_status='deal', org_id=self.org['id'], client_id=self.client_group['id'],
                                panorama_id=self.pano['id'], submitted_by=admin, customer_name='Meera Desai',
                                customer_email='meera@example.test', customer_phone='8888888888', deal_title='Plot A-1',
                                deal_stage='negotiation', deal_amount='4200000', deal_currency='INR', deal_is_active=True,
                                plots=[{'id': self.plot['id'], 'name': 'A-1'}], custom_fields={},
                                converted_at='2026-03-01T00:00:00+00:00', converted_by=admin)
        self.quote = db.add('crm_deal_quotes', deal_id=self.deal_lead['id'], contact_id=self.contact['id'],
                            quote_payload={'total': 4200000}, share_token='quote-token', created_by=admin,
                            status='draft')
        db.add('crm_master_attributes', client_id=self.client_group['id'], field_key='lead_source', label='Lead source',
               is_enabled=True, applies_to=['lead'])
        db.add('crm_master_values', client_id=self.client_group['id'], field_key='lead_source', value='Website',
               is_enabled=True)
        self.normal_project = db.add('crm_normal_projects', owner_user_id=admin, name='Offline Project',
                                     location='Nashik', project_type='plotted')
        db.add('crm_normal_plots', owner_user_id=admin, project_id=self.normal_project['id'],
               project_name='Offline Project', name='N-1', status='available')
        self.invite = db.add('client_team_invites', client_id=self.client_group['id'], org_id=self.org['id'],
                             invited_by=admin, email='new@example.test', member_role='client_user',
                             invite_token='invite-token', status='pending', display_name='New Person',
                             expires_at='2099-01-01T00:00:00+00:00')
        self.join_request = db.add('client_join_requests', client_id=self.client_group['id'], org_id=self.org['id'],
                                   user_id=self.users['stranger'], member_role='client_user', status='pending')
        db.add('user_invites', org_id=self.org['id'], invited_by=admin, email='invitee@example.test', role='admin',
               status='pending')

    # ---------------------------------------------------------------- helpers
    def set_profile(self, who, **fields):
        """Change a seeded user's profile (and auth email) and drop the cached copies."""
        import app.core.auth as auth
        from app.services.portal_identity_service import invalidate_portal_identity
        uid = self.users.get(who, who)
        self.db.one('profiles', user_id=uid).update(fields)
        if 'email' in fields:
            self.db.auth_users[uid]['email'] = fields['email']
        auth._profile_cache_invalidate(uid)
        invalidate_portal_identity(uid)

    def token(self, who):
        uid = self.users.get(who, who)
        now = int(time.time())
        return jwt.encode({'sub': uid, 'role': 'authenticated', 'iat': now, 'exp': now + 600}, SECRET, algorithm='HS256')

    def headers(self, as_=None, extra=None):
        headers = dict(extra or {})
        if as_:
            headers['Authorization'] = 'Bearer ' + self.token(as_)
        return headers

    def open(self, method, path, as_=None, json=None, data=None, headers=None, **kw):
        resp = self.client.open(path, method=method, json=json, data=data,
                                headers=self.headers(as_, headers), **kw)
        return _finished(resp)

    def get(self, path, as_=None, **kw):
        return self.open('GET', path, as_=as_, **kw)

    def post(self, path, as_=None, **kw):
        return self.open('POST', path, as_=as_, **kw)

    def put(self, path, as_=None, **kw):
        return self.open('PUT', path, as_=as_, **kw)

    def patch(self, path, as_=None, **kw):
        return self.open('PATCH', path, as_=as_, **kw)

    def delete(self, path, as_=None, **kw):
        return self.open('DELETE', path, as_=as_, **kw)

    def upload(self, path, field='file', filename='image.png', content=None, as_='admin', extra=None, method='POST'):
        data = dict(extra or {})
        data[field] = (io.BytesIO(content if content is not None else png_bytes()), filename)
        return _finished(self.client.open(path, method=method, data=data, content_type='multipart/form-data',
                                          headers=self.headers(as_)))
