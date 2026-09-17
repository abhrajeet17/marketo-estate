(function () {
    'use strict';

    var topZ = 1300;
    var panelSelector = [
        '.crm-modal-backdrop > .crm-modal',
        '.entity-filter-modal'
    ].join(',');
    var handleSelector = [
        '.crm-modal-header',
        '.filter-modal-head'
    ].join(',');
    var closeSelector = [
        '.crm-modal-close',
        '.filter-modal-close'
    ].join(',');

    function clamp(value, min, max) {
        return Math.max(min, Math.min(max, value));
    }

    function isInteractive(target) {
        return !!(target && target.closest('button,a,input,select,textarea,label,[role="button"]'));
    }

    function panelTitle(panel) {
        var title = panel.querySelector('h1,h2,h3,.modal-title');
        return title ? String(title.textContent || '').trim() : 'window';
    }

    function ensureTools(panel, handle) {
        if (handle.querySelector('.crm-window-collapse')) return;
        var tools = document.createElement('div');
        tools.className = 'crm-window-tools';

        var collapse = document.createElement('button');
        collapse.type = 'button';
        collapse.className = 'crm-window-collapse';
        collapse.setAttribute('aria-label', 'Collapse ' + panelTitle(panel));
        collapse.textContent = '-';
        collapse.addEventListener('click', function (event) {
            event.preventDefault();
            event.stopPropagation();
            var isCollapsed = panel.classList.toggle('is-collapsed');
            collapse.textContent = isCollapsed ? '+' : '-';
            collapse.setAttribute('aria-label', (isCollapsed ? 'Expand ' : 'Collapse ') + panelTitle(panel));
        });

        tools.appendChild(collapse);
        var closeButton = handle.querySelector(closeSelector);
        if (closeButton) {
            handle.insertBefore(tools, closeButton);
        } else {
            handle.appendChild(tools);
        }
    }

    function activatePanel(panel) {
        panel.style.zIndex = String(++topZ);
    }

    function isInlineFilterPanel(panel) {
        return !!(panel && (
            panel.classList.contains('crm-filter-panel') ||
            panel.closest('.crm-filter-rail')
        ));
    }

    function makeMovable(panel) {
        if (!panel || panel.dataset.crmWindowReady === '1' || isInlineFilterPanel(panel)) return;
        var handle = panel.querySelector(handleSelector) || panel.firstElementChild;
        if (!handle) return;

        panel.dataset.crmWindowReady = '1';
        panel.classList.add('crm-window');
        handle.classList.add('crm-window-handle');
        ensureTools(panel, handle);

        var drag = null;

        handle.addEventListener('pointerdown', function (event) {
            if (event.button !== 0 || isInteractive(event.target)) return;
            var rect = panel.getBoundingClientRect();
            if (!rect.width || !rect.height) return;

            activatePanel(panel);
            panel.classList.add('is-dragging');
            panel.dataset.crmDragged = '1';
            // Do not force width on the edit-project-modal (controlled by CSS)
            if (!panel.closest('#edit-project-modal')) {
                panel.style.width = rect.width + 'px';
            }
            panel.style.left = rect.left + 'px';
            panel.style.top = rect.top + 'px';
            panel.style.right = 'auto';
            panel.style.bottom = 'auto';

            drag = {
                pointerId: event.pointerId,
                startX: event.clientX,
                startY: event.clientY,
                left: rect.left,
                top: rect.top,
                width: rect.width,
                height: rect.height
            };

            try { handle.setPointerCapture(event.pointerId); } catch (_err) {}
            event.preventDefault();
        });

        handle.addEventListener('pointermove', function (event) {
            if (!drag || event.pointerId !== drag.pointerId) return;
            var nextLeft = drag.left + event.clientX - drag.startX;
            var nextTop = drag.top + event.clientY - drag.startY;
            var maxLeft = Math.max(12, window.innerWidth - drag.width - 12);
            var maxTop = Math.max(12, window.innerHeight - 48);
            panel.style.left = clamp(nextLeft, 12, maxLeft) + 'px';
            panel.style.top = clamp(nextTop, 12, maxTop) + 'px';
        });

        function stopDrag(event) {
            if (!drag || (event && event.pointerId !== drag.pointerId)) return;
            try { handle.releasePointerCapture(drag.pointerId); } catch (_err) {}
            drag = null;
            panel.classList.remove('is-dragging');
        }

        handle.addEventListener('pointerup', stopDrag);
        handle.addEventListener('pointercancel', stopDrag);
        panel.addEventListener('mousedown', function () { activatePanel(panel); });
    }

    function initCrmWindows(root) {
        Array.prototype.forEach.call((root || document).querySelectorAll(panelSelector), makeMovable);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () { initCrmWindows(document); });
    } else {
        initCrmWindows(document);
    }

    window.crmModalWorkspace = {
        refresh: function () { initCrmWindows(document); }
    };
})();
