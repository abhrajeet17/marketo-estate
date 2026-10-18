/**
 * Shared column-header sorting for CRM tables.
 *
 * Mark sortable headers in markup with `data-sort-key="<field>"`, then either:
 *   - server-paginated tables: CrmSort.attach(key, { tbodyId, onSort }) and merge
 *     CrmSort.params(key) into the list request, so the sort spans every page;
 *   - fully in-memory tables: CrmSort.bindClient(key, { tbodyId, render }) and run
 *     the array through CrmSort.sortRows(rows, key) inside the render function.
 */
(function (global) {
    'use strict';

    var STATES = {};
    var ISO_DATE = /^\d{4}-\d{2}-\d{2}/;

    function tableFor(tbodyId) {
        var tbody = document.getElementById(tbodyId);
        return tbody ? tbody.closest('table') : null;
    }

    function headerCells(table) {
        if (!table) return [];
        return Array.prototype.slice.call(table.querySelectorAll('thead th[data-sort-key]'));
    }

    function paint(table, state) {
        headerCells(table).forEach(function (th) {
            var active = !!(state && state.field && th.getAttribute('data-sort-key') === state.field);
            th.classList.add('crm-sortable');
            th.classList.toggle('is-sorted', active);
            th.setAttribute('aria-sort', active ? (state.dir === 'asc' ? 'ascending' : 'descending') : 'none');
            var icon = th.querySelector('.crm-sort-icon');
            if (!icon) {
                icon = document.createElement('span');
                icon.className = 'crm-sort-icon';
                icon.setAttribute('aria-hidden', 'true');
                th.appendChild(icon);
            }
            icon.textContent = active ? (state.dir === 'asc' ? '▲' : '▼') : '⇅';
        });
    }

    function attach(key, options) {
        var opts = options || {};
        var table = tableFor(opts.tbodyId);
        if (!table) return;
        if (!STATES[key] && opts.defaultField) {
            STATES[key] = { field: opts.defaultField, dir: opts.defaultDir === 'asc' ? 'asc' : 'desc' };
        }
        if (table.getAttribute('data-sort-bound') === key) {
            paint(table, STATES[key]);
            return;
        }
        table.setAttribute('data-sort-bound', key);
        headerCells(table).forEach(function (th) {
            // Header cells can be re-enabled after a mode switch; never bind twice.
            if (th._crmSortBound) return;
            th._crmSortBound = true;
            th.classList.add('crm-sortable');
            th.setAttribute('tabindex', '0');
            th.setAttribute('role', 'button');
            var activate = function () {
                var field = th.getAttribute('data-sort-key');
                // setEnabled() strips the attribute but cannot unbind this
                // listener; a visually disabled header must not sort.
                if (!field) return;
                var cur = STATES[key];
                // First click on a column sorts ascending; clicking it again flips.
                var dir = (cur && cur.field === field && cur.dir === 'asc') ? 'desc' : 'asc';
                STATES[key] = { field: field, dir: dir };
                paint(table, STATES[key]);
                if (typeof opts.onSort === 'function') opts.onSort(STATES[key]);
            };
            th.addEventListener('click', activate);
            th.addEventListener('keydown', function (e) {
                if (e.key === 'Enter' || e.key === ' ' || e.key === 'Spacebar') {
                    e.preventDefault();
                    activate();
                }
            });
        });
        paint(table, STATES[key]);
    }

    /** Convenience wrapper for tables whose whole dataset is already in memory. */
    function bindClient(key, options) {
        var opts = options || {};
        attach(key, {
            tbodyId: opts.tbodyId,
            defaultField: opts.defaultField,
            defaultDir: opts.defaultDir,
            onSort: function () { if (typeof opts.render === 'function') opts.render(); }
        });
    }

    function state(key) {
        return STATES[key] || null;
    }

    /** Query params for a server-sorted list request. */
    function params(key) {
        var s = STATES[key];
        return (s && s.field) ? { sort: s.field, dir: s.dir } : {};
    }

    function refresh(key, tbodyId) {
        paint(tableFor(tbodyId), STATES[key]);
    }

    function clear(key, tbodyId) {
        delete STATES[key];
        if (tbodyId) paint(tableFor(tbodyId), null);
    }

    /**
     * Show or hide the sort affordance for one column, for tables whose
     * sortable set depends on the active mode. Disabling the column that is
     * currently sorted drops the sort rather than leaving a dead state.
     */
    function setEnabled(key, tbodyId, field, enabled) {
        var table = tableFor(tbodyId);
        if (!table) return false;
        var attr = enabled ? 'data-sort-key-off' : 'data-sort-key';
        var th = table.querySelector('thead th[' + attr + '="' + field + '"]');
        var cleared = false;
        if (th) {
            th.removeAttribute(attr);
            th.setAttribute(enabled ? 'data-sort-key' : 'data-sort-key-off', field);
            if (!enabled) {
                th.classList.remove('crm-sortable', 'is-sorted');
                th.removeAttribute('aria-sort');
                th.removeAttribute('tabindex');
                th.removeAttribute('role');
                var icon = th.querySelector('.crm-sort-icon');
                if (icon) icon.remove();
            }
        }
        if (!enabled && STATES[key] && STATES[key].field === field) {
            delete STATES[key];
            cleared = true;
        }
        // Header cells changed, so the click bindings must be re-established.
        table.removeAttribute('data-sort-bound');
        return cleared;
    }

    function isEmpty(v) {
        return v === null || v === undefined || (typeof v === 'string' && !v.trim());
    }

    function numeric(v) {
        if (typeof v === 'number') return isFinite(v) ? v : null;
        if (typeof v === 'boolean') return v ? 1 : 0;
        var s = String(v).trim();
        if (!s) return null;
        if (ISO_DATE.test(s)) {
            var t = Date.parse(s);
            if (!isNaN(t)) return t;
        }
        // Currency / area / percentage cells: strip symbols and separators.
        var cleaned = s.replace(/[^0-9.+-]/g, '');
        if (!/\d/.test(cleaned)) return null;
        var n = parseFloat(cleaned);
        return isNaN(n) ? null : n;
    }

    function compare(a, b) {
        var na = numeric(a);
        var nb = numeric(b);
        if (na !== null && nb !== null) {
            if (na < nb) return -1;
            if (na > nb) return 1;
            return 0;
        }
        return String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: 'base' });
    }

    /**
     * Stable sort of `rows` by the active state for `key`.
     * `accessors` maps a sort key to a function deriving the value from a row,
     * for columns that are computed rather than a plain property.
     * Empty values always sort last, in both directions.
     */
    function sortRows(rows, key, accessors) {
        var list = Array.isArray(rows) ? rows.slice() : [];
        var s = STATES[key];
        if (!s || !s.field) return list;
        var mult = s.dir === 'asc' ? 1 : -1;
        var read = function (row) {
            var fn = accessors && accessors[s.field];
            if (fn) return fn(row);
            return row ? row[s.field] : null;
        };
        return list
            .map(function (row, i) { return { row: row, i: i }; })
            .sort(function (x, y) {
                var a = read(x.row);
                var b = read(y.row);
                var ea = isEmpty(a);
                var eb = isEmpty(b);
                if (ea || eb) {
                    if (ea && eb) return x.i - y.i;
                    return ea ? 1 : -1;
                }
                var c = compare(a, b);
                return c ? c * mult : x.i - y.i;
            })
            .map(function (w) { return w.row; });
    }

    global.CrmSort = {
        attach: attach,
        bindClient: bindClient,
        sortRows: sortRows,
        setEnabled: setEnabled,
        state: state,
        params: params,
        refresh: refresh,
        clear: clear
    };
})(window);
