/**
 * Project access by organization (client group): every member of a granted organization can open
 * the project, and people who join it later inherit that access. Each change saves immediately.
 */
import { api } from '../core/api.js';
import { esc, plural } from '../core/dom.js';
import { findProject } from '../core/store.js';
import { openModal } from '../ui/modal.js';
import { toast } from '../ui/toast.js';

const LEVELS = [
    { value: '', label: 'No access' },
    { value: 'client', label: 'Full access' },
    { value: 'viewer', label: 'View only' },
];
const SEARCH_THRESHOLD = 6;

function initials(name) {
    return String(name || '?').trim().split(/\s+/).slice(0, 2).map((w) => w[0]).join('').toUpperCase() || '?';
}

function subtitle(org) {
    if (!org.member_count) return 'No members yet';
    const members = plural(org.member_count, 'member');
    // Some members were granted individually: choosing a level extends it to the whole organization.
    if (!org.access_type && org.granted_count) return `${members} · ${org.granted_count} with individual access`;
    return members;
}

function rowHtml(org) {
    const empty = !org.member_count;
    const options = LEVELS.map((l) => `<option value="${l.value}"${(org.access_type || '') === l.value ? ' selected' : ''}>${l.label}</option>`).join('');
    return `<li class="dash-access__row${org.access_type ? ' has-access' : ''}" data-id="${esc(org.id)}" data-name="${esc(org.name.toLowerCase())}">
        <span class="dash-access__avatar" aria-hidden="true">${esc(initials(org.name))}</span>
        <span class="dash-access__meta">
            <span class="dash-access__name">${esc(org.name)}</span>
            <span class="dash-access__sub">${esc(subtitle(org))}</span>
        </span>
        <select class="dash-input dash-access__level" aria-label="Access for ${esc(org.name)}"${empty && !org.access_type ? ' disabled title="Add members in User Management first"' : ''}>${options}</select>
    </li>`;
}

export function openProjectAccess({ id }) {
    const project = findProject(id);
    let orgs = [];

    openModal('dash-access-modal', {
        onOpen(dialog) {
            const { el } = dialog;
            const list = el.querySelector('[data-access-list]');
            const summary = el.querySelector('[data-access-summary]');
            const searchWrap = el.querySelector('[data-access-search]');
            const filter = el.querySelector('[data-access-filter]');

            dialog.setTitle(project ? `Manage access · ${project.name}` : 'Manage access');
            filter.value = '';
            searchWrap.hidden = true;
            summary.textContent = '';
            list.innerHTML = Array.from({ length: 3 }, () => '<li class="dash-access__row" aria-hidden="true"><span class="dash-skel dash-access__avatar"></span><span class="dash-skel dash-skel--line" style="flex:1"></span></li>').join('');

            const updateSummary = () => {
                const granted = orgs.filter((o) => o.access_type).length;
                summary.textContent = granted
                    ? `Shared with ${plural(granted, 'organization')}`
                    : 'Not shared with any organization yet';
            };
            const applyFilter = () => {
                const q = filter.value.trim().toLowerCase();
                list.querySelectorAll('.dash-access__row[data-id]').forEach((row) => { row.hidden = !!q && !row.dataset.name.includes(q); });
            };
            filter.oninput = applyFilter;

            list.onchange = async (e) => {
                const select = e.target.closest('.dash-access__level');
                if (!select) return;
                const row = select.closest('[data-id]');
                const org = orgs.find((o) => o.id === row.dataset.id);
                const previous = org.access_type || '';
                const level = select.value;
                select.disabled = true;
                row.classList.add('is-saving');
                dialog.setError('');
                try {
                    if (level) await api.grantProjectOrganization(id, org.id, level);
                    else await api.revokeProjectOrganization(id, org.id);
                    org.access_type = level || null;
                    org.granted_count = level ? org.member_count : 0;
                    row.classList.toggle('has-access', !!level);
                    row.querySelector('.dash-access__sub').textContent = subtitle(org);
                    updateSummary();
                    toast(level ? `${org.name} now has ${level === 'viewer' ? 'view-only' : 'full'} access` : `Access removed for ${org.name}`);
                } catch (err) {
                    select.value = previous;
                    dialog.setError(err.message || 'Could not update access.');
                } finally {
                    row.classList.remove('is-saving');
                    select.disabled = !org.member_count && !org.access_type;
                }
            };

            api.projectOrganizations(id).then((data) => {
                orgs = Array.isArray(data) ? data : [];
                // Organizations with access first, then alphabetical.
                orgs.sort((a, b) => (!!b.access_type - !!a.access_type) || a.name.localeCompare(b.name));
                if (!orgs.length) {
                    list.innerHTML = '<li class="dash-empty dash-empty--compact">No organizations yet. Create one in <a href="/user-management" target="_blank" rel="noopener">User Management</a>.</li>';
                    summary.textContent = '';
                    return;
                }
                searchWrap.hidden = orgs.length < SEARCH_THRESHOLD;
                list.innerHTML = orgs.map(rowHtml).join('');
                updateSummary();
            }).catch((err) => {
                list.innerHTML = '';
                dialog.setError(err.message || 'Could not load organizations.');
            });
        },
        onSubmit: () => true,
    });
}
