/** Project management: create / edit details, rename, delete. */
import { api } from '../core/api.js';
import { debounce } from '../core/dom.js';
import { findProject, patchProject, projectKey, removeProject, select } from '../core/store.js';
import { refresh } from '../core/sync.js';
import { openModal } from '../ui/modal.js';
import { toast } from '../ui/toast.js';
import { openProjectAccess } from './access.js';
import { confirm, prompt } from './dialogs.js';

const TEXT_FIELDS = [
    'builder_name', 'project_type', 'location_address', 'location_city', 'location_state', 'google_maps_link',
    'rera_registration', 'total_area', 'launch_date', 'possession_date', 'description', 'contact_phone', 'contact_email',
];
const COORD_PATTERNS = [/@(-?\d+\.\d+),(-?\d+\.\d+)/, /!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)/, /q=(-?\d+\.\d+),(-?\d+\.\d+)/, /place\/(-?\d+\.\d+),(-?\d+\.\d+)/];
const SHORT_LINK = /goo\.gl\/|maps\.app\./i;

const quietRefresh = () => refresh().catch(() => {});

function coordsFromLink(link) {
    for (const pattern of COORD_PATTERNS) {
        const m = link.match(pattern);
        if (m) return { lat: parseFloat(m[1]), lng: parseFloat(m[2]) };
    }
    return null;
}

function fillForm(form, project) {
    form.elements.name.value = project.name || '';
    for (const name of TEXT_FIELDS) form.elements[name].value = project[name] ?? '';
    form.elements.launch_date.value = String(project.launch_date || '').slice(0, 10);
    if (!form.elements.project_type.value) form.elements.project_type.value = 'residential';
    const amenities = project.amenities;
    form.elements.amenities.value = Array.isArray(amenities) ? amenities.join(', ') : (amenities || '');
    form.elements.is_published.checked = !!project.is_published;
}

function readForm(form) {
    const payload = { name: form.elements.name.value.trim() };
    for (const name of TEXT_FIELDS) payload[name] = form.elements[name].value.trim();
    payload.amenities = form.elements.amenities.value.split(',').map((s) => s.trim()).filter(Boolean);
    payload.is_published = form.elements.is_published.checked;
    const coords = coordsFromLink(payload.google_maps_link);
    if (coords) {
        payload.location_lat = coords.lat;
        payload.location_lng = coords.lng;
    }
    return payload;
}

/** Live feedback for the Google Maps link; short links are resolved server-side and fill empty address fields. */
function bindMapsLink(form) {
    const input = form.elements.google_maps_link;
    const status = form.querySelector('[data-maps-status]');
    const show = (text, tone = '') => {
        status.textContent = text;
        status.dataset.tone = tone;
    };
    const resolve = debounce(async (link) => {
        try {
            const data = await api.resolveMapsLink(link);
            if (input.value.trim() !== link) return;
            if (data.lat == null || data.lng == null) throw new Error(data.error);
            show(`Location found: ${data.lat.toFixed(6)}, ${data.lng.toFixed(6)}`, 'ok');
            const fill = { location_address: data.address, location_city: data.city, location_state: data.state };
            for (const [name, value] of Object.entries(fill)) {
                if (value && !form.elements[name].value.trim()) form.elements[name].value = value;
            }
        } catch (err) {
            if (input.value.trim() === link) show('Could not read a location from this link', 'warn');
        }
    }, 500);
    const check = () => {
        const link = input.value.trim();
        const coords = link && coordsFromLink(link);
        if (!link) show('');
        else if (coords) show(`Location found: ${coords.lat.toFixed(6)}, ${coords.lng.toFixed(6)}`, 'ok');
        else if (SHORT_LINK.test(link)) { show('Resolving link…'); resolve(link); }
        else show('Could not read a location from this link', 'warn');
    };
    input.addEventListener('input', check);
    return check;
}

let checkMapsLink = null;

function openProjectForm(projectId) {
    const editing = !!projectId;
    openModal('dash-project-modal', {
        onOpen(dialog) {
            const { form } = dialog;
            if (!checkMapsLink) checkMapsLink = bindMapsLink(form);
            form.reset();
            dialog.setTitle(editing ? 'Edit project' : 'New project');
            dialog.setDescription(editing
                ? 'Changes appear on the customer portal once the project is published.'
                : 'Group panoramas into a project. Details appear on the customer portal.');
            dialog.setSubmitLabel(editing ? 'Save changes' : 'Create project');
            const details = form.querySelector('[data-details]');
            const fields = form.querySelector('[data-details-fields]');
            const loading = form.querySelector('[data-details-loading]');
            details.open = editing;
            checkMapsLink();
            if (!editing) return;

            // Open instantly with what we know, then load the full record.
            form.elements.name.value = findProject(projectId)?.name || '';
            fields.disabled = true;
            loading.hidden = false;
            dialog.submit.disabled = true;
            api.project(projectId)
                .then((project) => {
                    fillForm(form, project);
                    checkMapsLink();
                })
                .catch((err) => dialog.setError(err.message || 'Could not load project details.'))
                .finally(() => {
                    fields.disabled = false;
                    loading.hidden = true;
                    dialog.submit.disabled = false;
                });
        },
        async onSubmit(form) {
            const payload = readForm(form);
            if (editing) {
                await api.updateProject(projectId, payload);
                patchProject(projectId, { name: payload.name });
                toast('Project updated');
            } else {
                const created = await api.createProject(payload);
                toast('Project created');
                await refresh().catch(() => {});
                if (created && created.workspace && created.workspace.id) select(projectKey(created.workspace.id));
                return;
            }
            quietRefresh();
        },
    });
}

function renameProject({ id }) {
    const project = findProject(id);
    if (!project) return;
    prompt({
        title: 'Rename project',
        label: 'Project name',
        value: project.name,
        async onSubmit(name) {
            if (!name) throw new Error('Name is required.');
            await api.updateProject(id, { name });
            patchProject(id, { name });
            toast('Project renamed');
        },
    });
}

function deleteProject({ id }) {
    const project = findProject(id);
    if (!project) return;
    confirm({
        title: 'Delete project?',
        description: `“${project.name}” will be deleted. Its panoramas are kept and moved to Unlinked panoramas.`,
        confirmLabel: 'Delete project',
        async onConfirm() {
            await api.deleteProject(id);
            removeProject(id);
            toast('Project deleted');
            quietRefresh();
        },
    });
}

export const projectActions = {
    'new-project': () => openProjectForm(null),
    'edit-project': ({ id }) => openProjectForm(id),
    'rename-project': renameProject,
    'delete-project': deleteProject,
    'manage-access': openProjectAccess,
};
