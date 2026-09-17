/**
 * Shared modal open/close and backdrop behavior.
 * Usage: After DOM ready, call window.ModalComponent.init() or use data-modal-close and data-modal-open attributes.
 */
(function () {
    function closeModal(backdropEl) {
        if (backdropEl) {
            backdropEl.classList.remove('visible');
            backdropEl.setAttribute('aria-hidden', 'true');
        }
    }

    function openModal(modalId) {
        var el = document.getElementById(modalId);
        if (el) {
            el.classList.add('visible');
            el.setAttribute('aria-hidden', 'false');
        }
    }

    function init() {
        document.addEventListener('click', function (e) {
            var closeBtn = e.target.closest('[data-modal-close]');
            if (closeBtn) {
                var id = closeBtn.getAttribute('data-modal-close');
                var backdrop = document.getElementById(id);
                closeModal(backdrop);
                return;
            }
            if (e.target.classList.contains('modal-backdrop')) {
                closeModal(e.target);
            }
        });

        document.addEventListener('click', function (e) {
            var openBtn = e.target.closest('[data-modal-open]');
            if (openBtn) {
                var id = openBtn.getAttribute('data-modal-open');
                openModal(id);
            }
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    window.ModalComponent = { open: openModal, close: closeModal, init: init };
})();
