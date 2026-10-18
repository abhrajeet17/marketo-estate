/**
 * Controller for dialogs rendered by templates/components/dashboard/modal.html.
 *
 *   const dialog = openModal('dash-prompt-modal', {
 *       onOpen(dialog) {},             // fill fields
 *       async onSubmit(form, dialog) {} // throw to show an error; return false to stay open
 *   });
 */
const stack = [];
const handlers = new WeakMap();

function bind(el) {
    if (handlers.has(el)) return;
    handlers.set(el, {});
    const form = el.querySelector('form');
    el.addEventListener('click', (e) => {
        if (e.target.closest('[data-modal-dismiss]')) closeModal(el);
    });
    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const h = handlers.get(el);
        if (el.dataset.busy === '1' || !h.onSubmit) return;
        if (!form.checkValidity()) {
            form.reportValidity();
            return;
        }
        const dialog = h.dialog;
        dialog.setError('');
        dialog.setBusy(true);
        try {
            const result = await h.onSubmit(form, dialog);
            dialog.setBusy(false);
            if (result !== false) closeModal(el);
        } catch (err) {
            dialog.setBusy(false);
            dialog.setError((err && err.message) || 'Something went wrong. Please try again.');
        }
    });
}

function controller(el) {
    const form = el.querySelector('form');
    const error = el.querySelector('[data-modal-error]');
    const submit = el.querySelector('[data-submit]');
    return {
        el,
        form,
        submit,
        setTitle(text) { el.querySelector('[data-modal-title]').textContent = text; },
        setDescription(text) {
            const desc = el.querySelector('[data-modal-desc]');
            desc.textContent = text || '';
            desc.hidden = !text;
        },
        setSubmitLabel(text) { if (submit) submit.textContent = text; },
        setError(message) {
            error.textContent = message || '';
            error.hidden = !message;
        },
        setBusy(busy) {
            el.dataset.busy = busy ? '1' : '';
            form.setAttribute('aria-busy', busy ? 'true' : 'false');
            el.querySelectorAll('[data-modal-dismiss]').forEach((btn) => { btn.disabled = busy; });
            if (submit) {
                submit.disabled = busy;
                submit.classList.toggle('is-busy', busy);
            }
        },
        close() { closeModal(el); },
    };
}

export function openModal(id, { onOpen, onSubmit, onClose } = {}) {
    const el = document.getElementById(id);
    if (!el) throw new Error(`Missing modal #${id}`);
    bind(el);
    const dialog = controller(el);
    handlers.set(el, { onSubmit, onClose, dialog, opener: document.activeElement });
    dialog.setError('');
    dialog.setBusy(false);
    if (onOpen) onOpen(dialog);
    if (!stack.includes(el)) stack.push(el);
    el.hidden = false;
    requestAnimationFrame(() => {
        el.classList.add('is-open');
        const target = el.querySelector('[data-autofocus]:not([disabled])') || dialog.submit;
        if (target) {
            target.focus();
            if (target.select && target.tagName === 'INPUT') target.select();
        }
    });
    return dialog;
}

export function closeModal(el) {
    if (!el || el.hidden || el.dataset.busy === '1') return;
    const h = handlers.get(el) || {};
    el.classList.remove('is-open');
    el.hidden = true;
    stack.splice(stack.indexOf(el), 1);
    if (h.onClose) h.onClose();
    if (h.opener && document.contains(h.opener)) h.opener.focus({ preventScroll: true });
}

document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && stack.length) {
        e.preventDefault();
        closeModal(stack[stack.length - 1]);
    }
});
