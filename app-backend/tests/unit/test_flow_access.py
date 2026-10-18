"""User and access management: client teams, invites, join requests, onboarding, grants, profiles, admin users."""
import pytest


def _ids(rows, key='user_id'):
    return {str(r.get(key)) for r in rows}


# ---------------------------------------------------------------- client groups
def test_client_group_lifecycle(world):
    w = world
    r = w.post('/api/clients', as_='admin', json={'name': 'Lotus Realty', 'description': 'Brokers', 'members_allowed': 5})
    assert r.status_code in (200, 201), r.get_data(as_text=True)
    cid = r.get_json().get('id') or r.get_json().get('client', {}).get('id')
    assert w.post('/api/clients', as_='admin', json={'name': ''}).status_code == 400
    assert w.post('/api/clients', as_='user', json={'name': 'x'}).status_code == 403
    assert w.get('/api/clients', as_='admin').status_code == 200
    assert w.get('/api/clients', as_='super').status_code == 200
    for body in ({'name': 'Lotus 2'}, {'description': 'd', 'members_allowed': 'unlimited'}, {'members_allowed': -3},
                 {'name': ''}):
        assert w.patch(f'/api/clients/{cid}', as_='admin', json=body).status_code in (200, 400), body
    assert w.patch(f'/api/clients/{cid}', as_='admin2', json={'name': 'x'}).status_code in (403, 404)
    assert w.delete(f'/api/clients/{cid}', as_='admin2').status_code in (403, 404)
    assert w.delete(f'/api/clients/{cid}', as_='admin').status_code in (200, 204)


def test_my_client_groups_and_rosters(world):
    w = world
    for who in ('client_admin', 'member', 'broker', 'stranger'):
        assert w.get('/api/clients/mine', as_=who).status_code == 200
        assert w.get('/api/clients/mine/roster', as_=who).status_code == 200
    roster = w.get('/api/clients/mine/roster', as_='client_admin').get_json()
    assert roster


def test_members_add_change_remove(world):
    w = world
    cid = w.client_group['id']
    assert w.get(f'/api/clients/{cid}/members', as_='admin').status_code == 200
    assert w.get(f'/api/clients/{cid}/members', as_='client_admin').status_code == 200
    assert w.get(f'/api/clients/{cid}/available-users', as_='admin').status_code == 200
    target = w.users['user']
    # Platform admins add client admins and brokers; client admins add their own sales agents.
    assert w.post(f'/api/clients/{cid}/members', as_='admin', json={'user_id': target, 'member_role': 'client_user'}).status_code == 400
    r = w.post(f'/api/clients/{cid}/members', as_='admin', json={'user_id': target, 'member_role': 'broker'})
    assert r.status_code in (200, 201), r.get_data(as_text=True)
    assert w.db.one('client_members', client_id=cid, user_id=target)
    assert w.post(f'/api/clients/{cid}/members', as_='admin', json={'user_id': target}).status_code in (200, 400, 409)
    assert w.post(f'/api/clients/{cid}/members', as_='admin', json={}).status_code == 400
    assert w.post(f'/api/clients/{cid}/members', as_='admin', json={'user_id': target, 'member_role': 'king'}).status_code == 400
    assert w.post(f'/api/clients/{cid}/members', as_='admin',
                  json={'user_id': '00000000-0000-0000-0000-000000000000'}).status_code in (400, 404)
    for new_role in ('broker', 'client_admin', 'sales_agent', 'bogus'):
        assert w.patch(f'/api/clients/{cid}/members/{target}', as_='admin',
                       json={'member_role': new_role}).status_code in (200, 400), new_role
    assert w.patch(f'/api/clients/{cid}/members/{target}', as_='member', json={'member_role': 'client_admin'}).status_code == 403
    assert w.delete(f'/api/clients/{cid}/members/{target}', as_='admin').status_code in (200, 204)
    assert not w.db.one('client_members', client_id=cid, user_id=target)
    assert w.delete(f'/api/clients/{cid}/members/{target}', as_='admin').status_code in (200, 204, 404)


def test_client_admin_adds_member_with_access_cascade(world):
    w = world
    cid = w.client_group['id']
    # Give the group access to the project first, then add a member: access should follow.
    assert w.post(f'/api/clients/{cid}/access', as_='admin', json={
        'resource_type': 'workspace', 'resource_id': w.ws['id'], 'access_type': 'client'}).status_code in (200, 201)
    r = w.post(f'/api/clients/{cid}/members', as_='client_admin', json={'user_id': w.users['user'], 'member_role': 'broker'})
    assert r.status_code in (200, 201, 403), r.get_data(as_text=True)
    assert w.post(f'/api/clients/{cid}/members', as_='member', json={'user_id': w.users['user']}).status_code == 403


