import { esc, formatRelative, icon, plural, reconcile } from '../core/dom.js';
import {
    UNLINKED, accessOf, findPanorama, listedProjects, mainPanoramaId, panoramaCounts, projectKey, state,
} from '../core/store.js';
import { thumbImg } from '../ui/thumbs.js';

const grid = document.getElementById('ps-projects');
const total = document.getElementById('ps-projects-count');

const ACCESS_LABELS = { owner: 'Owned', client: 'Client team', broker: 'Broker access', admin: 'Admin access', viewer: 'View only' };

export function hasProjectActions(project) {
    const access = accessOf(project);
    if (access === 'owner') return state.builder;
    return (access === 'client' || access === 'broker') && !!mainPanoramaId(project);
}

/** Cover image: the main panorama, else the project's most recently edited one. */
function coverOf(project) {
    const main = findPanorama(mainPanoramaId(project));
    if (main) return main;
    const own = state.panoramas.filter((p) => String(p.workspace_id) === String(project.id));
    own.sort((a, b) => (Date.parse(b.updated_at) || 0) - (Date.parse(a.updated_at) || 0));
    return own[0] || null;
}

function card({ key, id, name, meta, chip, cover, latest, menu, active, eager }) {
    return `<article class="ps-card${active ? ' is-active' : ''}" tabindex="0" data-action="enter-project" data-select="${esc(key)}"
        aria-label="Open ${esc(name)}">
        <div class="ps-card__thumb">
            <span class="ps-card__placeholder">${icon(key === UNLINKED ? 'unlinked' : 'folder', 26)}</span>
            ${cover ? thumbImg(cover, { eager }) : ''}
            ${active ? '<span class="ps-card__tags"><span class="dash-tag dash-tag--main">Current</span></span>' : ''}
        </div>
        <div class="ps-card__body">
            <h3 class="ps-card__name" title="${esc(name)}">${esc(name)}</h3>
            <p class="ps-card__meta">
                <span>${esc(meta)}</span>
                ${latest ? `<span>${esc(formatRelative(latest))}</span>` : ''}
                ${chip ? `<span class="dash-chip">${esc(chip)}</span>` : ''}
            </p>
        </div>
        ${menu ? `<button type="button" class="dash-icon-btn ps-card__menu" data-action="project-menu" data-id="${esc(id)}"
            aria-haspopup="menu" aria-expanded="false" aria-label="Actions for ${esc(name)}">${icon('more', 16)}</button>` : ''}
    </article>`;
}

function latestUpdate(projectId) {
    let latest = 0;
    for (const p of state.panoramas) {
        if (String(p.workspace_id || '') !== String(projectId || '')) continue;
        latest = Math.max(latest, Date.parse(p.updated_at) || 0);
    }
    return latest ? new Date(latest).toISOString() : '';
}

function emptyState(query) {
    if (query) {
        return `<div class="dash-empty">${icon('search', 28)}
            <p class="dash-empty__title">No projects match “${esc(query)}”</p>
            <button type="button" class="dash-btn" data-action="clear-search">Clear search</button></div>`;
    }
    if (state.builder) {
        return `<div class="dash-empty">${icon('folder', 28)}
            <p class="dash-empty__title">No projects yet</p>
            <button type="button" class="dash-btn dash-btn--primary" data-action="new-project">${icon('plus', 16)}<span>New project</span></button></div>`;
    }
    return `<div class="dash-empty">${icon('folder', 28)}<p class="dash-empty__title">No projects have been shared with you yet</p></div>`;
}

function errorState() {
    return `<div class="dash-empty dash-empty--error">${icon('alert', 28)}
        <p class="dash-empty__title">We couldn’t load your projects</p>
        <p class="dash-empty__text">${esc(state.error || 'Check your connection and try again.')}</p>
        <button type="button" class="dash-btn dash-btn--primary" data-action="retry">Try again</button></div>`;
}

export function renderProjects() {
    if (!grid) return;
    if (state.status === 'loading') return;
    if (state.status === 'error') {
        total.textContent = '';
        grid.innerHTML = errorState();
        return;
    }
    const counts = panoramaCounts();
    const projects = listedProjects();
    const query = state.query.trim().toLowerCase();
    const items = [];
    projects.forEach((p, i) => {
        if (query && !p.name.toLowerCase().includes(query)) return;
        const access = accessOf(p);
        const key = projectKey(p.id);
        items.push({
            key,
            id: p.id,
            name: p.name,
            meta: plural(counts[key] || 0, 'panorama'),
            chip: access === 'owner' ? (mainPanoramaId(p) ? '' : 'No customer view') : (ACCESS_LABELS[access] || 'Shared'),
            cover: coverOf(p),
            latest: latestUpdate(p.id),
            menu: hasProjectActions(p),
            active: state.selection === key,
            eager: i < 8,
        });
    });
    if (!query && counts[UNLINKED]) {
        items.push({
            key: UNLINKED, id: '', name: 'Unlinked panoramas', meta: plural(counts[UNLINKED], 'panorama'),
            chip: 'Not in any project', cover: null, latest: latestUpdate(null), menu: false, active: false,
        });
    }
    total.textContent = projects.length ? plural(projects.length, 'project') : '';
    grid.classList.toggle('is-refreshing', state.refreshing);
    if (!items.length) {
        grid.innerHTML = emptyState(state.query.trim());
        return;
    }
    reconcile(grid, items, (item) => item.key, card);
}
