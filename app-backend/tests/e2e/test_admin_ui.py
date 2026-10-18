"""Admin tools in Chrome: Sales Tools tabs and editors, Day/Night, user management, organizations, login page.
Read-only: dialogs are opened and cancelled, nothing is saved."""
import pytest

SALES_TABS = ('floorplans', 'earth-views', 'project-plans', 'route-maps', 'flat360', 'galleries')


def test_sales_tools_tabs_render_cards_or_empty_state(open_page, main_project):
    page, watch = open_page('/salestools', active=main_project)
    for tab in SALES_TABS:
        button = page.locator(f'#subtab-{tab}')
        if not button.is_visible():
            continue
        button.click()
        page.wait_for_load_state('networkidle')
        panel = page.locator(f'#subpanel-{tab}, [data-subpanel="{tab}"], #panel-{tab}').first
        if panel.count():
            assert panel.is_visible(), tab
    watch.assert_clean()


@pytest.mark.parametrize('table,editor', [('sales_route_maps', '/sales-route-maps/editor/{id}'),
                                          ('sales_flat360_views', '/sales-flat360/editor/{id}'),
                                          ('earth_views', '/earth-view/admin/{id}'),
                                          ('building_maps', '/building-map/admin/{id}')])
def test_tool_editors_open(open_page, sb, main_project, table, editor):
    rows = sb.table(table).select('id').eq('workspace_id', main_project['id']).limit(1).execute().data
    if not rows:
        pytest.skip(f'no {table} in the main project')
    page, watch = open_page(editor.format(id=rows[0]['id']), active=main_project, wait='load')
    page.wait_for_timeout(1500)
    status = page.evaluate("performance.getEntriesByType('navigation')[0]?.responseStatus || 200")
    assert status < 400
    watch.assert_clean()


def test_user_management_lists_users(open_page, main_project):
    page, watch = open_page('/user-management', active=main_project)
    page.wait_for_load_state('networkidle')
    rows = page.locator('table tbody tr, [data-user-id]')
    assert rows.count() >= 1
    invite = page.locator('button:has-text("Invite"), button:has-text("Add user")').first
    if invite.count() and invite.is_visible():
        invite.click()
        page.wait_for_timeout(300)
        page.keyboard.press('Escape')
    watch.assert_clean()


def test_organizations_page(open_page, main_project):
    page, watch = open_page('/organizations', active=main_project)
    page.wait_for_load_state('networkidle')
    assert page.locator('body').inner_text().strip()
    watch.assert_clean()


def test_daynight_builder_lists_projects(open_page, main_project):
    page, watch = open_page('/daynight', active=main_project)
    page.wait_for_load_state('networkidle')
    assert any('/api/daynight' in p for _m, p, _s in watch.api_calls)
    watch.assert_clean()


def test_login_page_modes(open_page):
    page, watch = open_page('/login', signed_in=False)
    assert page.locator('#card-title').inner_text().strip()
    signup = page.locator('a[href*="mode=signup"], button:has-text("Sign up"), [data-mode="signup"]').first
    if signup.count() and signup.is_visible():
        signup.click()
        page.wait_for_timeout(300)
    forgot = page.locator('a:has-text("Forgot"), button:has-text("Forgot")').first
    if forgot.count() and forgot.is_visible():
        forgot.click()
        page.wait_for_timeout(300)
    watch.assert_clean()


def test_signed_out_admin_page_goes_to_login(open_page):
    page, _watch = open_page('/projectselection', signed_in=False, wait='load')
    page.wait_for_url('**/login**', timeout=20000)