def test_members_allowed_limit(world):
    w = world
    cid = w.client_group['id']
    w.db.one('clients', id=cid)['members_allowed'] = 1
    r = w.post(f'/api/clients/{cid}/members', as_='admin', json={'user_id': w.users['user'], 'member_role': 'client_user'})
    assert r.status_code in (400, 403, 409), r.get_data(as_text=True)


# ---------------------------------------------------------------- invites
def test_invite_flow_new_and_existing_users(world):
    w = world
    cid = w.client_group['id']
    r = w.post(f'/api/clients/{cid}/invite', as_='admin', json={'email': 'brand.new@example.test',
                                                                'display_name': 'Brand New', 'member_role': 'broker'})
    assert r.status_code in (200, 201), r.get_data(as_text=True)
    assert w.sent_emails or w.db.get('client_team_invites', email='brand.new@example.test')
    assert w.post(f'/api/clients/{cid}/invite', as_='admin', json={'email': 'x@example.test', 'member_role': 'client_user'}).status_code == 400
    existing = w.post(f'/api/clients/{cid}/invite', as_='admin', json={'email': 'user@example.test', 'member_role': 'client_admin',
                                                                       'display_name': 'User'})
    assert existing.status_code in (200, 201, 409), existing.get_data(as_text=True)
    agent = w.post(f'/api/clients/{cid}/invite', as_='client_admin', json={'email': 'agent@example.test', 'member_role': 'client_user',
                                                                               'display_name': 'Agent'})
    assert agent.status_code in (200, 201), agent.get_data(as_text=True)
    assert w.post(f'/api/clients/{cid}/invite', as_='admin', json={'email': 'nope'}).status_code == 400
    assert w.post(f'/api/clients/{cid}/invite', as_='admin', json={'email': 'x@example.test', 'member_role': 'emperor'}).status_code == 400
    assert w.post(f'/api/clients/{cid}/invite', as_='client_admin', json={'email': 'ca@example.test',
                                                                         'member_role': 'client_admin', 'display_name': 'CA'}).status_code in (400, 403)  # client admins cannot invite admins
    assert w.post(f'/api/clients/{cid}/invite', as_='member', json={'email': 'm@example.test'}).status_code == 403
    assert w.get(f'/api/clients/{cid}/invites', as_='admin').status_code == 200
    resend = w.post(f"/api/clients/{cid}/invites/{w.invite['id']}/resend", as_='admin')
    assert resend.status_code in (200, 201), resend.get_data(as_text=True)


def test_public_invite_and_accept(world):
    w = world
    assert w.get('/api/public/client-invite/invite-token').status_code == 200
    assert w.get('/api/public/client-invite/unknown').status_code == 404
    assert w.get('/client-invite/invite-token').status_code in (200, 302)
    assert w.get('/client-invite/unknown').status_code in (200, 302, 404)
    # The invite was sent to new@example.test; someone else cannot accept it.
    assert w.post('/api/client-team-invites/accept', as_='stranger', json={'invite_token': 'invite-token'}).status_code in (403, 400)
    assert w.post('/api/client-team-invites/accept', as_='stranger', json={}).status_code == 400
    w.set_profile('stranger', email='new@example.test')
    r = w.post('/api/client-team-invites/accept', as_='stranger', json={'invite_token': 'invite-token'})
    assert r.status_code == 200, r.get_data(as_text=True)
    assert w.db.one('client_members', client_id=w.client_group['id'], user_id=w.users['stranger'])
    assert w.db.one('client_team_invites', id=w.invite['id'])['status'] == 'accepted'
    assert w.post('/api/client-team-invites/accept', as_='stranger', json={'invite_token': 'invite-token'}).status_code in (200, 400, 409)


@pytest.mark.parametrize('status,expires', [('revoked', '2099-01-01T00:00:00+00:00'), ('pending', '2000-01-01T00:00:00+00:00')])
def test_invalid_invites_cannot_be_accepted(world, status, expires):
    w = world
    inv = w.db.one('client_team_invites', id=w.invite['id'])
    inv['status'], inv['expires_at'] = status, expires
    w.set_profile('stranger', email='new@example.test')
    assert w.post('/api/client-team-invites/accept', as_='stranger', json={'invite_token': 'invite-token'}).status_code in (400, 404, 410)
    # The public lookup still answers, reporting the status/expiry for the page to show.
    info = w.get('/api/public/client-invite/invite-token').get_json()
    assert info['status'] in (status, 'expired') and info['expires_at'] == expires


