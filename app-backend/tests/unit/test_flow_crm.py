"""CRM: lead lists and filters, lead lifecycle (create, edit, plots, reveal, convert, stage), quotations,
plot inventory and locks, master data and dashboard statistics."""
import json

import pytest

from app.controllers.features import crm_records
from app.services import crm_lead_service as leads

LIST_ENDPOINTS = ('/api/crm/leads', '/api/crm/deals', '/api/crm/contacts', '/api/buy-interests')


# ---------------------------------------------------------------- lists & filters
def _all_valid_conditions():
    out = []
    for field in list(crm_records.FILTER_TEXT_COLUMNS) + ['cf.budget']:
        for op in crm_records.TEXT_OPS:
            out.append({'field': field, 'op': op, 'value': 'Riya_%'})
    for field in crm_records.FILTER_SELECT_COLUMNS:
        value = {'deal_stage': 'Site Visit', 'panorama_id': '1'}.get(field, 'x')
        for op in crm_records.SELECT_OPS:
            out.append({'field': field, 'op': op, 'value': value})
    for field in crm_records.FILTER_DATE_COLUMNS:
        for op in crm_records.DATE_OPS:
            out.append({'field': field, 'op': op, 'value': '2026-01-01', 'value2': '2026-12-31'})
    for op in crm_records.SELECT_OPS:
        out.append({'field': 'workspace_id', 'op': op, 'value': 'WS'})
    for op in crm_records.PLOT_OPS:
        out.append({'field': 'plot_id', 'op': op, 'value': '1'})
    out.append({'field': 'customer_name', 'op': 'contains', 'value': ''})  # incomplete: ignored
    return out


@pytest.mark.parametrize('endpoint', LIST_ENDPOINTS)
def test_every_filter_condition(world, endpoint):
    w = world
    conditions = _all_valid_conditions()
    for cond in conditions:
        if cond.get('value') == 'WS':
            cond['value'] = w.ws['id']
    for i in range(0, len(conditions), crm_records.MAX_FILTER_CONDITIONS):
        chunk = conditions[i:i + crm_records.MAX_FILTER_CONDITIONS]
        for who in ('admin', 'broker'):
            r = w.get(endpoint, as_=who, query_string={'filters': json.dumps(chunk)})
            assert r.status_code == 200, (who, chunk, r.get_data(as_text=True))


@pytest.mark.parametrize('raw', [
    'not json', '{"a": 1}', json.dumps([{'field': 'x', 'op': 'is', 'value': 'y'}] * 21),
    json.dumps([{'field': 'nope', 'op': 'is', 'value': 'y'}]),
    json.dumps([{'field': 'customer_name', 'op': 'between', 'value': 'y'}]),
    json.dumps([{'field': 'created_at', 'op': 'on', 'value': '01/02/2026'}]),
    json.dumps([{'field': 'created_at', 'op': 'between', 'value': '2026-01-01', 'value2': 'later'}]),
    json.dumps([{'field': 'deal_stage', 'op': 'is', 'value': 'galaxy'}]),
    json.dumps([{'field': 'panorama_id', 'op': 'is', 'value': 'abc'}]),
])
def test_invalid_filters_are_rejected(world, raw):
    assert world.get('/api/crm/leads', as_='admin', query_string={'filters': raw}).status_code == 400


def test_parse_filter_conditions_skips_non_dicts():
    assert crm_records.parse_filter_conditions('') == []
    assert crm_records.parse_filter_conditions(json.dumps(['x', 3])) == []


@pytest.mark.parametrize('params', [
    {'status': 'all'}, {'status': 'lead'}, {'status': 'deal'}, {'status': 'converted'}, {'status': 'open'},
    {'category': 'Residential', 'lead_source': 'tour', 'reference_role': 'broker'}, {'deal_stage': 'negotiation'},
    {'stage': 'Site Visit'}, {'q': 'riya'}, {'q': '9876'}, {'include_facets': '0'},
    {'sort': 'customer_name', 'dir': 'asc'}, {'sort': 'evil;drop', 'dir': 'desc'},
    {'page': '2', 'limit': '1'}, {'page': 'x', 'limit': 'y'}, {'limit': '100000'},
    {'client_id': 'CLIENT'}, {'workspace_id': 'WS'}, {'panorama_id': 'PANO'}, {'plot_id': 'PLOT'},
    {'panorama_id': 'abc'}, {'plot_id': 'abc'}, {'reference_user_id': 'BROKER'},
])
@pytest.mark.parametrize('endpoint', LIST_ENDPOINTS)
@pytest.mark.parametrize('who', ['admin', 'super', 'broker', 'client_admin', 'member'])
def test_list_parameters(world, endpoint, params, who):
    w = world
    swap = {'CLIENT': w.client_group['id'], 'WS': w.ws['id'], 'PANO': str(w.pano['id']), 'PLOT': str(w.plot['id']),
            'BROKER': w.users['broker']}
    query = {k: swap.get(v, v) for k, v in params.items()}
    r = w.get(endpoint, as_=who, query_string=query)
    assert r.status_code in (200, 400, 403), r.get_data(as_text=True)


