"""
Every route x every method x every role, against the seeded in-memory world.

A route may answer 2xx, 3xx or 4xx depending on who asks, but it must never crash (5xx or an
unhandled exception). Non-GET calls send a plausible JSON body built from GENERIC_BODY, so write
handlers run their validation and their happy path. Each route gets a fresh world, and the
destructive roles go last, so one route's deletes cannot affect another route's test.
"""
import re

import pytest

from app import app as flask_application

ROLES = (None, 'stranger', 'user', 'member', 'broker', 'client_admin', 'admin2', 'super', 'admin')

# Routes that legitimately need a service the unit environment does not provide.
EXTERNAL = {
    # Resolves a Google Maps short link / geocodes over the internet.
    ('/api/resolve-maps-link', 'POST'),
}


def _rules():
    out = []
    for rule in flask_application.url_map.iter_rules():
        if rule.rule.startswith('/static/'):
            continue
        for method in sorted((rule.methods or set()) - {'HEAD', 'OPTIONS'}):
            out.append((rule.rule, method))
    return sorted(out)


def resolve(world, rule):
    """Fill <params> with ids of seeded rows that match the parameter and the route."""
    w = world
    path = rule

    def pick(name):
        r = rule.lower()
        table = {
            'workspace_id': w.ws['id'], 'panorama_id': w.pano['id'], 'plot_id': w.plot['id'],
            'zone_id': w.zone['id'], 'catalogue_id': w.catalogue['id'], 'gallery_id': w.gallery['id'],
            'client_id': w.client_group['id'], 'config_id': w.fv_config['id'],
            'deal_id': w.deal_lead['id'], 'quote_id': w.quote['id'], 'template_id': w.quote_template['id'],
            'lead_id': w.lead['id'], 'invite_id': w.invite['id'], 'invite_token': 'invite-token',
            'org_id': w.org['id'], 'org_slug': 'acme-developers', 'plan_id': w.project_plan['id'],
            'request_id': w.join_request['id'], 'endpoint': 'green-valley', 'field_key': 'lead_source',
            'target_user_id': w.users['user'], 'user_id': w.users['user'], 'filename': 'main.jpg',
            '_rest': 'x', 'building_map_id': w.building_map['id'],
        }
        if name in table:
            return table[name]
        if name == 'map_id':
            return w.building_map['id'] if 'building' in r else w.sales_map['id']
        if name == 'view_id':
            if 'earth' in r:
                return w.earth_view['id']
            return w.flat360['id']
        if name == 'project_id':
            return w.normal_project['id'] if 'normal' in r else w.daynight['id']
        if name == 'item_id':
            return w.gallery_item['id'] if 'gallery' in r else w.fp_item['id']
        if name == 'marker_id':
            if 'earth' in r:
                return w.db.rows('earth_view_markers')[0]['id'] if w.db.rows('earth_view_markers') else 'x'
            if 'sales' in r:
                return w.db.rows('sales_route_map_markers')[0]['id'] if w.db.rows('sales_route_map_markers') else 'x'
            return w.marker['id']
        if name == 'route_id':
            rows = w.db.rows('sales_route_map_routes')
            return rows[0]['id'] if rows else 'x'
        if name == 'hover_route_id':
            rows = w.db.rows('sales_route_map_hover_routes')
            return rows[0]['id'] if rows else 'x'
        if name == 'tab_id':
            return w.db.rows('full_view_tabs')[0]['id']
        if name == 'image_id':
            rows = w.db.rows('building_map_images')
            return rows[0]['id'] if rows else w.db.add('building_map_images', building_map_id=w.building_map['id'],
                                                       name='Elevation', image_filename='tower.png')['id']
        if name == 'value_id':
            return w.db.rows('crm_master_values')[0]['id']
        if name in ('token', 'share_token'):
            for key, value in (('daynight', 'dn-token'), ('gallery', 'gal-token'), ('floor', 'fp-token'),
                               ('building-plan', 'bm-token'), ('building', 'bm-token'), ('project-plan', 'pp-token'),
                               ('earth', 'ev-token'), ('sales-map', 'sm-token'), ('route', 'sm-token'),
                               ('flat360', 'f360-token'), ('quot', 'quote-token')):
                if key in r:
                    return value
            return 'bm-token'
        raise KeyError(f'no seed for <{name}> in {rule}')

    for conv, name in re.findall(r'<(?:(\w+):)?(\w+)>', rule):
        path = re.sub(r'<(?:\w+:)?' + re.escape(name) + '>', str(pick(name)), path, count=1)
    return path


