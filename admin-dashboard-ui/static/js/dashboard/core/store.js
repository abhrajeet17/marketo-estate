/**
 * Dashboard state. Views subscribe and re-render on change (batched per frame).
 * The last snapshot is cached per user so repeat visits paint instantly while
 * fresh data loads in the background.
 *
 * `selection` mirrors the global active project (window.msProjects in sidebar.js):
 * `ws:<id>`, UNLINKED (/dashboard?unlinked=1) or '' when none is picked.
 */

const SNAPSHOT_KEY = 'dash_snapshot_v1:';
export const UNLINKED = 'unlinked';

const listeners = new Set();
let frame = 0;

export const state = {
    userId: '',
    status: 'loading', // loading | ready | error
    error: '',
    refreshing: false,
    panoramas: [],
    projects: [],
    role: '',
    isAdmin: false,
    builder: false, // builder module loaded (admins only)
    selection: '',
    query: '',
    type: 'all',
    openingId: null,
};

export function subscribe(fn) {
    listeners.add(fn);
    return () => listeners.delete(fn);
}

export function update(patch) {
    Object.assign(state, patch);
    if (frame) return;
    frame = requestAnimationFrame(() => {
        frame = 0;
        listeners.forEach((fn) => fn(state));
    });
}

/** Resolves once dashboard data is available (cached or fresh). */
export function whenReady() {
    if (state.status === 'ready') return Promise.resolve();
    return new Promise((resolve) => {
        const stop = subscribe((s) => {
            if (s.status === 'ready') {
                stop();
                resolve();
            }
        });
    });
}

function storageGet(store, key) {
    try { return JSON.parse(store.getItem(key) || 'null'); } catch (e) { return null; }
}
function storageSet(store, key, value) {
    try { store.setItem(key, JSON.stringify(value)); } catch (e) { /* storage unavailable */ }
}

export function readCachedSnapshot(userId) {
    const cached = storageGet(sessionStorage, SNAPSHOT_KEY + userId);
    return cached && Array.isArray(cached.panoramas) && Array.isArray(cached.projects) ? cached : null;
}

/** `fresh`: straight from the server (the sidebar then drops a project that no longer exists). */
export function setSnapshot({ panoramas, projects }, fresh = false) {
    update({ panoramas, projects, status: 'ready', error: '' });
    publishProjects(fresh);
    ensureSelection();
}

/**
 * Keeps the cached snapshot, the sidebar's project rail and the stored active project in step
 * with local edits (a rename must not come back from a stale cache on the next page).
 */
function publishProjects(fresh = false) {
    const { panoramas, projects } = state;
    storageSet(sessionStorage, SNAPSHOT_KEY + state.userId, { panoramas, projects });
    if (window.msProjects) window.msProjects.fromSnapshot({ panoramas, projects }, fresh);
}

/** The active project from the sidebar's global filter, as a selection key. */
export function activeSelection() {
    if (new URLSearchParams(window.location.search).get('unlinked') === '1') return UNLINKED;
    const active = window.msProjects && window.msProjects.active();
    return active ? projectKey(active.id) : '';
}

/** Switch the global active project (rail, stored choice and this page's URL follow). */
export function select(selection) {
    update({ selection, query: '' });
    const id = projectIdOf(selection);
    if (!id || !window.msProjects) return;
    const project = findProject(id);
    window.msProjects.setActive({ id, name: project ? project.name : '' });
    publishProjects();
    if (window.location.pathname.startsWith('/dashboard')) {
        window.history.replaceState(window.history.state, '', `${window.location.pathname}?workspace_id=${encodeURIComponent(id)}`);
    }
}

// ── Derived data ──────────────────────────────────────────────────────────
export const projectKey = (id) => `ws:${id}`;
export const projectIdOf = (key) => (key && key.startsWith('ws:') ? key.slice(3) : null);
export const findProject = (id) => state.projects.find((p) => String(p.id) === String(id)) || null;
export const findPanorama = (id) => state.panoramas.find((p) => String(p.id) === String(id)) || null;
export const accessOf = (item) => item.access_type || 'owner';

export function selectedProject() {
    return findProject(projectIdOf(state.selection));
}

/** Builder may edit: platform admin acting on something they own. */
export function canManage(item) {
    return state.builder && accessOf(item) === 'owner';
}

export function panoramaCounts() {
    const counts = { [UNLINKED]: 0 };
    for (const p of state.panoramas) {
        const key = p.workspace_id ? projectKey(p.workspace_id) : UNLINKED;
        counts[key] = (counts[key] || 0) + 1;
    }
    return counts;
}

export function mainPanoramaId(project) {
    if (!project) return null;
    if (project.main_panorama_id) return Number(project.main_panorama_id);
    const first360 = state.panoramas.find((p) => String(p.workspace_id) === String(project.id) && p.is_360);
    return first360 ? Number(first360.id) : null;
}

const byRecent = (a, b) => (Date.parse(b.updated_at) || 0) - (Date.parse(a.updated_at) || 0);

/** Panoramas of the selected project (the global filter); none when no project is picked. */
export function selectedPanoramas() {
    if (state.selection === UNLINKED) return state.panoramas.filter((p) => !p.workspace_id);
    const id = projectIdOf(state.selection);
    return id ? state.panoramas.filter((p) => String(p.workspace_id || '') === String(id)) : [];
}

export function visiblePanoramas() {
    const query = state.query.trim().toLowerCase();
    let list = selectedPanoramas();
    if (query) list = list.filter((p) => (p.name || '').toLowerCase().includes(query));
    if (state.type === '360') list = list.filter((p) => p.is_360);
    if (state.type === 'flat') list = list.filter((p) => !p.is_360);
    return list.slice().sort(byRecent);
}

export function recentPanoramas(limit = 4) {
    return selectedPanoramas().sort(byRecent).slice(0, limit);
}

/** Projects worth listing: everything the user owns, plus shared ones that hold panoramas. */
export function listedProjects() {
    const counts = panoramaCounts();
    return state.projects.filter((p) => accessOf(p) === 'owner' || counts[projectKey(p.id)]);
}

/** Follow the global active project; a project that is gone leaves nothing selected. */
export function ensureSelection() {
    const next = activeSelection();
    const valid = next === UNLINKED || listedProjects().some((p) => projectKey(p.id) === next);
    if (state.selection !== (valid ? next : '')) update({ selection: valid ? next : '' });
}

/** Optimistic local edits; the caller refreshes from the server afterwards. */
export function patchPanorama(id, patch) {
    update({ panoramas: state.panoramas.map((p) => (String(p.id) === String(id) ? { ...p, ...patch } : p)) });
}
export function removePanorama(id) {
    update({ panoramas: state.panoramas.filter((p) => String(p.id) !== String(id)) });
}
export function patchProject(id, patch) {
    update({ projects: state.projects.map((p) => (String(p.id) === String(id) ? { ...p, ...patch } : p)) });
    publishProjects();
}
export function removeProject(id) {
    update({
        projects: state.projects.filter((p) => String(p.id) !== String(id)),
        panoramas: state.panoramas.map((p) => (String(p.workspace_id) === String(id) ? { ...p, workspace_id: null } : p)),
    });
    const active = window.msProjects && window.msProjects.active();
    if (active && String(active.id) === String(id)) window.msProjects.clear();
    publishProjects();
    ensureSelection();
}
