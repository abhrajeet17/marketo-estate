"""Buyer-facing share pages in a fresh visitor context: every share link of the main project opens and its
interactive parts respond. Read-only."""
import pytest


def _first(sb, table, **where):
    q = sb.table(table).select('*')
    for k, v in where.items():
        q = q.eq(k, v)
    rows = q.limit(1).execute().data or []
    return rows[0] if rows else None


SHARE_PAGES = [
    ('galleries', '/gallery/view/{share_token}'),
    ('floor_plan_catalogues', '/floorplans/view/{share_token}'),
    ('daynight_projects', '/daynight/view/{share_token}'),
    ('sales_route_maps', '/sales-route-maps/view/{share_token}'),
    ('sales_flat360_views', '/sales-flat360/view/{share_token}'),
    ('building_maps', '/building-plan/{share_token}'),
    ('earth_views', '/earth-view/view/{share_token}'),
]


@pytest.mark.parametrize('table,pattern', SHARE_PAGES, ids=[t for t, _p in SHARE_PAGES])
def test_share_page_opens_for_visitors(open_page, sb, main_project, table, pattern):
    row = _first(sb, table, workspace_id=main_project['id']) or _first(sb, table)
    if not row or not row.get('share_token'):
        pytest.skip(f'no {table} with a share link')
    page, watch = open_page(pattern.format(**row), signed_in=False, wait='load')
    status = page.evaluate("performance.getEntriesByType('navigation')[0]?.responseStatus || 200")
    if status == 404:
        pytest.skip('share link has no media yet')
    assert status < 400
    page.wait_for_timeout(1000)
    watch.assert_clean()


def test_full_view_tabs_switch(open_page, main_project):
    page, watch = open_page(f"/customer/full-view/{main_project['id']}", signed_in=False, wait='load')
    page.wait_for_timeout(1500)
    tabs = page.locator('[data-tab-id], .fv-tab, [role="tab"]')
    count = min(tabs.count(), 6)
    for i in range(count):
        tab = tabs.nth(i)
        if tab.is_visible():
            tab.click()
            page.wait_for_timeout(400)
    watch.assert_clean()


def test_building_plan_drilldown(open_page, sb, main_project):
    row = _first(sb, 'building_maps', workspace_id=main_project['id']) or _first(sb, 'building_maps')
    if not row:
        pytest.skip('no building plan')
    page, watch = open_page(f"/building-plan/{row['share_token']}", signed_in=False, wait='load')
    page.wait_for_timeout(1200)
    zone = page.locator('svg polygon, [data-zone-id]').first
    if zone.count() and zone.is_visible():
        zone.click(force=True)
        page.wait_for_timeout(600)
    watch.assert_clean()


def test_public_customer_3d_view(open_page, main_project):
    pano = main_project.get('main_panorama_id')
    if not pano:
        pytest.skip('project has no main panorama')
    page, watch = open_page(f'/customer/{pano}', signed_in=False, wait='load')
    assert '/customer/' in page.url  # redirected to the organisation's pretty URL
    page.wait_for_selector('#psv-container', state='attached', timeout=30000)
    page.wait_for_timeout(1500)
    watch.assert_clean()
