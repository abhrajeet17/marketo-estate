import { api } from '../core/api.js';
import { accessOf, findPanorama, state, update } from '../core/store.js';
import { toast } from '../ui/toast.js';

const MODE_BY_ACCESS = { owner: 'admin', client: 'client' };

/** Open a panorama in the editor matching the user's access (owner → admin, client → client, else customer view). */
export async function openPanorama(id) {
    if (state.openingId) return;
    const panorama = findPanorama(id);
    if (!panorama) return;
    const mode = MODE_BY_ACCESS[accessOf(panorama)] || 'customer';
    const path = `/${mode}/${panorama.is_360 ? '3d/' : ''}${encodeURIComponent(id)}`;
    if (mode === 'customer') {
        window.location.href = path;
        return;
    }
    update({ openingId: id });
    try {
        const { token } = await api.pageToken(id, mode);
        if (!token) throw new Error('Access denied');
        window.location.href = `${path}?pt=${encodeURIComponent(token)}`;
    } catch (err) {
        update({ openingId: null });
        toast(err.message || 'Could not open this panorama', 'error');
    }
}

// Leaving via the back button restores this page from the bfcache; clear the spinner.
window.addEventListener('pageshow', (e) => {
    if (e.persisted && state.openingId) update({ openingId: null });
});
