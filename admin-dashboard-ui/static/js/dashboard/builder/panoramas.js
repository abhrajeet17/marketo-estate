/** Panorama management: rename, delete (re-assigning the project main), set main, move. */
import { api } from '../core/api.js';
import {
    UNLINKED, accessOf, findPanorama, findProject, patchPanorama, patchProject, projectKey, removePanorama, state,
} from '../core/store.js';
import { refresh } from '../core/sync.js';
import { toast } from '../ui/toast.js';
import { thumbSrc } from '../ui/thumbs.js';
import { choose, confirm, prompt, selectOption } from './dialogs.js';

const quietRefresh = () => refresh().catch(() => {});

function rename({ id }) {
    const panorama = findPanorama(id);
    if (!panorama) return;
    prompt({
        title: 'Rename panorama',
        label: 'Panorama name',
        value: panorama.name || '',
        async onSubmit(name) {
            if (!name) throw new Error('Name is required.');
            await api.renamePanorama(id, name);
            patchPanorama(id, { name });
            toast('Panorama renamed');
        },
    });
}

function remove({ id }) {
    const panorama = findPanorama(id);
    if (!panorama) return;
    const project = panorama.workspace_id ? findProject(panorama.workspace_id) : null;
    const isMain = project && Number(project.main_panorama_id) === Number(id);
    const siblings = isMain
        ? state.panoramas.filter((p) => String(p.workspace_id) === String(project.id) && String(p.id) !== String(id))
        : [];

    const finish = async (newMainId) => {
        await api.deletePanorama(id, newMainId);
        removePanorama(id);
        if (isMain) patchProject(project.id, { main_panorama_id: newMainId ? Number(newMainId) : null });
        toast('Panorama deleted');
        quietRefresh();
    };

    if (siblings.length) {
        choose({
            title: 'Choose a new main panorama',
            description: `“${panorama.name}” is the main panorama of ${project.name}. Shared customer links open the main panorama, so pick a replacement before deleting.`,
            options: siblings.map((p) => ({ value: p.id, label: p.name || 'Untitled', thumb: thumbSrc(p) })),
            submitLabel: 'Delete and set main',
            onSubmit: (value) => finish(Number(value)),
        });
        return;
    }
    confirm({
        title: 'Delete panorama?',
        description: `“${panorama.name || 'Untitled'}” and all of its plot markings will be permanently deleted.`,
        onConfirm: () => finish(null),
    });
}

async function setMain({ id }) {
    const panorama = findPanorama(id);
    if (!panorama || !panorama.workspace_id) return;
    const projectId = panorama.workspace_id;
    const previous = findProject(projectId)?.main_panorama_id ?? null;
    patchProject(projectId, { main_panorama_id: Number(id) });
    try {
        await api.updateProject(projectId, { main_panorama_id: Number(id) });
        toast('Main panorama updated');
    } catch (err) {
        patchProject(projectId, { main_panorama_id: previous });
        toast(err.message || 'Could not set the main panorama', 'error');
    }
}

/** Move a panorama to a project key (`ws:<id>` or UNLINKED). Optimistic, rolled back on failure. */
export async function moveTo(id, targetKey) {
    const panorama = findPanorama(id);
    if (!panorama) return;
    const projectId = targetKey === UNLINKED ? null : targetKey.slice(3);
    if (String(panorama.workspace_id || '') === String(projectId || '')) return;
    const previous = panorama.workspace_id || null;
    patchPanorama(id, { workspace_id: projectId });
    try {
        await api.movePanorama(id, projectId);
        const target = projectId ? findProject(projectId) : null;
        toast(`Moved to ${target ? target.name : 'Unlinked panoramas'}`);
        quietRefresh();
    } catch (err) {
        patchPanorama(id, { workspace_id: previous });
        toast(err.message || 'Could not move the panorama', 'error');
    }
}

function move({ id }) {
    const panorama = findPanorama(id);
    if (!panorama) return;
    const options = [{ value: UNLINKED, label: 'Unlinked (no project)' }].concat(
        state.projects.filter((p) => accessOf(p) === 'owner').map((p) => ({ value: projectKey(p.id), label: p.name })),
    );
    selectOption({
        title: 'Move panorama',
        description: `Choose where “${panorama.name || 'Untitled'}” belongs.`,
        label: 'Project',
        options,
        value: panorama.workspace_id ? projectKey(panorama.workspace_id) : UNLINKED,
        submitLabel: 'Move',
        onSubmit: (key) => moveTo(id, key),
    });
}

export const panoramaActions = {
    'rename-panorama': rename,
    'delete-panorama': remove,
    'set-main': setMain,
    'move-panorama': move,
};
