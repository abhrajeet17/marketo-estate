/** Editing tools: registers builder actions and wires drag-and-drop between projects. */
import { registerActions } from '../core/actions.js';
import { canManage, findPanorama, whenReady } from '../core/store.js';
import { moveTo, panoramaActions } from './panoramas.js';
import { projectActions } from './projects.js';
import { openUpload } from './upload.js';

function bindDragAndDrop(root) {
    let draggingId = null;
    const clearTargets = () => root.querySelectorAll('.is-drop-target').forEach((el) => el.classList.remove('is-drop-target'));

    root.addEventListener('dragstart', (e) => {
        const card = e.target.closest('.dash-pano[draggable="true"]');
        if (!card) return;
        draggingId = card.dataset.id;
        e.dataTransfer.effectAllowed = 'move';
        e.dataTransfer.setData('text/plain', draggingId);
        card.classList.add('is-dragging');
    });
    root.addEventListener('dragend', (e) => {
        e.target.closest?.('.dash-pano')?.classList.remove('is-dragging');
        draggingId = null;
        clearTargets();
    });
    root.addEventListener('dragover', (e) => {
        const target = draggingId && e.target.closest('[data-drop]');
        if (!target) return;
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';
        if (!target.classList.contains('is-drop-target')) {
            clearTargets();
            target.classList.add('is-drop-target');
        }
    });
    root.addEventListener('dragleave', (e) => {
        const target = e.target.closest('[data-drop]');
        if (target && !target.contains(e.relatedTarget)) target.classList.remove('is-drop-target');
    });
    root.addEventListener('drop', (e) => {
        const target = draggingId && e.target.closest('[data-drop]');
        if (!target) return;
        e.preventDefault();
        const panorama = findPanorama(draggingId);
        clearTargets();
        if (panorama && canManage(panorama)) moveTo(panorama.id, target.dataset.drop);
    });
}

export function installBuilder(root) {
    registerActions({ upload: openUpload, ...projectActions, ...panoramaActions });
    bindDragAndDrop(root);

    // Sidebar "Upload" opens the dialog in place; from other pages it links here with ?upload=1.
    const sidebarUpload = document.getElementById('sidebar-upload-link');
    if (sidebarUpload) {
        sidebarUpload.addEventListener('click', (e) => {
            e.preventDefault();
            openUpload();
        });
    }
    const params = new URLSearchParams(window.location.search);
    if (params.get('upload') === '1') {
        params.delete('upload');
        const query = params.toString();
        window.history.replaceState(null, '', window.location.pathname + (query ? `?${query}` : ''));
        whenReady().then(openUpload);
    }
}