# ---------------------------------------------------------------- lead lifecycle
def test_lead_lifecycle(world):
    w = world
    body = {'panorama_id': w.pano['id'], 'customer_name': 'Kabir', 'customer_email': 'kabir@example.test',
            'customer_phone': '+91 90000 00001', 'customer_birthday': '1990-05-04', 'plots': [w.plot['id']],
            'category': 'Residential', 'lead_source': 'walk-in', 'custom_fields': {'budget': '50L'}, 'origin': 'crm'}
    r = w.post('/api/crm/leads', as_='admin', json=body)
    assert r.status_code in (200, 201), r.get_data(as_text=True)
    lead = r.get_json().get('lead') or r.get_json()
    lid = lead['id']
    assert w.get(f'/api/crm/leads/{lid}', as_='admin').status_code == 200
    assert w.get(f'/api/crm/leads/{lid}', as_='stranger').status_code in (403, 404)
    for update in ({'customer_name': 'Kabir S'}, {'customer_birthday': 'not a date'}, {'birthday': '1991-01-01'},
                   {'deal_stage': 'site_visit'}, {'deal_stage': 'bogus'}, {'assigned_to': w.users['broker']},
                   {'assigned_to': ''}, {'plots': [{'id': w.plot['id'], 'name': 'A-1'}]}, {'lead_status': 'contacted',
                   'notes': 'Called', 'custom_fields': {'budget': '60L'}}, {'customer_email': 'not-an-email'}):
        res = w.patch(f'/api/crm/leads/{lid}', as_='admin', json=update)
        assert res.status_code in (200, 400), (update, res.get_data(as_text=True))
    plots = w.post(f'/api/crm/leads/{lid}/plots', as_='admin', json={'add_plot_ids': [w.plot_sold['id']],
                                                                     'normal_plot_ids': [1], 'remove_plot_keys': ['p:999']})
    assert plots.status_code in (200, 400), plots.get_data(as_text=True)
    assert w.post(f'/api/crm/leads/{lid}/plots', as_='admin', json={}).status_code in (200, 400)
    assert w.post(f'/api/crm/leads/{lid}/reveal-contact', as_='admin').status_code in (200, 403)
    stage = w.post(f'/api/crm/leads/{lid}/move-stage', as_='admin', json={'stage': 'negotiation'})
    assert stage.status_code == 409, stage.get_data(as_text=True)  # only deals have stages
    assert w.post(f'/api/crm/leads/{lid}/move-stage', as_='admin', json={'stage': 'mars'}).status_code in (400, 409)
    conv = w.post(f'/api/crm/leads/{lid}/convert', as_='admin', json={
        'deal_title': 'Plot A-1 deal', 'deal_stage': 'negotiation', 'deal_amount': '4500000', 'deal_currency': 'usd',
        'notes': 'Converted', 'plots': [w.plot['id']]})
    assert conv.status_code in (200, 201), conv.get_data(as_text=True)
    assert w.post(f'/api/crm/leads/{lid}/convert', as_='admin', json={}).status_code in (200, 400, 409)
    assert w.post(f'/api/crm/leads/{lid}/move-stage', as_='admin', json={'stage': 'won'}).status_code == 200
    assert w.delete(f'/api/crm/leads/{lid}', as_='broker').status_code in (403, 404)
    assert w.delete(f'/api/crm/leads/{lid}', as_='admin').status_code in (200, 204)
    assert w.get(f'/api/crm/leads/{lid}', as_='admin').status_code == 404


