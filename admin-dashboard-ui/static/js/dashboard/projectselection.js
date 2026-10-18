/**
 * Project selection entry point (/projectselection, the landing page for platform admins).
 * Lists projects as cards with their actions (the ⋯ menu), creation and upload. Picking a project
 * makes it the global active project (window.msProjects in sidebar.js) and opens the dashboard.
 * Shares core/, features/, builder/ and ui/ with the dashboard (main.js).
 */
import { registerActions, runAction } from './core/actions.js';
import { api } from './core/api.js';
import { debounce } from './core/dom.js';
import {
    UNLINKED, activeSelection, findProject, projectIdOf, readCachedSnapshot, setSnapshot, state, subscribe, update,
} from './core/store.js';
import { refresh } from './core/sync.js';
import { installBuilder } from './builder/index.js';
import { initAccount } from './features/account.js';
import { projectMenuItems } from './features/menus.js';
import { openMenu } from './ui/menu.js';
import { toast } from './ui/toast.js';
import { renderProjects } from './views/projects.js';

const root = document.getElementById('projectselection');
const search = document.getElementById('dash-search');
const clearSearch = root.querySelector('.dash-search__clear');
const builderOnly = root.querySelectorAll('[data-builder-only]');

function readJson(store, key) {
    try { return JSON.parse(store.getItem(key) || 'null'); } catch (e) { return null; }
}

function enterProject(key) {
    if (key === UNLINKED) {
        window.location.href = '/dashboard?unlinked=1';
        return;
    }
    const id = projectIdOf(key);
    const project = id && findProject(id);
    if (!project) return;
    window.msProjects.setActive({ id: project.id, name: project.name });
    window.location.href = `/dashboard?workspace_id=${encodeURIComponent(project.id)}`;
}

/** Customer-facing Full View URL: the custom link when one is set, else the default one. */
async function fullViewUrl(id) {
    let share = {};
    try { share = (await api.shareEndpoint(id)).share || {}; } catch (e) { /* default link below */ }
    const url = share.full_view_effective_url || share.full_view_custom_url || share.full_view_default_url
        || `/customer/full-view/${encodeURIComponent(id)}`;
    return /^https?:\/\//i.test(url) ? url : window.location.origin + url;
}

async function copyText(text) {
    try {
        await navigator.clipboard.writeText(text);
        return true;
    } catch (e) {
        const area = document.createElement('textarea');
        area.value = text;
        area.style.position = 'fixed';
        area.style.opacity = '0';
        document.body.appendChild(area);
        area.select();
        const ok = document.execCommand('copy');
        area.remove();
        return ok;
    }
}

async function copyFullViewLink(id) {
    const url = await fullViewUrl(id);
    if (await copyText(url)) toast('Full View link copied');
    else toast(`Copy this link: ${url}`, 'error');
}

subscribe(() => {
    builderOnly.forEach((el) => { el.hidden = !state.builder; });
    clearSearch.hidden = !state.query;
    if (search.value !== state.query && document.activeElement !== search) search.value = state.query;
    renderProjects();
});

registerActions({
    'enter-project': ({ el }) => enterProject(el.dataset.select),
    'share-project': ({ id }) => window.showProjectShareModal(id),
    'copy-fullview-link': ({ id }) => copyFullViewLink(id),
    'create-share-link': ({ id }) => window.showCreateShareLinkModal(id),
    'clear-search': () => { update({ query: '' }); search.focus(); },
    retry: () => { update({ status: 'loading' }); refresh().catch(() => {}); },
    'project-menu': ({ el, id }) => {
        const project = findProject(id);
        if (project) openMenu(el, projectMenuItems(project), (item) => runAction(item.action, { id }));
    },
});

root.addEventListener('click', (e) => {
    const el = e.target.closest('[data-action]');
    if (!el || !root.contains(el)) return;
    e.preventDefault();
    runAction(el.dataset.action, { el, id: el.dataset.id, event: e });
});

root.addEventListener('keydown', (e) => {
    if ((e.key === 'Enter' || e.key === ' ') && e.target.matches('[data-action][tabindex]:not(button)')) {
        e.preventDefault();
        e.target.click();
    }
});

const setQuery = debounce((value) => update({ query: value }), 120);
search.addEventListener('input', () => setQuery(search.value));
search.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && search.value) {
        e.stopPropagation();
        search.value = '';
        update({ query: '' });
    }
});
document.addEventListener('keydown', (e) => {
    const typing = e.target.closest('input, textarea, select, [contenteditable]');
    if (e.key === '/' && !typing && !e.ctrlKey && !e.metaKey) {
        e.preventDefault();
        search.focus();
    }
});

let builderInstalled = false;
function applyRole({ role, isAdmin }) {
    update({ role: role || '', isAdmin: !!isAdmin, builder: !!isAdmin });
    if (isAdmin && !builderInstalled) {
        builderInstalled = true;
        installBuilder(root);
    }
}

(function boot() {
    const session = readJson(localStorage, 'marketostate_auth_session_v1');
    const userId = (session && session.user && session.user.id) || '';
    update({ userId, selection: activeSelection() });

    const cachedRole = userId ? readJson(sessionStorage, `sidebar_state_v3:${userId}`) : null;
    if (cachedRole) applyRole(cachedRole);

    const snapshot = userId ? readCachedSnapshot(userId) : null;
    if (snapshot) setSnapshot(snapshot);

    refresh().catch(() => {
        if (snapshot) toast('Showing saved data — could not reach the server.', 'error');
    });

    window.sidebarReady.then((ctx) => {
        const profileUserId = ctx.profile && ctx.profile.user_id;
        if (!state.userId && profileUserId) update({ userId: String(profileUserId) });
        applyRole(ctx);
    });

    window.initShareWorkspaceModal({ showToast: toast });
    window.initCreateShareLinkModal({
        showToast: toast,
        pathPrefix: '/fullview/',
        pickEffectiveUrl: (share) => (share && (share.full_view_effective_url || share.full_view_default_url)) || '',
    });
    initAccount();
})();
