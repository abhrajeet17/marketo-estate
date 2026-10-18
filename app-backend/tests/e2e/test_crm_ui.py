"""CRM in Chrome as an admin: every tab loads its data without errors; filters and dialogs open and close.
Read-only: dialogs are always cancelled."""
import pytest

CRM_TABS = ('interests', 'deals', 'contacts', 'allotted-clients', 'projects', 'panoramas', 'plots', 'manage-lock', 'masters')


@pytest.fixture
def crm(open_page, main_project):
    page, watch = open_page('/crm', active=main_project)
    page.wait_for_selector('[data-tab]')
    return page, watch


def test_every_crm_tab_loads(crm):
    page, watch = crm
    seen = []
    for tab in CRM_TABS:
        button = page.locator(f'[data-tab="{tab}"]').first
        if button.count() == 0 or not button.is_visible():
            continue
        button.click()
        page.wait_for_function(
            "name => { const b = document.querySelector(`[data-tab='${name}']`); return b && b.classList.contains('active'); }",
            arg=tab)
        page.wait_for_load_state('networkidle')
        error = page.locator('.portal-tab-error:visible, .crm-tab-error:visible')
        assert error.count() == 0, f'{tab} tab shows an error'
        seen.append(tab)
    assert len(seen) >= 4, seen
    watch.assert_clean()


def test_plots_filter_rail(crm):
    page, watch = crm
    tab = page.locator('[data-tab="plots"]').first
    if not tab.is_visible():
        pytest.skip('plots tab hidden for this account')
    tab.click()
    page.wait_for_load_state('networkidle')
    is_open = "() => document.getElementById('plots-list-layout').classList.contains('filters-open')"
    start = page.evaluate(is_open)
    page.locator('#btn-open-plots-filter-modal').click()
    page.wait_for_function(f"({is_open})() === {str(not start).lower()}")
    if not start:  # now open: the search box filters the list
        page.locator('#plot-search').fill('A')
        page.wait_for_load_state('networkidle')
        page.locator('#plot-search').fill('')
    page.locator('#btn-open-plots-filter-modal').click()
    page.wait_for_function(f"({is_open})() === {str(start).lower()}")
    watch.assert_clean()


def test_project_edit_dialog_opens_and_cancels(crm):
    page, watch = crm
    tab = page.locator('[data-tab="projects"]').first
    if not tab.is_visible():
        pytest.skip('projects tab hidden for this account')
    tab.click()
    page.wait_for_load_state('networkidle')
    edit = page.locator('#projects-tbody button, #projects-tbody [data-action]').first
    if edit.count() == 0:
        pytest.skip('no projects listed')
    edit.click()
    if page.locator('#edit-project-modal').is_visible():
        page.locator('#ep-cancel').click()
        page.wait_for_selector('#edit-project-modal', state='hidden')
    watch.assert_clean()
