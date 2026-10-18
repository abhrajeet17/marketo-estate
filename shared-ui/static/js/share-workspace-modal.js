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
        getSessionUserId: null,
        pickShareBaseUrl: function (share) {
            var payload = share || {};
            return payload.effective_url || payload.default_url || '';
        },
    };

    function extractSessionUserId(session) {
        return session && session.user && session.user.id ? String(session.user.id) : '';
    }

    async function defaultGetSessionUserId() {
        if (root.pmApi && typeof root.pmApi.waitForSession === 'function') {
            try {
                var pmSession = await root.pmApi.waitForSession(20, 180);
                var pmUserId = extractSessionUserId(pmSession);
                if (pmUserId) return pmUserId;
            } catch (e) {}
        }
        var sb = root._supabase;
        if (sb && sb.auth && typeof sb.auth.getSession === 'function') {
            try {
                var result = await sb.auth.getSession();
                var sbSession = result && result.data ? result.data.session : null;
                var sbUserId = extractSessionUserId(sbSession);
                if (sbUserId) return sbUserId;
            } catch (e2) {}
        }
        return '';
    }

    async function resolveSessionUserId() {
        if (typeof config.getSessionUserId === 'function') {
            try {
                var customUserId = await config.getSessionUserId();
                if (customUserId) return String(customUserId);
            } catch (e3) {}
        }
        return defaultGetSessionUserId();
    }

    var shareTargetId = null;
    var initialized = false;

    function $(id) {
        return document.getElementById(id);
    }

    function showShareError(message) {
        var el = $('workspace-share-error');
        if (!el) return;
        el.textContent = message || '';
        el.style.display = message ? 'block' : 'none';
    }

    function setReferralLink(url) {
        var input = $('workspace-referral-share-link');
        if (!input) return;
        input.value = String(url || '').trim();
        input.placeholder = url ? '' : 'Loading link…';
    }

    function buildShareUrlWithReference(baseUrl, referenceUserId) {
        var urlValue = String(baseUrl || '').trim();
        var refValue = String(referenceUserId || '').trim();
        if (!urlValue || !refValue) return '';
        try {
            var nextUrl = new URL(urlValue, root.location.origin);
            nextUrl.searchParams.set('ref_user_id', refValue);
            return nextUrl.toString();
        } catch (e) {
            var joiner = urlValue.indexOf('?') >= 0 ? '&' : '?';
            return urlValue + joiner + 'ref_user_id=' + encodeURIComponent(refValue);
        }
    }

    function closeShareWorkspaceModal() {
        var modal = $('share-workspace-modal');
        if (!modal) return;
        modal.classList.remove('visible');
        shareTargetId = null;
        setReferralLink('');
        showShareError('');
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

    async function loadReferralShareLink(workspaceId) {
        var sessionUserId = await resolveSessionUserId();
        if (!sessionUserId) {
            throw new Error('Could not determine your user session');
        }
        var url = '/api/workspaces/' + encodeURIComponent(workspaceId) + '/share-endpoint';
        var data = null;
        if (root.pmApi && typeof root.pmApi.fetchJsonWithRetry === 'function') {
            data = await root.pmApi.fetchJsonWithRetry(url, {}, {
                retries: 2,
                baseDelayMs: 220,
                waitAttempts: 24,
                waitDelayMs: 180
            });
        } else {
            var headers = await config.getAuthHeaders();
            var response = await fetch(url, { headers: headers, credentials: 'same-origin' });
            data = await response.json().catch(function () { return {}; });
            if (!response.ok) {
                throw new Error((data && data.error) || 'Failed to load share link');
            }
        }
        var share = data && data.share ? data.share : null;
        var baseUrl = share ? String(config.pickShareBaseUrl(share) || '').trim() : '';
        if (!baseUrl) {
            throw new Error('Share link is not available for this project');
        }
        return buildShareUrlWithReference(baseUrl, sessionUserId);
    }

    async function showShareWorkspaceModal(workspaceId) {
        var wsId = String(workspaceId || '').trim();
        if (!wsId) {
            config.showToast('This project is not available for sharing', 'error');
            return;
        }
        var modal = $('share-workspace-modal');
        if (!modal) return;

        shareTargetId = wsId;
        showShareError('');
        setReferralLink('');
        modal.classList.add('visible');

        try {
            var referralUrl = await loadReferralShareLink(wsId);
            setReferralLink(referralUrl);
            var input = $('workspace-referral-share-link');
            if (input) input.focus();
        } catch (error) {
            showShareError(error.message || 'Failed to load share link');
        }
    }

    function bindEvents() {
        if (initialized) return;
        initialized = true;

        var modal = $('share-workspace-modal');
        var cancelBtn = $('cancel-share-workspace');
        var closeBtn = $('share-reference-close');
        var copyBtn = $('copy-referral-share-link');

        if (cancelBtn) cancelBtn.addEventListener('click', closeShareWorkspaceModal);
        if (closeBtn) closeBtn.addEventListener('click', closeShareWorkspaceModal);
        if (modal) {
            modal.addEventListener('click', function (e) {
                if (e.target === modal) closeShareWorkspaceModal();
            });
        }

        if (copyBtn) {
            copyBtn.addEventListener('click', async function () {
                var input = $('workspace-referral-share-link');
                var ok = await copyTextValue(input ? input.value : '');
                config.showToast(ok ? 'Reference link copied' : 'Failed to copy link', ok ? 'success' : 'error');
            });
        }
    }

    function initShareWorkspaceModal(userConfig) {
        config = Object.assign({}, config, userConfig || {});
        bindEvents();
    }

    root.initShareWorkspaceModal = initShareWorkspaceModal;
    root.showShareWorkspaceModal = showShareWorkspaceModal;
    root.closeShareWorkspaceModal = closeShareWorkspaceModal;
    root.showProjectShareModal = showShareWorkspaceModal;
    root.closeProjectShareModal = closeShareWorkspaceModal;
}(window));