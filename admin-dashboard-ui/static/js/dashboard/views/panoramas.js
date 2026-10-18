import { esc, formatRelative, icon, plural, reconcile } from '../core/dom.js';
import { thumbImg } from '../ui/thumbs.js';
import {
    UNLINKED, accessOf, canManage, findProject, selectedProject, state, visiblePanoramas,
} from '../core/store.js';

const grid = document.getElementById('dash-panoramas');
const title = document.getElementById('dash-panoramas-title');
const count = document.getElementById('dash-panoramas-count');
const actions = document.getElementById('dash-panoramas-actions');

const ACCESS_CHIP = { client: 'Client', broker: 'Broker', viewer: 'View only', admin: 'Admin' };

function card(p, eager) {
    const access = accessOf(p);
    const project = p.workspace_id ? findProject(p.workspace_id) : null;
    const isMain = !!project && Number(project.main_panorama_id) === Number(p.id);
    const opening = String(state.openingId) === String(p.id);
    const plots = Number(p.plot_count || 0);
    return `<article class="dash-pano${isMain ? ' is-main' : ''}${opening ? ' is-opening' : ''}" tabindex="0"
        data-action="open-panorama" data-id="${esc(p.id)}"${canManage(p) ? ' draggable="true"' : ''}
        aria-label="Open ${esc(p.name || 'Untitled')}">
        <div class="dash-pano__thumb">
            <span class="dash-pano__placeholder">${icon('image', 22)}</span>
            ${thumbImg(p, { eager })}
            <span class="dash-pano__tags">
                ${isMain ? '<span class="dash-tag dash-tag--main">Main</span>' : ''}
                <span class="dash-tag">${p.is_360 ? '360°' : 'Flat'}</span>
            </span>
            ${opening ? '<span class="dash-pano__opening"><span class="dash-spinner"></span>Opening…</span>' : ''}
        </div>
        <div class="dash-pano__body">
            <h3 class="dash-pano__name" title="${esc(p.name || 'Untitled')}">${esc(p.name || 'Untitled')}</h3>
            <p class="dash-pano__meta">
                <span>${icon('pin', 13)}${esc(plural(plots, 'plot'))}</span>
                <span>${esc(formatRelative(p.updated_at))}</span>
                ${access !== 'owner' ? `<span class="dash-chip">${esc(ACCESS_CHIP[access] || access)}</span>` : ''}
            </p>
        </div>
        <button type="button" class="dash-icon-btn dash-pano__menu" data-action="panorama-menu" data-id="${esc(p.id)}"
            aria-haspopup="menu" aria-expanded="false" aria-label="Actions for ${esc(p.name || 'Untitled')}">${icon('more', 16)}</button>
    </article>`;
}

function emptyState() {
    const query = state.query.trim();
    if (query) {
        return `<div class="dash-empty">${icon('search', 28)}
            <p class="dash-empty__title">No panoramas match “${esc(query)}”</p>
            <button type="button" class="dash-btn" data-action="clear-search">Clear search</button></div>`;
    }
    if (state.type !== 'all') {
        return `<div class="dash-empty">${icon('image', 28)}
            <p class="dash-empty__title">No ${state.type === '360' ? '360°' : 'flat'} panoramas here</p>
            <button type="button" class="dash-btn" data-action="filter-type" data-type="all">Show all</button></div>`;
    }
    if (!state.selection) {
        return `<div class="dash-empty">${icon('folder', 28)}
            <p class="dash-empty__title">No project selected</p>
            <a class="dash-btn dash-btn--primary" href="/projectselection">Choose a project</a></div>`;
    }
    if (state.builder) {
        return `<div class="dash-empty">${icon('upload', 28)}
            <p class="dash-empty__title">No panoramas in ${state.selection === UNLINKED ? 'this list' : 'this project'} yet</p>
            <button type="button" class="dash-btn dash-btn--primary" data-action="upload">${icon('upload', 16)}<span>Upload panoramas</span></button></div>`;
    }
    return `<div class="dash-empty">${icon('image', 28)}
        <p class="dash-empty__title">Nothing here yet</p>
        <p class="dash-empty__text">Panoramas shared with you will appear here.</p></div>`;
}

function errorState() {
    return `<div class="dash-empty dash-empty--error">${icon('alert', 28)}
        <p class="dash-empty__title">We couldn’t load your projects</p>
        <p class="dash-empty__text">${esc(state.error || 'Check your connection and try again.')}</p>
        <button type="button" class="dash-btn dash-btn--primary" data-action="retry">Try again</button></div>`;
}

function renderHeader(list) {
    const query = state.query.trim();
    const project = selectedProject();
    if (state.selection === UNLINKED) title.textContent = 'Unlinked panoramas';
    else title.textContent = project ? project.name : 'Panoramas';
    if (query) title.textContent += ` · “${query}”`;
    count.textContent = state.status === 'ready' ? plural(list.length, 'panorama') : '';
    const canUploadHere = state.builder && !query && (state.selection === UNLINKED || (project && accessOf(project) === 'owner'));
    actions.innerHTML = canUploadHere && list.length
        ? `<button type="button" class="dash-btn dash-btn--sm" data-action="upload">${icon('upload', 14)}<span>Upload here</span></button>`
        : '';
}

export function renderPanoramas() {
    if (state.status === 'loading') {
        // Retrying after an error: swap the message for a spinner right away.
        if (grid.querySelector('.dash-empty--error')) {
            grid.innerHTML = '<div class="dash-empty"><span class="dash-spinner"></span><p class="dash-empty__text">Loading your projects…</p></div>';
        }
        return;
    }
    if (state.status === 'error') {
        title.textContent = 'Panoramas';
        count.textContent = '';
        actions.innerHTML = '';
        grid.innerHTML = errorState();
        return;
    }
    const list = visiblePanoramas();
    renderHeader(list);
    grid.classList.toggle('is-refreshing', state.refreshing);
    if (!list.length) {
        grid.innerHTML = emptyState();
        return;
    }
    // The first rows are above the fold (and hold the LCP image): load them eagerly at high priority.
    const eager = new Set(list.slice(0, 8).map((p) => p.id));
    reconcile(grid, list, (p) => p.id, (p) => card(p, eager.has(p.id)));
}
