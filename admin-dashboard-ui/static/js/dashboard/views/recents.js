import { esc, reconcile } from '../core/dom.js';
import { recentPanoramas, state } from '../core/store.js';
import { thumbImg } from '../ui/thumbs.js';

const track = document.getElementById('dash-recents');

function chip(p) {
    return `<button type="button" class="dash-recent" data-action="open-panorama" data-id="${esc(p.id)}" title="${esc(p.name || 'Untitled')}">
        ${thumbImg(p, { eager: true })}
        <span>${esc(p.name || 'Untitled')}</span>
    </button>`;
}

export function renderRecents() {
    if (state.status === 'loading') return;
    const list = state.status === 'ready' ? recentPanoramas() : [];
    track.parentElement.hidden = !list.length;
    reconcile(track, list, (p) => p.id, chip);
}
