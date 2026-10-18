"""
Create / rename / delete flows through the UI (E2E_WRITE=1 only).

Each test works on a project it creates itself, named "[e2e] …", and removes it in a finalizer
even if the test fails, so no existing data is touched.
"""
import pytest

pytestmark = pytest.mark.write


@pytest.fixture
def cleanup(api):
    created = []
    yield created
    if not created:
        return
    for project_id in created:
        api.request('DELETE', f'/api/workspaces/{project_id}')
    leftovers = [p for p in api.get('/api/dashboard')['projects'] if p['id'] in created]
    assert not leftovers, f'could not remove test projects: {leftovers}'


def _find(api, name):
    return next((p for p in api.get('/api/dashboard')['projects'] if p['name'] == name), None)


def test_create_rename_delete_project(open_page, api, unique_name, cleanup):
    page, watch = open_page('/projectselection')
    page.wait_for_selector('[data-builder-only]:not([hidden]) [data-action="new-project"]')

    # Create: the new project becomes the current one.
    page.locator('[data-builder-only] [data-action="new-project"]').click()
    page.wait_for_selector('#dash-project-modal', state='visible')
    page.locator('#dash-project-modal [name="name"]').fill(unique_name)
    page.locator('#dash-project-modal [data-submit]').click()
    page.wait_for_selector('#dash-project-modal', state='hidden', timeout=30000)
    created = _find(api, unique_name)
    assert created, 'project was not created'
    cleanup.append(created['id'])
    card = page.locator(f'.ps-card[data-select="ws:{created["id"]}"]')
    card.wait_for()
    page.wait_for_selector(f'.ps-card.is-active[data-select="ws:{created["id"]}"]')

    # Rename through the ⋯ menu.
    renamed = unique_name + ' renamed'
    card.locator('.ps-card__menu').click()
    page.locator('.dash-menu__item', has_text='Rename').click()
    page.wait_for_selector('#dash-prompt-modal', state='visible')
    page.locator('#dash-prompt-modal [name="value"]').fill(renamed)
    page.locator('#dash-prompt-modal [data-submit]').click()
    page.wait_for_selector('#dash-prompt-modal', state='hidden')
    card.locator('.ps-card__name', has_text=renamed).wait_for()
    assert _find(api, renamed)

    # The rail on a Workspace page shows the new name.
    card.locator('.ps-card__name').click()
    page.wait_for_url(f'**/dashboard?workspace_id={created["id"]}')
    page.wait_for_selector(f'.project-rail__item.is-active[data-project-id="{created["id"]}"]')
    assert page.locator('.project-rail__item.is-active').get_attribute('data-tooltip') == renamed

    # Delete through the ⋯ menu: the card disappears and the current project is cleared.
    page.locator('.project-rail__home').click()
    page.wait_for_url('**/projectselection')
    card = page.locator(f'.ps-card[data-select="ws:{created["id"]}"]')
    card.locator('.ps-card__menu').click()
    page.locator('.dash-menu__item', has_text='Delete project').click()
    page.wait_for_selector('#dash-confirm-modal', state='visible')
    page.locator('#dash-confirm-modal [data-submit]').click()
    card.wait_for(state='detached', timeout=30000)
    assert not _find(api, renamed)
    page.goto(page.url.replace('/projectselection', '/dashboard'), wait_until='networkidle')
    page.wait_for_url('**/projectselection')
    watch.assert_clean()
