/** Helpers over the generic dialogs in components/dashboard/prompt_modals.html. */
import { esc } from '../core/dom.js';
import { openModal } from '../ui/modal.js';

export function prompt({ title, description = '', label, value = '', submitLabel = 'Save', onSubmit }) {
    openModal('dash-prompt-modal', {
        onOpen(dialog) {
            dialog.setTitle(title);
            dialog.setDescription(description);
            dialog.setSubmitLabel(submitLabel);
            dialog.el.querySelector('[data-prompt-label]').textContent = label;
            dialog.form.elements.value.value = value;
        },
        onSubmit: (form) => onSubmit(form.elements.value.value.trim()),
    });
}

export function confirm({ title, description, confirmLabel = 'Delete', onConfirm }) {
    openModal('dash-confirm-modal', {
        onOpen(dialog) {
            dialog.setTitle(title);
            dialog.setDescription(description);
            dialog.setSubmitLabel(confirmLabel);
        },
        onSubmit: () => onConfirm(),
    });
}

/** Radio list with optional thumbnails; resolves with the chosen value. */
export function choose({ title, description, options, submitLabel, onSubmit }) {
    openModal('dash-choice-modal', {
        onOpen(dialog) {
            dialog.setTitle(title);
            dialog.setDescription(description);
            dialog.setSubmitLabel(submitLabel);
            dialog.el.querySelector('[data-choices]').innerHTML = options.map((o, i) => `
                <label class="dash-choice">
                    <input type="radio" name="choice" value="${esc(o.value)}" required${i === 0 ? ' checked data-autofocus' : ''}>
                    ${o.thumb ? `<img src="${esc(o.thumb)}" alt="" loading="lazy">` : ''}
                    <span>${esc(o.label)}</span>
                </label>`).join('');
        },
        onSubmit: (form) => onSubmit(form.elements.choice.value),
    });
}

export function selectOption({ title, description = '', label, options, value = '', submitLabel, onSubmit }) {
    openModal('dash-select-modal', {
        onOpen(dialog) {
            dialog.setTitle(title);
            dialog.setDescription(description);
            dialog.setSubmitLabel(submitLabel);
            dialog.el.querySelector('[data-select-label]').textContent = label;
            const select = dialog.form.elements.value;
            select.innerHTML = options.map((o) => `<option value="${esc(o.value)}">${esc(o.label)}</option>`).join('');
            select.value = value;
        },
        onSubmit: (form) => onSubmit(form.elements.value.value),
    });
}
