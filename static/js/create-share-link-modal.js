(function (root) {
    'use strict';

    function defaultGetAuthHeaders() {
        if (root.pmApi && typeof root.pmApi.getAuthHeaders === 'function') {
            return root.pmApi.getAuthHeaders({
                waitAttempts: 24,
                waitDelayMs: 180
            });
        }
        if (root.__ACCESS_TOKEN__) {
            return Promise.resolve({ Authorization: 'Bearer ' + root.__ACCESS_TOKEN__ });
        }
        return Promise.resolve({});
    }

    var config = {
        getAuthHeaders: defaultGetAuthHeaders,
        showToast: function () {},
        pathPrefix: '/fullview/',
        pickEffectiveUrl: function (share) {
            var payload = share || {};
            return payload.full_view_effective_url || payload.full_view_default_url || payload.effective_url || payload.default_url || '';
        },
        onSaved: null,
    };

    var targetWorkspaceId = null;
    var currentShare = null;
    var initialized = false;

    function $(id) {
        return document.getElementById(id);
    }

    function showError(message) {
        var el = $('create-share-link-error');
        if (!el) return;
        el.textContent = message || '';
        el.style.display = message ? 'block' : 'none';
    }

    function showStatus(message, tone) {
        var el = $('create-share-link-status');
        if (!el) return;
        el.textContent = message || '';
        el.classList.remove('ok', 'warn');
        if (tone) el.classList.add(tone);
        el.style.display = message ? 'block' : 'none';
    }

    function setShareUrl(url) {
        var input = $('create-share-link-url');
        if (!input) return;
        input.value = String(url || '').trim();
        input.placeholder = url ? '' : 'Save a suffix to generate your link';
    }

    function absoluteUrl(url) {
        var value = String(url || '').trim();
        if (!value) return '';
        if (/^https?:\/\//i.test(value)) return value;
        return String(root.location.origin || '').replace(/\/$/, '') + (value.charAt(0) === '/' ? value : '/' + value);
    }

    function buildCustomUrl(endpoint) {
        var suffix = String(endpoint || '').trim();
        if (!suffix) return '';
        var prefix = String(config.pathPrefix || '/fullview/');
        if (prefix.charAt(0) !== '/') prefix = '/' + prefix;
        if (prefix.charAt(prefix.length - 1) !== '/') prefix += '/';
        return absoluteUrl(prefix + suffix);
    }

    async function copyTextValue(text) {
        var value = String(text || '');
        if (!value) return false;
        try {
            if (navigator.clipboard && navigator.clipboard.writeText) {
                await navigator.clipboard.writeText(value);
                return true;
            }
        } catch (e) {}
        try {
            var tmp = document.createElement('textarea');
            tmp.value = value;
            tmp.setAttribute('readonly', '');
            tmp.style.position = 'absolute';
            tmp.style.left = '-9999px';
            document.body.appendChild(tmp);
            tmp.select();
            var ok = document.execCommand('copy');
            document.body.removeChild(tmp);
            return !!ok;
        } catch (e2) {
            return false;
        }
    }

    async function fetchJsonWithAuth(url, opts, retryOpts) {
        if (root.pmApi && typeof root.pmApi.fetchJsonWithRetry === 'function') {
            return root.pmApi.fetchJsonWithRetry(url, opts || {}, Object.assign({
                retries: 2,
                baseDelayMs: 220,
                waitAttempts: 24,
                waitDelayMs: 180
            }, retryOpts || {}));
        }
        var headers = await config.getAuthHeaders();
        if (opts && opts.headers) {
            headers = Object.assign({}, headers, opts.headers);
        }
        var response = await fetch(url, Object.assign({ credentials: 'same-origin' }, opts || {}, { headers: headers }));
        var data = await response.json().catch(function () { return {}; });
        if (!response.ok) {
            throw new Error((data && data.error) || 'Request failed');
        }
        return data;
    }

    async function loadShare(workspaceId) {
        var url = '/api/workspaces/' + encodeURIComponent(workspaceId) + '/share-endpoint';
        var data = await fetchJsonWithAuth(url, { method: 'GET' });
        return data && data.share ? data.share : null;
    }

    async function checkEndpointAvailability(endpoint, workspaceId) {
        return fetchJsonWithAuth('/api/workspaces/share-endpoint/check', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                endpoint: endpoint,
                workspace_id: workspaceId,
            }),
        });
    }

    async function saveEndpoint(workspaceId, endpoint) {
        var data = await fetchJsonWithAuth('/api/workspaces/' + encodeURIComponent(workspaceId) + '/share-endpoint', {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ endpoint: endpoint }),
        });
        return data && data.share ? data.share : null;
    }

    function syncFormFromShare(share) {
        var suffixInput = $('create-share-link-suffix');
        if (suffixInput) suffixInput.value = share && share.custom_endpoint ? String(share.custom_endpoint) : '';
        setShareUrl(config.pickEffectiveUrl(share));
    }

    function closeCreateShareLinkModal() {
        var modal = $('create-share-link-modal');
        if (!modal) return;
        modal.classList.remove('visible');
        targetWorkspaceId = null;
        currentShare = null;
        showError('');
        showStatus('');
        setShareUrl('');
        var suffixInput = $('create-share-link-suffix');
        if (suffixInput) suffixInput.value = '';
    }

    async function showCreateShareLinkModal(workspaceId) {
        var wsId = String(workspaceId || '').trim();
        if (!wsId) {
            config.showToast('Select a project first', 'warn');
            return;
        }
        var modal = $('create-share-link-modal');
        if (!modal) return;

        bindEvents();
        targetWorkspaceId = wsId;
        showError('');
        showStatus('Loading current link…');
        setShareUrl('');
        modal.classList.add('visible');

        try {
            currentShare = await loadShare(wsId);
            syncFormFromShare(currentShare);
            showStatus('');
            var suffixInput = $('create-share-link-suffix');
            if (suffixInput) suffixInput.focus();
        } catch (error) {
            showStatus('');
            showError(error.message || 'Failed to load share settings');
        }
    }

    function updatePrefixLabel() {
        var prefixEl = $('create-share-link-prefix');
        if (!prefixEl) return;
        var origin = String(root.location.origin || '').replace(/\/$/, '');
        var prefix = String(config.pathPrefix || '/fullview/');
        if (prefix.charAt(0) !== '/') prefix = '/' + prefix;
        prefixEl.textContent = origin + prefix;
    }

    function bindEvents() {
        if (initialized) return;
        initialized = true;

        var modal = $('create-share-link-modal');
        var panel = $('create-share-link-panel') || (modal ? modal.querySelector('.crm-modal') : null);
        var cancelBtn = $('create-share-link-cancel');
        var closeBtn = $('create-share-link-close');
        var checkBtn = $('create-share-link-check');
        var saveBtn = $('create-share-link-save');
        var copyBtn = $('create-share-link-copy');
        var suffixInput = $('create-share-link-suffix');

        updatePrefixLabel();

        function onCloseClick(event) {
            if (event) {
                event.preventDefault();
                event.stopPropagation();
            }
            closeCreateShareLinkModal();
        }

        if (cancelBtn) cancelBtn.addEventListener('click', onCloseClick);
        if (closeBtn) closeBtn.addEventListener('click', onCloseClick);
        if (modal) {
            modal.addEventListener('click', function (e) {
                if (e.target === modal) closeCreateShareLinkModal();
            });
        }
        if (panel) {
            panel.addEventListener('click', function (e) {
                e.stopPropagation();
            });
        }

        if (suffixInput) {
            suffixInput.addEventListener('input', function () {
                showStatus('');
                showError('');
                var next = String(suffixInput.value || '').trim();
                setShareUrl(next ? buildCustomUrl(next) : config.pickEffectiveUrl(currentShare));
            });
        }

        if (checkBtn) {
            checkBtn.addEventListener('click', async function (event) {
                event.preventDefault();
                event.stopPropagation();
                if (!targetWorkspaceId) return;
                var endpoint = suffixInput ? String(suffixInput.value || '').trim() : '';
                showError('');
                if (!endpoint) {
                    showStatus('Enter a suffix to check availability.', 'warn');
                    return;
                }
                checkBtn.disabled = true;
                showStatus('Checking availability…');
                try {
                    var result = await checkEndpointAvailability(endpoint, targetWorkspaceId);
                    if (result.available) {
                        showStatus('Suffix is available.', 'ok');
                        if (result.normalized_endpoint && suffixInput) {
                            suffixInput.value = result.normalized_endpoint;
                        }
                        setShareUrl(buildCustomUrl(result.normalized_endpoint || endpoint));
                    } else {
                        showStatus((result.error || 'Suffix is not available.'), 'warn');
                    }
                } catch (error) {
                    showStatus('');
                    showError(error.message || 'Availability check failed');
                } finally {
                    checkBtn.disabled = false;
                }
            });
        }

        if (saveBtn) {
            saveBtn.addEventListener('click', async function (event) {
                event.preventDefault();
                event.stopPropagation();
                if (!targetWorkspaceId) return;
                var endpoint = suffixInput ? String(suffixInput.value || '').trim() : '';
                showError('');
                saveBtn.disabled = true;
                try {
                    currentShare = await saveEndpoint(targetWorkspaceId, endpoint);
                    syncFormFromShare(currentShare);
                    showStatus(endpoint ? 'Custom link saved.' : 'Custom suffix removed. Default link is active.', 'ok');
                    config.showToast('Share link updated', 'success');
                    if (typeof config.onSaved === 'function') {
                        config.onSaved(currentShare);
                    }
                } catch (error) {
                    showError(error.message || 'Failed to save link');
                } finally {
                    saveBtn.disabled = false;
                }
            });
        }

        if (copyBtn) {
            copyBtn.addEventListener('click', async function (event) {
                event.preventDefault();
                event.stopPropagation();
                var input = $('create-share-link-url');
                var ok = await copyTextValue(input ? input.value : '');
                config.showToast(ok ? 'Link copied' : 'Failed to copy link', ok ? 'success' : 'error');
            });
        }
    }

    function initCreateShareLinkModal(userConfig) {
        config = Object.assign({}, config, userConfig || {});
        if (typeof config.getAuthHeaders !== 'function') {
            config.getAuthHeaders = defaultGetAuthHeaders;
        }
        bindEvents();
        updatePrefixLabel();
    }

    function scheduleBind() {
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', bindEvents);
        } else {
            bindEvents();
        }
    }

    scheduleBind();

    root.initCreateShareLinkModal = initCreateShareLinkModal;
    root.showCreateShareLinkModal = showCreateShareLinkModal;
    root.closeCreateShareLinkModal = closeCreateShareLinkModal;
}(window));