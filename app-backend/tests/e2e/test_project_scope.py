"""The selected project is a global filter: project rail, URL scoping and every Workspace page's API calls."""
import uuid

import pytest

SALES_LIST_APIS = ('/api/floorplans/catalogues', '/api/galleries', '/api/project-plans', '/api/sales-maps',
                   '/api/sales-flat360', '/api/earth-views')
SALES_TABS = {
    'floorplans': '/api/floorplans/catalogues', 'earth-views': '/api/earth-views', 'project-plans': '/api/project-plans',
    'route-maps': '/api/sales-maps', 'flat360': '/api/sales-flat360', 'galleries': '/api/galleries',
}


def _scoped(calls, prefixes, project_id):
    hits = [path for _m, path, _s in calls if path.split('?')[0] in prefixes]
    unscoped = [p for p in hits if f'workspace_id={project_id}' not in p]
    return hits, unscoped


def test_dashboard_shows_only_the_project(open_page, main_project, projects):
    page, watch = open_page('/dashboard', active=main_project)
    assert f'workspace_id={main_project["id"]}' in page.url
    page.wait_for_selector('.dash-pano[data-action="open-panorama"], .dash-empty')
    expected = {str(p['id']) for p in projects['panoramas'] if str(p.get('workspace_id')) == str(main_project['id'])}
    shown = set(page.locator('.dash-pano[data-action="open-panorama"]').evaluate_all('els => els.map(e => e.dataset.id)'))
    assert shown == expected
    assert page.locator('.dash-panel--projects').count() == 0
    recent = set(page.locator('#dash-recents .dash-recent').evaluate_all('els => els.map(e => e.dataset.id)'))
    assert recent <= expected
    watch.assert_clean()


def test_rail_lists_projects_with_hover_names(open_page, main_project, projects):
    page, watch = open_page('/dashboard', active=main_project)
    page.wait_for_function(f"document.querySelectorAll('.project-rail__item').length === {len(projects['all'])}")
    active = page.locator('.project-rail__item.is-active')
    assert active.count() == 1 and active.get_attribute('data-project-id') == str(main_project['id'])
    # Names only on hover.
    assert page.locator('.project-rail__tip').is_hidden()
    active.hover()
    tip = page.locator('.project-rail__tip')
    tip.wait_for(state='visible')
    assert tip.inner_text() == main_project['name']
    page.mouse.move(900, 500)
    tip.wait_for(state='hidden')
    # The rail is the left-most column.
    rail_box = page.locator('#project-rail').bounding_box()
    sidebar_box = page.locator('#dashboard-sidebar').bounding_box()
    assert rail_box['x'] == 0 and rail_box['x'] + rail_box['width'] <= sidebar_box['x'] + 1
    watch.assert_clean()


def test_sales_tools_are_scoped(open_page, main_project):
    page, watch = open_page('/salestools', active=main_project)
    assert f'workspace_id={main_project["id"]}' in page.url
    assert page.locator('#fp-global-workspace-filter').is_hidden()
    frame_src = page.locator('#fp-daynight-frame').get_attribute('src') or ''
    assert f'workspace_id={main_project["id"]}' in frame_src
    for tab, api_path in SALES_TABS.items():
        loaded = any(path.split('?')[0] == api_path for _m, path, _s in watch.api_calls)
        if loaded:
            page.locator(f'#subtab-{tab}').click()
            continue
        with page.expect_response(lambda r, p=api_path: r.url.split('?')[0].endswith(p), timeout=20000):
            page.locator(f'#subtab-{tab}').click()
    hits, unscoped = _scoped(watch.api_calls, SALES_LIST_APIS, main_project['id'])
    assert {h.split('?')[0] for h in hits} == set(SALES_LIST_APIS)
    assert not unscoped, f'lists loaded without the project filter: {unscoped}'
    watch.assert_clean()


def test_building_plans_are_scoped(open_page, main_project):
    page, watch = open_page('/building-plans', active=main_project)
    assert f'workspace_id={main_project["id"]}' in page.url
    assert page.locator('#bp-project-filter').is_hidden()
    hits, unscoped = _scoped(watch.api_calls, ('/api/building-maps',), main_project['id'])
    assert hits and not unscoped
    watch.assert_clean()


def test_full_view_opens_the_project(open_page, main_project):
    page, watch = open_page('/full-view', active=main_project)
    page.wait_for_selector('#fv-builder', state='visible')
    assert page.locator('#fv-builder-ws-name').inner_text() == main_project['name']
    hits, unscoped = _scoped(watch.api_calls, ('/api/full-view/config',), main_project['id'])
    assert hits and not unscoped
    watch.assert_clean()


def test_day_night_is_scoped(open_page, main_project):
    page, watch = open_page('/daynight', active=main_project)
    hits, unscoped = _scoped(watch.api_calls, ('/api/daynight',), main_project['id'])
    assert hits and not unscoped
    watch.assert_clean()


def test_rail_switches_project_on_the_same_page(open_page, main_project, projects):
    others = [p for p in projects['all'] if str(p['id']) != str(main_project['id'])]
    if not others:
        pytest.skip('needs two projects')
    other = others[0]
    page, watch = open_page('/building-plans', active=main_project)
    page.wait_for_selector(f'.project-rail__item[data-project-id="{other["id"]}"]')
    page.locator(f'.project-rail__item[data-project-id="{other["id"]}"]').click()
    page.wait_for_url(f'**/building-plans?workspace_id={other["id"]}')
    page.wait_for_selector(f'.project-rail__item.is-active[data-project-id="{other["id"]}"]')
    # The choice follows to other pages.
    page.goto(page.url.split('/building-plans')[0] + '/dashboard', wait_until='networkidle')
    assert f'workspace_id={other["id"]}' in page.url
    watch.assert_clean()


def test_project_in_link_becomes_active(open_page, main_project, projects):
    others = [p for p in projects['all'] if str(p['id']) != str(main_project['id'])]
    if not others:
        pytest.skip('needs two projects')
    other = others[0]
    page, watch = open_page(f'/salestools?workspace_id={other["id"]}', active=main_project)
    page.wait_for_selector(f'.project-rail__item.is-active[data-project-id="{other["id"]}"]')
    watch.assert_clean()


def test_deleted_or_foreign_project_falls_back_to_selection(open_page):
    page, watch = open_page('/dashboard', active={'id': str(uuid.uuid4()), 'name': 'Gone'})
    page.wait_for_url('**/projectselection', timeout=30000)
    watch.assert_clean()


def test_phone_width_has_no_horizontal_scroll(open_page, main_project):
    for path in ('/dashboard', '/projectselection', '/salestools'):
        page, watch = open_page(path, active=main_project, viewport=(390, 844))
        page.wait_for_timeout(500)
        width = page.evaluate('document.documentElement.scrollWidth')
        assert width <= 392, f'{path} scrolls sideways at phone width ({width}px)'
        watch.assert_clean()
