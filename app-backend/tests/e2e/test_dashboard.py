"""Plotted Development dashboard inside a project: filters, search, panorama menu, opening the editor."""
import pytest


def _ids(page):
    return page.locator('.dash-pano[data-action="open-panorama"]').evaluate_all('els => els.map(e => e.dataset.id)')


def _project_panoramas(projects, project):
    return [p for p in projects['panoramas'] if str(p.get('workspace_id')) == str(project['id'])]


def test_type_filter(open_page, main_project, projects):
    panos = _project_panoramas(projects, main_project)
    page, watch = open_page('/dashboard', active=main_project)
    page.wait_for_selector('.dash-pano[data-action="open-panorama"], .dash-empty')
    for kind, keep in (('360', lambda p: p.get('is_360')), ('flat', lambda p: not p.get('is_360')), ('all', lambda p: True)):
        page.locator(f'.dash-seg__btn[data-type="{kind}"]').click()
        page.wait_for_timeout(300)
        assert set(_ids(page)) == {str(p['id']) for p in panos if keep(p)}, kind
    watch.assert_clean()


def test_search_stays_inside_the_project(open_page, main_project, projects):
    panos = _project_panoramas(projects, main_project)
    if not panos:
        pytest.skip('project has no panoramas')
    term = (panos[0].get('name') or '')[:4]
    page, watch = open_page('/dashboard', active=main_project)
    page.wait_for_selector('.dash-pano[data-action="open-panorama"]')
    page.locator('#dash-search').fill(term)
    page.wait_for_timeout(400)
    expected = {str(p['id']) for p in panos if term.lower() in (p.get('name') or '').lower()}
    assert set(_ids(page)) == expected
    assert term in page.locator('#dash-panoramas-title').inner_text()
    watch.assert_clean()


def test_panorama_menu(open_page, main_project, projects):
    if not _project_panoramas(projects, main_project):
        pytest.skip('project has no panoramas')
    page, watch = open_page('/dashboard', active=main_project)
    page.wait_for_selector('.dash-pano__menu')
    page.locator('.dash-pano__menu').first.click()
    labels = page.locator('.dash-menu__item').all_inner_texts()
    for label in ('Open editor', 'Manage access', 'Rename', 'Delete'):
        assert label in labels, labels
    page.keyboard.press('Escape')
    watch.assert_clean()


def test_opening_a_panorama_loads_the_editor(open_page, main_project, projects):
    owned = [p for p in _project_panoramas(projects, main_project) if (p.get('access_type') or 'owner') == 'owner']
    if not owned:
        pytest.skip('no owned panorama in the project')
    target = owned[0]
    page, watch = open_page('/dashboard', active=main_project)
    page.wait_for_selector(f'.dash-pano[data-id="{target["id"]}"]')
    page.locator(f'.dash-pano[data-id="{target["id"]}"] .dash-pano__name').click()
    page.wait_for_url(f'**/admin/{"3d/" if target.get("is_360") else ""}{target["id"]}?pt=*', timeout=30000)
    page.wait_for_load_state('domcontentloaded')
    assert page.title()
    watch.assert_clean()


def test_upload_dialog_defaults_to_current_project(open_page, main_project):
    page, watch = open_page('/dashboard', active=main_project)
    page.wait_for_selector('.dash-toolbar__actions:not([hidden]) [data-action="upload"]')
    page.locator('.dash-toolbar__actions [data-action="upload"]').click()
    page.wait_for_selector('#dash-upload-modal', state='visible')
    assert page.locator('#dash-upload-modal [data-project-select]').input_value() == str(main_project['id'])
    page.keyboard.press('Escape')
    watch.assert_clean()


def test_unlinked_panoramas_view(open_page, projects):
    unlinked = {str(p['id']) for p in projects['panoramas'] if not p.get('workspace_id')}
    if not unlinked:
        pytest.skip('no unlinked panoramas')
    page, watch = open_page('/projectselection')
    page.wait_for_selector('.ps-card[data-select="unlinked"]')
    page.locator('.ps-card[data-select="unlinked"] .ps-card__name').click()
    page.wait_for_url('**/dashboard?unlinked=1')
    page.wait_for_selector('.dash-pano[data-action="open-panorama"]')
    assert set(_ids(page)) == unlinked
    assert page.locator('#dash-panoramas-title').inner_text() == 'Unlinked panoramas'
    watch.assert_clean()
