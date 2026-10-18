/**
 * Dashboard API client. Auth headers and GET retries come from window.pmApi (sidebar.js).
 * Every call resolves with parsed JSON or rejects with an Error carrying `status`.
 */

async function request(path, { method = 'GET', json, body, retries } = {}) {
    const options = { method };
    if (json !== undefined) {
        options.headers = { 'Content-Type': 'application/json' };
        options.body = JSON.stringify(json);
    } else if (body !== undefined) {
        options.body = body;
    }
    const retryOpts = { retries: retries ?? (method === 'GET' ? 2 : 0), baseDelayMs: 220 };
    return window.pmApi.fetchJsonWithRetry(path, options, retryOpts);
}

const enc = encodeURIComponent;

export const api = {
    authHeaders: () => window.pmApi.getAuthHeaders({}),

    dashboard: () => request('/api/dashboard'),
    project: (id) => request(`/api/workspaces/${enc(id)}`),
    createProject: (payload) => request('/api/workspaces', { method: 'POST', json: payload }),
    updateProject: (id, payload) => request(`/api/workspaces/${enc(id)}`, { method: 'PATCH', json: payload }),
    deleteProject: (id) => request(`/api/workspaces/${enc(id)}`, { method: 'DELETE' }),
    shareEndpoint: (id) => request(`/api/workspaces/${enc(id)}/share-endpoint`),
    projectOrganizations: (id) => request(`/api/workspaces/${enc(id)}/organizations`),
    grantProjectOrganization: (id, orgId, accessType) => request(`/api/workspaces/${enc(id)}/organizations/${enc(orgId)}`, {
        method: 'PUT',
        json: { access_type: accessType },
    }),
    revokeProjectOrganization: (id, orgId) => request(`/api/workspaces/${enc(id)}/organizations/${enc(orgId)}`, { method: 'DELETE' }),

    renamePanorama: (id, name) => request(`/api/panoramas/${enc(id)}`, { method: 'PUT', json: { name } }),
    deletePanorama: (id, newMainId) => request(`/api/panoramas/${enc(id)}`, {
        method: 'DELETE',
        json: newMainId ? { new_main_panorama_id: newMainId } : undefined,
    }),
    movePanorama: (id, projectId) => request(`/api/panoramas/${enc(id)}/workspace`, {
        method: 'PATCH',
        json: { workspace_id: projectId || null },
    }),
    pageToken: (id, mode) => request(`/api/panoramas/${enc(id)}/page-token`, { method: 'POST', json: { mode } }),

    uploadUrl: (payload) => request('/api/panoramas/upload-url', { method: 'POST', json: payload }),
    createPanorama: (formData) => request('/api/panoramas', { method: 'POST', body: formData }),
    resolveMapsLink: (link) => request('/api/resolve-maps-link', { method: 'POST', json: { link } }),
};
