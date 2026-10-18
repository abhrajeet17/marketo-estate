def test_world_boots(world):
    resp = world.get('/api/dashboard', as_='admin')
    assert resp.status_code == 200, resp.get_data(as_text=True)[:500]
    body = resp.get_json()
    assert body