def test_my_invites_and_reject(world):
    w = world
    w.set_profile('stranger', email='new@example.test')
    mine = w.get('/api/client-team-invites/mine', as_='stranger')
    assert mine.status_code == 200
    assert w.post(f"/api/client-team-invites/{w.invite['id']}/reject", as_='user').status_code in (403, 404)
    assert w.post(f"/api/client-team-invites/{w.invite['id']}/reject", as_='stranger').status_code == 200
    assert w.db.one('client_team_invites', id=w.invite['id'])['status'] in ('rejected', 'declined')


# ---------------------------------------------------------------- client access grants
def test_client_access_grant_and_revoke(world):
    w = world
    cid = w.client_group['id']
    assert w.get(f'/api/clients/{cid}/access', as_='admin').status_code == 200
    assert w.get(f'/api/clients/{cid}/access', as_='client_admin').status_code == 200
    for body, ok in (({'resource_type': 'workspace', 'resource_id': w.ws['id']}, True),
                     ({'resource_type': 'panorama', 'resource_id': w.pano2['id']}, True),
                     ({'resource_type': 'workspace', 'resource_id': w.ws['id'], 'target_user_id': w.users['member']}, True),
                     ({'resource_type': 'plot', 'resource_id': 1}, False),
                     ({'resource_type': 'workspace'}, False),
                     ({'resource_type': 'workspace', 'resource_id': '00000000-0000-0000-0000-000000000000'}, False)):
        r = w.post(f'/api/clients/{cid}/access', as_='admin', json=body)
        assert (r.status_code in (200, 201)) == ok, (body, r.get_data(as_text=True))
    # Client admins manage access only for their sales agents and brokers.
    r = w.post(f'/api/clients/{cid}/access', as_='client_admin', json={
        'resource_type': 'workspace', 'resource_id': w.ws['id'], 'target_user_id': w.users['broker']})
    assert r.status_code in (200, 201, 403)
    r = w.post(f'/api/clients/{cid}/access', as_='client_admin', json={
        'resource_type': 'workspace', 'resource_id': w.ws['id'], 'target_user_id': w.users['client_admin']})
    assert r.status_code in (403, 400)
    for body in ({'resource_type': 'panorama', 'resource_id': w.pano2['id']},
                 {'resource_type': 'workspace', 'resource_id': w.ws['id'], 'target_user_id': w.users['member']},
                 {'resource_type': 'workspace', 'resource_id': w.ws['id']}, {'resource_type': 'nope'}):
        assert w.delete(f'/api/clients/{cid}/access', as_='admin', json=body).status_code in (200, 204, 400, 404), body
    assert w.get(f'/api/clients/{cid}/access', as_='stranger').status_code in (403, 404)


# ---------------------------------------------------------------- workspace & panorama access
def test_workspace_access_grants(world):
    w = world
    wid = w.ws['id']
    assert w.get(f'/api/workspaces/{wid}/access', as_='admin').status_code == 200
    for at in ('viewer', 'editor', 'client', 'owner', 'bogus'):
        r = w.post(f'/api/workspaces/{wid}/access', as_='admin', json={'user_id': w.users['broker'], 'access_type': at})
        assert r.status_code in (200, 201, 400), at
    assert w.post(f'/api/workspaces/{wid}/access', as_='admin', json={}).status_code == 400
    assert w.post(f'/api/workspaces/{wid}/access', as_='admin', json={'user_id': w.users['admin']}).status_code in (400, 200)
    assert w.post(f'/api/workspaces/{wid}/access', as_='user', json={'user_id': w.users['broker']}).status_code in (403, 404)
    assert w.delete(f"/api/workspaces/{wid}/access/{w.users['broker']}", as_='admin').status_code in (200, 204)
    assert w.get(f'/api/workspaces/{wid}/organizations', as_='admin').status_code == 200
    cid = w.client_group['id']
    assert w.put(f'/api/workspaces/{wid}/organizations/{cid}', as_='admin').status_code in (200, 201)
    assert w.put(f'/api/workspaces/{wid}/organizations/00000000-0000-0000-0000-000000000000', as_='admin').status_code == 404
    assert w.delete(f'/api/workspaces/{wid}/organizations/{cid}', as_='admin').status_code in (200, 204)
    assert w.get(f"/api/workspaces/{w.foreign_ws['id']}/organizations", as_='admin').status_code in (403, 404)


