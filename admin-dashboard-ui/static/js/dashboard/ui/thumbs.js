/**
 * Thumbnail loading for every <img data-thumb> on the page.
 *
 * 1. src is the direct signed storage URL from /api/dashboard (one request, no redirect hop).
 * 2. On error it retries once via data-fallback (/uploads/<file>?size=thumb), which also
 *    generates a missing thumbnail on the server.
 * 3. If that fails too the image is hidden and the placeholder icon underneath stays visible,
 *    so a missing or expired image never breaks the card layout.
 *
 * load/error do not bubble, so one capturing listener covers images rendered at any time.
 */
import { esc } from '../core/dom.js';

const fallbackUrl = (filename) => `/uploads/${encodeURIComponent(filename || '')}?size=thumb`;

export function thumbSrc(panorama) {
    return panorama.thumb_url || fallbackUrl(panorama.filename);
}

/** <img> markup with the fallback wired in. `eager` marks above-the-fold images. */
export function thumbImg(panorama, { eager = false, className = '' } = {}) {
    const fallback = fallbackUrl(panorama.filename);
    const src = thumbSrc(panorama);
    const attrs = eager ? 'loading="eager" fetchpriority="high"' : 'loading="lazy"';
    return `<img class="${esc(className)}" data-thumb src="${esc(src)}"${src !== fallback ? ` data-fallback="${esc(fallback)}"` : ''}
        alt="" width="400" height="225" decoding="async" ${attrs}>`;
}

document.addEventListener('load', (e) => {
    const img = e.target;
    if (img.tagName === 'IMG' && img.hasAttribute('data-thumb')) img.classList.add('is-loaded');
}, true);

document.addEventListener('error', (e) => {
    const img = e.target;
    if (img.tagName !== 'IMG' || !img.hasAttribute('data-thumb')) return;
    const fallback = img.getAttribute('data-fallback');
    if (fallback) {
        img.removeAttribute('data-fallback');
        img.src = fallback;
        return;
    }
    img.classList.add('is-broken');
}, true);
