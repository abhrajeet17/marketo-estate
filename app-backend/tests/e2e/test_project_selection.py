"""/projectselection: the admin landing page, project cards, ⋯ menu (incl. share links), dialogs."""
import re

PROJECT_ACTIONS = ('Manage access', 'Edit details', 'Rename', 'Delete project')
SHARE_ACTIONS = ('Copy Full View link', 'Create custom link', 'Open Full View ↗')


def _card(page, project):
    return page.locator(f'.ps-card[data-select="ws:{project["id"]}"]')


def _open_menu(page, project):
    _card(page, project).locator('.ps-card__menu').click()
    page.wait_for_selector('.dash-menu:not([hidden]) .dash-menu__item')
    return page.locator('.dash-menu__item').all_inner_texts()


def test_workspace_page_without_project_redirects_here(open_page):
    page, watch = open_page('/dashboard')
    page.wait_for_url('**/projectselection', timeout=20000)
    page.wait_for_selector('.ps-card[data-action="enter-project"]')
    watch.assert_clean()


def test_cards_and_sidebar(open_page, projects):
    page, watch = open_page('/projectselection')
    page.wait_for_selector('.ps-card[data-action="enter-project"]')
    for project in projects['all']:
        card = _card(page, project)
        assert card.count() == 1, project['name']
        assert card.locator('.ps-card__name').inner_text() == project['name']
    assert page.locator('#ps-projects-count').inner_text() == f"{len(projects['all'])} project{'s' if len(projects['all']) != 1 else ''}"
    # Choosing a project: no project rail, no Workspace links, no sidebar upload.
    assert page.locator('#project-rail').count() == 0
    assert page.locator('#sidebar-upload-wrap').count() == 0
    assert page.locator('.sidebar-group__label', has_text='Workspace').count() == 0
    page.wait_for_selector('[data-builder-only]:not([hidden])')
    watch.assert_clean()


def test_menu_has_project_and_share_actions(open_page, main_project):
    page, watch = open_page('/projectselection')
    page.wait_for_selector('.ps-card__menu')
    labels = _open_menu(page, main_project)
    for label in PROJECT_ACTIONS + SHARE_ACTIONS:
        assert label in labels, f'{label!r} missing from {labels}'
    if main_project.get('main_panorama_id'):
        assert 'Share reference link' in labels and 'Set customer view' in labels
    page.keyboard.press('Escape')
    assert page.locator('.dash-menu').is_hidden()
    watch.assert_clean()


def test_copy_full_view_link_opens_for_customers(open_page, main_project, browser):
    page, watch = open_page('/projectselection')
    page.wait_for_selector('.ps-card__menu')
    _open_menu(page, main_project)
    page.locator('.dash-menu__item', has_text='Copy Full View link').click()
    page.wait_for_selector('.dash-toast', timeout=10000)
    link = page.evaluate('navigator.clipboard.readText()')
    assert re.match(r'https?://.+/(fullview/|customer/full-view/)', link), link
    watch.assert_clean()
    # The copied link works for a visitor who is not signed in.
    visitor = browser.new_context()
    try:
        resp = visitor.new_page().goto(link, wait_until='domcontentloaded', timeout=60000)
        assert resp.status < 400, f'{link} -> {resp.status}'
    finally:
        visitor.close()


def test_open_full_view_opens_new_tab(open_page, main_project):
    page, watch = open_page('/projectselection')
    page.wait_for_selector('.ps-card__menu')
    _open_menu(page, main_project)
    with page.context.expect_page() as new_tab:
        page.locator('.dash-menu__item', has_text='Open Full View').click()
    tab = new_tab.value
    tab.wait_for_load_state('domcontentloaded')
    assert f'/customer/full-view/{main_project["id"]}' in tab.url
    watch.assert_clean()


def test_create_link_and_reference_dialogs(open_page, main_project):
    page, watch = open_page('/projectselection')
    page.wait_for_selector('.ps-card__menu')
    _open_menu(page, main_project)
    page.locator('.dash-menu__item', has_text='Create custom link').click()
    page.wait_for_selector('#create-share-link-modal', state='visible')
    page.wait_for_function("document.getElementById('create-share-link-prefix').textContent.includes('/fullview/')")
    page.locator('#create-share-link-close').click()
    page.wait_for_selector('#create-share-link-modal', state='hidden')
    if main_project.get('main_panorama_id'):
        _open_menu(page, main_project)
        page.locator('.dash-menu__item', has_text='Share reference link').click()
        page.wait_for_selector('#share-workspace-modal', state='visible')
    watch.assert_clean()


def test_edit_details_dialog_loads_project(open_page, main_project):
    page, watch = open_page('/projectselection')
    page.wait_for_selector('.ps-card__menu')
    _open_menu(page, main_project)
    page.locator('.dash-menu__item', has_text='Edit details').click()
    page.wait_for_selector('#dash-project-modal', state='visible')
    page.wait_for_function("!document.querySelector('#dash-project-modal [data-details-fields]').disabled")
    assert page.locator('#dash-project-modal [name="name"]').input_value() == main_project['name']
    page.keyboard.press('Escape')
    page.wait_for_selector('#dash-project-modal', state='hidden')
    watch.assert_clean()


def test_new_project_and_upload_dialogs_open(open_page):
    page, watch = open_page('/projectselection')
    page.wait_for_selector('[data-builder-only]:not([hidden])')
    page.locator('[data-builder-only] [data-action="new-project"]').click()
    page.wait_for_selector('#dash-project-modal', state='visible')
    page.keyboard.press('Escape')
    page.locator('[data-builder-only] [data-action="upload"]').click()
    page.wait_for_selector('#dash-upload-modal', state='visible')
    options = page.locator('#dash-upload-modal [data-project-select] option').all_inner_texts()
    assert options[0].startswith('Unlinked') and len(options) >= 2
    page.keyboard.press('Escape')
    watch.assert_clean()


def test_search_filters_cards(open_page, main_project, projects):
    page, watch = open_page('/projectselection')
    page.wait_for_selector('.ps-card[data-action="enter-project"]')
    page.locator('#dash-search').fill(main_project['name'][:6])
    page.wait_for_timeout(400)
    names = page.locator('.ps-card__name').all_inner_texts()
    assert main_project['name'] in names
    assert all(main_project['name'][:6].lower() in n.lower() for n in names)
    page.locator('#dash-search').fill('zzzz-no-such-project')
    page.locator('.dash-empty', has_text='No projects match').wait_for()
    page.locator('.dash-empty [data-action="clear-search"]').click()
    page.wait_for_function(f"document.querySelectorAll('.ps-card[data-action=\"enter-project\"]').length >= {len(projects['all'])}")
    watch.assert_clean()


def test_picking_a_project_opens_its_dashboard(open_page, main_project):
    page, watch = open_page('/projectselection')
    page.wait_for_selector('.ps-card[data-action="enter-project"]')
    _card(page, main_project).locator('.ps-card__name').click()
    page.wait_for_url(f'**/dashboard?workspace_id={main_project["id"]}')
    page.wait_for_selector('#dash-panoramas-title')
    page.wait_for_function(f"document.getElementById('dash-panoramas-title').textContent === {main_project['name']!r}")
    # Back on the selection page the project is marked as current.
    page.locator('.project-rail__home').click()
    page.wait_for_url('**/projectselection')
    page.wait_for_selector(f'.ps-card.is-active[data-select="ws:{main_project["id"]}"]')
    watch.assert_clean()
