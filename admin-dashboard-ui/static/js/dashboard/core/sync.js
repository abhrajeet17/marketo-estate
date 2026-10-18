import { api } from './api.js';
import { setSnapshot, state, update } from './store.js';

let inflight = null;

/** The request started by the inline script in dashboard.html, used once; null when it failed. */
function takePrefetch() {
    const prefetch = window.__dashboardPrefetch;
    window.__dashboardPrefetch = null;
    return prefetch ? prefetch.then((data) => data || api.dashboard()) : api.dashboard();
}

/** Load (or silently refresh) panoramas + projects from /api/dashboard. Concurrent calls share one request. */
export function refresh() {
    if (inflight) return inflight;
    update({ refreshing: true });
    inflight = takePrefetch()
        .then((data) => setSnapshot({ panoramas: data.panoramas || [], projects: data.projects || [] }, true))
        .catch((err) => {
            // Keep showing cached data if we have it; otherwise surface the error with a retry.
            if (state.status !== 'ready') update({ status: 'error', error: err.message || '' });
            throw err;
        })
        .finally(() => {
            inflight = null;
            update({ refreshing: false });
        });
    return inflight;
}
