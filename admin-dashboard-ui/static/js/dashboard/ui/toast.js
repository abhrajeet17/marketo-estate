import { icon } from '../core/dom.js';

const container = document.getElementById('dash-toasts');

export function toast(message, type = 'success') {
    if (!container || !message) return;
    const el = document.createElement('div');
    el.className = `dash-toast dash-toast--${type === 'error' ? 'error' : 'success'}`;
    el.innerHTML = icon(type === 'error' ? 'alert' : 'check', 16);
    const text = document.createElement('span');
    text.textContent = message;
    el.appendChild(text);
    container.appendChild(el);
    const dismiss = () => {
        el.classList.add('is-leaving');
        setTimeout(() => el.remove(), 200);
    };
    el.addEventListener('click', dismiss);
    setTimeout(dismiss, type === 'error' ? 5000 : 3200);
}