def generic_body(world):
    w = world
    return {
        'name': 'Unit Test Name', 'title': 'Unit Title', 'description': 'desc', 'label': 'Label',
        'status': 'available', 'area': '1000', 'price': '10L', 'color': '#123456',
        'points': [[0.1, 0.1], [0.2, 0.1], [0.2, 0.2]], 'path_points': [{'x': 0.1, 'y': 0.1}, {'x': 0.2, 'y': 0.2}],
        'longitude': 10.0, 'latitude': 5.0, 'x_ratio': 0.3, 'y_ratio': 0.4,
        'workspace_id': w.ws['id'], 'panorama_id': w.pano['id'], 'plot_id': w.plot['id'],
        'user_id': w.users['user'], 'target_user_id': w.users['user'], 'email': 'someone@example.test',
        'role': 'user', 'access_type': 'view', 'member_role': 'member', 'display_name': 'Some One',
        'customer_name': 'Buyer', 'customer_email': 'buyer@example.test', 'customer_phone': '9876543210',
        'full_name': 'Buyer', 'phone': '9876543210', 'plots': [{'id': w.plot['id'], 'name': 'A-1'}],
        'stage': 'negotiation', 'lead_status': 'contacted', 'amount': '100', 'currency': 'INR',
        'client_id': w.client_group['id'], 'org_id': w.org['id'], 'ids': [w.pano['id']],
        'panorama_ids': [w.pano['id']], 'user_ids': [w.users['user']], 'items': [], 'order': [],
        'value': 'Website', 'field_key': 'lead_source', 'is_enabled': True, 'enabled': True,
        'tab_type': 'content', 'content_data': {'html': '<p>x</p>'}, 'is_visible': True, 'icon': 'info',
        'style': {'accent': '#000000'}, 'endpoint': 'unit-endpoint', 'message': 'hello', 'notes': 'note',
        'locked_for_name': 'Buyer', 'locked_for_email': 'buyer@example.test', 'start_view': {'yaw': 0},
        'is_published': True, 'main_panorama_id': w.pano['id'], 'zoom': 12, 'center_lng': 73.8, 'center_lat': 18.5,
        'floor_number': 2, 'link_type': 'floor_plan', 'marker_type': 'poi', 'line_width': 2,
        'join_positions': [0.5], 'drag_speed': 1, 'quote_payload': {'total': 1}, 'template_payload': {'rows': []},
        'password': 'Sup3r-Secret-Pass!', 'new_password': 'Sup3r-Secret-Pass!', 'url': 'https://maps.app.goo.gl/x',
        'grants': [], 'members': [], 'sort_order': 1, 'project_type': 'plotted', 'location': 'Pune',
    }


@pytest.mark.parametrize('rule,method', _rules(), ids=lambda v: str(v))
def test_route_never_crashes(world, rule, method):
    if (rule, method) in EXTERNAL:
        pytest.skip('needs the internet')
    path = resolve(world, rule)
    body = generic_body(world) if method != 'GET' else None
    failures = []
    for role in ROLES:
        try:
            resp = world.open(method, path, as_=role, json=body)
        except Exception as exc:  # TESTING propagates unhandled exceptions
            failures.append(f'{role}: {type(exc).__name__}: {exc}')
            continue
        if resp.status_code >= 500:
            failures.append(f'{role}: HTTP {resp.status_code} {resp.get_data(as_text=True)[:300]}')
    assert not failures, f'{method} {path}\n' + '\n'.join(failures)
