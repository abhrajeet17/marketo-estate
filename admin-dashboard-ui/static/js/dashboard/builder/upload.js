/**
 * Panorama upload dialog. One list-based flow for one or many files:
 * presigned direct upload to storage, server-side upload as the fallback when storage is not configured.
 */
import { api } from '../core/api.js';
import { esc, formatBytes, icon, plural } from '../core/dom.js';
import { UNLINKED, accessOf, findPanorama, projectKey, select, selectedProject, state } from '../core/store.js';
import { refresh } from '../core/sync.js';
import { openPanorama } from '../features/open.js';
import { openModal } from '../ui/modal.js';
import { toast } from '../ui/toast.js';

const MAX_BYTES = 50 * 1024 * 1024;
const ACCEPTED_TYPES = ['image/jpeg', 'image/png', 'image/webp'];
const CONCURRENCY = 2;
const STATUS_TEXT = { queued: 'Waiting…', uploading: 'Uploading', finalizing: 'Finishing…', done: 'Uploaded' };

let files = [];
let nextId = 1;
let uploading = false;
let dialog = null;

const el = () => document.getElementById('dash-upload-modal');
const listEl = () => el().querySelector('[data-file-list]');

// ── Transport ─────────────────────────────────────────────────────────────
function xhr(method, url, body, { headers = {}, onProgress, timeout }) {
    return new Promise((resolve, reject) => {
        const req = new XMLHttpRequest();
        req.open(method, url);
        req.timeout = timeout;
        Object.entries(headers).forEach(([k, v]) => req.setRequestHeader(k, v));
        req.upload.addEventListener('progress', (e) => { if (e.lengthComputable) onProgress(e.loaded / e.total); });
        req.addEventListener('load', () => {
            let data = null;
            try { data = JSON.parse(req.responseText || 'null'); } catch (e) { data = null; }
            if (req.status >= 200 && req.status < 300) resolve(data);
            else reject(new Error((data && data.error) || `Upload failed (${req.status})`));
        });
        req.addEventListener('error', () => reject(new Error('Network error — check your connection.')));
        req.addEventListener('timeout', () => reject(new Error('Upload timed out.')));
        req.send(body);
    });
}

function panoramaFields(item, projectId) {
    const form = new FormData();
    form.append('name', item.name.trim() || 'Untitled');
    form.append('is_360', String(item.is360));
    form.append('width', String(item.width || 0));
    form.append('height', String(item.height || 0));
    if (projectId) form.append('workspace_id', projectId);
    return form;
}

async function uploadOne(item, projectId, onProgress) {
    const { file } = item;
    let target = null;
    try {
        target = await api.uploadUrl({ original_filename: file.name, content_type: file.type, size_bytes: file.size, name: item.name });
    } catch (err) {
        if (err.status !== 503) throw err; // 503: direct storage upload not configured → server upload
    }

    if (target && target.upload_url) {
        if (target.max_bytes && file.size > target.max_bytes) {
            throw new Error(`File is larger than ${Math.floor(target.max_bytes / 1048576)} MB.`);
        }
        await xhr('PUT', target.upload_url, file, {
            headers: target.content_type ? { 'Content-Type': target.content_type } : {},
            onProgress: (f) => onProgress(f * 0.95),
            timeout: 10 * 60 * 1000,
        });
        onProgress(0.97, 'finalizing');
        const form = panoramaFields(item, projectId);
        form.append('filename', target.filename);
        form.append('upload_token', target.upload_token);
        form.append('original_filename', file.name);
        return api.createPanorama(form);
    }

    const form = panoramaFields(item, projectId);
    form.append('file', file);
    const headers = await api.authHeaders();
    return xhr('POST', '/api/panoramas', form, {
        headers: headers.Authorization ? { Authorization: headers.Authorization } : {},
        onProgress,
        timeout: 4 * 60 * 1000,
    });
}

// ── File list ─────────────────────────────────────────────────────────────
function readDimensions(item) {
    const img = new Image();
    img.onload = () => {
        item.width = img.naturalWidth;
        item.height = img.naturalHeight;
        const ratio = item.width / item.height;
        if (!item.touched360 && ratio > 1.9 && ratio < 2.1) item.is360 = true;
        // Patch the row in place so a name being typed keeps focus.
        const row = dialog && listEl().querySelector(`[data-file="${item.id}"]`);
        if (!row) return;
        row.querySelector('.dash-file__meta').textContent = fileMeta(item);
        row.querySelector('[data-360]').checked = item.is360;
        renderSummary();
    };
    img.src = item.url;
}

