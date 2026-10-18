const ESCAPES = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };

export const $ = (selector, root = document) => root.querySelector(selector);
export const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

export function esc(value) {
    return String(value ?? '').replace(/[&<>"']/g, (ch) => ESCAPES[ch]);
}

/** Icon paths mirror templates/components/dashboard/icons.html for markup rendered in JS. */
const ICONS = {
    search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
    folder: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    unlinked: '<circle cx="12" cy="12" r="9"/><path d="m5.6 5.6 12.8 12.8"/>',
    more: '<circle cx="12" cy="5" r="1.4"/><circle cx="12" cy="12" r="1.4"/><circle cx="12" cy="19" r="1.4"/>',
    pin: '<path d="M12 21s-7-6.2-7-11a7 7 0 0 1 14 0c0 4.8-7 11-7 11z"/><circle cx="12" cy="10" r="2.5"/>',
    image: '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="2"/><path d="m21 16-5-5-9 9"/>',
    upload: '<path d="M12 16V4M7 9l5-5 5 5"/><path d="M20 16v3a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-3"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    alert: '<circle cx="12" cy="12" r="9"/><path d="M12 8v5M12 16.5v.01"/>',
    check: '<path d="m5 12 5 5 9-10"/>',
    x: '<path d="M18 6 6 18M6 6l12 12"/>',
};

export function icon(name, size = 18) {
    return `<svg class="dash-svg" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name] || ''}</svg>`;
}

export function debounce(fn, ms) {
    let timer = 0;
    return (...args) => {
        clearTimeout(timer);
        timer = setTimeout(() => fn(...args), ms);
    };
}

export function formatBytes(bytes) {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

const RELATIVE = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' });

export function formatRelative(value) {
    const time = new Date(value).getTime();
    if (!Number.isFinite(time)) return '';
    const seconds = Math.round((time - Date.now()) / 1000);
    const abs = Math.abs(seconds);
    if (abs < 60) return 'just now';
    if (abs < 3600) return RELATIVE.format(Math.round(seconds / 60), 'minute');
    if (abs < 86400) return RELATIVE.format(Math.round(seconds / 3600), 'hour');
    if (abs < 604800) return RELATIVE.format(Math.round(seconds / 86400), 'day');
    return new Date(time).toLocaleDateString();
}

export function plural(count, word) {
    return `${count} ${word}${count === 1 ? '' : 's'}`;
}

/**
 * Keyed list rendering: reuses existing child elements whose markup is unchanged,
 * so thumbnails do not reload and scroll position stays put on every re-render.
 */
export function reconcile(container, items, keyOf, render) {
    const existing = new Map();
    for (const child of Array.from(container.children)) {
        if (child.dataset.key) existing.set(child.dataset.key, child);
        else child.remove();
    }
    let cursor = container.firstElementChild;
    for (const item of items) {
        const key = String(keyOf(item));
        const html = render(item);
        let node = existing.get(key);
        if (node && node._html === html) {
            existing.delete(key);
        } else {
            const tpl = document.createElement('template');
            tpl.innerHTML = html.trim();
            const fresh = tpl.content.firstElementChild;
            fresh.dataset.key = key;
            fresh._html = html;
            if (node) {
                node.replaceWith(fresh);
                existing.delete(key);
                if (cursor === node) cursor = fresh;
            }
            node = fresh;
        }
        if (node !== cursor) container.insertBefore(node, cursor);
        else cursor = cursor.nextElementSibling;
    }
    for (const stale of existing.values()) stale.remove();
}
