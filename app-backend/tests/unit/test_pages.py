"""Admin page templates: project selection landing, project rail and global project filter."""
import re

import pytest

SCOPED_PAGES = ('/dashboard', '/salestools', '/building-plans', '/full-view', '/daynight')


@pytest.mark.parametrize('path', ('/projectselection',) + SCOPED_PAGES + ('/login', '/user-management', '/organizations'))
def test_admin_pages_render(client, path):
    resp = client.get(path)
    assert resp.status_code == 200, path
    assert b'<html' in resp.data.lower()


def test_project_selection_page(client):
    html = client.get('/projectselection').get_data(as_text=True)
    assert 'id="projectselection"' in html
    assert '/static/js/dashboard/projectselection.js' in html
    assert 'id="ps-projects"' in html
    # Sidebar: no Workspace group, no upload, no project rail while choosing a project.
    assert 'id="project-rail"' not in html
    assert 'id="sidebar-upload-wrap"' not in html
    assert '>Workspace<' not in html
    # Share link dialogs are available for the project menu.
    assert 'id="share-workspace-modal"' in html
    assert 'id="create-share-link-modal"' in html
    assert 'create-share-link-modal.js' in html
    assert 'data-action="new-project"' in html and 'data-action="upload"' in html


@pytest.mark.parametrize('path', SCOPED_PAGES)
def test_workspace_pages_have_project_rail(client, path):
    html = client.get(path).get_data(as_text=True)
    assert 'id="project-rail"' in html
    assert 'href="/projectselection"' in html
    # The rail must come before the sidebar so it is the left-most column.
    assert html.index('id="project-rail"') < html.index('id="dashboard-sidebar"')


def test_only_dashboard_rail_loads_from_page_data(client):
    assert 'data-self-load' in client.get('/dashboard').get_data(as_text=True)
    assert 'data-self-load' not in client.get('/salestools').get_data(as_text=True)


def test_dashboard_has_no_projects_box(client):
    html = client.get('/dashboard').get_data(as_text=True)
    assert 'dash-panel--projects' not in html
    assert 'id="dash-projects"' not in html
    assert 'data-action="new-project"' not in html
    assert 'dash-columns--single' in html


def test_brand_links_to_project_selection(client):
    html = client.get('/salestools').get_data(as_text=True)
    assert re.search(r'class="sidebar-brand__link"', html)
    assert 'href="/projectselection" class="sidebar-brand__link"' in html


def test_per_page_project_pickers_are_hidden(client):
    sales = client.get('/salestools').get_data(as_text=True)
    assert '<div class="fp-global-toolbar" style="display:none;">' in sales
    plans = client.get('/building-plans').get_data(as_text=True)
    assert re.search(r'id="bp-project-filter"[^>]*style="display:none;"', plans)
    full = client.get('/full-view').get_data(as_text=True)
    assert '<div class="fv-step" style="display:none;">' in full


def test_admins_land_on_project_selection():
    from app.services import portal_identity_service
    source = open(portal_identity_service.__file__, encoding='utf-8').read()
    assert "'/projectselection' if is_platform_admin and not portal_only" in source