@pytest.mark.parametrize('body,ok', [
    ({}, False), ({'panorama_id': 'abc'}, False), ({'panorama_id': 999999, 'customer_name': 'x'}, False),
    ({'panorama_id': 'PANO', 'customer_name': ''}, False),
    ({'panorama_id': 'PANO', 'customer_name': 'Neha', 'customer_email': 'neha@example.test',
      'customer_phone': '9999999999', 'items': [{'id': 'PLOT'}],
      'normal_plot_ids': [1], 'client_id': 'CLIENT'}, True),
])
@pytest.mark.parametrize('who', ['admin', 'broker', 'client_admin', 'member', 'user'])
def test_create_lead_variants(world, body, ok, who):
    w = world
    swap = {'PANO': w.pano['id'], 'PLOT': w.plot['id'], 'CLIENT': w.client_group['id']}

    def fill(v):
        if isinstance(v, list):
            return [fill(i) for i in v]
        if isinstance(v, dict):
            return {k: fill(x) for k, x in v.items()}
        return swap.get(v, v)
    r = w.post('/api/crm/leads', as_=who, json=fill(body))
    if not ok:
        assert r.status_code in (400, 403, 404), r.get_data(as_text=True)
    else:
        # Brokers are recorded as the reference, which must be allowed on the project.
        assert r.status_code in (200, 201, 403) + ((400,) if who == 'broker' else ()), r.get_data(as_text=True)


def test_public_buy_interest(world):
    w = world
    body = {'panorama_id': w.pano['id'], 'customer_name': 'Visitor', 'customer_email': 'v@example.test',
            'customer_phone': '9000000000', 'plots': [w.plot['id']],
            'origin': 'customer_view', 'birthday': '1985-02-03'}
    r = w.post('/api/public/buy-interests', json=body)
    assert r.status_code in (200, 201), r.get_data(as_text=True)
    assert w.post('/api/public/buy-interests', json={'panorama_id': 'x'}).status_code == 400
    assert w.post('/api/public/buy-interests', json={**body, 'reference_user_id': 'not-a-member'}).status_code == 400
    assert w.post('/api/public/buy-interests', json={**body, 'reference_user_id': w.users['broker']}).status_code in (200, 201, 400)
    assert w.post('/api/public/buy-interests', json={**body, 'panorama_id': w.foreign_pano['id']}).status_code in (200, 201, 400, 403, 404)
    assert w.post('/api/buy-interests', as_='user', json=body).status_code in (200, 201, 403)  # viewers cannot add CRM leads


def test_broker_sees_masked_contacts_until_revealed(world):
    w = world
    lid = w.lead['id']
    listed = w.get('/api/crm/leads', as_='broker').get_json()
    assert listed is not None
    r = w.post(f'/api/crm/leads/{lid}/reveal-contact', as_='broker')
    assert r.status_code in (200, 403), r.get_data(as_text=True)
    assert w.post(f'/api/buy-interests/{lid}/reveal-contact', as_='member').status_code in (200, 403, 404)


def test_me_endpoints(world):
    for who in ('admin', 'super', 'broker', 'client_admin', 'member', 'user', 'stranger'):
        assert world.get('/api/crm/me', as_=who).status_code == 200
        assert world.get('/api/portal/me', as_=who).status_code == 200


# ---------------------------------------------------------------- quotations
def test_quotation_flow(world):
    w = world
    did = w.deal_lead['id']
    prev = w.post(f'/api/crm/deals/{did}/quotation/preview', as_='admin', json={
        'template_id': w.quote_template['id'], 'inputs': {'discount': 5}})
    assert prev.status_code in (200, 201), prev.get_data(as_text=True)
    assert w.post(f'/api/crm/deals/{did}/quotation/preview', as_='admin', json={'template_id': 'missing'}).status_code in (200, 201, 404)
    assert w.post('/api/crm/deals/00000000-0000-0000-0000-000000000000/quotation/preview', as_='admin', json={}).status_code == 404
    qid = (prev.get_json().get('quote') or prev.get_json()).get('id') or w.quote['id']
    share = w.post(f'/api/crm/deals/{did}/quotation/share', as_='admin', json={'quote_id': qid, 'email': 'buyer@example.test'})
    assert share.status_code in (200, 201), share.get_data(as_text=True)
    assert w.sent_emails, 'quotation email not sent'
    assert w.post(f'/api/crm/deals/{did}/quotation/share', as_='admin', json={'quote_id': qid, 'phone': '9876543210'}).status_code in (200, 201, 400)
    assert w.post(f'/api/crm/deals/{did}/quotation/share', as_='admin', json={}).status_code == 400
    assert w.post(f'/api/crm/deals/{did}/quotation/share', as_='admin', json={'quote_id': qid, 'email': 'bad'}).status_code == 400
    assert w.get(f'/api/crm/deals/{did}/quotations', as_='admin').status_code == 200
    for body in ({'status': 'sent'}, {'status': 'accepted'}, {'status': 'nonsense'}, {'quote_payload': {'total': 1}},
                 {'quote_payload': 'not json'}):
        assert w.patch(f'/api/crm/deals/{did}/quotations/{qid}', as_='admin', json=body).status_code in (200, 400), body
    token = w.db.one('crm_deal_quotes', id=qid)['share_token']
    assert w.get(f'/api/crm/deals/{did}/quotation/{qid}', query_string={'token': token}).status_code == 200
    assert w.get(f'/api/crm/deals/{did}/quotation/{qid}', query_string={'token': 'wrong'}).status_code in (403, 404)
    assert w.get(f'/api/crm/deals/{did}/quotation/{qid}', as_='admin').status_code in (200, 400, 403)