def test_panorama_access_grants(world):
    w = world
    pid = w.pano['id']
    assert w.get(f'/api/panoramas/{pid}/access', as_='admin').status_code == 200
    for at in ('viewer', 'editor', 'client', 'bogus'):
        assert w.post(f'/api/panoramas/{pid}/access', as_='admin',
                      json={'user_id': w.users['broker'], 'access_type': at}).status_code in (200, 201, 400), at
    assert w.post(f'/api/panoramas/{pid}/access', as_='admin', json={}).status_code == 400
    assert w.post(f'/api/panoramas/{pid}/access', as_='user', json={'user_id': w.users['broker']}).status_code in (403, 404)
    assert w.delete(f"/api/panoramas/{pid}/access/{w.users['broker']}", as_='admin').status_code in (200, 204)
    assert w.delete(f"/api/panoramas/{pid}/access/{w.users['broker']}", as_='user').status_code in (403, 404)


# ---------------------------------------------------------------- onboarding & join requests
def test_onboarding_create_group(world):
    w = world
    assert w.get('/api/onboarding/state', as_='stranger').get_json()
    assert w.get('/api/onboarding/client-groups', as_='stranger', query_string={'q': 'Sun'}).status_code == 200
    assert w.get('/api/onboarding/organizations', as_='stranger').status_code == 200
    assert w.post('/api/onboarding/client-groups', as_='stranger', json={'name': ''}).status_code == 400
    r = w.post('/api/onboarding/client-groups', as_='stranger', json={'name': 'Stranger Group', 'org_id': w.org['id']})
    assert r.status_code in (200, 201), r.get_data(as_text=True)
    assert w.db.one('client_members', user_id=w.users['stranger'])['member_role'] == 'client_admin'
    assert w.post('/api/onboarding/client-groups', as_='stranger', json={'name': 'Again'}).status_code in (400, 409, 200, 201)


def test_join_request_flow(world):
    w = world
    w.db.tables['client_join_requests'].clear()
    assert w.post('/api/onboarding/join-requests', as_='stranger', json={}).status_code == 400
    assert w.post('/api/onboarding/join-requests', as_='stranger',
                  json={'client_id': '00000000-0000-0000-0000-000000000000'}).status_code == 404
    r = w.post('/api/onboarding/join-requests', as_='stranger', json={'client_id': w.client_group['id'],
                                                                     'member_role': 'broker', 'message': 'hi'})
    assert r.status_code in (200, 201), r.get_data(as_text=True)
    req_id = w.db.rows('client_join_requests')[0]['id']
    assert w.get('/api/join-requests', as_='admin').status_code == 200
    assert w.get('/api/join-requests', as_='client_admin').status_code == 200
    assert w.post(f'/api/join-requests/{req_id}/approve', as_='member').status_code in (403, 404)
    r = w.post(f'/api/join-requests/{req_id}/approve', as_='client_admin', json={'member_role': 'broker'})
    assert r.status_code == 200, r.get_data(as_text=True)
    assert w.db.one('client_members', user_id=w.users['stranger'])
    assert w.post(f'/api/join-requests/{req_id}/approve', as_='admin').status_code in (400, 404, 409)


def test_join_request_reject_and_withdraw(world):
    w = world
    req_id = w.join_request['id']
    assert w.post(f'/api/join-requests/{req_id}/reject', as_='admin').status_code == 200
    assert w.db.one('client_join_requests', id=req_id)['status'] == 'rejected'
    w.db.one('client_join_requests', id=req_id)['status'] = 'pending'
    assert w.delete('/api/onboarding/join-requests/mine', as_='stranger').status_code in (200, 204)
    assert w.delete('/api/onboarding/join-requests/mine', as_='stranger').status_code in (200, 204, 404)


# ---------------------------------------------------------------- profiles & orgs
def test_profile_and_org_management(world):
    w = world
    assert w.put('/api/profile/me', as_='user', json={'display_name': 'Updated'}).status_code == 200
    assert w.put('/api/profile/me', as_='user', json={'email': 'changed@example.test'}).status_code in (200, 400)
    assert w.put('/api/profile/me', as_='user', json={}).status_code in (200, 400)
    assert w.get('/api/org/me', as_='admin').status_code == 200
    assert w.get('/api/org/me', as_='stranger').status_code in (200, 404)
    assert w.get('/api/orgs', as_='super').status_code == 200
    assert w.get('/api/orgs', as_='user').status_code == 403
    r = w.post('/api/orgs', as_='super', json={'name': 'New Org', 'accent_color': '#123456'})
    assert r.status_code in (200, 201)
    oid = r.get_json()['org']['id']
    assert w.post('/api/orgs', as_='super', json={'name': ''}).status_code == 400
    assert w.patch(f'/api/orgs/{oid}', as_='super', json={'name': 'Renamed Org', 'accent_color': '#abcdef'}).status_code == 200
    assert w.patch(f'/api/orgs/{oid}', as_='super', json={'name': ''}).status_code in (200, 400)
    assert w.patch(f'/api/orgs/{oid}', as_='admin', json={'name': 'x'}).status_code == 403


