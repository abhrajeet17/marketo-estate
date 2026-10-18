/**
 * One floating action menu for the whole page.
 * items: [{ label, action?, href?, newTab?, danger?, divider? }]; `onPick(item)` runs for action items.
 */
import { esc } from '../core/dom.js';

const menu = document.createElement('div');
menu.className = 'dash-menu';
menu.setAttribute('role', 'menu');
menu.hidden = true;
document.body.appendChild(menu);

let trigger = null;
let pick = null;
let current = [];

function position() {
    const r = trigger.getBoundingClientRect();
    const { offsetWidth: w, offsetHeight: h } = menu;
    const left = Math.max(8, Math.min(r.right - w, window.innerWidth - w - 8));
    const below = r.bottom + 6 + h <= window.innerHeight - 8;
    menu.style.left = `${left}px`;
    menu.style.top = `${below ? r.bottom + 6 : Math.max(8, r.top - h - 6)}px`;
}

export function closeMenu({ restoreFocus = false } = {}) {
    if (menu.hidden) return;
    menu.hidden = true;
    if (trigger) {
        trigger.setAttribute('aria-expanded', 'false');
        if (restoreFocus) trigger.focus();
    }
    trigger = null;
}

export function openMenu(button, items, onPick) {
    if (trigger === button && !menu.hidden) {
        closeMenu();
        return;
    }
    closeMenu();
    trigger = button;
    pick = onPick;
    current = items;
    menu.innerHTML = items.map((item, i) => {
        if (item.divider) return '<div class="dash-menu__divider" role="separator"></div>';
        const cls = `dash-menu__item${item.danger ? ' dash-menu__item--danger' : ''}`;
        return item.href
            ? `<a class="${cls}" role="menuitem" href="${esc(item.href)}" data-index="${i}"${item.newTab ? ' target="_blank" rel="noopener"' : ''}>${esc(item.label)}</a>`
            : `<button type="button" class="${cls}" role="menuitem" data-index="${i}">${esc(item.label)}</button>`;
    }).join('');
    menu.hidden = false;
    button.setAttribute('aria-expanded', 'true');
    position();
    const first = menu.querySelector('[role="menuitem"]');
    if (first) first.focus({ preventScroll: true });
}

menu.addEventListener('click', (e) => {
    const el = e.target.closest('[data-index]');
    if (!el) return;
    const item = current[Number(el.dataset.index)];
    if (item.href) { // native navigation
        if (item.newTab) closeMenu();
        return;
    }
    e.preventDefault();
    closeMenu();
    if (pick) pick(item);
});

menu.addEventListener('keydown', (e) => {
    const items = Array.from(menu.querySelectorAll('[role="menuitem"]'));
    const i = items.indexOf(document.activeElement);
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        const next = (i + (e.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length;
        items[next].focus();
    } else if (e.key === 'Escape' || e.key === 'Tab') {
        e.preventDefault();
        e.stopPropagation();
        closeMenu({ restoreFocus: true });
    }
});

document.addEventListener('click', (e) => {
    if (!menu.hidden && !menu.contains(e.target) && !(trigger && trigger.contains(e.target))) closeMenu();
});
window.addEventListener('resize', () => closeMenu());
document.addEventListener('scroll', () => closeMenu(), true);