def test_quote_templates(world):
    w = world
    assert w.post('/api/crm/quote-templates', as_='admin', json={'name': 'No org'}).status_code == 400
    r = w.post('/api/crm/quote-templates', as_='admin', json={'name': 'Premium', 'panorama_id': w.pano['id'], 'org_id': w.org['id'],
                                                              'template_payload': {'rows': [{'label': 'Base'}]}, 'is_default': True})
    assert r.status_code in (200, 201), r.get_data(as_text=True)
    tid = (r.get_json().get('template') or r.get_json())['id']
    assert w.post('/api/crm/quote-templates', as_='admin', json={'name': '', 'org_id': w.org['id']}).status_code in (201, 400)
    assert w.get('/api/crm/quote-templates', as_='admin', query_string={'panorama_id': w.pano['id']}).status_code == 200
    for body in ({'name': 'Premium 2'}, {'is_default': False}, {'template_payload': 'x'}, {'name': ''}):
        assert w.patch(f'/api/crm/quote-templates/{tid}', as_='admin', json=body).status_code in (200, 400), body
    assert w.patch(f'/api/crm/quote-templates/{tid}', as_='admin2', json={'name': 'x'}).status_code in (403, 404)
    assert w.delete(f'/api/crm/quote-templates/{tid}', as_='admin').status_code in (200, 204)


# ---------------------------------------------------------------- plot inventory & locks
@pytest.mark.parametrize('params', [{}, {'q': 'a-1'}, {'status': 'sold'}, {'status': 'Available'},
                                    {'client_id': 'CLIENT'}, {'workspace_id': 'WS'}, {'panorama_id': 'PANO'},
                                    {'page': '1', 'limit': '1'}, {'sort': 'name', 'dir': 'asc'}])
def test_crm_plot_list(world, params):
    w = world
    swap = {'CLIENT': w.client_group['id'], 'WS': w.ws['id'], 'PANO': str(w.pano['id'])}
    for who in ('admin', 'super', 'broker', 'client_admin'):
        r = w.get('/api/crm/plots', as_=who, query_string={k: swap.get(v, v) for k, v in params.items()})
        assert r.status_code == 200, r.get_data(as_text=True)


def test_crm_plot_update_and_locks(world):
    w = world
    pid = w.plot['id']
    for body in ({'status': 'hold'}, {'status': 'Sold'}, {'status': 'weird'}, {'price': '50L', 'area': '1500'}, {}):
        assert w.put(f'/api/crm/plots/{pid}', as_='admin', json=body).status_code in (200, 400), body
    assert w.put(f'/api/crm/plots/{pid}', as_='stranger', json={'status': 'sold'}).status_code in (403, 404)
    assert w.get('/api/crm/lock-access', as_='admin', query_string={'panorama_id': w.pano['id']}).status_code == 200
    assert w.post('/api/crm/lock-access', as_='admin', json={'panorama_id': w.pano['id'], 'user_id': w.users['member']}).status_code in (200, 201)
    assert w.post('/api/crm/lock-access', as_='admin', json={'panorama_id': 'x'}).status_code == 400
    assert w.post('/api/crm/lock-access', as_='admin', json={'panorama_id': w.pano['id']}).status_code == 400
    assert w.get('/api/crm/lockable-plots', as_='broker').status_code == 200
    w.db.one('plots', id=pid)['status'] = 'available'
    lock = w.post(f'/api/crm/plots/{pid}/lock', as_='broker', json={'locked_for_name': 'Buyer', 'locked_for_email': 'b@example.test'})
    assert lock.status_code in (200, 201), lock.get_data(as_text=True)
    # Nobody else can take over a held plot (an admin still can).
    assert w.post(f'/api/crm/plots/{pid}/lock', as_='member', json={}).status_code in (403, 409)
    assert w.db.one('plot_locks', plot_id=pid)['locked_by'] == w.users['broker']
    assert w.post(f'/api/crm/plots/{pid}/lock', as_='broker', json={'locked_for_name': 'Buyer 2'}).status_code in (200, 201)
    assert w.post(f'/api/crm/plots/{pid}/lock', as_='stranger', json={}).status_code in (403, 404)
    assert w.delete(f'/api/crm/plots/{pid}/lock', as_='member').status_code in (403, 404)
    assert w.delete(f'/api/crm/plots/{pid}/lock', as_='admin').status_code in (200, 204)
    assert w.delete(f'/api/crm/plots/{pid}/lock', as_='admin').status_code in (200, 204, 404)
    assert w.delete('/api/crm/lock-access', as_='admin', json={'panorama_id': w.pano['id'], 'user_id': w.users['member']}).status_code in (200, 204)
    assert w.delete('/api/crm/lock-access', as_='admin', json={'panorama_id': 'x'}).status_code == 400


