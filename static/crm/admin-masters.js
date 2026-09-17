(function (global) {
    'use strict';

    const MASTER_FIELD_ORDER = ['lead_source', 'lead_category', 'lead_status', 'campaign_type', 'campaign_status', 'deal_stage', 'plot_status', 'state', 'country'];
    const MASTER_FIELD_LABELS = {
        lead_source: 'Lead Source',
        lead_category: 'Lead Category',
        lead_status: 'Lead Status',
        campaign_type: 'Campaign Type',
        campaign_status: 'Campaign Status',
        deal_stage: 'Deal Stage',
        plot_status: 'Plot Status',
        state: 'State',
        country: 'Country'
    };
    const MASTER_ENTITY_OPTIONS = [
        { id: 'interests', label: 'Interests' },
        { id: 'deals', label: 'Deals' },
        { id: 'contacts', label: 'Contacts' },
        { id: 'plots', label: 'Plots' }
    ];

    let config = null;
    let configLoaded = false;

    function esc(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function api(path, opts) {
        if (typeof global.getAuthHeaders !== 'function') {
            return fetch(path, opts || {});
        }
        return global.getAuthHeaders().then(function (headers) {
            const o = Object.assign({}, opts || {});
            o.headers = Object.assign({}, headers, o.headers || {});
            return fetch(path, o);
        });
    }

    function masterFields() {
        return config && Array.isArray(config.fields) ? config.fields : [];
    }

    function masterField(key) {
        return masterFields().find(function (f) { return String(f.field_key || '') === key; }) || null;
    }

    function masterAppliesList(field) {
        if (field && Array.isArray(field.applies_to) && field.applies_to.length) {
            return field.applies_to.map(function (x) { return String(x || '').trim().toLowerCase(); }).filter(Boolean);
        }
        return ['interests'];
    }

    function masterOptions(key) {
        const field = masterField(key);
        const dynamic = field && Array.isArray(field.values) ? field.values.filter(function (v) { return v && v.is_enabled !== false; }) : [];
        return dynamic;
    }

    function masterAppliesToKey(key, entity) {
        const field = masterField(key);
        if (!field || field.is_enabled === false) return false;
        return masterAppliesList(field).includes(String(entity || '').toLowerCase());
    }

    function plotStatusToken(label, forAdmin) {
        const k = String(label || '').trim().toLowerCase();
        if (k === 'available') return 'available';
        if (k === 'sold') return 'sold';
        if (k === 'hold' || k === 'on hold' || k === 'on_hold' || k === 'onhold') return forAdmin ? 'on_hold' : 'hold';
        return k.replace(/\s+/g, '_').replace(/-/g, '_');
    }

    function defaultPlotStatusOptionsHtml(currentValue, forAdmin) {
        const cur = String(currentValue || '').toLowerCase();
        const opts = forAdmin
            ? [['available', 'Available'], ['on_hold', 'On Hold'], ['sold', 'Sold']]
            : [['available', 'Available'], ['hold', 'Hold'], ['sold', 'Sold']];
        return opts.map(function (pair) {
            const val = pair[0];
            const label = pair[1];
            const selected = val === cur || (val === 'on_hold' && cur === 'hold') || (val === 'hold' && cur === 'on_hold') ? ' selected' : '';
            return '<option value="' + esc(val) + '"' + selected + '>' + esc(label) + '</option>';
        }).join('');
    }

    function plotStatusOptionsHtml(currentValue, forAdmin) {
        if (!masterAppliesToKey('plot_status', 'plots')) return defaultPlotStatusOptionsHtml(currentValue, forAdmin);
        const options = masterOptions('plot_status');
        if (!options.length) return defaultPlotStatusOptionsHtml(currentValue, forAdmin);
        const cur = String(currentValue || '').toLowerCase();
        return options.map(function (v) {
            const label = String(v.value || '').trim();
            const val = plotStatusToken(label, forAdmin);
            const selected = val === cur || (val === 'on_hold' && (cur === 'hold' || cur === 'onhold')) ? ' selected' : '';
            return '<option value="' + esc(val) + '"' + selected + '>' + esc(label) + '</option>';
        }).join('');
    }

    function manageBody() {
        return { client_id: global.CRM_MASTER_CLIENT_ID || '', panorama_id: String(global.PANORAMA_ID || '') };
    }

    async function loadConfig(force) {
        if (configLoaded && !force && config) return config;
        const qs = new URLSearchParams();
        const clientId = String(global.CRM_MASTER_CLIENT_ID || '').trim();
        if (clientId) qs.set('client_id', clientId);
        if (global.PANORAMA_ID != null) qs.set('panorama_id', String(global.PANORAMA_ID));
        qs.set('include_disabled', '1');
        const r = await api('/api/crm/master-config?' + qs.toString());
        const data = await r.json().catch(function () { return {}; });
        if (!r.ok) throw new Error(data.error || 'Failed to load masters');
        config = data;
        configLoaded = true;
        return config;
    }

    function renderEntityChecks(field) {
        const applies = masterAppliesList(field);
        return '<div class="master-entity-checks">' + MASTER_ENTITY_OPTIONS.map(function (ent) {
            return '<label class="master-entity-check"><input type="checkbox" class="master-entity-cb" value="' + esc(ent.id) + '" ' + (applies.includes(ent.id) ? 'checked' : '') + '><span>' + esc(ent.label) + '</span></label>';
        }).join('') + '</div>';
    }

    function renderValuesRow(field) {
        const key = String(field.field_key || '');
        const values = Array.isArray(field.values) ? field.values.filter(function (v) { return v && v.is_enabled !== false; }) : [];
        const chips = values.map(function (v) {
            return '<span class="master-value-chip" data-value-id="' + esc(String(v.id || '')) + '">' +
                '<span class="master-value-chip-label">' + esc(String(v.value || '')) + '</span>' +
                '<button type="button" class="master-value-remove" aria-label="Remove">&times;</button></span>';
        }).join('');
        return '<tr class="master-values-row" data-field-key="' + esc(key) + '"><td colspan="4"><div class="master-values-editor">' +
            '<div class="master-value-chips">' + chips + '</div>' +
            '<div class="master-value-add"><input type="text" class="form-input master-value-input" maxlength="100" placeholder="Add option" autocomplete="off">' +
            '<button type="button" class="modal-btn secondary master-value-add-btn">Add</button></div></div></td></tr>';
    }

    function masterSortAccessors() {
        return {
            label: function (f) { return f.label || MASTER_FIELD_LABELS[String(f.field_key || '')] || String(f.field_key || ''); },
            is_enabled: function (f) { return f.is_enabled !== false ? 1 : 0; },
            rule: function (f) { return f.is_required ? 'required' : 'optional'; },
            applies_to: function (f) { return (Array.isArray(f.applies_to) ? f.applies_to.slice().sort().join(', ') : ''); }
        };
    }

    function renderTable(fields) {
        let ordered = fields.slice().sort(function (a, b) {
            const ai = MASTER_FIELD_ORDER.indexOf(String(a.field_key || ''));
            const bi = MASTER_FIELD_ORDER.indexOf(String(b.field_key || ''));
            return (ai < 0 ? 999 : ai) - (bi < 0 ? 999 : bi);
        }).filter(function (field) { return String(field.field_key || '') !== 'title'; });
        if (global.CrmSort) {
            ordered = global.CrmSort.sortRows(ordered, 'master-attributes', masterSortAccessors());
        }
        const rows = ordered.map(function (field) {
            const key = String(field.field_key || '');
            const label = field.label || MASTER_FIELD_LABELS[key] || key;
            const mode = field.is_required ? 'required' : 'optional';
            return '<tr class="master-row" data-field-key="' + esc(key) + '">' +
                '<td><strong>' + esc(label) + '</strong><span>' + esc(key) + '</span></td>' +
                '<td><label class="master-switch"><input type="checkbox" class="master-enabled" ' + (field.is_enabled !== false ? 'checked' : '') + '><span></span></label></td>' +
                '<td><select class="form-input master-mode-select"><option value="required" ' + (mode === 'required' ? 'selected' : '') + '>Required</option><option value="optional" ' + (mode === 'optional' ? 'selected' : '') + '>Optional</option></select></td>' +
                '<td class="master-entities-cell">' + renderEntityChecks(field) + '</td></tr>' + renderValuesRow(field);
        }).join('');
        return '<div class="master-table-wrap"><table class="master-table"><thead><tr><th data-sort-key="label">Attribute</th><th data-sort-key="is_enabled">Status</th><th data-sort-key="rule">Rule</th><th data-sort-key="applies_to">Used in</th></tr></thead><tbody id="master-attrs-tbody">' + rows + '</tbody></table></div>';
    }

    function bindGrid(root) {
        root.querySelectorAll('.master-row').forEach(function (row) {
            const fieldKey = row.getAttribute('data-field-key');
            const saveAttr = async function () {
                const appliesTo = [];
                row.querySelectorAll('.master-entity-cb').forEach(function (cb) {
                    if (cb.checked) appliesTo.push(cb.value);
                });
                if (!appliesTo.length) throw new Error('Select at least one section');
                const mode = row.querySelector('.master-mode-select').value;
                const body = Object.assign({}, manageBody(), {
                    is_required: mode === 'required',
                    is_optional: mode !== 'required',
                    is_enabled: !!row.querySelector('.master-enabled').checked,
                    applies_to: appliesTo
                });
                const r = await api('/api/crm/master-attributes/' + encodeURIComponent(fieldKey), {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body)
                });
                const data = await r.json().catch(function () { return {}; });
                if (!r.ok) throw new Error(data.error || 'Failed to save');
                configLoaded = false;
            };
            row.querySelectorAll('.master-mode-select,.master-enabled,.master-entity-cb').forEach(function (input) {
                input.addEventListener('change', function () { saveAttr().catch(function (e) { alert(e.message || 'Failed'); }); });
            });
        });
        root.querySelectorAll('.master-values-row').forEach(function (row) {
            const fieldKey = row.getAttribute('data-field-key');
            const input = row.querySelector('.master-value-input');
            const addBtn = row.querySelector('.master-value-add-btn');
            const chips = row.querySelector('.master-value-chips');
            const addValue = async function () {
                const value = String(input && input.value || '').trim();
                if (!value) return;
                const body = Object.assign({}, manageBody(), { field_key: fieldKey, value: value });
                const r = await api('/api/crm/master-values', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body)
                });
                const data = await r.json().catch(function () { return {}; });
                if (!r.ok) throw new Error(data.error || 'Failed to add');
                configLoaded = false;
                await renderMastersPanel(true);
                populatePlotStatusSelect(plotStatusSelect ? plotStatusSelect.value : 'available');
            };
            if (addBtn) addBtn.addEventListener('click', function () { addValue().catch(function (e) { alert(e.message || 'Failed'); }); });
            if (input) input.addEventListener('keydown', function (ev) {
                if (ev.key === 'Enter') { ev.preventDefault(); addValue().catch(function (e) { alert(e.message || 'Failed'); }); }
            });
            if (chips) chips.querySelectorAll('.master-value-remove').forEach(function (btn) {
                btn.addEventListener('click', async function () {
                    const chip = btn.closest('.master-value-chip');
                    const valueId = chip && chip.getAttribute('data-value-id');
                    if (!valueId) return;
                    const body = Object.assign({}, manageBody(), { is_enabled: false });
                    const r = await api('/api/crm/master-values/' + encodeURIComponent(valueId), {
                        method: 'PATCH',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(body)
                    });
                    const data = await r.json().catch(function () { return {}; });
                    if (!r.ok) throw new Error(data.error || 'Failed to remove');
                    configLoaded = false;
                    await renderMastersPanel(true);
                    populatePlotStatusSelect(plotStatusSelect ? plotStatusSelect.value : 'available');
                });
            });
        });
    }

    let plotStatusSelect = null;

    async function renderMastersPanel(force) {
        const grid = document.getElementById('admin-master-grid');
        const empty = document.getElementById('admin-master-empty');
        if (!grid) return;
        grid.innerHTML = '';
        if (empty) empty.style.display = 'none';
        if (!global.CRM_MASTER_CLIENT_ID) {
            if (empty) {
                empty.style.display = '';
                empty.textContent = 'No client scope for this project. Masters cannot be loaded.';
            }
            return;
        }
        try {
            const cfg = await loadConfig(!!force);
            const fields = Array.isArray(cfg.fields) ? cfg.fields : [];
            if (!fields.length) {
                if (empty) empty.style.display = '';
                return;
            }
            const paint = function () {
                grid.innerHTML = renderTable(fields);
                bindGrid(grid);
                if (global.CrmSort) {
                    global.CrmSort.bindClient('master-attributes', {
                        tbodyId: 'master-attrs-tbody',
                        render: paint
                    });
                }
            };
            paint();
        } catch (e) {
            if (empty) {
                empty.style.display = '';
                empty.textContent = e.message || 'Failed to load masters';
            }
        }
    }

    function populatePlotStatusSelect(currentValue) {
        if (!plotStatusSelect) return;
        plotStatusSelect.innerHTML = plotStatusOptionsHtml(currentValue, true);
    }

    function init(opts) {
        plotStatusSelect = opts.plotStatusSelect || document.getElementById('plot-status');
        const mastersBtn = document.getElementById('crm-masters-btn');
        const modal = document.getElementById('crm-masters-modal');
        const closeBtn = document.getElementById('crm-masters-close');
        if (mastersBtn && modal) {
            mastersBtn.addEventListener('click', function () {
                modal.classList.add('visible');
                renderMastersPanel(false);
            });
        }
        if (closeBtn && modal) {
            closeBtn.addEventListener('click', function () { modal.classList.remove('visible'); });
        }
        if (modal) {
            modal.addEventListener('click', function (e) {
                if (e.target === modal) modal.classList.remove('visible');
            });
        }
        return loadConfig(false).then(function () {
            populatePlotStatusSelect('available');
        }).catch(function () {
            populatePlotStatusSelect('available');
        });
    }

    global.AdminCrmMasters = {
        init: init,
        loadConfig: loadConfig,
        renderMastersPanel: renderMastersPanel,
        populatePlotStatusSelect: populatePlotStatusSelect,
        plotStatusOptionsHtml: plotStatusOptionsHtml,
        masterAppliesToKey: masterAppliesToKey
    };
})(typeof window !== 'undefined' ? window : global);
