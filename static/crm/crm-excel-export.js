(function (global) {
    'use strict';

    var HEADER_FILL = '1F2937';
    var HEADER_FONT = 'FFFFFF';
    var BORDER_COLOR = 'D1D5DB';

    function pad(n) { return n < 10 ? '0' + n : String(n); }

    function timestamp() {
        var d = new Date();
        return d.getFullYear() + pad(d.getMonth() + 1) + pad(d.getDate()) + '-' + pad(d.getHours()) + pad(d.getMinutes());
    }

    function cellValue(row, col) {
        var v = typeof col.formatter === 'function' ? col.formatter(row) : row[col.key];
        if (v == null) return '';
        return v;
    }

    function buildSheet(rows, columns) {
        var header = columns.map(function (c) { return c.header; });
        var dataRows = rows.map(function (row) {
            return columns.map(function (c) { return cellValue(row, c); });
        });
        var ws = global.XLSX.utils.aoa_to_sheet([header].concat(dataRows));
        ws['!cols'] = columns.map(function (c) { return { wch: c.width || 20 }; });
        ws['!rows'] = [{ hpt: 22 }];
        var lastCol = columns.length - 1;
        ws['!autofilter'] = { ref: global.XLSX.utils.encode_range({ s: { r: 0, c: 0 }, e: { r: dataRows.length, c: lastCol } }) };

        var headerStyle = {
            font: { bold: true, color: { rgb: HEADER_FONT }, sz: 11 },
            fill: { patternType: 'solid', fgColor: { rgb: HEADER_FILL } },
            alignment: { vertical: 'center', horizontal: 'left' },
            border: {
                top: { style: 'thin', color: { rgb: BORDER_COLOR } },
                bottom: { style: 'thin', color: { rgb: BORDER_COLOR } },
                left: { style: 'thin', color: { rgb: BORDER_COLOR } },
                right: { style: 'thin', color: { rgb: BORDER_COLOR } }
            }
        };
        var bodyBorder = {
            border: {
                top: { style: 'hair', color: { rgb: BORDER_COLOR } },
                bottom: { style: 'hair', color: { rgb: BORDER_COLOR } },
                left: { style: 'hair', color: { rgb: BORDER_COLOR } },
                right: { style: 'hair', color: { rgb: BORDER_COLOR } }
            }
        };
        for (var c = 0; c <= lastCol; c++) {
            var addr = global.XLSX.utils.encode_cell({ r: 0, c: c });
            if (!ws[addr]) ws[addr] = { t: 's', v: '' };
            ws[addr].s = headerStyle;
        }
        for (var r = 1; r <= dataRows.length; r++) {
            for (var c2 = 0; c2 <= lastCol; c2++) {
                var a = global.XLSX.utils.encode_cell({ r: r, c: c2 });
                if (!ws[a]) continue;
                ws[a].s = bodyBorder;
            }
        }
        return ws;
    }

    // rows: array of plain objects. columns: [{ header, key, width, formatter(row) }]
    // fileName: exact name to save as (".xlsx" appended if missing).
    function exportRows(rows, columns, sheetName, fileName) {
        if (typeof global.XLSX === 'undefined') {
            throw new Error('Excel library is still loading, please try again in a moment');
        }
        if (!rows || !rows.length) return false;
        var wb = global.XLSX.utils.book_new();
        var ws = buildSheet(rows, columns);
        global.XLSX.utils.book_append_sheet(wb, ws, String(sheetName || 'Data').slice(0, 31));
        var name = String(fileName || 'CRM_Export').trim() || 'CRM_Export';
        if (!/\.xlsx$/i.test(name)) name += '.xlsx';
        global.XLSX.writeFile(wb, name);
        return true;
    }

    function suggestFileName(prefix) {
        return (prefix || 'CRM_Export') + '_' + timestamp();
    }

    function sanitizeFileName(name) {
        return String(name || '').trim().replace(/[\\/:*?"<>|]+/g, '-').slice(0, 150);
    }

    // Shows the shared "name the download" modal (markup lives once in
    // crm.html) and resolves with the sanitized name, or null if cancelled.
    function promptFilename(defaultName, title) {
        return new Promise(function (resolve) {
            var backdrop = document.getElementById('crm-export-filename-modal');
            var input = document.getElementById('crm-export-filename-input');
            var confirmBtn = document.getElementById('crm-export-filename-confirm');
            var cancelBtn = document.getElementById('crm-export-filename-cancel');
            var closeBtn = document.getElementById('crm-export-filename-close');
            var titleEl = document.getElementById('crm-export-filename-title');
            var errorEl = document.getElementById('crm-export-filename-error');
            if (!backdrop || !input || !confirmBtn || !cancelBtn) {
                resolve(sanitizeFileName(defaultName) || 'CRM_Export');
                return;
            }
            input.value = defaultName || 'CRM_Export';
            if (titleEl) titleEl.textContent = title || 'Export to Excel';
            if (errorEl) errorEl.style.display = 'none';
            backdrop.classList.add('visible');
            setTimeout(function () { input.focus(); input.select(); }, 30);

            function cleanup() {
                backdrop.classList.remove('visible');
                confirmBtn.removeEventListener('click', onConfirm);
                cancelBtn.removeEventListener('click', onCancel);
                if (closeBtn) closeBtn.removeEventListener('click', onCancel);
                backdrop.removeEventListener('click', onBackdropClick);
                input.removeEventListener('keydown', onKeydown);
            }
            function onConfirm() {
                var name = sanitizeFileName(input.value);
                if (!name) {
                    if (errorEl) errorEl.style.display = 'block';
                    return;
                }
                cleanup();
                resolve(name);
            }
            function onCancel() { cleanup(); resolve(null); }
            function onBackdropClick(e) { if (e.target === backdrop) onCancel(); }
            function onKeydown(e) {
                if (e.key === 'Enter') { e.preventDefault(); onConfirm(); }
                else if (e.key === 'Escape') { e.preventDefault(); onCancel(); }
            }
            confirmBtn.addEventListener('click', onConfirm);
            cancelBtn.addEventListener('click', onCancel);
            if (closeBtn) closeBtn.addEventListener('click', onCancel);
            backdrop.addEventListener('click', onBackdropClick);
            input.addEventListener('keydown', onKeydown);
        });
    }

    global.CrmExcelExport = {
        exportRows: exportRows,
        suggestFileName: suggestFileName,
        promptFilename: promptFilename
    };
})(typeof window !== 'undefined' ? window : this);