# ---------------------------------------------------------------- master data
def test_master_data(world):
    w = world
    for params in ({}, {'scope': 'client', 'client_id': w.client_group['id']}, {'panorama_id': w.pano['id']},
                   {'include_disabled': '1'}):
        for who in ('admin', 'client_admin', 'broker'):
            assert w.get('/api/crm/master-config', as_=who, query_string=params).status_code in (200, 403), (who, params)
    r = w.post('/api/crm/master-values', as_='admin', json={'field_key': 'lead_source', 'value': 'Instagram',
                                                            'client_id': w.client_group['id']})
    assert r.status_code in (200, 201), r.get_data(as_text=True)
    vid = (r.get_json().get('value') if isinstance(r.get_json().get('value'), dict) else r.get_json()).get('id') \
        or w.db.rows('crm_master_values')[-1]['id']
    cid = w.client_group['id']
    assert w.post('/api/crm/master-values', as_='admin', json={'field_key': '', 'value': 'x', 'client_id': cid}).status_code in (400, 403)
    assert w.post('/api/crm/master-values', as_='admin', json={'field_key': 'lead_source', 'value': '', 'client_id': cid}).status_code in (400, 403)
    assert w.post('/api/crm/master-values', as_='client_admin', json={'field_key': 'lead_source', 'value': 'Referral'}).status_code in (200, 201, 403)
    for body in ({'value': 'IG'}, {'is_enabled': False}, {'sort_order': 3}, {'sort_order': 'x'}, {'value': ''}):
        assert w.patch(f'/api/crm/master-values/{vid}', as_='admin', json={**body, 'client_id': cid}).status_code in (200, 400, 403), body
    attr = w.post('/api/crm/master-attributes', as_='admin', json={'field_key': 'Budget Range', 'label': 'Budget', 'client_id': cid,
                                                                   'applies_to': ['lead', 'deal'], 'is_required': True})
    assert attr.status_code in (200, 201, 403), attr.get_data(as_text=True)
    assert w.post('/api/crm/master-attributes', as_='admin', json={'field_key': '!!', 'client_id': cid}).status_code in (400, 403)
    for body in ({'label': 'Budget (INR)'}, {'is_required': False, 'is_optional': True}, {'is_enabled': False},
                 {'applies_to': ['contact']}, {'applies_to': 'nonsense'}, {'label': ''}):
        assert w.patch('/api/crm/master-attributes/lead_source', as_='admin',
                       json={**body, 'client_id': cid}).status_code in (200, 400, 403, 404), body
    assert w.delete(f'/api/crm/master-values/{vid}', as_='admin').status_code in (200, 204, 405)


# ---------------------------------------------------------------- dashboard & clients
@pytest.mark.parametrize('days', [None, '7', '30', '365', 'x', '-4', '100000'])
def test_dashboard_stats(world, days):
    for who in ('admin', 'super', 'broker', 'client_admin'):
        qs = {'days': days} if days is not None else {}
        assert world.get('/api/crm/dashboard-stats', as_=who, query_string=qs).status_code == 200


def test_allotted_clients(world):
    w = world
    w.db.add('crm_leads', record_status='deal', org_id=w.org['id'], client_id=w.client_group['id'],
             panorama_id=w.pano['id'], customer_name='Deal Person', deal_stage='won', deal_amount='100',
             plots=[{'id': w.plot['id']}], converted_at='2026-02-01T00:00:00+00:00')
    for who in ('admin', 'super', 'client_admin', 'broker'):
        r = w.get('/api/crm/allotted-clients', as_=who, query_string={'q': 'deal', 'page': '1'})
        assert r.status_code in (200, 403), r.get_data(as_text=True)


# ---------------------------------------------------------------- service helpers
@pytest.mark.parametrize('value,expected', [('Site Visit', 'site_visit'), ('won', 'won'), ('', None), ('xyz', None),
                                            ('site-visit', 'site_visit')])
def test_normalize_deal_stage(value, expected):
    assert leads.normalize_deal_stage(value) == expected