function addFiles(fileList) {
    const rejected = [];
    for (const file of fileList) {
        if (!ACCEPTED_TYPES.includes(file.type)) rejected.push(`${file.name}: not a JPG, PNG or WebP image`);
        else if (file.size > MAX_BYTES) rejected.push(`${file.name}: larger than 50 MB`);
        else {
            const item = {
                id: nextId++, file, url: URL.createObjectURL(file), status: 'ready', progress: 0, error: '',
                name: file.name.replace(/\.[^.]+$/, '').replace(/[-_]+/g, ' ').trim(),
                is360: false, touched360: false, width: 0, height: 0,
            };
            files.push(item);
            readDimensions(item);
        }
    }
    if (rejected.length) toast(rejected.join(' · '), 'error');
    renderList();
}

function removeFile(id) {
    const item = files.find((f) => f.id === id);
    if (item) URL.revokeObjectURL(item.url);
    files = files.filter((f) => f.id !== id);
    renderList();
}

function clearFiles() {
    files.forEach((f) => URL.revokeObjectURL(f.url));
    files = [];
}

function fileMeta(item) {
    const dims = item.width ? ` · ${item.width} × ${item.height}` : '';
    return `${item.file.name} · ${formatBytes(item.file.size)}${dims}`;
}

function rowHtml(item) {
    const locked = uploading || item.status === 'done';
    let status = '';
    if (item.status === 'error') status = `<p class="dash-file__error">${icon('alert', 13)}${esc(item.error)}</p>`;
    else if (item.status !== 'ready') {
        status = `<div class="dash-file__progress" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${Math.round(item.progress * 100)}">
            <span style="width:${Math.round(item.progress * 100)}%"></span></div>
            <p class="dash-file__status">${item.status === 'done' ? icon('check', 13) : ''}<span data-status-text>${esc(STATUS_TEXT[item.status] || '')}</span></p>`;
    }
    return `<li class="dash-file" data-file="${item.id}" data-status="${item.status}">
        <img class="dash-file__thumb" src="${esc(item.url)}" alt="">
        <div class="dash-file__main">
            <input class="dash-input dash-input--sm" data-name value="${esc(item.name)}" aria-label="Panorama name" maxlength="120"${locked ? ' disabled' : ''}>
            <p class="dash-file__meta">${esc(fileMeta(item))}</p>
            ${status}
        </div>
        <label class="dash-check dash-check--sm"><input type="checkbox" data-360${item.is360 ? ' checked' : ''}${locked ? ' disabled' : ''}><span>360°</span></label>
        <button type="button" class="dash-icon-btn" data-remove aria-label="Remove ${esc(item.file.name)}"${locked ? ' hidden' : ''}>${icon('x', 16)}</button>
    </li>`;
}

function renderList() {
    if (!dialog) return;
    listEl().innerHTML = files.map(rowHtml).join('');
    renderSummary();
}

function renderSummary() {
    if (!dialog) return;
    const root = el();
    root.querySelector('[data-upload-options]').hidden = !files.length;
    root.querySelector('[data-dropzone]').classList.toggle('is-compact', files.length > 0);
    root.querySelector('[data-dropzone]').hidden = uploading;
    const pending = files.filter((f) => f.status !== 'done');
    const all360 = root.querySelector('[data-all-360]');
    all360.checked = pending.length > 0 && pending.every((f) => f.is360);
    all360.disabled = uploading;
    root.querySelector('[data-project-select]').disabled = uploading;
    const failed = pending.filter((f) => f.status === 'error').length;
    dialog.setSubmitLabel(failed && failed === pending.length ? `Retry ${plural(failed, 'upload')}` : `Upload ${pending.length || ''}`.trim());
    if (!uploading) dialog.submit.disabled = !pending.length;
    root.querySelector('[data-upload-summary]').textContent = files.length ? plural(files.length, 'file') : '';
}

function paintProgress(item) {
    const row = listEl().querySelector(`[data-file="${item.id}"]`);
    if (!row) return;
    const bar = row.querySelector('.dash-file__progress span');
    if (bar) bar.style.width = `${Math.round(item.progress * 100)}%`;
    const text = row.querySelector('[data-status-text]');
    if (text) text.textContent = item.status === 'uploading' ? `Uploading ${Math.round(item.progress * 100)}%` : (STATUS_TEXT[item.status] || '');
}

// ── Run ───────────────────────────────────────────────────────────────────
function warnBeforeLeaving(e) {
    e.preventDefault();
    e.returnValue = '';
}

