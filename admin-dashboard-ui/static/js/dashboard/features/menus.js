import { accessOf, canManage, findProject, mainPanoramaId, state } from '../core/store.js';

const OPEN_LABELS = { owner: 'Open editor', client: 'Open as client' };

/** Project card menu on /projectselection: customer view, every share link, then management. */
export function projectMenuItems(project) {
    const access = accessOf(project);
    const manage = canManage(project);
    const hasMain = !!mainPanoramaId(project);
    const id = encodeURIComponent(project.id);
    const items = [];
    if (manage && hasMain) items.push({ label: 'Set customer view', href: `/customer/edit/${id}` });
    const share = [];
    if (manage) {
        share.push(
            { label: 'Copy Full View link', action: 'copy-fullview-link' },
            { label: 'Create custom link', action: 'create-share-link' },
        );
    }
    if (hasMain && (manage || access === 'client' || access === 'broker')) {
        share.push({ label: 'Share reference link', action: 'share-project' });
    }
    if (manage) share.push({ label: 'Open Full View ↗', href: `/customer/full-view/${id}`, newTab: true });
    if (share.length) {
        if (items.length) items.push({ divider: true });
        items.push(...share);
    }
    if (manage) {
        items.push(
            { divider: true },
            { label: 'Manage access', action: 'manage-access' },
            { label: 'Edit details', action: 'edit-project' },
            { label: 'Rename', action: 'rename-project' },
            { divider: true },
            { label: 'Delete project', action: 'delete-project', danger: true },
        );
    }
    return items;
}

export function panoramaMenuItems(panorama) {
    const access = accessOf(panorama);
    const items = [{ label: OPEN_LABELS[access] || 'Open customer view', action: 'open-panorama' }];
    if (!canManage(panorama)) return items;
    const project = panorama.workspace_id ? findProject(panorama.workspace_id) : null;
    if (project && Number(project.main_panorama_id) !== Number(panorama.id)) {
        items.push({ label: 'Set as project main', action: 'set-main' });
    }
    const ownedProjects = state.projects.filter((p) => accessOf(p) === 'owner');
    if (ownedProjects.length) items.push({ label: 'Move to project…', action: 'move-panorama' });
    items.push(
        { label: 'Manage access', href: `/panorama/${encodeURIComponent(panorama.id)}/access` },
        { label: 'Rename', action: 'rename-panorama' },
        { divider: true },
        { label: 'Delete', action: 'delete-panorama', danger: true },
    );
    return items;
}
