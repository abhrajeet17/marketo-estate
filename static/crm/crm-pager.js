(function (global) {
    'use strict';

    var DEFAULT_SIZE = 10;
    var PAGE_SIZE_OPTIONS = [10, 25, 50, 100];

    function parsePageResponse(data) {
        if (data && Array.isArray(data.items)) {
            return {
                items: data.items,
                total: parseInt(data.total, 10) || 0,
                page: parseInt(data.page, 10) || 1,
                limit: parseInt(data.limit, 10) || DEFAULT_SIZE,
                pages: parseInt(data.pages, 10) || 1
            };
        }
        var items = Array.isArray(data) ? data : [];
        return {
            items: items,
            total: items.length,
            page: 1,
            limit: items.length || DEFAULT_SIZE,
            pages: 1
        };
    }

    function buildQuery(pager, params) {
        var parts = [];
        var p = params || {};
        Object.keys(p).forEach(function (key) {
            var val = p[key];
            if (val === '' || val == null) return;
            parts.push(encodeURIComponent(key) + '=' + encodeURIComponent(String(val)));
        });
        parts.push('page=' + encodeURIComponent(String(pager.page || 1)));
        parts.push('limit=' + encodeURIComponent(String(pager.size || DEFAULT_SIZE)));
        return parts.length ? ('?' + parts.join('&')) : '';
    }

    function renderPagination(containerId, meta, pager, onChange, esc) {
        var el = typeof containerId === 'string' ? document.getElementById(containerId) : containerId;
        if (!el) return;
        var escape = typeof esc === 'function' ? esc : function (v) { return String(v == null ? '' : v); };
        var total = parseInt(meta && meta.total, 10) || 0;
        var limit = Math.max(1, parseInt(pager.size || DEFAULT_SIZE, 10));
        var pages = Math.max(1, parseInt(meta && meta.pages, 10) || Math.ceil(total / limit) || 1);
        pager.page = Math.min(Math.max(1, parseInt(pager.page || 1, 10)), pages);
        pager.size = limit;
        var hasRows = total > 0;
        var start = hasRows ? (((pager.page - 1) * limit) + 1) : 0;
        var end = hasRows ? Math.min(total, pager.page * limit) : 0;
        var sizeId = 'crm-page-size-' + (el.id || 'pager');
        el.innerHTML =
            '<span class="crm-pagination__meta crm-pagination__meta--range">' +
                (hasRows
                    ? 'Showing ' + escape(start) + '–' + escape(end) + ' of ' + escape(total) + ' records'
                    : 'No records to show') +
            '</span>' +
            '<span class="crm-pagination__size">' +
                '<label class="crm-pagination__label" for="' + escape(sizeId) + '">Rows per page</label>' +
                '<select id="' + escape(sizeId) + '" data-page-size title="Set how many rows are shown per page">' +
                    PAGE_SIZE_OPTIONS.map(function (size) {
                        return '<option value="' + size + '"' + (size === limit ? ' selected' : '') + '>' + size + ' rows</option>';
                    }).join('') +
                '</select>' +
            '</span>' +
            '<button class="btn" type="button" data-page-prev' + (pager.page <= 1 ? ' disabled' : '') +
                ' title="Go to the previous page" aria-label="Go to the previous page">&#8592; Previous page</button>' +
            '<span class="crm-pagination__meta crm-pagination__meta--page" aria-live="polite">Page ' + escape(pager.page) + ' of ' + escape(pages) + '</span>' +
            '<button class="btn" type="button" data-page-next' + (pager.page >= pages ? ' disabled' : '') +
                ' title="Go to the next page" aria-label="Go to the next page">Next page &#8594;</button>';
        var sizeEl = el.querySelector('[data-page-size]');
        if (sizeEl) {
            sizeEl.addEventListener('change', function () {
                pager.size = parseInt(sizeEl.value || String(DEFAULT_SIZE), 10) || DEFAULT_SIZE;
                pager.page = 1;
                onChange();
            });
        }
        var prev = el.querySelector('[data-page-prev]');
        if (prev) {
            prev.addEventListener('click', function () {
                pager.page = Math.max(1, pager.page - 1);
                onChange();
            });
        }
        var next = el.querySelector('[data-page-next]');
        if (next) {
            next.addEventListener('click', function () {
                pager.page = Math.min(pages, pager.page + 1);
                onChange();
            });
        }
    }

    global.CrmPager = {
        DEFAULT_SIZE: DEFAULT_SIZE,
        PAGE_SIZE_OPTIONS: PAGE_SIZE_OPTIONS,
        parsePageResponse: parsePageResponse,
        buildQuery: buildQuery,
        renderPagination: renderPagination
    };
})(typeof window !== 'undefined' ? window : this);
