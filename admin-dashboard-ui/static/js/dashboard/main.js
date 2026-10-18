/**
 * Builder dashboard entry point (platform admins; sidebar.js routes everyone else to the client portal).
 * Shows the panoramas of the active project picked on /projectselection (the sidebar's global filter);
 * projectselection.js is the entry point of that page and shares these modules.
 *
 * core/      state, API client, data sync, action registry
 * views/     render functions for project cards, panoramas and recents
 * features/  open panorama, action menus, account
 * builder/   upload and project / panorama management, enabled once the admin role is confirmed
 */
import { registerActions, runAction } from './core/actions.js';
import { debounce } from './core/dom.js';
import {
    activeSelection, findPanorama, readCachedSnapshot, setSnapshot, state, subscribe, update,
} from './core/store.js';
import { refresh } from './core/sync.js';
import { installBuilder } from './builder/index.js';
import { initAccount } from './features/account.js';
import { panoramaMenuItems } from './features/menus.js';
import { openPanorama } from './features/open.js';
import { openMenu } from './ui/menu.js';
import { toast } from './ui/toast.js';
import { renderPanoramas } from './views/panoramas.js';
import { renderRecents } from './views/recents.js';

const root = document.getElementById('dashboard');
const search = document.getElementById('dash-search');
const clearSearch = root.querySelector('.dash-search__clear');
const builderOnly = root.querySelectorAll('[data-builder-only]');

function readJson(store, key) {
    try { return JSON.parse(store.getItem(key) || 'null'); } catch (e) { return null; }
}

// ── Render ────────────────────────────────────────────────────────────────
function renderToolbar() {
    builderOnly.forEach((el) => { el.hidden = !state.builder; });
    clearSearch.hidden = !state.query;
    if (search.value !== state.query && document.activeElement !== search) search.value = state.query;
    root.querySelectorAll('[data-action="filter-type"][aria-pressed]').forEach((btn) => {
        btn.setAttribute('aria-pressed', String(btn.dataset.type === state.type));
    });
}

subscribe(() => {
    renderToolbar();
    renderPanoramas();
    renderRecents();
});

// ── Actions ───────────────────────────────────────────────────────────────
registerActions({
    'open-panorama': ({ id }) => openPanorama(id),
    'share-project': ({ id }) => window.showProjectShareModal(id),
    'clear-search': () => { update({ query: '' }); search.focus(); },
    'filter-type': ({ el }) => update({ type: el.dataset.type }),
    retry: () => { update({ status: 'loading' }); refresh().catch(() => {}); },
    'panorama-menu': ({ el, id }) => {
        const panorama = findPanorama(id);
        if (panorama) openMenu(el, panoramaMenuItems(panorama), (item) => runAction(item.action, { id }));
    },
});

root.addEventListener('click', (e) => {
    const el = e.target.closest('[data-action]');
    if (!el || !root.contains(el)) return;
    e.preventDefault();
    runAction(el.dataset.action, { el, id: el.dataset.id, event: e });
});

// Cards and project rows are focusable non-buttons: Enter/Space activates them.
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

// ── Role ──────────────────────────────────────────────────────────────────
let builderInstalled = false;
function applyRole({ role, isAdmin }) {
    update({ role: role || '', isAdmin: !!isAdmin, builder: !!isAdmin });
    if (isAdmin && !builderInstalled) {
        builderInstalled = true;
        installBuilder(root);
    }
}

// ── Boot ──────────────────────────────────────────────────────────────────
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
    initAccount();
})();