async function runUploads(form) {
    const projectId = form.querySelector('[data-project-select]').value || null;
    const queue = files.filter((f) => f.status !== 'done');
    if (!queue.length) return false;
    if (queue.some((f) => !f.name.trim())) throw new Error('Every panorama needs a name.');

    uploading = true;
    window.addEventListener('beforeunload', warnBeforeLeaving);
    queue.forEach((f) => Object.assign(f, { status: 'queued', progress: 0, error: '' }));
    renderList();

    const created = [];
    const worker = async () => {
        for (let item = queue.shift(); item; item = queue.shift()) {
            item.status = 'uploading';
            renderList();
            try {
                const panorama = await uploadOne(item, projectId, (fraction, phase) => {
                    item.progress = fraction;
                    if (phase) item.status = phase;
                    paintProgress(item);
                });
                Object.assign(item, { status: 'done', progress: 1 });
                created.push(panorama);
            } catch (err) {
                Object.assign(item, { status: 'error', error: err.message || 'Upload failed' });
            }
            renderList();
        }
    };
    try {
        await Promise.all(Array.from({ length: CONCURRENCY }, worker));
    } finally {
        uploading = false;
        window.removeEventListener('beforeunload', warnBeforeLeaving);
    }

    const failed = files.filter((f) => f.status === 'error').length;
    if (created.length) {
        toast(`${plural(created.length, 'panorama')} uploaded`);
        await refresh().catch(() => {});
        select(projectId ? projectKey(projectId) : UNLINKED);
    }
    if (failed) {
        files.filter((f) => f.status === 'done').forEach((f) => removeFile(f.id));
        renderList();
        throw new Error(`${plural(failed, 'upload')} failed. Fix the issue and retry, or remove ${failed === 1 ? 'it' : 'them'}.`);
    }
    const only = created.length === 1 && files.length === 1 ? created[0] : null;
    clearFiles();
    if (only && findPanorama(only.id)) openPanorama(only.id);
    return true;
}

// ── Dialog wiring ─────────────────────────────────────────────────────────
function bindOnce(root) {
    if (root.dataset.bound) return;
    root.dataset.bound = '1';
    const input = root.querySelector('[data-file-input]');
    const zone = root.querySelector('[data-dropzone]');
    input.addEventListener('change', () => {
        addFiles(Array.from(input.files || []));
        input.value = '';
    });
    ['dragenter', 'dragover'].forEach((type) => zone.addEventListener(type, (e) => {
        e.preventDefault();
        zone.classList.add('is-dragover');
    }));
    ['dragleave', 'drop'].forEach((type) => zone.addEventListener(type, () => zone.classList.remove('is-dragover')));
    zone.addEventListener('drop', (e) => {
        e.preventDefault();
        if (!uploading) addFiles(Array.from(e.dataTransfer.files || []));
    });
    listEl().addEventListener('input', (e) => {
        const row = e.target.closest('[data-file]');
        const item = row && files.find((f) => f.id === Number(row.dataset.file));
        if (item && e.target.matches('[data-name]')) item.name = e.target.value;
    });
    listEl().addEventListener('change', (e) => {
        const row = e.target.closest('[data-file]');
        const item = row && files.find((f) => f.id === Number(row.dataset.file));
        if (item && e.target.matches('[data-360]')) {
            item.is360 = e.target.checked;
            item.touched360 = true;
            renderSummary();
        }
    });
    listEl().addEventListener('click', (e) => {
        const btn = e.target.closest('[data-remove]');
        if (btn) removeFile(Number(btn.closest('[data-file]').dataset.file));
    });
    root.querySelector('[data-all-360]').addEventListener('change', (e) => {
        files.forEach((f) => { if (f.status !== 'done') Object.assign(f, { is360: e.target.checked, touched360: true }); });
        renderList();
    });
}

export function openUpload() {
    openModal('dash-upload-modal', {
        onOpen(d) {
            dialog = d;
            bindOnce(d.el);
            const selectEl = d.el.querySelector('[data-project-select]');
            const owned = state.projects.filter((p) => accessOf(p) === 'owner');
            selectEl.innerHTML = '<option value="">Unlinked (no project)</option>'
                + owned.map((p) => `<option value="${esc(p.id)}">${esc(p.name)}</option>`).join('');
            const current = selectedProject();
            selectEl.value = current && accessOf(current) === 'owner' ? current.id : '';
            renderList();
        },
        onSubmit: (form) => runUploads(form),
        onClose() {
            clearFiles();
            dialog = null;
        },
    });
}