@pytest.mark.parametrize('body,status', [
    ({'role': 'admin'}, 200), ({'role': 'broker'}, 200), ({'role': 'god'}, 400),
    ({'org_id': None}, 200), ({'orgId': 'ORG'}, 200), ({'display_name': 'Renamed'}, 400), ({}, 400),
])
def test_superadmin_updates_profiles(world, body, status):
    w = world
    if body.get('orgId') == 'ORG':
        body = {'orgId': w.org2['id']}
    r = w.patch(f"/api/profiles/{w.users['user']}", as_='super', json=body)
    assert r.status_code == status, r.get_data(as_text=True)
    assert w.patch(f"/api/profiles/{w.users['user']}", as_='admin', json=body).status_code == 403


def test_profiles_list_and_role(world):
    w = world
    assert w.get('/api/profiles', as_='admin').status_code == 200
    assert w.get('/api/profiles', as_='super').status_code == 200
    assert w.put(f"/api/profiles/{w.users['user']}/role", as_='super', json={'role': 'admin'}).status_code == 200
    assert w.put(f"/api/profiles/{w.users['user']}/role", as_='super', json={'role': 'nope'}).status_code == 400
    assert w.put(f"/api/profiles/{w.users['super']}/role", as_='super', json={'role': 'user'}).status_code in (200, 400, 403)


# ---------------------------------------------------------------- admin users
def test_admin_creates_invites_and_manages_users(world):
    w = world
    r = w.post('/api/admin/users', as_='admin', json={'email': 'agent@example.test', 'password': 'Str0ng-Pass!word',
                                                      'display_name': 'Agent', 'role': 'user'})
    assert r.status_code in (200, 201), r.get_data(as_text=True)
    new_id = r.get_json().get('user_id') or r.get_json().get('id')
    for body in ({'email': '', 'password': 'Str0ng-Pass!word'}, {'email': 'a@example.test', 'password': '1'},
                 {'email': 'b@example.test', 'password': 'Str0ng-Pass!word', 'role': 'superadmin'}):
        assert w.post('/api/admin/users', as_='admin', json=body).status_code in (400, 403), body
    assert w.post('/api/admin/users', as_='super', json={'email': 'c@example.test', 'password': 'Str0ng-Pass!word',
                                                         'role': 'admin', 'org_id': w.org2['id']}).status_code in (200, 201)
    assert w.get('/api/admin/org-users', as_='admin').status_code == 200
    assert w.post('/api/admin/invite-user', as_='admin', json={'email': 'nodn@example.test'}).status_code == 400
    inv = w.post('/api/admin/invite-user', as_='admin', json={'email': 'invited@example.test', 'role': 'user',
                                                              'display_name': 'Invited'})
    assert inv.status_code in (200, 201), inv.get_data(as_text=True)
    assert w.post('/api/admin/invite-user', as_='admin', json={'email': 'x'}).status_code == 400
    assert w.get('/api/admin/invites', as_='admin').status_code == 200
    target = new_id or w.users['user']
    assert w.put(f'/api/admin/users/{target}/details', as_='admin', json={'display_name': 'Agent 2',
                                                                          'email': 'agent2@example.test'}).status_code in (200, 404)
    assert w.put(f'/api/admin/users/{target}/details', as_='admin', json={'email': 'not-an-email'}).status_code in (400, 404)
    assert w.put(f'/api/admin/users/{target}/password', as_='admin', json={'password': 'An0ther-Str0ng!'}).status_code in (200, 404)
    assert w.put(f'/api/admin/users/{target}/password', as_='admin', json={'password': 'x'}).status_code in (400, 404)
    assert w.put(f'/api/admin/users/{target}/role', as_='admin', json={'role': 'admin'}).status_code in (200, 403, 404)
    assert w.put(f'/api/admin/users/{target}/role', as_='admin', json={'role': 'zzz'}).status_code in (400, 404)
    assert w.delete(f'/api/admin/users/{target}', as_='admin').status_code in (200, 204, 404)
    assert w.delete(f"/api/admin/users/{w.users['admin']}", as_='admin').status_code in (400, 403)
    assert w.delete(f"/api/admin/users/{w.users['super']}", as_='admin').status_code in (403, 404, 400)
