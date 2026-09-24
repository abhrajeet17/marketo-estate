/**
 * CRM records — Interests, Deals and Contacts on the unified crm_leads table.
 *
 * One record type, two statuses (interest | deal). Interests and deals share
 * the same drawer (view / edit), the same filters and the same list API:
 *   GET /api/crm/leads?status=interest|deal
 *
 * Exposed on window.CrmRecords for crm.html (tab loader, boot, lock modal):
 *   loadTab(name, force), refreshIfStale(force), reset(), preload(force),
 *   setProjects(list), setTeamUsers(list), setProfile(me), getCachedRows(),
 *   openRecord(recordOrId), exportActiveTab()
 */
(function (global) {
    'use strict';

    const $ = (id) => document.getElementById(id);
    const API_LEADS = '/api/crm/leads';
    const STAGES = ['new', 'contacted', 'site_visit', 'negotiation', 'won', 'lost'];
    const STAGE_LABELS = { new: 'New', contacted: 'Contacted', site_visit: 'Site Visit', negotiation: 'Negotiation', won: 'Won', lost: 'Lost' };
    const ROLE_LABELS = { broker: 'Broker', client_admin: 'Client Admin', client_user: 'Sales Agent' };
    const STALE_MS = 5 * 60 * 1000;
    const KANBAN_LIMIT = 500;
    const HIDDEN_LABEL = 'Hidden until broker reveals';

    const SVG = (body, size) => '<svg width="' + (size || 14) + '" height="' + (size || 14) + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + body + '</svg>';
    const ICON = {
        edit: SVG('<path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.12 2.12 0 0 1 3 3L12 15l-4 1 1-4Z"/>'),
        view: SVG('<path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7-11-7-11-7Z"/><circle cx="12" cy="12" r="3"/>'),
        save: SVG('<polyline points="20 6 9 17 4 12"/>', 15),
        plus: SVG('<line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>', 13),
        lock: SVG('<rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>', 12),
        pin: SVG('<path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/>', 12),
    };

    // ------------------------------------------------------------------ utils
    function esc(v) {
        return String(v == null ? '' : v)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }
    function fmtDate(iso) {
        try { const d = new Date(iso); return isNaN(d.getTime()) ? String(iso || '—') : d.toLocaleString(undefined, { year: 'numeric', month: 'short', day: '2-digit' }); } catch (e) { return String(iso || '—'); }
    }
    function fmtTime(iso) {
        try { const d = new Date(iso); return isNaN(d.getTime()) ? '' : d.toLocaleString(undefined, { hour: '2-digit', minute: '2-digit' }); } catch (e) { return ''; }
    }
    function fmtRelative(iso) {
        try {
            const d = new Date(iso);
            if (isNaN(d.getTime())) return '';
            const mins = Math.floor((Date.now() - d.getTime()) / 60000);
            if (mins < 1) return 'just now';
            if (mins < 60) return mins + 'm ago';
            const hrs = Math.floor(mins / 60);
            if (hrs < 24) return hrs + 'h ago';
            const days = Math.floor(hrs / 24);
            if (days < 30) return days + 'd ago';
            return fmtDate(iso);
        } catch (e) { return ''; }
    }
    function fmtBirthday(value) {
        const raw = String(value || '').trim();
        if (!raw) return '';
        const d = new Date(raw.length > 10 ? raw : raw + 'T00:00:00');
        if (isNaN(d.getTime())) return raw;
        return d.toLocaleDateString(undefined, { day: '2-digit', month: 'short', year: 'numeric' });
    }
    function initials(name) {
        const parts = String(name || '').trim().split(/\s+/).filter(Boolean);
        if (!parts.length) return '?';
        return (parts.length >= 2 ? parts[0][0] + parts[parts.length - 1][0] : parts[0].slice(0, 2)).toUpperCase();
    }
    function normalizeText(v) { return String(v || '').trim().toLowerCase(); }
    function toast(msg, type) {
        if (typeof global.showToast === 'function') { global.showToast(msg, type); return; }
        if (type === 'error') console.error(msg); else console.log(msg);
    }
    async function api(path, opts) {
        if (typeof global.crmFetch === 'function') return global.crmFetch(path, opts);
        const headers = await global.ensureAuthenticated();
        return fetch(path, Object.assign({ headers: Object.assign({ 'Content-Type': 'application/json' }, headers || {}) }, opts || {}));
    }
    async function apiJson(path, opts) {
        const r = await api(path, opts);
        const data = await r.json().catch(() => null);
        if (!r.ok) {
            const err = new Error((data && data.error) || ('Request failed (' + r.status + ')'));
            err.status = r.status;
            err.field = data && data.field;
            throw err;
        }
        return data || {};
    }
    function setBusy(btn, busy, label) {
        if (!btn) return;
        if (busy) {
            if (!btn.dataset.busyHtml) btn.dataset.busyHtml = btn.innerHTML;
            btn.disabled = true;
            btn.classList.add('is-busy');
            if (label) btn.setAttribute('aria-label', label);
        } else {
            if (btn.dataset.busyHtml) { btn.innerHTML = btn.dataset.busyHtml; delete btn.dataset.busyHtml; }
            btn.disabled = false;
            btn.classList.remove('is-busy');
            btn.removeAttribute('aria-label');
        }
    }
    function toggleHidden(el, hidden) { if (el) el.hidden = !!hidden; }
    function debounce(fn, ms) { let t = null; return function () { const args = arguments; clearTimeout(t); t = setTimeout(() => fn.apply(null, args), ms); }; }
    function plotKey(p, idx) {
        if (!p) return 'idx:' + (idx || 0);
        if (p.normal_plot_id != null && String(p.normal_plot_id).trim()) return 'normal:' + String(p.normal_plot_id).trim();
        const pid = String((p.plot_id != null ? p.plot_id : p.id) || '').trim();
        if (pid) return 'id:' + pid;
        const nm = normalizeText(p.name);
        return nm ? 'name:' + nm : 'idx:' + (idx || 0);
    }
    function plotLabel(p) {
        const name = String((p && p.name) || '').trim();
        if (name) return name;
        const pid = p && (p.plot_id != null ? p.plot_id : p.id);
        return pid != null && pid !== '' ? 'Plot #' + pid : 'Plot';
    }
    function plotStatusTone(status) {
        const k = String(status || '').toLowerCase().replace(/[^a-z]/g, '');
        if (k === 'sold') return ['lost', 'Sold'];
        if (k === 'hold' || k === 'onhold' || k === 'reserved') return ['contacted', 'Hold'];
        return ['won', 'Available'];
    }
    function plotStatusPill(status) { const t = plotStatusTone(status); return '<span class="rec-pill rec-pill--' + t[0] + '">' + esc(t[1]) + '</span>'; }
    function stagePill(stage) {
        const s = STAGES.includes(String(stage || '')) ? String(stage) : 'new';
        return '<span class="rec-pill rec-pill--' + esc(s) + '"><span class="dot"></span>' + esc(STAGE_LABELS[s]) + '</span>';
    }
    function statusPill(rec) {
        return rec.is_deal
            ? '<span class="rec-pill rec-pill--deal"><span class="dot"></span>Deal</span>'
            : '<span class="rec-pill rec-pill--interest"><span class="dot"></span>Interest</span>';
    }
    function rolePill(rec) {
        const role = String((rec && rec.reference_user_role) || '').trim();
        const label = (rec && rec.reference_user_role_label) || ROLE_LABELS[role] || '';
        if (!label) return '<span class="rec-empty">—</span>';
        return '<span class="rec-role rec-role--' + esc(role) + '">' + esc(label) + '</span>';
    }
    function contactCell(rec) {
        if (rec.contact_hidden) return '<span class="rec-hidden">' + ICON.lock + esc(rec.contact_hidden_label || HIDDEN_LABEL) + '</span>';
        const email = rec.customer_email ? '<div class="rec-cell-truncate">' + esc(rec.customer_email) + '</div>' : '';
        const phone = rec.customer_phone ? '<div class="rec-cell-sub mono">' + esc(rec.customer_phone) + '</div>' : '';
        return (email + phone) || '<span class="rec-empty">—</span>';
    }
    function plotsCell(rec) {
        const plots = Array.isArray(rec.plots) ? rec.plots : [];
        if (!plots.length) return '<span class="rec-empty">—</span>';
        const names = plots.map(plotLabel);
        const label = plots.length === 1 ? names[0] : plots.length + ' plots';
        return '<span class="rec-plots-chip" title="' + esc(names.join(', ')) + '">' + ICON.pin + esc(label) + '</span>';
    }
    function projectCell(rec) {
        const main = rec.workspace_name || rec.panorama_name || (rec.panorama_id ? 'Project #' + rec.panorama_id : '—');
        const sub = rec.workspace_name && rec.panorama_name && rec.workspace_name !== rec.panorama_name ? rec.panorama_name : '';
        return '<div class="rec-cell-primary rec-cell-truncate">' + esc(main) + '</div>' + (sub ? '<div class="rec-cell-sub">' + esc(sub) + '</div>' : '');
    }
    function referenceCell(rec) {
        if (!rec.reference_user_id) return '<span class="rec-empty">—</span>';
        return '<div class="rec-cell-truncate">' + esc(rec.reference_user_name || 'Reference') + '</div>';
    }
    function actionButton(rec) {
        const edit = rec.can_edit;
        return '<button class="btn plot-row-action-btn" type="button" data-open-record="' + esc(rec.id) + '" title="' + (edit ? 'Open and edit' : 'View') + '" aria-label="' + (edit ? 'Open record' : 'View record') + '">' + (edit ? ICON.edit : ICON.view) + '<span>' + (edit ? 'Edit' : 'View') + '</span></button>';
    }
    function stageSlug(label) { return String(label || '').trim().toLowerCase().replace(/-/g, '_').replace(/\s+/g, '_'); }
    function refUserLabel(u) {
        if (!u) return 'Reference';
        const name = String(u.display_name || u.email || 'Reference').trim();
        const meta = [];
        if (u.member_role_label) meta.push(u.member_role_label);
        if (Array.isArray(u.client_group_names) && u.client_group_names.length) meta.push(u.client_group_names.join(', '));
        return meta.length ? name + ' (' + meta.join(' · ') + ')' : name;
    }

    // ------------------------------------------------------------------ state
    const TABS = {
        interests: {
            status: 'interest', sortKey: 'interests', exportName: 'CRM_Interests', sheet: 'Interests', cols: 9,
            ids: { tbody: 'tbody', pagination: 'interests-pagination', empty: 'table-empty', meta: 'interests-results-meta', card: 'interests-table-card', search: 'q', filterRoot: 'interests-filter-fields', filterBtn: 'btn-open-filters', badge: 'interests-filter-badge', apply: 'btn-apply-filters', clear: 'btn-clear', exportBtn: 'btn-export-interests', rail: 'interests', tabBtn: 'tab-interests' },
        },
        deals: {
            status: 'deal', sortKey: 'deals', exportName: 'CRM_Deals', sheet: 'Deals', cols: 10,
            ids: { tbody: 'deals-tbody', pagination: 'deals-pagination', empty: 'deals-empty', meta: 'deals-results-meta', card: 'deals-table-card', search: 'deal-q', filterRoot: 'deals-filter-fields', filterBtn: 'btn-open-deals-filter-modal', badge: 'deals-filter-badge', apply: 'deals-filter-apply', clear: 'deals-filter-clear', exportBtn: 'btn-export-deals', rail: 'deals', tabBtn: 'tab-deals' },
        },
        contacts: {
            status: 'deal', sortKey: 'contacts', exportName: 'CRM_Contacts', sheet: 'Contacts', cols: 9,
            ids: { tbody: 'contacts-tbody', pagination: 'contacts-pagination', empty: 'contacts-empty', meta: 'contacts-results-meta', card: 'contacts-table-card', search: 'contact-q', filterRoot: 'contacts-filter-fields', filterBtn: 'btn-open-contacts-filter-modal', badge: 'contacts-filter-badge', apply: 'contacts-filter-apply', clear: 'contacts-filter-clear', exportBtn: 'btn-export-contacts', rail: 'contacts', tabBtn: 'tab-contacts' },
        },
    };

    const state = {
        me: null,
        caps: { canManageDeals: false, isBroker: false, isPlatformAdmin: false, brokerOnly: false },
        projects: [],
        projectById: new Map(),
        teamUsers: [],
        masters: new Map(),
        mastersInflight: new Map(),
        filterMasters: null,
        filterMastersPromise: null,
        refUsers: new Map(),
        normalProjects: null,
        lastLoadedAt: 0,
        activeTab: 'interests',
        dealsView: 'list',
        kanban: { rows: [], loaded: false, promise: null, seq: 0, stale: false },
        drawer: { record: null, tabKey: null, mode: 'view', masters: [], refUsers: [], pendingPlots: null, seq: 0, quotesSeq: 0 },
        convert: { record: null, plots: [] },
        addPlots: { record: null, source: null, all: [], selected: new Set(), attached: new Set(), seq: 0 },
        addInterest: { plots: [], selected: new Set(), refUsers: [], masters: [], seq: 0 },
        deleteTarget: null,
        tabs: {},
    };
    Object.keys(TABS).forEach((key) => {
        state.tabs[key] = {
            key, cfg: TABS[key], rows: [], meta: { total: 0, pages: 1 },
            pager: { page: 1, size: (global.CrmPager && global.CrmPager.DEFAULT_SIZE) || 10 },
            filters: [], draft: {}, q: '', fieldSearch: '', facets: null, loaded: false, stale: false, promise: null, seq: 0,
        };
    });

    // ---------------------------------------------------------------- profile
    function applyProfile(me) {
        if (!me || typeof me !== 'object') return;
        state.me = me;
        const role = String(me.role || '').toLowerCase();
        const platformAdmin = role === 'admin' || role === 'superadmin';
        const isBroker = !!me.is_broker || role === 'broker';
        const canManage = typeof me.can_manage_deals === 'boolean' ? me.can_manage_deals : (platformAdmin || !!me.is_client_admin || !!me.is_client_user);
        state.caps = {
            canManageDeals: canManage,
            isBroker,
            isPlatformAdmin: platformAdmin,
            brokerOnly: isBroker && !canManage,
        };
        document.querySelectorAll('#deals-kanban-board .kanban-col').forEach(col => col.classList.toggle('is-locked', !canManage));
    }
    async function ensureProfile() {
        if (state.me) return state.me;
        if (global.__crmMeData && typeof global.__crmMeData === 'object') { applyProfile(global.__crmMeData); return state.me; }
        try {
            const me = await apiJson('/api/crm/me');
            global.__crmMeData = me;
            applyProfile(me);
        } catch (e) { /* caps stay conservative */ }
        return state.me;
    }

    // ---------------------------------------------------------------- filters
    // Zoho-style: a searchable checklist of fields. Ticking a field reveals an
    // operator dropdown plus a value control; conditions are ANDed on the
    // server via GET /api/crm/leads?filters=[{field,op,value,value2}].
    const OPS = {
        text: [['contains', 'contains'], ['not_contains', "doesn't contain"], ['is', 'is'], ['isnt', "isn't"], ['starts_with', 'starts with'], ['ends_with', 'ends with'], ['empty', 'is empty'], ['not_empty', 'is not empty']],
        select: [['is', 'is'], ['isnt', "isn't"], ['empty', 'is empty'], ['not_empty', 'is not empty']],
        plot: [['is', 'is'], ['isnt', "isn't"], ['empty', 'is empty'], ['not_empty', 'is not empty']],
        date: [['on', 'is on'], ['after', 'is after'], ['before', 'is before'], ['between', 'is between'], ['empty', 'is empty'], ['not_empty', 'is not empty']],
    };
    const NO_VALUE_OPS = new Set(['empty', 'not_empty']);
    const DEFAULT_OP = { text: 'contains', select: 'is', plot: 'is', date: 'on' };
    // Master keys that live in real columns (everything else is custom_fields).
    const MASTER_COLUMN_KEYS = { lead_source: 1, lead_category: 1, lead_status: 1, campaign_type: 1, campaign_status: 1, state: 1, country: 1, title: 1 };
    const MASTER_SKIP_KEYS = new Set(['deal_stage', 'plot_status', 'builder_name', 'project_type']);

    async function ensureFilterMasters() {
        if (state.filterMasters) return state.filterMasters;
        if (state.filterMastersPromise) return state.filterMastersPromise;
        state.filterMastersPromise = loadMastersFor(null)
            .then(list => { state.filterMasters = Array.isArray(list) ? list : []; return state.filterMasters; })
            .catch(() => { state.filterMasters = []; return state.filterMasters; })
            .finally(() => { state.filterMastersPromise = null; });
        return state.filterMastersPromise;
    }
    function masterValueList(m) {
        return (m && Array.isArray(m.values)) ? m.values.filter(v => v && v.is_enabled !== false).map(v => String(v.value || '').trim()).filter(Boolean) : [];
    }
    function filterFieldDefs(tab) {
        const f = tab.facets || {};
        const isDeal = tab.cfg.status === 'deal';
        const masters = (state.filterMasters || []).filter(m => m && m.is_enabled !== false);
        const masterByKey = (k) => masters.find(m => String(m.field_key || '') === k) || null;
        const pairs = (arr) => (arr || []).map(x => Array.isArray(x) ? x : [x, x]);
        const masterOrText = (key, label, masterKey, suggestions) => {
            const m = masterByKey(masterKey);
            const values = masterValueList(m);
            const finalLabel = (m && m.label) || label;
            if (values.length) return { key, label: finalLabel, type: 'select', options: pairs(values) };
            return { key, label: finalLabel, type: 'text', suggest: suggestions || [] };
        };
        const defs = [
            { key: 'customer_name', label: 'Customer Name', type: 'text' },
            { key: 'customer_email', label: 'Email', type: 'text' },
            { key: 'customer_phone', label: 'Phone', type: 'text' },
            masterOrText('title', 'Title', 'title'),
            { key: 'category', label: 'Category', type: 'text', suggest: f.categories || [] },
            masterOrText('lead_source', 'Lead Source', 'lead_source', f.lead_sources),
            masterOrText('lead_category', 'Lead Category', 'lead_category', f.lead_categories),
            masterOrText('lead_status', 'Lead Status', 'lead_status', f.lead_statuses),
            masterOrText('campaign_type', 'Campaign Type', 'campaign_type', f.campaign_types),
            masterOrText('campaign_status', 'Campaign Status', 'campaign_status', f.campaign_statuses),
            { key: 'customer_city', label: 'City', type: 'text' },
            masterOrText('customer_state', 'State', 'state'),
            masterOrText('customer_country', 'Country', 'country'),
            { key: 'customer_zip_code', label: 'Zip Code', type: 'text' },
            { key: 'workspace_id', label: 'Project', type: 'select', options: (f.workspaces || []).map(w => [w.id, w.name]) },
            { key: 'panorama_id', label: 'Sector', type: 'select', options: (f.panoramas || []).map(p => [String(p.id), p.name]) },
            { key: 'plot_id', label: 'Plot', type: 'plot', options: (f.plots || []).map(p => [p.id, p.name]) },
            { key: 'reference_user_id', label: 'Reference', type: 'select', options: (f.references || []).map(r => [r.id, r.name + (r.role_label ? ' · ' + r.role_label : '')]) },
            { key: 'reference_user_role', label: 'Ref Role', type: 'select', options: (f.reference_roles || []).map(r => [r.key, r.label]) },
            { key: 'description', label: 'Description', type: 'text' },
            { key: 'notes', label: 'Notes', type: 'text' },
            { key: 'created_at', label: 'Created Time', type: 'date' },
            { key: 'customer_birthday', label: 'Birthday', type: 'date' },
        ];
        if ((f.clients || []).length > 1) defs.push({ key: 'client_id', label: 'Client', type: 'select', options: (f.clients || []).map(c => [c.id, c.name]) });
        if (isDeal) {
            defs.push(
                { key: 'deal_title', label: 'Deal Name', type: 'text' },
                { key: 'deal_stage', label: 'Stage', type: 'select', options: (f.stages || []).map(st => [st.key, st.label + (st.count ? ' (' + st.count + ')' : '')]) },
                { key: 'deal_amount', label: 'Amount', type: 'text' },
                { key: 'deal_project_name', label: 'Deal Project', type: 'text' },
                { key: 'converted_at', label: 'Converted Time', type: 'date' }
            );
        }
        masters.forEach(m => {
            const key = String(m.field_key || '').trim();
            if (!key || MASTER_SKIP_KEYS.has(key) || MASTER_COLUMN_KEYS[key]) return;
            const applies = Array.isArray(m.applies_to) ? m.applies_to.map(x => String(x || '').toLowerCase()) : ['interests'];
            if (!applies.includes('interests') && !(isDeal && applies.includes('deals'))) return;
            const values = masterValueList(m);
            defs.push({ key: 'cf.' + key, label: m.label || key, type: values.length ? 'select' : 'text', options: pairs(values), custom: true });
        });
        defs.sort((a, b) => String(a.label).localeCompare(String(b.label)));
        return defs;
    }
    function fieldDomId(key) { return 'zf-' + key.replace(/[^a-z0-9_]/gi, '-'); }
    function readDraft(tab) {
        const root = $(tab.cfg.ids.filterRoot);
        const draft = {};
        if (!root) return draft;
        root.querySelectorAll('.zf-field.is-active').forEach(el => {
            const key = el.getAttribute('data-field');
            const opEl = el.querySelector('.zf-op');
            const v1 = el.querySelector('[data-zf-value]');
            const v2 = el.querySelector('[data-zf-value2]');
            draft[key] = { op: opEl ? opEl.value : '', value: v1 ? String(v1.value || '').trim() : '', value2: v2 ? String(v2.value || '').trim() : '' };
        });
        return draft;
    }
    function draftToConditions(defs, draft) {
        const byKey = new Map(defs.map(d => [d.key, d]));
        const out = [];
        Object.keys(draft || {}).forEach(key => {
            const def = byKey.get(key);
            const d = draft[key];
            if (!def || !d || !d.op) return;
            if (!NO_VALUE_OPS.has(d.op) && !d.value) return;
            if (d.op === 'between' && !d.value2) return;
            const c = { field: key, op: d.op };
            if (!NO_VALUE_OPS.has(d.op)) c.value = d.value;
            if (d.op === 'between') c.value2 = d.value2;
            out.push(c);
        });
        return out;
    }
    function renderFilterValue(def, op, d) {
        if (NO_VALUE_OPS.has(op)) return '<div class="zf-empty-note">No value needed.</div>';
        const v = (d && d.value) || '';
        const v2 = (d && d.value2) || '';
        if (def.type === 'date') {
            const one = '<input type="date" class="zf-input" data-zf-value value="' + esc(v) + '" aria-label="' + esc(def.label) + ' date">';
            if (op === 'between') return '<div class="zf-range">' + one + '<span>and</span><input type="date" class="zf-input" data-zf-value2 value="' + esc(v2) + '" aria-label="' + esc(def.label) + ' end date"></div>';
            return one;
        }
        if (def.type === 'select' || def.type === 'plot') {
            const opts = def.options || [];
            const has = opts.some(o => String(o[0]) === v);
            return '<select class="zf-input" data-zf-value aria-label="' + esc(def.label) + ' value"><option value="">Select ' + esc(String(def.label).toLowerCase()) + '</option>' +
                opts.map(o => '<option value="' + esc(o[0]) + '"' + (String(o[0]) === v ? ' selected' : '') + '>' + esc(o[1]) + '</option>').join('') +
                (v && !has ? '<option value="' + esc(v) + '" selected>' + esc(v) + '</option>' : '') + '</select>';
        }
        const listId = def.suggest && def.suggest.length ? fieldDomId(def.key) + '-list' : '';
        return '<input type="text" class="zf-input" data-zf-value value="' + esc(v) + '" placeholder="Type a value" aria-label="' + esc(def.label) + ' value"' + (listId ? ' list="' + listId + '"' : '') + '>' +
            (listId ? '<datalist id="' + listId + '">' + def.suggest.slice(0, 200).map(x => '<option value="' + esc(x) + '"></option>').join('') + '</datalist>' : '');
    }
    function renderFilterField(def, d, q) {
        const active = !!d;
        const hidden = !!q && !normalizeText(def.label).includes(q) && !active;
        const op = (d && d.op) || DEFAULT_OP[def.type] || 'is';
        const id = fieldDomId(def.key);
        return '<div class="zf-field' + (active ? ' is-active' : '') + '" data-field="' + esc(def.key) + '" data-type="' + esc(def.type) + '"' + (hidden ? ' hidden' : '') + '>' +
            '<label class="zf-field__head" for="' + id + '"><input type="checkbox" id="' + id + '" class="zf-check"' + (active ? ' checked' : '') + '><span class="zf-field__label">' + esc(def.label) + '</span></label>' +
            '<div class="zf-field__body"' + (active ? '' : ' hidden') + '>' +
                '<div class="zf-op-wrap"><select class="zf-op" aria-label="Condition for ' + esc(def.label) + '">' + (OPS[def.type] || OPS.text).map(([k, l]) => '<option value="' + k + '"' + (k === op ? ' selected' : '') + '>' + esc(l) + '</option>').join('') + '</select></div>' +
                '<div class="zf-value-wrap">' + renderFilterValue(def, op, d) + '</div>' +
            '</div></div>';
    }
    function renderFilterFields(tab) {
        const root = $(tab.cfg.ids.filterRoot);
        if (!root) return;
        if (!state.filterMasters && !state.filterMastersPromise) {
            ensureFilterMasters().then(() => renderFilterFields(tab));
        }
        const defs = filterFieldDefs(tab);
        const draft = root.children.length ? readDraft(tab) : (tab.draft || {});
        tab.draft = draft;
        const q = normalizeText(tab.fieldSearch || '');
        root.innerHTML =
            '<div class="zf-search"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><circle cx="11" cy="11" r="7"/><line x1="20" y1="20" x2="16.65" y2="16.65"/></svg>' +
                '<input type="search" class="zf-search__input" placeholder="Search" value="' + esc(tab.fieldSearch || '') + '" aria-label="Search filter fields"></div>' +
            '<div class="zf-list">' + defs.map(def => renderFilterField(def, draft[def.key], q)).join('') + '</div>';
        bindFilterEvents(tab, root, defs);
        updateDraftCount(tab, root);
    }
    function bindFilterEvents(tab, root, defs) {
        const byKey = new Map(defs.map(d => [d.key, d]));
        const search = root.querySelector('.zf-search__input');
        if (search) {
            search.addEventListener('input', debounce(() => {
                tab.fieldSearch = search.value;
                const q = normalizeText(search.value);
                root.querySelectorAll('.zf-field').forEach(el => {
                    const def = byKey.get(el.getAttribute('data-field'));
                    const active = el.classList.contains('is-active');
                    el.hidden = !!q && !!def && !normalizeText(def.label).includes(q) && !active;
                });
            }, 120));
        }
        const bindValueInputs = (wrap) => {
            wrap.querySelectorAll('input[data-zf-value], input[data-zf-value2]').forEach(inp => {
                inp.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); applyFilters(tab); } });
            });
        };
        root.querySelectorAll('.zf-field').forEach(el => {
            const def = byKey.get(el.getAttribute('data-field'));
            if (!def) return;
            const check = el.querySelector('.zf-check');
            const body = el.querySelector('.zf-field__body');
            const opSel = el.querySelector('.zf-op');
            const valueWrap = el.querySelector('.zf-value-wrap');
            check.addEventListener('change', () => {
                el.classList.toggle('is-active', check.checked);
                body.hidden = !check.checked;
                if (check.checked) {
                    const first = valueWrap.querySelector('[data-zf-value]');
                    if (first) setTimeout(() => first.focus(), 20);
                }
                updateDraftCount(tab, root);
            });
            opSel.addEventListener('change', () => {
                const cur = readDraft(tab)[def.key] || {};
                valueWrap.innerHTML = renderFilterValue(def, opSel.value, cur);
                bindValueInputs(valueWrap);
                const first = valueWrap.querySelector('[data-zf-value]');
                if (first) first.focus();
            });
            bindValueInputs(valueWrap);
        });
    }
    function updateDraftCount(tab, root) {
        const active = root ? root.querySelectorAll('.zf-field.is-active').length : 0;
        const countEl = $(tab.key + '-filter-count');
        if (countEl) { countEl.textContent = String(active); countEl.hidden = active === 0; }
    }
    function applyFilters(tab) {
        const defs = filterFieldDefs(tab);
        tab.draft = readDraft(tab);
        tab.filters = draftToConditions(defs, tab.draft);
        const search = $(tab.cfg.ids.search);
        tab.q = search ? String(search.value || '').trim() : '';
        updateFilterBadge(tab);
        tab.pager.page = 1;
        state.kanban.stale = true;
        const incomplete = Object.keys(tab.draft).length - tab.filters.length;
        if (incomplete > 0) toast(incomplete === 1 ? '1 ticked field has no value yet and was skipped' : incomplete + ' ticked fields have no value yet and were skipped', 'error');
        return loadTab(tab.key, true).then(() => {
            if (state.activeTab === 'deals' && state.dealsView === 'kanban') return loadKanban(true);
            return null;
        }).catch(() => {});
    }
    function clearFilters(tab) {
        tab.draft = {};
        tab.filters = [];
        tab.q = '';
        tab.fieldSearch = '';
        const search = $(tab.cfg.ids.search);
        if (search) search.value = '';
        const root = $(tab.cfg.ids.filterRoot);
        if (root) root.innerHTML = '';
        renderFilterFields(tab);
        updateFilterBadge(tab);
        tab.pager.page = 1;
        state.kanban.stale = true;
        return loadTab(tab.key, true).then(() => {
            if (state.activeTab === 'deals' && state.dealsView === 'kanban') return loadKanban(true);
            return null;
        }).catch(() => {});
    }
    function updateFilterBadge(tab) {
        const count = (tab.filters || []).length + (tab.q ? 1 : 0);
        const badge = $(tab.cfg.ids.badge);
        const btn = $(tab.cfg.ids.filterBtn);
        if (badge) { badge.textContent = String(count); badge.style.display = count ? '' : 'none'; }
        if (btn) btn.classList.toggle('filter-btn--has-filters', count > 0);
    }
    function buildParams(tab, extra) {
        const params = { status: tab.cfg.status };
        if (tab.q) params.q = tab.q;
        if (tab.filters && tab.filters.length) params.filters = JSON.stringify(tab.filters);
        if (global.CrmSort) Object.assign(params, global.CrmSort.params(tab.cfg.sortKey));
        return Object.assign(params, extra || {});
    }

    // ---------------------------------------------------------------- loading
    function setTableBusy(tab, busy) {
        const card = $(tab.cfg.ids.card);
        if (card) { card.classList.toggle('is-refreshing', !!busy); card.setAttribute('aria-busy', busy ? 'true' : 'false'); }
    }
    function renderSkeleton(tab) {
        const tbody = $(tab.cfg.ids.tbody);
        if (!tbody || tbody.children.length) return;
        const cells = Array.from({ length: tab.cfg.cols }, (_, i) => '<td><span class="rec-skel" style="width:' + (i === 0 ? 70 : 55 + ((i * 17) % 40)) + '%"></span></td>').join('');
        tbody.innerHTML = Array.from({ length: 5 }, () => '<tr class="rec-row-skeleton" aria-hidden="true">' + cells + '</tr>').join('');
    }
    async function loadTab(key, force) {
        const tab = state.tabs[key];
        if (!tab) return;
        await ensureProfile();
        if (tab.loaded && !force && !tab.stale) { renderTab(key); return; }
        if (tab.promise && !force) return tab.promise;
        tab.promise = fetchTab(tab).finally(() => { tab.promise = null; });
        return tab.promise;
    }
    async function fetchTab(tab) {
        const seq = ++tab.seq;
        setTableBusy(tab, true);
        if (!tab.rows.length) renderSkeleton(tab);
        try {
            const path = API_LEADS + global.CrmPager.buildQuery(tab.pager, buildParams(tab));
            const data = await apiJson(path);
            if (seq !== tab.seq) return;
            const page = global.CrmPager.parsePageResponse(data);
            tab.rows = Array.isArray(page.items) ? page.items : [];
            tab.meta = page;
            tab.pager.page = page.page;
            tab.pager.size = page.limit;
            if (data && data.filter_options) tab.facets = data.filter_options;
            if (data && data.caps && !state.me) applyCapsFromList(data.caps);
            tab.loaded = true;
            tab.stale = false;
            state.lastLoadedAt = Date.now();
            renderTab(tab.key);
        } catch (e) {
            if (seq !== tab.seq) return;
            const tbody = $(tab.cfg.ids.tbody);
            if (tbody) tbody.querySelectorAll('.rec-row-skeleton').forEach(r => r.remove());
            if (!tab.rows.length) tab.loaded = false;
            toast(e.message || 'Failed to load ' + tab.key, 'error');
            throw e;
        } finally {
            if (seq === tab.seq) setTableBusy(tab, false);
        }
    }
    function applyCapsFromList(caps) {
        state.caps.canManageDeals = !!caps.can_manage_deals;
        state.caps.isBroker = !!caps.is_broker;
        state.caps.isPlatformAdmin = !!caps.is_platform_admin;
        state.caps.brokerOnly = state.caps.isBroker && !state.caps.canManageDeals;
    }
    function renderTab(key) {
        const tab = state.tabs[key];
        if (!tab) return;
        renderFilterFields(tab);
        updateFilterBadge(tab);
        renderTable(tab);
        if (key === 'deals' && state.dealsView === 'kanban') renderKanban();
    }
    function bindSort(tab) {
        if (!global.CrmSort) return;
        if (state.caps.brokerOnly) {
            ['customer_email', 'customer_phone'].forEach(f => global.CrmSort.setEnabled(tab.cfg.sortKey, tab.cfg.ids.tbody, f, false));
        }
        global.CrmSort.attach(tab.cfg.sortKey, {
            tbodyId: tab.cfg.ids.tbody,
            onSort: () => { tab.pager.page = 1; loadTab(tab.key, true).catch(() => {}); },
        });
    }
    function renderTable(tab) {
        const tbody = $(tab.cfg.ids.tbody);
        if (!tbody) return;
        bindSort(tab);
        const rows = tab.rows;
        const total = tab.meta.total || rows.length;
        const metaEl = $(tab.cfg.ids.meta);
        if (metaEl) metaEl.textContent = total + (total === 1 ? ' record' : ' records');
        const emptyEl = $(tab.cfg.ids.empty);
        if (emptyEl) emptyEl.style.display = rows.length ? 'none' : '';
        const rowFn = tab.key === 'deals' ? dealRow : (tab.key === 'contacts' ? contactRow : interestRow);
        tbody.innerHTML = rows.map(rowFn).join('');
        global.CrmPager.renderPagination(tab.cfg.ids.pagination, tab.meta, tab.pager, () => { loadTab(tab.key, true).catch(() => {}); }, esc);
        tbody.querySelectorAll('tr[data-record-id]').forEach(tr => {
            tr.addEventListener('click', (e) => {
                if (e.target.closest('a, button')) return;
                openRecordById(tr.getAttribute('data-record-id'), tab.key);
            });
        });
        tbody.querySelectorAll('[data-open-record]').forEach(btn => {
            btn.addEventListener('click', (e) => { e.stopPropagation(); openRecordById(btn.getAttribute('data-open-record'), tab.key); });
        });
    }
    function interestRow(rec) {
        return '<tr data-record-id="' + esc(rec.id) + '">' +
            '<td class="mono"><div class="rec-cell-primary">' + esc(fmtDate(rec.created_at)) + '</div><div class="rec-cell-sub">' + esc(fmtTime(rec.created_at)) + '</div></td>' +
            '<td><div class="rec-cell-primary rec-cell-truncate">' + esc(rec.customer_name || '—') + '</div>' + (rec.title ? '<div class="rec-cell-sub">' + esc(rec.title) + '</div>' : '') + '</td>' +
            '<td>' + contactCell(rec) + '</td>' +
            '<td>' + esc(rec.category || '—') + '</td>' +
            '<td>' + projectCell(rec) + '</td>' +
            '<td>' + plotsCell(rec) + '</td>' +
            '<td>' + referenceCell(rec) + '</td>' +
            '<td>' + rolePill(rec) + '</td>' +
            '<td>' + actionButton(rec) + '</td></tr>';
    }
    function dealRow(rec) {
        return '<tr data-record-id="' + esc(rec.id) + '">' +
            '<td><div class="rec-cell-primary rec-cell-truncate">' + esc(rec.deal_title || rec.customer_name || 'Deal') + '</div><div class="rec-cell-sub">' + esc(rec.converted_at ? 'Converted ' + fmtRelative(rec.converted_at) : fmtDate(rec.created_at)) + '</div></td>' +
            '<td>' + stagePill(rec.deal_stage) + '</td>' +
            '<td><div class="rec-cell-truncate">' + esc(rec.customer_name || '—') + '</div></td>' +
            '<td>' + contactCell(rec) + '</td>' +
            '<td>' + projectCell(Object.assign({}, rec, { workspace_name: rec.deal_project_name || rec.workspace_name })) + '</td>' +
            '<td class="mono">' + esc(rec.deal_amount ? (rec.deal_amount + (rec.deal_currency && rec.deal_currency !== 'INR' ? ' ' + rec.deal_currency : '')) : '—') + '</td>' +
            '<td>' + plotsCell(rec) + '</td>' +
            '<td>' + referenceCell(rec) + '</td>' +
            '<td>' + rolePill(rec) + '</td>' +
            '<td>' + actionButton(rec) + '</td></tr>';
    }
    function contactRow(rec) {
        const address = rec.contact_hidden ? '' : (rec.customer_address || [rec.customer_street, rec.customer_city, rec.customer_state, rec.customer_country, rec.customer_zip_code].filter(Boolean).join(', '));
        return '<tr data-record-id="' + esc(rec.id) + '">' +
            '<td><div class="rec-cell-primary rec-cell-truncate">' + esc(rec.customer_name || '—') + '</div>' + (rec.deal_title && rec.deal_title !== rec.customer_name ? '<div class="rec-cell-sub">' + esc(rec.deal_title) + '</div>' : '') + '</td>' +
            '<td>' + (rec.contact_hidden ? '<span class="rec-hidden">' + ICON.lock + esc(HIDDEN_LABEL) + '</span>' : '<div class="rec-cell-truncate">' + esc(rec.customer_email || '—') + '</div>') + '</td>' +
            '<td class="mono">' + (rec.contact_hidden ? '<span class="rec-empty">—</span>' : esc(rec.customer_phone || '—')) + '</td>' +
            '<td>' + esc(fmtBirthday(rec.customer_birthday) || '—') + '</td>' +
            '<td class="rec-cell-truncate" title="' + esc(address) + '">' + (rec.contact_hidden ? '<span class="rec-empty">—</span>' : esc(address || '—')) + '</td>' +
            '<td>' + projectCell(Object.assign({}, rec, { workspace_name: rec.deal_project_name || rec.workspace_name })) + '</td>' +
            '<td>' + stagePill(rec.deal_stage) + '</td>' +
            '<td>' + referenceCell(rec) + '</td>' +
            '<td>' + actionButton(rec) + '</td></tr>';
    }

    // ----------------------------------------------------------------- kanban
    function setDealsView(mode) {
        state.dealsView = mode === 'kanban' ? 'kanban' : 'list';
        const listWrap = $('deals-list-view');
        const board = $('deals-kanban-board');
        if (listWrap) listWrap.style.display = state.dealsView === 'list' ? '' : 'none';
        if (board) board.style.display = state.dealsView === 'kanban' ? '' : 'none';
        const emptyEl = $('deals-kanban-empty');
        if (emptyEl && state.dealsView === 'list') emptyEl.style.display = 'none';
        const toggle = $('deals-mode-toggle');
        if (toggle) toggle.querySelectorAll('[data-mode]').forEach(btn => {
            const active = btn.getAttribute('data-mode') === state.dealsView;
            btn.classList.toggle('active', active);
            btn.setAttribute('aria-pressed', active ? 'true' : 'false');
        });
        if (state.dealsView === 'kanban') loadKanban(false).catch(() => {});
    }
    async function loadKanban(force) {
        const k = state.kanban;
        if (k.loaded && !force && !k.stale) { renderKanban(); return; }
        if (k.promise && !force) return k.promise;
        const seq = ++k.seq;
        const loader = $('deals-mode-loader');
        if (loader) loader.hidden = false;
        k.promise = (async () => {
            try {
                const tab = state.tabs.deals;
                const data = await apiJson(API_LEADS + global.CrmPager.buildQuery({ page: 1, size: KANBAN_LIMIT }, buildParams(tab, { include_facets: '0' })));
                if (seq !== k.seq) return;
                const page = global.CrmPager.parsePageResponse(data);
                k.rows = Array.isArray(page.items) ? page.items : [];
                k.loaded = true;
                k.stale = false;
                renderKanban();
                if (page.total > k.rows.length) toast('Board shows the first ' + k.rows.length + ' of ' + page.total + ' deals. Use filters to narrow down.', 'error');
            } catch (e) {
                if (seq !== k.seq) return;
                toast(e.message || 'Failed to load board', 'error');
                throw e;
            } finally {
                if (seq === k.seq && loader) loader.hidden = true;
                k.promise = null;
            }
        })();
        return k.promise;
    }
    function renderKanban() {
        const rows = state.kanban.rows;
        const canMove = state.caps.canManageDeals;
        let any = false;
        STAGES.forEach(stage => {
            const zone = $('dk-' + stage);
            const countEl = $('dk-count-' + stage);
            if (!zone || !countEl) return;
            const items = rows.filter(r => String(r.deal_stage || 'new') === stage);
            countEl.textContent = String(items.length);
            if (items.length) any = true;
            zone.innerHTML = items.map(r => {
                const plots = Array.isArray(r.plots) ? r.plots.length : 0;
                return '<div class="kb-card' + (canMove && r.can_move_stage ? '' : ' is-static') + '" draggable="' + (canMove && r.can_move_stage ? 'true' : 'false') + '" data-record-id="' + esc(r.id) + '">' +
                    '<div class="kb-card-title" title="' + esc(r.deal_title || '') + '">' + esc(r.deal_title || r.customer_name || 'Deal') + '</div>' +
                    '<div class="kb-card-line">' + esc(r.customer_name || '—') + (r.contact_hidden ? ' · <span class="rec-hidden">' + ICON.lock + 'hidden</span>' : '') + '</div>' +
                    '<div class="kb-card-line">' + esc(r.deal_project_name || r.workspace_name || r.panorama_name || '—') + (r.deal_amount ? ' · <span class="kb-card-amount">' + esc(r.deal_amount) + '</span>' : '') + '</div>' +
                    '<div class="kb-card-foot"><span class="rec-plots-chip">' + ICON.pin + esc(plots + (plots === 1 ? ' plot' : ' plots')) + '</span>' + (r.reference_user_id ? rolePill(r) : '') + '</div>' +
                    '</div>';
            }).join('');
            zone.querySelectorAll('.kb-card').forEach(card => {
                card.addEventListener('click', () => openRecordById(card.getAttribute('data-record-id'), 'deals'));
                if (card.getAttribute('draggable') === 'true') {
                    card.addEventListener('dragstart', (ev) => { ev.dataTransfer.setData('text/plain', card.getAttribute('data-record-id')); card.classList.add('kb-card--dragging'); });
                    card.addEventListener('dragend', () => card.classList.remove('kb-card--dragging'));
                }
            });
        });
        const emptyEl = $('deals-kanban-empty');
        if (emptyEl) emptyEl.style.display = any ? 'none' : '';
        bindKanbanDropTargets();
    }
    function bindKanbanDropTargets() {
        STAGES.forEach(stage => {
            const zone = $('dk-' + stage);
            if (!zone || zone._crmDropBound) return;
            zone._crmDropBound = true;
            zone.addEventListener('dragover', (ev) => { if (!state.caps.canManageDeals) return; ev.preventDefault(); zone.classList.add('kb-drop-active'); });
            zone.addEventListener('dragleave', () => zone.classList.remove('kb-drop-active'));
            zone.addEventListener('drop', (ev) => {
                ev.preventDefault();
                zone.classList.remove('kb-drop-active');
                const id = String(ev.dataTransfer.getData('text/plain') || '').trim();
                if (id) moveStage(id, stage);
            });
        });
    }
    async function moveStage(id, stage) {
        const rec = state.kanban.rows.find(r => String(r.id) === String(id)) || state.tabs.deals.rows.find(r => String(r.id) === String(id));
        if (!rec || String(rec.deal_stage || 'new') === stage) return;
        if (!state.caps.canManageDeals) { toast('Only client admins and client users can move deals', 'error'); return; }
        const prev = rec.deal_stage;
        rec.deal_stage = stage;
        renderKanban();
        const card = document.querySelector('#dk-' + stage + ' .kb-card[data-record-id="' + id + '"]');
        if (card) card.classList.add('is-moving');
        try {
            const data = await apiJson(API_LEADS + '/' + encodeURIComponent(id) + '/move-stage', { method: 'POST', body: JSON.stringify({ deal_stage: stage }) });
            applyRecordUpdate(data.lead || Object.assign({}, rec, { deal_stage: stage }));
            toast('Moved to ' + STAGE_LABELS[stage]);
        } catch (e) {
            rec.deal_stage = prev;
            renderKanban();
            toast(e.message || 'Failed to move deal', 'error');
        }
    }

    // ------------------------------------------------------------ record sync
    function applyRecordUpdate(updated) {
        if (!updated || !updated.id) return;
        const id = String(updated.id);
        Object.keys(state.tabs).forEach(key => {
            const tab = state.tabs[key];
            const idx = tab.rows.findIndex(r => String(r.id) === id);
            const belongs = updated.record_status === tab.cfg.status;
            if (idx >= 0) {
                if (belongs) tab.rows[idx] = updated;
                else { tab.rows.splice(idx, 1); tab.meta.total = Math.max(0, (tab.meta.total || 1) - 1); tab.stale = true; }
                if (tab.loaded) renderTable(tab);
            } else if (belongs && tab.loaded) {
                tab.stale = true;
            }
        });
        const k = state.kanban;
        const kIdx = k.rows.findIndex(r => String(r.id) === id);
        if (updated.record_status === 'deal') {
            if (kIdx >= 0) k.rows[kIdx] = updated; else if (k.loaded) k.rows.unshift(updated);
        } else if (kIdx >= 0) k.rows.splice(kIdx, 1);
        if (state.dealsView === 'kanban') renderKanban();
        if (state.drawer.record && String(state.drawer.record.id) === id) state.drawer.record = updated;
    }
    function removeRecord(id) {
        id = String(id);
        Object.keys(state.tabs).forEach(key => {
            const tab = state.tabs[key];
            const idx = tab.rows.findIndex(r => String(r.id) === id);
            if (idx >= 0) { tab.rows.splice(idx, 1); tab.meta.total = Math.max(0, (tab.meta.total || 1) - 1); if (tab.loaded) renderTable(tab); tab.stale = true; }
        });
        const kIdx = state.kanban.rows.findIndex(r => String(r.id) === id);
        if (kIdx >= 0) { state.kanban.rows.splice(kIdx, 1); if (state.dealsView === 'kanban') renderKanban(); }
    }
    function markStale(keys) {
        (keys || Object.keys(state.tabs)).forEach(k => { if (state.tabs[k]) state.tabs[k].stale = true; });
        state.kanban.stale = true;
    }
    function findRecord(id) {
        id = String(id);
        for (const key of Object.keys(state.tabs)) {
            const hit = state.tabs[key].rows.find(r => String(r.id) === id);
            if (hit) return hit;
        }
        return state.kanban.rows.find(r => String(r.id) === id) || null;
    }

    // ----------------------------------------------------------------- drawer
    const drawer = $('drawer');
    const drawerBackdrop = $('record-drawer-backdrop');

    function showDrawer() {
        if (drawer) drawer.classList.add('show');
        if (drawerBackdrop) { drawerBackdrop.classList.add('visible'); drawerBackdrop.setAttribute('aria-hidden', 'false'); }
    }
    function hideDrawer() {
        if (drawer) drawer.classList.remove('show', 'is-editing');
        if (drawerBackdrop) { drawerBackdrop.classList.remove('visible'); drawerBackdrop.setAttribute('aria-hidden', 'true'); }
    }
    function closeDrawer() {
        if (state.drawer.mode === 'edit' && drawerIsDirty()) {
            if (!global.confirm('Discard unsaved changes?')) return;
        }
        state.drawer.seq++;
        state.drawer.record = null;
        state.drawer.mode = 'view';
        state.drawer.pendingPlots = null;
        global.__crmQuoteDealId = null;
        global.__crmQuoteContext = null;
        hideDrawer();
    }
    function drawerIsDirty() {
        const root = $('d-sections');
        const rec = state.drawer.record;
        if (!root || !rec) return false;
        if (state.drawer.pendingPlots) return true;
        let dirty = false;
        root.querySelectorAll('[data-key]').forEach(input => {
            const key = input.getAttribute('data-key');
            const custom = input.getAttribute('data-custom') === '1';
            const current = String(input.value || '').trim();
            const original = custom ? String((rec.custom_fields || {})[key] == null ? '' : (rec.custom_fields || {})[key]).trim() : String(rec[key] == null ? '' : rec[key]).trim();
            if (input.type === 'date') { if (current !== original.slice(0, 10)) dirty = true; }
            else if (current !== original) dirty = true;
        });
        return dirty;
    }
    function setDrawerLoading(on, text) {
        const el = $('d-loading');
        if (el) { el.hidden = !on; const t = $('d-loading-text'); if (t && text) t.textContent = text; }
    }
    function setDrawerBusy(on) { if (drawer) drawer.classList.toggle('is-busy', !!on); }
    function showDrawerMsg(text, type) {
        const el = $('d-msg');
        if (!el) return;
        el.textContent = text || '';
        el.className = 'rec-msg' + (type === 'error' ? ' rec-msg--error' : ' rec-msg--success');
        el.style.display = text ? '' : 'none';
        if (text && type !== 'error') setTimeout(() => { if (el.textContent === text) el.style.display = 'none'; }, 2600);
        if (text && typeof el.scrollIntoView === 'function') el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
    function renderDrawerHead(rec) {
        const title = $('d-title');
        const sub = $('d-subtitle');
        const avatar = $('d-avatar');
        if (title) title.textContent = rec.is_deal ? (rec.deal_title || rec.customer_name || 'Deal') : (rec.customer_name || 'Interest');
        if (avatar) { avatar.textContent = initials(rec.customer_name || rec.deal_title); avatar.classList.toggle('is-deal', !!rec.is_deal); }
        if (sub) {
            const bits = [statusPill(rec)];
            if (rec.is_deal) bits.push(stagePill(rec.deal_stage));
            if (rec.is_deal && rec.deal_title && rec.customer_name) bits.push('<span>' + esc(rec.customer_name) + '</span>');
            bits.push('<span>' + esc(rec.workspace_name || rec.panorama_name || '') + (rec.workspace_name && rec.panorama_name && rec.workspace_name !== rec.panorama_name ? ' · ' + esc(rec.panorama_name) : '') + '</span>');
            bits.push('<span title="' + esc(fmtDate(rec.created_at) + ' ' + fmtTime(rec.created_at)) + '">Created ' + esc(fmtRelative(rec.created_at)) + '</span>');
            sub.innerHTML = bits.join('');
        }
    }
    async function loadMastersFor(rec) {
        const broker = !!global.__crmIsExternalBroker || state.caps.brokerOnly;
        const clientId = broker ? '' : String((rec && rec.client_id) || '').trim();
        const key = broker ? 'broker' : (clientId ? 'client:' + clientId : 'default');
        if (state.masters.has(key)) return state.masters.get(key);
        if (state.mastersInflight.has(key)) return state.mastersInflight.get(key);
        const qs = new URLSearchParams();
        if (broker) qs.set('scope', 'broker'); else if (clientId) qs.set('client_id', clientId);
        else if (rec && rec.panorama_id) qs.set('panorama_id', String(rec.panorama_id));
        const job = apiJson('/api/crm/master-config' + (qs.toString() ? '?' + qs.toString() : ''))
            .then(cfg => { const fields = Array.isArray(cfg.fields) ? cfg.fields : []; state.masters.set(key, fields); return fields; })
            .catch(() => [])
            .finally(() => state.mastersInflight.delete(key));
        state.mastersInflight.set(key, job);
        return job;
    }
    async function loadReferenceUsers(panoramaId, clientId) {
        const pid = String(panoramaId || '').trim();
        if (!pid) return [];
        const key = pid + ':' + String(clientId || '');
        if (state.refUsers.has(key)) return state.refUsers.get(key);
        try {
            const data = await apiJson('/api/public/panoramas/' + encodeURIComponent(pid) + '/reference-users');
            let users = Array.isArray(data.reference_users) ? data.reference_users : [];
            if (clientId) users = users.filter(u => Array.isArray(u.client_ids) && u.client_ids.map(String).includes(String(clientId)));
            state.refUsers.set(key, users);
            return users;
        } catch (e) { return []; }
    }
    function openRecordById(id, tabKey) {
        const rec = findRecord(id);
        if (rec) return openRecord(rec, { tabKey });
        apiJson(API_LEADS + '/' + encodeURIComponent(id)).then(d => openRecord(d.lead || d, { tabKey })).catch(e => toast(e.message || 'Record not found', 'error'));
    }
    async function openRecord(rec, opts) {
        if (!rec || !rec.id) return;
        opts = opts || {};
        const token = ++state.drawer.seq;
        state.drawer.record = rec;
        state.drawer.tabKey = opts.tabKey || state.activeTab;
        state.drawer.mode = 'view';
        state.drawer.pendingPlots = null;
        if (rec.is_deal) {
            global.__crmQuoteDealId = String(rec.id);
            global.__crmQuoteContext = {
                clientName: rec.customer_name || rec.deal_title || '',
                email: rec.contact_hidden ? '' : (rec.customer_email || ''),
                phone: rec.contact_hidden ? '' : (rec.customer_phone || ''),
                address: rec.contact_hidden ? '' : (rec.customer_address || ''),
                projectName: rec.deal_project_name || rec.workspace_name || rec.panorama_name || '',
                plots: (rec.plots || []).map(p => ({ name: plotLabel(p), area: p.area || '', price: p.price || '' })),
            };
        } else { global.__crmQuoteDealId = null; global.__crmQuoteContext = null; }
        renderDrawerHead(rec);
        showDrawerMsg('');
        showDrawer();
        const sections = $('d-sections');
        if (sections) sections.innerHTML = '';
        setDrawerLoading(true, 'Loading record…');
        updateDrawerFooter();
        const [masters, refUsers] = await Promise.all([loadMastersFor(rec), loadReferenceUsers(rec.panorama_id, rec.client_id)]);
        if (token !== state.drawer.seq) return;
        state.drawer.masters = masters;
        state.drawer.refUsers = refUsers;
        setDrawerLoading(false);
        renderSections();
        updateDrawerFooter();
        if (opts.edit && rec.can_edit) setDrawerMode('edit');
        if (rec.is_deal) loadDealQuotationsList(rec.id);
        const closeBtn = $('drawer-close');
        if (closeBtn && !opts.edit) setTimeout(() => closeBtn.focus({ preventScroll: true }), 40);
    }
    function masterHelpers(rec) {
        const fields = (state.drawer.masters || []).filter(f => f && f.is_enabled !== false);
        const appliesTo = (f, ent) => Array.isArray(f.applies_to) ? f.applies_to.map(x => String(x || '').toLowerCase()).includes(ent) : ent === 'interests';
        const relevant = fields.filter(f => appliesTo(f, 'interests') || (rec.is_deal && appliesTo(f, 'deals')));
        return {
            relevant,
            byKey: (k) => relevant.find(f => String(f.field_key || '') === k) || null,
            opts: (f) => (f && Array.isArray(f.values)) ? f.values.filter(v => v && v.is_enabled !== false).map(v => String(v.value || '').trim()).filter(Boolean) : [],
        };
    }
    function stageOptions(rec) {
        const m = masterHelpers(Object.assign({}, rec || {}, { is_deal: true }));
        const f = m.byKey('deal_stage');
        const out = [];
        (f ? m.opts(f) : []).forEach(label => {
            const slug = stageSlug(label);
            if (STAGES.includes(slug) && !out.some(o => o[0] === slug)) out.push([slug, label]);
        });
        return out.length ? out : STAGES.map(s => [s, STAGE_LABELS[s]]);
    }
    function fieldDef(key, label, o) {
        o = o || {};
        return { key, label, type: o.type || 'text', required: !!o.required, locked: !!o.locked, custom: !!o.custom, options: o.options || [], wide: !!o.wide, readonly: !!o.readonly, href: o.href || '', rows: o.rows || 3, placeholder: o.placeholder || '' };
    }
    function valueOf(rec, f) {
        if (!rec) return '';
        if (f.custom) { const c = rec.custom_fields || {}; return c[f.key] == null ? '' : String(c[f.key]); }
        const v = rec[f.key];
        return v == null ? '' : String(v);
    }
    function buildSchema(rec) {
        const m = masterHelpers(rec);
        const locked = !!rec.contact_hidden;
        const withCurrent = (options, current) => { const list = options.slice(); const cur = String(current || '').trim(); if (cur && !list.includes(cur)) list.unshift(cur); return list; };
        const selectOrText = (key, label, masterKey, extra) => {
            const f = m.byKey(masterKey || key);
            const options = f ? m.opts(f) : [];
            const cur = valueOf(rec, { key, custom: !!(extra && extra.custom) });
            return fieldDef(key, (f && f.label) || label, Object.assign({}, extra || {}, options.length ? { type: 'select', options: withCurrent(options, cur) } : {}, f ? { required: !!(extra && extra.required) || !!f.is_required } : {}));
        };
        const KNOWN = new Set(['lead_source', 'lead_category', 'lead_status', 'campaign_type', 'campaign_status', 'state', 'country', 'title', 'deal_stage', 'plot_status', 'builder_name', 'project_type']);
        const contact = [
            fieldDef('customer_name', 'Full name', { required: true }),
            selectOrText('title', 'Title', 'title'),
            fieldDef('customer_email', 'Email', { required: true, type: 'email', locked, href: 'mailto:' }),
            fieldDef('customer_phone', 'Phone', { required: true, type: 'tel', locked, href: 'tel:' }),
            fieldDef('customer_birthday', 'Birthday', { type: 'date', locked }),
            fieldDef('customer_street', 'Street', { locked }),
            fieldDef('customer_city', 'City', { locked }),
            selectOrText('customer_state', 'State', 'state', { locked }),
            selectOrText('customer_country', 'Country', 'country', { locked }),
            fieldDef('customer_zip_code', 'Zip code', { locked }),
        ];
        const lead = [fieldDef('category', 'Category', {})];
        ['lead_source', 'lead_category', 'lead_status', 'campaign_type', 'campaign_status'].forEach(k => {
            if (m.byKey(k)) lead.push(selectOrText(k, k.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()), k));
        });
        m.relevant.filter(f => !KNOWN.has(String(f.field_key || ''))).forEach(f => {
            const key = String(f.field_key || '').trim();
            if (!key) return;
            const options = m.opts(f);
            lead.push(fieldDef(key, f.label || key, { custom: true, type: options.length ? 'select' : 'text', options: withCurrent(options, valueOf(rec, { key, custom: true })), required: !!f.is_required }));
        });
        lead.push(fieldDef('reference_user_id', 'Reference', { type: 'reference' }));
        lead.push(fieldDef('reference_user_role_label', 'Reference role', { readonly: true }));
        lead.push(fieldDef('description', 'Description', { type: 'textarea', wide: true, rows: 3 }));
        const sections = [
            { key: 'contact', title: 'Contact', fields: contact, note: locked ? (rec.contact_hidden_label || HIDDEN_LABEL) : '' },
            { key: 'lead', title: 'Lead details', fields: lead },
        ];
        if (rec.is_deal) {
            sections.push({ key: 'deal', title: 'Deal', fields: [
                fieldDef('deal_title', 'Deal name', { required: true, wide: true }),
                fieldDef('deal_stage', 'Stage', { type: 'stage' }),
                fieldDef('deal_amount', 'Amount', { placeholder: 'e.g. 25,00,000' }),
                fieldDef('deal_currency', 'Currency', { placeholder: 'INR' }),
                fieldDef('deal_project_name', 'Project name', { wide: true }),
            ] });
        }
        sections.push({ key: 'plots', title: 'Plots', custom: 'plots' });
        sections.push({ key: 'notes', title: 'Notes', fields: [fieldDef('notes', 'Notes', { type: 'textarea', wide: true, rows: 4, placeholder: 'Call summary, next steps, objections…' })] });
        if (rec.is_deal) sections.push({ key: 'quotes', title: 'Quotations', custom: 'quotes' });
        return sections;
    }
    function renderField(rec, f, editing) {
        const raw = valueOf(rec, f);
        const wide = f.wide ? ' rec-field--wide' : '';
        const req = f.required ? '<i class="rec-req" aria-hidden="true">*</i>' : '';
        const lockedNow = f.locked && rec.contact_hidden;
        const editable = editing && !f.readonly && !lockedNow;
        if (!editable) {
            let display;
            if (lockedNow) display = '<span class="rec-hidden">' + ICON.lock + esc(rec.contact_hidden_label || HIDDEN_LABEL) + '</span>';
            else if (f.type === 'reference') display = rec.reference_user_id ? esc(rec.reference_user_name || 'Reference') : '<span class="rec-empty">No reference</span>';
            else if (f.key === 'reference_user_role_label') display = rec.reference_user_id ? rolePill(rec) : '<span class="rec-empty">—</span>';
            else if (f.type === 'stage') display = stagePill(rec.deal_stage);
            else if (f.type === 'date') display = raw ? esc(fmtBirthday(raw)) : '<span class="rec-empty">—</span>';
            else if (!raw) display = '<span class="rec-empty">—</span>';
            else if (f.href) display = '<a class="rec-link" href="' + esc(f.href + raw) + '">' + esc(raw) + '</a>';
            else display = esc(raw).replace(/\n/g, '<br>');
            return '<div class="rec-field rec-field--view' + wide + '"><span class="rec-field__label">' + esc(f.label) + req + '</span><div class="rec-field__value">' + display + '</div></div>';
        }
        const attrs = ' data-key="' + esc(f.key) + '"' + (f.custom ? ' data-custom="1"' : '') + (f.required ? ' data-required="1"' : '') + ' class="rec-field__input"';
        let control;
        if (f.type === 'textarea') {
            control = '<textarea' + attrs + ' rows="' + f.rows + '" placeholder="' + esc(f.placeholder) + '">' + esc(raw) + '</textarea>';
        } else if (f.type === 'select') {
            control = '<select' + attrs + '><option value="">Select ' + esc(f.label) + '</option>' + f.options.map(o => '<option value="' + esc(o) + '"' + (o === raw ? ' selected' : '') + '>' + esc(o) + '</option>').join('') + '</select>';
        } else if (f.type === 'stage') {
            control = '<select' + attrs + '>' + stageOptions(rec).map(([slug, label]) => '<option value="' + esc(slug) + '"' + (slug === String(rec.deal_stage || 'new') ? ' selected' : '') + '>' + esc(label) + '</option>').join('') + '</select>';
        } else if (f.type === 'reference') {
            const users = state.drawer.refUsers || [];
            const cur = String(rec.reference_user_id || '');
            const hasCur = users.some(u => String(u.user_id) === cur);
            control = '<select' + attrs + '><option value="">' + (users.length ? 'No reference' : 'No reference available') + '</option>' +
                users.map(u => '<option value="' + esc(u.user_id) + '"' + (String(u.user_id) === cur ? ' selected' : '') + '>' + esc(refUserLabel(u)) + '</option>').join('') +
                (cur && !hasCur ? '<option value="' + esc(cur) + '" selected>' + esc(rec.reference_user_name || 'Current reference') + '</option>' : '') + '</select>';
        } else {
            const type = f.type === 'date' ? 'date' : (f.type === 'email' ? 'email' : (f.type === 'tel' ? 'tel' : 'text'));
            control = '<input' + attrs + ' type="' + type + '" value="' + esc(f.type === 'date' ? raw.slice(0, 10) : raw) + '" placeholder="' + esc(f.placeholder) + '">';
        }
        return '<label class="rec-field' + wide + '" data-field="' + esc(f.key) + '"><span class="rec-field__label">' + esc(f.label) + req + '</span>' + control + '<span class="rec-field__hint" aria-live="polite"></span></label>';
    }
    function currentDrawerPlots() {
        return state.drawer.pendingPlots || (state.drawer.record && Array.isArray(state.drawer.record.plots) ? state.drawer.record.plots : []);
    }
    function renderPlotsBlock(rec, editing) {
        const plots = currentDrawerPlots();
        if (!plots.length) return '<div class="rec-empty-block">No plots attached yet.' + (rec.can_edit ? ' Use “Add plots” to attach some.' : '') + '</div>';
        return '<div class="rec-plots">' + plots.map((p, i) => {
            const k = plotKey(p, i);
            const meta = [p.area, p.price].filter(Boolean).map(esc).join(' · ') + (p.normal_project_name ? (p.area || p.price ? ' · ' : '') + esc(p.normal_project_name) : '');
            return '<div class="rec-plot" data-plot-key="' + esc(k) + '"><div class="rec-plot__name">' + esc(plotLabel(p)) + '</div><div class="rec-plot__meta">' + (meta || '&nbsp;') + '</div>' + plotStatusPill(p.status) +
                (editing && plots.length > 1 ? '<button type="button" class="rec-plot__remove" data-remove-plot="' + esc(k) + '" aria-label="Remove plot" title="Remove from this record">&times;</button>' : '') + '</div>';
        }).join('') + '</div>';
    }
    function renderQuotesBlock() {
        return '<div class="rec-quotes" id="deal-quotes-list">Loading quotations…</div>' +
            '<div class="rec-quotes__actions">' +
            '<button type="button" class="rec-mini-btn" id="deal-btn-quotation">' + ICON.plus + '<span>New quotation</span></button>' +
            '<button type="button" class="rec-mini-btn" id="deal-btn-send-quote">Send last quote by email</button>' +
            '</div>';
    }
    function renderSections() {
        const rec = state.drawer.record;
        const root = $('d-sections');
        if (!rec || !root) return;
        const editing = state.drawer.mode === 'edit';
        root.innerHTML = buildSchema(rec).map(sec => {
            let body;
            if (sec.custom === 'plots') body = renderPlotsBlock(rec, editing);
            else if (sec.custom === 'quotes') body = renderQuotesBlock(rec);
            else body = '<div class="rec-grid">' + sec.fields.map(f => renderField(rec, f, editing)).join('') + '</div>';
            const note = sec.note ? '<span class="rec-section__note">' + ICON.lock + esc(sec.note) + '</span>' : '';
            const tools = sec.custom === 'plots' && rec.can_edit ? '<button type="button" class="rec-mini-btn" id="d-add-plots">' + ICON.plus + '<span>Add plots</span></button>' : '';
            return '<section class="rec-section" data-section="' + esc(sec.key) + '"><header class="rec-section__head"><h6>' + esc(sec.title) + '</h6><div class="rec-section__tools">' + note + tools + '</div></header><div class="rec-section__body">' + body + '</div></section>';
        }).join('');
        bindSectionEvents(root);
    }
    function bindSectionEvents(root) {
        const addBtn = root.querySelector('#d-add-plots');
        if (addBtn) addBtn.addEventListener('click', () => openAddPlotsModal(state.drawer.record));
        root.querySelectorAll('[data-remove-plot]').forEach(btn => {
            btn.addEventListener('click', () => {
                const key = btn.getAttribute('data-remove-plot');
                const plots = currentDrawerPlots().slice();
                const next = plots.filter((p, i) => plotKey(p, i) !== key);
                if (!next.length) { toast('A record must keep at least one plot', 'error'); return; }
                state.drawer.pendingPlots = next;
                const body = root.querySelector('[data-section="plots"] .rec-section__body');
                if (body) { body.innerHTML = renderPlotsBlock(state.drawer.record, true); bindSectionEvents(root); }
            });
        });
        root.querySelectorAll('.rec-field.is-invalid [data-key]').forEach(inp => inp.addEventListener('input', () => clearInvalid(inp.closest('.rec-field'))));
        root.querySelectorAll('[data-key]').forEach(inp => inp.addEventListener('input', () => clearInvalid(inp.closest('.rec-field')), { once: false }));
        const qBtn = root.querySelector('#deal-btn-quotation');
        if (qBtn) qBtn.addEventListener('click', () => {
            if (!global.__crmQuoteDealId) { toast('Open a deal first', 'error'); return; }
            if (state.drawer.record && state.drawer.record.contact_hidden) { toast('Contact must be revealed before a quotation can be generated', 'error'); return; }
            if (typeof global.openDealQuotationModal === 'function') global.openDealQuotationModal();
        });
        const sendBtn = root.querySelector('#deal-btn-send-quote');
        if (sendBtn) sendBtn.addEventListener('click', async () => {
            const did = global.__crmQuoteDealId;
            const qid = global.__crmLastQuoteId;
            if (!did || !qid) { toast('Create a quotation first', 'error'); return; }
            setBusy(sendBtn, true);
            try {
                await apiJson('/api/crm/deals/' + encodeURIComponent(did) + '/quotation/share', { method: 'POST', body: JSON.stringify({ quote_id: qid }) });
                toast('Quote email sent');
                loadDealQuotationsList(did);
            } catch (e) { toast(e.message || 'Send failed', 'error'); }
            finally { setBusy(sendBtn, false); }
        });
    }
    async function loadDealQuotationsList(dealId) {
        const el = $('deal-quotes-list');
        if (!el || !dealId) return;
        const seq = ++state.drawer.quotesSeq;
        el.textContent = 'Loading quotations…';
        try {
            const rows = await apiJson('/api/crm/deals/' + encodeURIComponent(String(dealId)) + '/quotations');
            if (seq !== state.drawer.quotesSeq) return;
            const list = Array.isArray(rows) ? rows : [];
            if (!list.length) { el.innerHTML = '<div class="rec-empty-block">No quotations yet.</div>'; global.__crmLastQuoteId = null; return; }
            el.innerHTML = list.map(q => '<div class="rec-quote-line"><span>' + esc(fmtDate(q.created_at)) + ' · ' + esc(String(q.status || 'draft')) + (q.sent_to_email ? ' → ' + esc(q.sent_to_email) : '') + '</span>' + (q.sent_at ? '<span class="rec-pill rec-pill--won">sent</span>' : '<span class="rec-pill">draft</span>') + '</div>').join('');
            global.__crmLastQuoteId = list[0].id;
        } catch (e) {
            if (seq !== state.drawer.quotesSeq) return;
            el.innerHTML = '<div class="rec-empty-block">' + esc(e.message || 'Could not load quotations') + '</div>';
        }
    }
    global.loadDealQuotationsList = loadDealQuotationsList;

    function markInvalid(wrap, message) {
        if (!wrap) return;
        wrap.classList.add('is-invalid');
        const hint = wrap.querySelector('.rec-field__hint');
        if (hint) hint.textContent = message || 'Required';
    }
    function clearInvalid(wrap) {
        if (!wrap) return;
        wrap.classList.remove('is-invalid');
        const hint = wrap.querySelector('.rec-field__hint');
        if (hint) hint.textContent = '';
    }
    function collectPatch() {
        const root = $('d-sections');
        const rec = state.drawer.record;
        const payload = {};
        const custom = {};
        let firstInvalid = null;
        let invalidCount = 0;
        root.querySelectorAll('.rec-field.is-invalid').forEach(clearInvalid);
        root.querySelectorAll('[data-key]').forEach(input => {
            const key = input.getAttribute('data-key');
            const value = String(input.value || '').trim();
            const wrap = input.closest('.rec-field');
            let error = '';
            if (input.getAttribute('data-required') === '1' && !value) error = 'This field is required';
            else if (key === 'customer_email' && value && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value)) error = 'Enter a valid email address';
            if (error) { markInvalid(wrap, error); invalidCount += 1; if (!firstInvalid) firstInvalid = input; return; }
            if (input.getAttribute('data-custom') === '1') custom[key] = value; else payload[key] = value;
        });
        if (Object.keys(custom).length) payload.custom_fields = custom;
        if (state.drawer.pendingPlots) payload.plots = state.drawer.pendingPlots;
        if (rec && rec.is_deal && 'deal_currency' in payload && !payload.deal_currency) payload.deal_currency = 'INR';
        return { ok: invalidCount === 0, payload, firstInvalid, invalidCount };
    }
    function setDrawerMode(mode) {
        const rec = state.drawer.record;
        if (!rec) return;
        if (mode === 'edit' && !rec.can_edit) { toast(rec.is_deal ? 'Only client admins and client users can edit deals' : 'You cannot edit this record', 'error'); return; }
        state.drawer.mode = mode === 'edit' ? 'edit' : 'view';
        if (state.drawer.mode === 'view') state.drawer.pendingPlots = null;
        showDrawerMsg('');
        renderSections();
        updateDrawerFooter();
        if (state.drawer.mode === 'edit') {
            const first = $('d-sections').querySelector('[data-key]');
            if (first) setTimeout(() => first.focus({ preventScroll: true }), 30);
        }
    }
    function updateDrawerFooter() {
        const rec = state.drawer.record;
        const editing = state.drawer.mode === 'edit';
        const revealBtn = $('btn-reveal-contact');
        const convertBtn = $('btn-convert-lead');
        const delBtn = $('btn-delete-record');
        const editBtn = $('btn-edit-toggle');
        const cancelBtn = $('btn-edit-cancel');
        toggleHidden(revealBtn, !(rec && rec.can_reveal_contact));
        if (revealBtn) revealBtn.disabled = editing;
        const showConvert = !!(rec && !rec.is_deal && state.caps.canManageDeals);
        toggleHidden(convertBtn, !showConvert);
        if (convertBtn) {
            convertBtn.disabled = !(rec && rec.can_convert) || editing;
            convertBtn.title = rec && rec.convert_blocked_reason ? rec.convert_blocked_reason : 'Convert this interest into a deal';
        }
        toggleHidden(delBtn, !(rec && rec.can_delete));
        if (delBtn) delBtn.disabled = editing;
        toggleHidden(editBtn, !(rec && rec.can_edit));
        toggleHidden(cancelBtn, !editing);
        if (editBtn && !editBtn.classList.contains('is-busy')) {
            editBtn.dataset.state = editing ? 'edit' : 'view';
            editBtn.innerHTML = editing ? ICON.save + '<span>Save changes</span>' : ICON.edit + '<span>Edit</span>';
            editBtn.classList.toggle('rec-btn--save', editing);
        }
        if (drawer) drawer.classList.toggle('is-editing', editing);
    }
    async function saveDrawer() {
        const rec = state.drawer.record;
        if (!rec) return;
        const result = collectPatch();
        if (!result.ok) {
            showDrawerMsg(result.invalidCount === 1 ? 'Please fill the highlighted field.' : 'Please fill the ' + result.invalidCount + ' highlighted fields.', 'error');
            if (result.firstInvalid) { result.firstInvalid.focus(); result.firstInvalid.scrollIntoView({ block: 'center', behavior: 'smooth' }); }
            toast('Some required fields are missing', 'error');
            return;
        }
        const btn = $('btn-edit-toggle');
        setBusy(btn, true, 'Saving');
        setDrawerBusy(true);
        try {
            const data = await apiJson(API_LEADS + '/' + encodeURIComponent(rec.id), { method: 'PATCH', body: JSON.stringify(result.payload) });
            const updated = data.lead || data;
            state.drawer.pendingPlots = null;
            applyRecordUpdate(updated);
            state.drawer.record = updated;
            renderDrawerHead(updated);
            setBusy(btn, false);
            setDrawerMode('view');
            showDrawerMsg('Saved.', 'success');
            toast('Changes saved');
        } catch (e) {
            setBusy(btn, false);
            updateDrawerFooter();
            if (e.field) {
                const wrap = $('d-sections').querySelector('.rec-field[data-field="' + e.field + '"]');
                if (wrap) { markInvalid(wrap, e.message); const inp = wrap.querySelector('[data-key]'); if (inp) inp.focus(); }
            }
            showDrawerMsg(e.message || 'Failed to save', 'error');
            toast(e.message || 'Failed to save', 'error');
        } finally {
            setDrawerBusy(false);
        }
    }
    async function revealContact() {
        const rec = state.drawer.record;
        const btn = $('btn-reveal-contact');
        if (!rec || !rec.can_reveal_contact) return;
        setBusy(btn, true, 'Revealing');
        try {
            const data = await apiJson(API_LEADS + '/' + encodeURIComponent(rec.id) + '/reveal-contact', { method: 'POST', body: '{}' });
            const updated = data.lead || Object.assign({}, rec, { contact_revealed: true, can_reveal_contact: false });
            applyRecordUpdate(updated);
            state.drawer.record = updated;
            renderSections();
            updateDrawerFooter();
            showDrawerMsg('Contact revealed to the client team.', 'success');
            toast('Contact revealed to client team');
        } catch (e) {
            showDrawerMsg(e.message || 'Failed to reveal contact', 'error');
            toast(e.message || 'Failed to reveal contact', 'error');
        } finally { setBusy(btn, false); }
    }

    // ------------------------------------------------------------- modals
    function openModal(el) { if (!el) return; el.classList.add('visible'); el.setAttribute('aria-hidden', 'false'); }
    function closeModal(el) { if (!el) return; el.classList.remove('visible'); el.setAttribute('aria-hidden', 'true'); }
    function modalError(id, text) {
        const el = $(id);
        if (!el) return;
        el.textContent = text || '';
        el.style.display = text ? '' : 'none';
    }
    function validateModalFields(root) {
        let first = null;
        root.querySelectorAll('.rec-field.is-invalid').forEach(clearInvalid);
        root.querySelectorAll('[data-required-input]').forEach(input => {
            const value = String(input.value || '').trim();
            if (!value) { markInvalid(input.closest('.rec-field'), 'This field is required'); if (!first) first = input; }
            else if (input.type === 'email' && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value)) { markInvalid(input.closest('.rec-field'), 'Enter a valid email address'); if (!first) first = input; }
        });
        if (first) { first.focus(); first.scrollIntoView({ block: 'center', behavior: 'smooth' }); }
        return !first;
    }

    // Convert to deal ---------------------------------------------------------
    function openConvertModal(rec) {
        if (!rec || rec.is_deal) return;
        if (!rec.can_convert) { toast(rec.convert_blocked_reason || 'This interest cannot be converted yet', 'error'); return; }
        state.convert.record = rec;
        state.convert.plots = Array.isArray(rec.plots) ? rec.plots.slice() : [];
        const modal = $('convert-deal-modal');
        const project = rec.workspace_name || rec.panorama_name || '';
        $('convert-deal-subtitle').textContent = (rec.customer_name || 'Customer') + (project ? ' · ' + project : '');
        $('cd-title').value = [rec.customer_name, project].filter(Boolean).join(' · ') || 'Deal';
        $('cd-stage').innerHTML = stageOptions(rec).map(([slug, label]) => '<option value="' + esc(slug) + '">' + esc(label) + '</option>').join('');
        $('cd-amount').value = amountFromPlots(state.convert.plots);
        $('cd-currency').value = 'INR';
        $('cd-project').value = project;
        $('cd-notes').value = '';
        modalError('cd-error', '');
        modal.querySelectorAll('.rec-field.is-invalid').forEach(clearInvalid);
        renderConvertPlots();
        openModal(modal);
        setTimeout(() => $('cd-title').focus(), 40);
    }
    function amountFromPlots(plots) {
        const prices = (plots || []).map(p => String((p && p.price) || '').trim()).filter(Boolean);
        if (!prices.length) return '';
        let total = 0;
        let numeric = true;
        prices.forEach(t => { const n = parseFloat(t.replace(/[^0-9.\-]/g, '')); if (!isFinite(n)) numeric = false; else total += n; });
        if (numeric && prices.length > 1) return Number.isInteger(total) ? total.toLocaleString('en-IN') : total.toLocaleString('en-IN', { maximumFractionDigits: 2 });
        return prices.length === 1 ? prices[0] : prices[0] + ' + more';
    }
    function renderConvertPlots() {
        const root = $('cd-plots');
        const plots = state.convert.plots;
        if (!plots.length) { root.innerHTML = '<div class="rec-plot-list__empty">This interest has no plots. Add plots before converting.</div>'; $('cd-plots-meta').textContent = ''; return; }
        root.innerHTML = plots.map((p, i) => {
            const k = plotKey(p, i);
            return '<label class="rec-plot-option is-checked" data-key="' + esc(k) + '"><input type="checkbox" checked data-convert-plot="' + esc(k) + '"><span><span class="rec-plot-option__name">' + esc(plotLabel(p)) + '</span><div class="rec-plot-option__meta">' + [p.area, p.price].filter(Boolean).map(esc).join(' · ') + '</div></span>' + plotStatusPill(p.status) + '</label>';
        }).join('');
        const update = () => {
            const checked = root.querySelectorAll('input:checked').length;
            root.querySelectorAll('.rec-plot-option').forEach(l => l.classList.toggle('is-checked', l.querySelector('input').checked));
            $('cd-plots-meta').textContent = checked + ' of ' + plots.length + ' selected';
        };
        root.querySelectorAll('input').forEach(cb => cb.addEventListener('change', update));
        update();
    }
    async function submitConvert() {
        const rec = state.convert.record;
        if (!rec) return;
        const modal = $('convert-deal-modal');
        modalError('cd-error', '');
        if (!validateModalFields(modal)) return;
        const selectedKeys = new Set(Array.from(modal.querySelectorAll('[data-convert-plot]:checked')).map(cb => cb.getAttribute('data-convert-plot')));
        const plots = state.convert.plots.filter((p, i) => selectedKeys.has(plotKey(p, i)));
        if (!plots.length) { modalError('cd-error', 'Select at least one plot for this deal.'); return; }
        const payload = {
            deal_title: $('cd-title').value.trim(),
            deal_stage: $('cd-stage').value,
            deal_amount: $('cd-amount').value.trim(),
            deal_currency: $('cd-currency').value.trim() || 'INR',
            deal_project_name: $('cd-project').value.trim(),
            notes: $('cd-notes').value.trim(),
            plots: plots.map(p => ({ plot_id: p.plot_id != null ? p.plot_id : p.id, id: p.id != null ? p.id : p.plot_id, normal_plot_id: p.normal_plot_id, name: p.name })),
        };
        const btn = $('cd-save');
        setBusy(btn, true, 'Creating deal');
        try {
            const data = await apiJson(API_LEADS + '/' + encodeURIComponent(rec.id) + '/convert', { method: 'POST', body: JSON.stringify(payload) });
            const deal = data.lead || data.deal;
            closeModal(modal);
            applyRecordUpdate(deal);
            markStale(['deals', 'contacts']);
            toast('Converted to deal · contact created');
            const dealsTab = $('tab-deals');
            if (dealsTab) dealsTab.click();
            state.activeTab = 'deals';
            await loadTab('deals', true).catch(() => {});
            if (state.dealsView === 'kanban') await loadKanban(true).catch(() => {});
            openRecord(deal, { tabKey: 'deals' });
        } catch (e) {
            if (e.field) markInvalid(modal.querySelector('.rec-field[data-field="' + e.field + '"]'), e.message);
            modalError('cd-error', e.message || 'Failed to convert');
            toast(e.message || 'Failed to convert', 'error');
        } finally { setBusy(btn, false); }
    }

    // Delete -------------------------------------------------------------------
    function openDeleteModal(rec) {
        if (!rec || !rec.can_delete) return;
        state.deleteTarget = rec;
        $('rd-title').textContent = rec.is_deal ? 'Delete deal' : 'Delete interest';
        $('rd-text').textContent = 'Permanently delete ' + (rec.is_deal ? 'the deal “' + (rec.deal_title || rec.customer_name || 'Deal') + '”' : 'the interest from ' + (rec.customer_name || 'this customer')) + '? This cannot be undone.';
        openModal($('record-delete-modal'));
        setTimeout(() => $('rd-cancel').focus(), 40);
    }
    async function submitDelete() {
        const rec = state.deleteTarget;
        if (!rec) return;
        const btn = $('rd-confirm');
        setBusy(btn, true, 'Deleting');
        try {
            await apiJson(API_LEADS + '/' + encodeURIComponent(rec.id), { method: 'DELETE' });
            closeModal($('record-delete-modal'));
            removeRecord(rec.id);
            if (state.drawer.record && String(state.drawer.record.id) === String(rec.id)) { state.drawer.mode = 'view'; state.drawer.record = null; hideDrawer(); }
            toast(rec.is_deal ? 'Deal deleted' : 'Interest deleted');
        } catch (e) {
            toast(e.message || 'Failed to delete', 'error');
        } finally { setBusy(btn, false); state.deleteTarget = null; }
    }

    // Add plots ----------------------------------------------------------------
    function recordUsesNormalPlots(rec) { return Array.isArray(rec.plots) && rec.plots.some(p => p && p.normal_plot_id != null); }
    async function openAddPlotsModal(rec) {
        if (!rec || !rec.can_edit) return;
        const ap = state.addPlots;
        ap.record = rec;
        ap.selected = new Set();
        ap.attached = new Set((rec.plots || []).map((p, i) => plotKey(p, i)));
        ap.all = [];
        const seq = ++ap.seq;
        $('add-plots-subtitle').textContent = (rec.customer_name || 'Record') + ' · ' + (rec.workspace_name || rec.panorama_name || 'Project');
        $('ap-search').value = '';
        modalError('ap-error', '');
        updateAddPlotsCount();
        const list = $('ap-list');
        list.innerHTML = '<div class="rec-plot-list__loading"><span class="rec-spinner"></span>Loading plots…</div>';
        openModal($('add-plots-modal'));
        try {
            let rows = [];
            if (recordUsesNormalPlots(rec)) {
                ap.source = 'normal';
                const projectId = (rec.plots.find(p => p && p.normal_project_id) || {}).normal_project_id;
                const data = await apiJson('/api/crm/normal-plots?page=1&limit=500' + (projectId ? '&project_id=' + encodeURIComponent(projectId) : ''));
                rows = global.CrmPager.parsePageResponse(data).items.map(p => ({ id: p.id, normal_plot_id: p.id, name: p.name, area: p.area, price: p.price, status: p.status, panorama_name: p.project_name }));
            } else {
                ap.source = 'visual';
                const params = rec.workspace_id ? 'workspace_id=' + encodeURIComponent(rec.workspace_id) : 'panorama_id=' + encodeURIComponent(rec.panorama_id);
                const data = await apiJson('/api/crm/plots?page=1&limit=100&' + params);
                rows = global.CrmPager.parsePageResponse(data).items;
            }
            if (seq !== ap.seq) return;
            ap.all = rows;
            renderAddPlotsList();
        } catch (e) {
            if (seq !== ap.seq) return;
            list.innerHTML = '<div class="rec-plot-list__empty">' + esc(e.message || 'Failed to load plots') + '</div>';
        }
    }
    function renderAddPlotsList() {
        const ap = state.addPlots;
        const list = $('ap-list');
        const q = normalizeText($('ap-search').value);
        const rows = ap.all.filter(p => !q || [p.name, p.area, p.status, p.panorama_name, p.description].some(v => normalizeText(v).includes(q)));
        if (!rows.length) { list.innerHTML = '<div class="rec-plot-list__empty">' + (ap.all.length ? 'No plots match your search.' : 'No plots found for this project.') + '</div>'; return; }
        list.innerHTML = rows.map(p => {
            const k = ap.source === 'normal' ? 'normal:' + p.id : 'id:' + p.id;
            const attached = ap.attached.has(k);
            const checked = ap.selected.has(String(p.id));
            return '<label class="rec-plot-option' + (attached ? ' is-disabled' : '') + (checked ? ' is-checked' : '') + '"><input type="checkbox" data-ap-plot="' + esc(p.id) + '"' + (attached ? ' checked disabled' : (checked ? ' checked' : '')) + '><span><span class="rec-plot-option__name">' + esc(p.name || ('Plot #' + p.id)) + '</span><div class="rec-plot-option__meta">' + [p.panorama_name, p.area, p.price].filter(Boolean).map(esc).join(' · ') + (attached ? ' · already attached' : '') + '</div></span>' + plotStatusPill(p.status) + '</label>';
        }).join('');
        list.querySelectorAll('input[data-ap-plot]:not(:disabled)').forEach(cb => cb.addEventListener('change', () => {
            const id = String(cb.getAttribute('data-ap-plot'));
            if (cb.checked) ap.selected.add(id); else ap.selected.delete(id);
            cb.closest('.rec-plot-option').classList.toggle('is-checked', cb.checked);
            updateAddPlotsCount();
        }));
    }
    function updateAddPlotsCount() {
        const n = state.addPlots.selected.size;
        $('ap-count').textContent = n + ' selected';
        $('ap-save').disabled = n === 0;
    }
    async function submitAddPlots() {
        const ap = state.addPlots;
        const rec = ap.record;
        if (!rec || !ap.selected.size) return;
        const ids = Array.from(ap.selected).map(Number).filter(n => Number.isFinite(n));
        const body = ap.source === 'normal' ? { normal_plot_ids: ids } : { add_plot_ids: ids };
        const btn = $('ap-save');
        setBusy(btn, true, 'Adding');
        try {
            const data = await apiJson(API_LEADS + '/' + encodeURIComponent(rec.id) + '/plots', { method: 'POST', body: JSON.stringify(body) });
            const updated = data.lead || data;
            closeModal($('add-plots-modal'));
            applyRecordUpdate(updated);
            if (state.drawer.record && String(state.drawer.record.id) === String(rec.id)) {
                state.drawer.record = updated;
                state.drawer.pendingPlots = null;
                const root = $('d-sections');
                const body = root && root.querySelector('[data-section="plots"] .rec-section__body');
                if (body) { body.innerHTML = renderPlotsBlock(updated, state.drawer.mode === 'edit'); bindSectionEvents(root); }
                renderDrawerHead(updated);
            }
            toast(ids.length + (ids.length === 1 ? ' plot added' : ' plots added'));
        } catch (e) {
            modalError('ap-error', e.message || 'Failed to add plots');
            toast(e.message || 'Failed to add plots', 'error');
        } finally { setBusy(btn, false); updateAddPlotsCount(); }
    }

    // Add interest ---------------------------------------------------------------
    async function ensureProjects() {
        if (state.projects.length) return state.projects;
        try {
            const rows = await apiJson('/api/crm/panoramas');
            setProjects(Array.isArray(rows) ? rows : []);
        } catch (e) { /* keep empty */ }
        return state.projects;
    }
    function setProjects(list) {
        state.projects = Array.isArray(list) ? list : [];
        state.projectById = new Map(state.projects.map(p => [String(p.id), p]));
    }
    async function ensureNormalProjects() {
        if (state.normalProjects) return state.normalProjects;
        try {
            const data = await apiJson('/api/crm/normal-projects?page=1&limit=500');
            state.normalProjects = global.CrmPager.parsePageResponse(data).items;
        } catch (e) { state.normalProjects = []; }
        return state.normalProjects;
    }
    async function openAddInterestModal() {
        const modal = $('add-interest-modal');
        const ai = state.addInterest;
        ai.selected = new Set();
        ai.plots = [];
        modalError('add-interest-error', '');
        modal.querySelectorAll('.rec-field.is-invalid').forEach(clearInvalid);
        ['ai-customer-name', 'ai-customer-email', 'ai-customer-phone', 'ai-category', 'ai-customer-city', 'ai-description', 'ai-plot-search'].forEach(id => { const el = $(id); if (el) el.value = ''; });
        $('ai-plots-wrap').innerHTML = '<div class="rec-plot-list__empty">Select a project first.</div>';
        $('ai-plots-count').textContent = '';
        $('ai-reference').innerHTML = '<option value="">No reference</option>';
        $('add-interest-master-fields').innerHTML = '';
        openModal(modal);
        const btn = $('add-interest-save');
        setBusy(btn, true, 'Loading');
        try {
            const [projects, normalProjects, masters] = await Promise.all([ensureProjects(), ensureNormalProjects(), loadMastersFor(null)]);
            ai.masters = masters || [];
            renderAiProjects(projects, normalProjects);
            renderAiMasters();
        } finally { setBusy(btn, false); }
        setTimeout(() => $('ai-workspace').focus(), 40);
    }
    function renderAiProjects(projects, normalProjects) {
        const sel = $('ai-workspace');
        const groups = new Map();
        const loose = [];
        projects.forEach(p => {
            if (p.workspace_id) { if (!groups.has(p.workspace_id)) groups.set(p.workspace_id, { name: p.workspace_name || ('Project #' + String(p.workspace_id).slice(0, 8)), panos: [] }); groups.get(p.workspace_id).panos.push(p); }
            else loose.push(p);
        });
        let html = '<option value="">Select project</option>';
        const visual = Array.from(groups.entries()).sort((a, b) => a[1].name.localeCompare(b[1].name)).map(([id, g]) => '<option value="ws:' + esc(id) + '">' + esc(g.name) + '</option>').join('')
            + loose.sort((a, b) => String(a.name || '').localeCompare(String(b.name || ''))).map(p => '<option value="pano:' + esc(p.id) + '">' + esc(p.name || ('Panorama #' + p.id)) + '</option>').join('');
        if (visual) html += '<optgroup label="Visual projects">' + visual + '</optgroup>';
        if (normalProjects && normalProjects.length) html += '<optgroup label="Normal projects">' + normalProjects.map(p => '<option value="np:' + esc(p.id) + '">' + esc(p.name || ('Project #' + p.id)) + '</option>').join('') + '</optgroup>';
        sel.innerHTML = html;
        sel.__groups = groups;
        $('ai-panorama-wrap').style.display = '';
        $('ai-panorama-id').innerHTML = '<option value="">Select sector</option>';
    }
    async function onAiWorkspaceChange() {
        const sel = $('ai-workspace');
        const value = String(sel.value || '');
        const panoSel = $('ai-panorama-id');
        const panoWrap = $('ai-panorama-wrap');
        const ai = state.addInterest;
        ai.selected = new Set();
        ai.plots = [];
        clearInvalid(sel.closest('.rec-field'));
        if (value.startsWith('ws:')) {
            const g = sel.__groups && sel.__groups.get(value.slice(3));
            const panos = (g ? g.panos : []).slice().sort((a, b) => String(a.name || '').localeCompare(String(b.name || '')));
            panoWrap.style.display = '';
            panoSel.innerHTML = '<option value="">Select sector</option>' + panos.map(p => '<option value="' + esc(p.id) + '">' + esc(p.name || ('Panorama #' + p.id)) + '</option>').join('');
            if (panos.length === 1) { panoSel.value = String(panos[0].id); await onAiPanoramaChange(); }
            else { $('ai-plots-wrap').innerHTML = '<div class="rec-plot-list__empty">Select a sector to list its plots.</div>'; $('ai-plots-count').textContent = ''; }
        } else if (value.startsWith('pano:')) {
            panoWrap.style.display = 'none';
            panoSel.innerHTML = '<option value="' + esc(value.slice(5)) + '" selected>—</option>';
            await onAiPanoramaChange();
        } else if (value.startsWith('np:')) {
            panoWrap.style.display = 'none';
            panoSel.innerHTML = '<option value="">—</option>';
            await loadAiPlots({ normalProjectId: value.slice(3) });
        } else {
            panoWrap.style.display = '';
            panoSel.innerHTML = '<option value="">Select sector</option>';
            $('ai-plots-wrap').innerHTML = '<div class="rec-plot-list__empty">Select a project first.</div>';
        }
    }
    async function onAiPanoramaChange() {
        const pid = String($('ai-panorama-id').value || '').trim();
        clearInvalid($('ai-panorama-id').closest('.rec-field'));
        if (!pid) { $('ai-plots-wrap').innerHTML = '<div class="rec-plot-list__empty">Select a sector to list its plots.</div>'; return; }
        await Promise.all([loadAiPlots({ panoramaId: pid }), loadAiReferenceUsers(pid)]);
    }
    async function loadAiPlots(src) {
        const ai = state.addInterest;
        const seq = ++ai.seq;
        const wrap = $('ai-plots-wrap');
        wrap.innerHTML = '<div class="rec-plot-list__loading"><span class="rec-spinner"></span>Loading plots…</div>';
        try {
            let rows = [];
            if (src.normalProjectId) {
                const data = await apiJson('/api/crm/normal-plots?page=1&limit=500&project_id=' + encodeURIComponent(src.normalProjectId));
                rows = global.CrmPager.parsePageResponse(data).items.map(p => ({ id: p.id, name: p.name, area: p.area, price: p.price, status: p.status, normal: true }));
            } else {
                const data = await apiJson('/api/crm/plots?page=1&limit=100&panorama_id=' + encodeURIComponent(src.panoramaId));
                rows = global.CrmPager.parsePageResponse(data).items;
            }
            if (seq !== ai.seq) return;
            ai.plots = rows;
            ai.selected = new Set();
            renderAiPlots();
        } catch (e) {
            if (seq !== ai.seq) return;
            wrap.innerHTML = '<div class="rec-plot-list__empty">' + esc(e.message || 'Failed to load plots') + '</div>';
        }
    }
    function renderAiPlots() {
        const ai = state.addInterest;
        const wrap = $('ai-plots-wrap');
        const q = normalizeText($('ai-plot-search').value);
        const rows = ai.plots.filter(p => !q || [p.name, p.area, p.status].some(v => normalizeText(v).includes(q)));
        $('ai-plots-count').textContent = ai.selected.size ? ai.selected.size + ' selected' : '';
        if (!rows.length) { wrap.innerHTML = '<div class="rec-plot-list__empty">' + (ai.plots.length ? 'No plots match your search.' : 'No plots in this project yet.') + '</div>'; return; }
        wrap.innerHTML = rows.map(p => '<label class="rec-plot-option' + (ai.selected.has(String(p.id)) ? ' is-checked' : '') + '"><input type="checkbox" data-ai-plot="' + esc(p.id) + '"' + (ai.selected.has(String(p.id)) ? ' checked' : '') + '><span><span class="rec-plot-option__name">' + esc(p.name || ('Plot #' + p.id)) + '</span><div class="rec-plot-option__meta">' + [p.area, p.price].filter(Boolean).map(esc).join(' · ') + '</div></span>' + plotStatusPill(p.status) + '</label>').join('');
        wrap.querySelectorAll('input[data-ai-plot]').forEach(cb => cb.addEventListener('change', () => {
            const id = String(cb.getAttribute('data-ai-plot'));
            if (cb.checked) ai.selected.add(id); else ai.selected.delete(id);
            cb.closest('.rec-plot-option').classList.toggle('is-checked', cb.checked);
            $('ai-plots-count').textContent = ai.selected.size ? ai.selected.size + ' selected' : '';
            clearInvalid(wrap.closest('.rec-field'));
        }));
    }
    async function loadAiReferenceUsers(panoramaId) {
        const users = await loadReferenceUsers(panoramaId, '');
        state.addInterest.refUsers = users;
        const sel = $('ai-reference');
        const cur = sel.value;
        sel.innerHTML = '<option value="">' + (users.length ? 'No reference' : 'No reference available') + '</option>' + users.map(u => '<option value="' + esc(u.user_id) + '">' + esc(refUserLabel(u)) + '</option>').join('');
        if (cur && users.some(u => String(u.user_id) === cur)) sel.value = cur;
    }
    function renderAiMasters() {
        const root = $('add-interest-master-fields');
        const skip = new Set(['deal_stage', 'state', 'country', 'title', 'plot_status', 'builder_name', 'project_type']);
        const fields = (state.addInterest.masters || []).filter(f => f && f.is_enabled !== false && Array.isArray(f.applies_to) && f.applies_to.map(x => String(x).toLowerCase()).includes('interests') && !skip.has(String(f.field_key || '')));
        root.innerHTML = fields.map(f => {
            const key = String(f.field_key || '').trim();
            const opts = Array.isArray(f.values) ? f.values.filter(v => v && v.is_enabled !== false).map(v => String(v.value || '').trim()).filter(Boolean) : [];
            const required = !!f.is_required;
            const label = '<span class="rec-field__label">' + esc(f.label || key) + (required ? '<i class="rec-req" aria-hidden="true">*</i>' : '') + '</span>';
            const control = opts.length
                ? '<select class="rec-field__input ai-master-field" data-key="' + esc(key) + '"' + (required ? ' data-required-input="1"' : '') + '><option value="">Select ' + esc(f.label || key) + '</option>' + opts.map(v => '<option value="' + esc(v) + '">' + esc(v) + '</option>').join('') + '</select>'
                : '<input class="rec-field__input ai-master-field" data-key="' + esc(key) + '"' + (required ? ' data-required-input="1"' : '') + ' maxlength="100">';
            return '<label class="rec-field" data-field="' + esc(key) + '">' + label + control + '<span class="rec-field__hint"></span></label>';
        }).join('');
        root.querySelectorAll('[data-key]').forEach(inp => inp.addEventListener('input', () => clearInvalid(inp.closest('.rec-field'))));
    }
    async function submitAddInterest() {
        const modal = $('add-interest-modal');
        const ai = state.addInterest;
        modalError('add-interest-error', '');
        const wsValue = String($('ai-workspace').value || '');
        const isNormal = wsValue.startsWith('np:');
        let panoramaId = '';
        if (wsValue.startsWith('ws:')) panoramaId = String($('ai-panorama-id').value || '').trim();
        else if (wsValue.startsWith('pano:')) panoramaId = wsValue.slice(5);
        let ok = validateModalFields(modal);
        if (!wsValue) { markInvalid($('ai-workspace').closest('.rec-field'), 'Select a project'); ok = false; }
        if (!isNormal && !panoramaId) { markInvalid($('ai-panorama-id').closest('.rec-field'), 'Select a sector'); ok = false; }
        if (!ai.selected.size) { markInvalid($('ai-plots-wrap').closest('.rec-field'), 'Select at least one plot'); ok = false; }
        if (!ok) { toast('Some required fields are missing', 'error'); return; }
        const body = {
            origin: isNormal ? 'manual_normal' : 'manual',
            customer_name: $('ai-customer-name').value.trim(),
            customer_email: $('ai-customer-email').value.trim(),
            customer_phone: $('ai-customer-phone').value.trim(),
            customer_city: $('ai-customer-city').value.trim(),
            category: $('ai-category').value.trim(),
            description: $('ai-description').value.trim(),
            reference_user_id: $('ai-reference').value || null,
            plots: Array.from(ai.selected).map(Number),
        };
        if (isNormal) { body.normal_project_id = Number(wsValue.slice(3)); body.normal_plot_ids = body.plots; }
        else body.panorama_id = Number(panoramaId);
        modal.querySelectorAll('.ai-master-field').forEach(inp => { const v = String(inp.value || '').trim(); if (v) body[inp.getAttribute('data-key')] = v; });
        const btn = $('add-interest-save');
        setBusy(btn, true, 'Creating');
        try {
            const data = await apiJson(API_LEADS, { method: 'POST', body: JSON.stringify(body) });
            closeModal(modal);
            toast('Interest added');
            const created = data.lead || data.buy_interest;
            const tab = state.tabs.interests;
            tab.pager.page = 1;
            await loadTab('interests', true).catch(() => {});
            if (created && created.id) openRecord(findRecord(created.id) || created, { tabKey: 'interests' });
        } catch (e) {
            if (e.field) {
                const map = { panorama_id: 'panorama_id', plots: 'plots' };
                const wrap = modal.querySelector('.rec-field[data-field="' + (map[e.field] || e.field) + '"]');
                if (wrap) markInvalid(wrap, e.message);
            }
            modalError('add-interest-error', e.message || 'Failed to add interest');
            toast(e.message || 'Failed to add interest', 'error');
        } finally { setBusy(btn, false); }
    }

    // ------------------------------------------------------------------ export
    async function fetchAllPages(params) {
        const rows = [];
        let page = 1;
        let total = Infinity;
        while (rows.length < total && page <= 200) {
            const data = await apiJson(API_LEADS + global.CrmPager.buildQuery({ page, size: 100 }, Object.assign({ include_facets: '0' }, params)));
            const parsed = global.CrmPager.parsePageResponse(data);
            total = parsed.total;
            rows.push.apply(rows, parsed.items);
            if (!parsed.items.length) break;
            page += 1;
        }
        return rows;
    }
    const EXPORT_COLUMNS = {
        interests: [
            { header: 'Created At', width: 20, formatter: r => r.created_at ? new Date(r.created_at).toLocaleString() : '' },
            { header: 'Customer Name', key: 'customer_name', width: 24 },
            { header: 'Email', width: 28, formatter: r => r.contact_hidden ? HIDDEN_LABEL : (r.customer_email || '') },
            { header: 'Phone', width: 18, formatter: r => r.contact_hidden ? '' : (r.customer_phone || '') },
            { header: 'Category', key: 'category', width: 16 },
            { header: 'Lead Source', key: 'lead_source', width: 16 },
            { header: 'Project', width: 24, formatter: r => r.workspace_name || r.panorama_name || '' },
            { header: 'Sector', key: 'panorama_name', width: 22 },
            { header: 'Plot Count', width: 10, formatter: r => (r.plots || []).length },
            { header: 'Plot Names', width: 30, formatter: r => (r.plots || []).map(plotLabel).join('; ') },
            { header: 'Reference', key: 'reference_user_name', width: 22 },
            { header: 'Ref Role', key: 'reference_user_role_label', width: 14 },
            { header: 'City', width: 16, formatter: r => r.contact_hidden ? '' : (r.customer_city || '') },
            { header: 'Notes', key: 'notes', width: 40 },
        ],
        deals: [
            { header: 'Deal', width: 28, formatter: r => r.deal_title || r.customer_name || 'Deal' },
            { header: 'Stage', width: 14, formatter: r => STAGE_LABELS[r.deal_stage] || r.deal_stage },
            { header: 'Customer', key: 'customer_name', width: 24 },
            { header: 'Email', width: 28, formatter: r => r.contact_hidden ? HIDDEN_LABEL : (r.customer_email || '') },
            { header: 'Phone', width: 18, formatter: r => r.contact_hidden ? '' : (r.customer_phone || '') },
            { header: 'Project', width: 24, formatter: r => r.deal_project_name || r.workspace_name || r.panorama_name || '' },
            { header: 'Amount', key: 'deal_amount', width: 14 },
            { header: 'Currency', key: 'deal_currency', width: 10 },
            { header: 'Plots', width: 10, formatter: r => (r.plots || []).length },
            { header: 'Plot Names', width: 30, formatter: r => (r.plots || []).map(plotLabel).join('; ') },
            { header: 'Reference', key: 'reference_user_name', width: 22 },
            { header: 'Ref Role', key: 'reference_user_role_label', width: 14 },
            { header: 'Converted At', width: 20, formatter: r => r.converted_at ? new Date(r.converted_at).toLocaleString() : '' },
            { header: 'Notes', key: 'notes', width: 40 },
        ],
        contacts: [
            { header: 'Name', key: 'customer_name', width: 26 },
            { header: 'Email', width: 28, formatter: r => r.contact_hidden ? HIDDEN_LABEL : (r.customer_email || '') },
            { header: 'Phone', width: 18, formatter: r => r.contact_hidden ? '' : (r.customer_phone || '') },
            { header: 'Birthday', width: 16, formatter: r => fmtBirthday(r.customer_birthday) },
            { header: 'Address', width: 34, formatter: r => r.contact_hidden ? '' : (r.customer_address || '') },
            { header: 'Project', width: 24, formatter: r => r.deal_project_name || r.workspace_name || r.panorama_name || '' },
            { header: 'Deal', width: 26, formatter: r => r.deal_title || '' },
            { header: 'Deal Stage', width: 14, formatter: r => STAGE_LABELS[r.deal_stage] || r.deal_stage },
            { header: 'Reference', key: 'reference_user_name', width: 22 },
            { header: 'Notes', key: 'notes', width: 40 },
        ],
    };
    async function exportTab(key) {
        const tab = state.tabs[key];
        if (!tab || !global.CrmExcelExport) return;
        const btn = $(tab.cfg.ids.exportBtn);
        const fileName = await global.CrmExcelExport.promptFilename(global.CrmExcelExport.suggestFileName(tab.cfg.exportName), 'Export ' + tab.cfg.sheet + ' to Excel');
        if (!fileName) return;
        setBusy(btn, true, 'Exporting');
        try {
            const rows = await fetchAllPages(buildParams(tab));
            if (!rows.length) { toast('No ' + key + ' to export', 'error'); return; }
            global.CrmExcelExport.exportRows(rows, EXPORT_COLUMNS[key], tab.cfg.sheet, fileName);
            toast(tab.cfg.sheet + ' exported');
        } catch (e) {
            toast(e.message || 'Failed to export', 'error');
        } finally { setBusy(btn, false); }
    }

    // ------------------------------------------------------- drawer resizing
    (function initDrawerResize() {
        if (!drawer) return;
        const KEY = 'crm_interest_drawer_width';
        const MIN = 380;
        const DEFAULT = 680;
        const maxWidth = () => Math.round(window.innerWidth * 0.96);
        const clamp = (px) => Math.min(maxWidth(), Math.max(Math.min(MIN, maxWidth()), Math.round(px)));
        const current = () => (drawer.getBoundingClientRect().width || DEFAULT);
        const apply = (px, persist) => {
            const w = clamp(px);
            drawer.style.setProperty('--crm-drawer-width', w + 'px');
            const expandBtn = $('drawer-expand');
            if (expandBtn) {
                const expanded = w > DEFAULT + 40;
                expandBtn.setAttribute('aria-pressed', expanded ? 'true' : 'false');
                expandBtn.title = expanded ? 'Restore panel width' : 'Expand panel';
            }
            if (persist) { try { localStorage.setItem(KEY, String(w)); } catch (e) { /* blocked */ } }
        };
        try { const saved = parseInt(localStorage.getItem(KEY) || '', 10); if (saved > 0) apply(saved, false); } catch (e) { /* blocked */ }
        const grip = $('drawer-resizer');
        if (grip) {
            let startX = 0;
            let startWidth = 0;
            const onMove = (e) => apply(startWidth + (startX - e.clientX), false);
            const onUp = () => {
                drawer.classList.remove('is-resizing');
                document.removeEventListener('pointermove', onMove);
                document.removeEventListener('pointerup', onUp);
                document.removeEventListener('pointercancel', onUp);
                apply(current(), true);
            };
            grip.addEventListener('pointerdown', (e) => {
                if (e.button !== 0) return;
                e.preventDefault();
                startX = e.clientX;
                startWidth = current();
                drawer.classList.add('is-resizing');
                try { grip.setPointerCapture(e.pointerId); } catch (err) { /* unsupported */ }
                document.addEventListener('pointermove', onMove);
                document.addEventListener('pointerup', onUp);
                document.addEventListener('pointercancel', onUp);
            });
            grip.addEventListener('keydown', (e) => {
                const step = e.shiftKey ? 80 : 24;
                if (e.key === 'ArrowLeft') { e.preventDefault(); apply(current() + step, true); }
                else if (e.key === 'ArrowRight') { e.preventDefault(); apply(current() - step, true); }
            });
        }
        const expandBtn = $('drawer-expand');
        if (expandBtn) expandBtn.addEventListener('click', () => {
            const isWide = current() > DEFAULT + 40;
            apply(isWide ? DEFAULT : Math.min(maxWidth(), 1100), true);
        });
        window.addEventListener('resize', () => { if (drawer.style.getPropertyValue('--crm-drawer-width')) apply(current(), false); });
    })();

    // ---------------------------------------------------------------- wiring
    function bindTab(key) {
        const tab = state.tabs[key];
        const ids = tab.cfg.ids;
        const applyBtn = $(ids.apply);
        const clearBtn = $(ids.clear);
        const search = $(ids.search);
        const exportBtn = $(ids.exportBtn);
        if (applyBtn) applyBtn.addEventListener('click', () => applyFilters(tab));
        if (clearBtn) clearBtn.addEventListener('click', () => clearFilters(tab));
        if (search) {
            search.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); applyFilters(tab); } });
            search.addEventListener('input', debounce(() => {
                const value = String(search.value || '').trim();
                if (value === tab.q) return;
                if (value === '' || value.length >= 2) applyFilters(tab);
            }, 380));
        }
        if (exportBtn) exportBtn.addEventListener('click', () => exportTab(key));
        const tabBtn = $(ids.tabBtn);
        if (tabBtn) tabBtn.addEventListener('click', () => {
            state.activeTab = key;
            if (tab.loaded && tab.stale) loadTab(key, true).catch(() => {});
            if (key === 'deals' && state.dealsView === 'kanban' && state.kanban.stale) loadKanban(true).catch(() => {});
        });
    }
    Object.keys(TABS).forEach(bindTab);

    const dealsToggle = $('deals-mode-toggle');
    if (dealsToggle) dealsToggle.querySelectorAll('[data-mode]').forEach(btn => btn.addEventListener('click', () => setDealsView(btn.getAttribute('data-mode'))));
    const refreshDealsBtn = $('btn-refresh-deals');
    if (refreshDealsBtn) refreshDealsBtn.addEventListener('click', async () => {
        setBusy(refreshDealsBtn, true, 'Refreshing');
        try {
            await loadTab('deals', true);
            if (state.dealsView === 'kanban') await loadKanban(true);
            toast('Deals refreshed');
        } catch (e) { /* toasted by loader */ }
        finally { setBusy(refreshDealsBtn, false); }
    });

    if ($('drawer-close')) $('drawer-close').addEventListener('click', closeDrawer);
    if (drawerBackdrop) drawerBackdrop.addEventListener('click', closeDrawer);
    if ($('btn-edit-toggle')) $('btn-edit-toggle').addEventListener('click', () => { if (state.drawer.mode === 'edit') saveDrawer(); else setDrawerMode('edit'); });
    if ($('btn-edit-cancel')) $('btn-edit-cancel').addEventListener('click', () => {
        if (drawerIsDirty() && !global.confirm('Discard unsaved changes?')) return;
        setDrawerMode('view');
    });
    if ($('btn-reveal-contact')) $('btn-reveal-contact').addEventListener('click', revealContact);
    if ($('btn-convert-lead')) $('btn-convert-lead').addEventListener('click', () => openConvertModal(state.drawer.record));
    if ($('btn-delete-record')) $('btn-delete-record').addEventListener('click', () => openDeleteModal(state.drawer.record));

    [['convert-deal-modal', ['convert-deal-close', 'cd-cancel']], ['add-plots-modal', ['ap-close', 'ap-cancel']], ['add-interest-modal', ['add-interest-close', 'add-interest-cancel']], ['record-delete-modal', ['rd-close', 'rd-cancel']]].forEach(([modalId, closeIds]) => {
        const modal = $(modalId);
        if (!modal) return;
        closeIds.forEach(id => { const b = $(id); if (b) b.addEventListener('click', () => closeModal(modal)); });
        modal.addEventListener('click', (e) => { if (e.target === modal) closeModal(modal); });
    });
    if ($('cd-save')) $('cd-save').addEventListener('click', submitConvert);
    if ($('cd-title')) $('cd-title').addEventListener('input', () => clearInvalid($('cd-title').closest('.rec-field')));
    if ($('cd-title')) $('cd-title').setAttribute('data-required-input', '1');
    if ($('ap-save')) $('ap-save').addEventListener('click', submitAddPlots);
    if ($('ap-search')) $('ap-search').addEventListener('input', debounce(renderAddPlotsList, 120));
    if ($('rd-confirm')) $('rd-confirm').addEventListener('click', submitDelete);
    if ($('btn-add-interest')) $('btn-add-interest').addEventListener('click', () => openAddInterestModal().catch(e => toast(e.message || 'Could not open form', 'error')));
    if ($('add-interest-save')) $('add-interest-save').addEventListener('click', submitAddInterest);
    if ($('ai-workspace')) $('ai-workspace').addEventListener('change', () => onAiWorkspaceChange().catch(() => {}));
    if ($('ai-panorama-id')) $('ai-panorama-id').addEventListener('change', () => onAiPanoramaChange().catch(() => {}));
    if ($('ai-plot-search')) $('ai-plot-search').addEventListener('input', debounce(renderAiPlots, 120));
    ['ai-customer-name', 'ai-customer-email', 'ai-customer-phone'].forEach(id => {
        const el = $(id);
        if (!el) return;
        el.setAttribute('data-required-input', '1');
        el.addEventListener('input', () => clearInvalid(el.closest('.rec-field')));
    });
    const reportsBtn = $('btn-reports');
    if (reportsBtn) reportsBtn.addEventListener('click', () => {
        if (state.tabs[state.activeTab]) exportTab(state.activeTab);
        else toast('Open Interests, Deals or Contacts to export', 'error');
    });
    document.addEventListener('keydown', (e) => {
        if (e.key !== 'Escape') return;
        const openModalEl = document.querySelector('.rec-modal-backdrop.visible');
        if (openModalEl) { closeModal(openModalEl); return; }
        const inModal = e.target && typeof e.target.closest === 'function' && e.target.closest('.crm-modal-backdrop.visible');
        if (drawer && drawer.classList.contains('show') && !inModal) closeDrawer();
    });
    document.querySelectorAll('.crm-tab[data-tab]').forEach(btn => btn.addEventListener('click', () => {
        const name = btn.getAttribute('data-tab');
        if (state.tabs[name]) state.activeTab = name;
    }));
    setDealsView('list');

    // ------------------------------------------------------------ public API
    global.CrmRecords = {
        loadTab: (name, force) => loadTab(name, !!force),
        isLoaded: (name) => !!(state.tabs[name] && state.tabs[name].loaded),
        refreshIfStale: async (force) => {
            const tab = state.tabs[state.activeTab];
            if (!tab) return;
            if (!force && tab.loaded && (Date.now() - state.lastLoadedAt) < STALE_MS) return;
            if (drawer && drawer.classList.contains('show') && state.drawer.mode === 'edit') return;
            await loadTab(state.activeTab, true);
            if (state.activeTab === 'deals' && state.dealsView === 'kanban') await loadKanban(true);
        },
        reset: () => { Object.keys(state.tabs).forEach(k => { const t = state.tabs[k]; t.loaded = false; t.stale = false; t.rows = []; t.seq++; }); state.kanban.loaded = false; state.kanban.rows = []; },
        preload: (force) => loadTab('deals', !!force).catch(() => {}),
        setProjects,
        setTeamUsers: (list) => { state.teamUsers = Array.isArray(list) ? list : []; },
        setProfile: applyProfile,
        getCachedRows: () => { const seen = new Set(); const out = []; Object.keys(state.tabs).forEach(k => state.tabs[k].rows.forEach(r => { if (!seen.has(String(r.id))) { seen.add(String(r.id)); out.push(r); } })); return out; },
        openRecord: (recOrId) => { if (recOrId && typeof recOrId === 'object') openRecord(recOrId); else openRecordById(recOrId); },
        exportActiveTab: () => exportTab(state.activeTab),
        state,
    };
})(typeof window !== 'undefined' ? window : this);
