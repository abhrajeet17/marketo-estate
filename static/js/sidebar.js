/**
 * Common sidebar logic — toggle, role-based nav visibility, logout.
 * Include on every page that uses the sidebar component.
 *
 * Exposes window.sidebarReady (Promise) that resolves with { role, profile }
 * so page-specific scripts can await user data.
 */
(function () {
    'use strict';

    var CACHE_KEY = 'sidebar_cache_v2_client_admin';
    var AUTH_FALLBACK_KEY = 'marketostate_auth_session_v1';

    var url = window.__SUPABASE_URL__;
    var key = window.__SUPABASE_ANON_KEY__;
    if (!url || !key || !window.supabase) return;

    var sb = window.supabase.createClient(url, key);
    window._supabase = sb;

    function _pmCacheAuthSession(session) {
        if (!session || !session.access_token) return;
        try {
            window.localStorage.setItem(AUTH_FALLBACK_KEY, JSON.stringify({
                access_token: session.access_token,
                refresh_token: session.refresh_token || '',
                expires_at: session.expires_at || 0,
                user: session.user || null,
                ts: Date.now()
            }));
        } catch (e) { /* ignore */ }
    }

    function _pmClearCachedAuthSession() {
        try { window.localStorage.removeItem(AUTH_FALLBACK_KEY); } catch (e) { /* ignore */ }
    }

    function _pmReadCachedAuthSession() {
        try {
            var raw = window.localStorage.getItem(AUTH_FALLBACK_KEY);
            if (!raw) return null;
            var parsed = JSON.parse(raw);
            if (!parsed || !parsed.access_token) return null;
            var expiresAtMs = Number(parsed.expires_at || 0) * 1000;
            if (expiresAtMs && expiresAtMs < Date.now() + 30000) {
                _pmClearCachedAuthSession();
                return null;
            }
            return parsed;
        } catch (e) {
            return null;
        }
    }

    function _pmIsAbortError(err) {
        var name = String((err && err.name) || '').toLowerCase();
        var msg = String((err && err.message) || '').toLowerCase();
        return name === 'aborterror' || msg.indexOf('signal is aborted') >= 0 || msg.indexOf('aborted') >= 0;
    }

    function _pmSafeSignOut(after) {
        _pmClearCachedAuthSession();
        return sb.auth.signOut()
            .catch(function (err) {
                if (!_pmIsAbortError(err)) {
                    try { console.warn('sidebar signOut failed', err); } catch (_e) { /* ignore */ }
                }
            })
            .finally(function () {
                if (typeof after === 'function') after();
            });
    }

    function _pmSleep(ms) {
        return new Promise(function (resolve) { setTimeout(resolve, Number(ms) || 0); });
    }

    function _pmGetSessionOnce() {
        return sb.auth.getSession()
            .then(function (r) {
                var session = (r && r.data && r.data.session) ? r.data.session : null;
                if (session) {
                    _pmCacheAuthSession(session);
                    return session;
                }
                var cached = _pmReadCachedAuthSession();
                if (!cached) return null;
                if (cached.refresh_token && typeof sb.auth.setSession === 'function') {
                    return sb.auth.setSession({
                        access_token: cached.access_token,
                        refresh_token: cached.refresh_token
                    }).then(function (setResult) {
                        var hydrated = setResult && setResult.data && setResult.data.session;
                        if (hydrated) {
                            _pmCacheAuthSession(hydrated);
                            return hydrated;
                        }
                        return cached;
                    }).catch(function () { return cached; });
                }
                return cached;
            })
            .catch(function () { return _pmReadCachedAuthSession(); });
    }

    function _pmWaitForSession(maxAttempts, delayMs) {
        var attemptsLeft = Math.max(0, Number(maxAttempts) || 0);
        var waitMs = Math.max(40, Number(delayMs) || 120);
        function step() {
            return _pmGetSessionOnce().then(function (session) {
                if (session || attemptsLeft <= 0) return session;
                attemptsLeft -= 1;
                return _pmSleep(waitMs).then(step);
            });
        }
        return step();
    }

    function _pmWaitForSessionOrAuthEvent(maxAttempts, delayMs, eventTimeoutMs) {
        return _pmWaitForSession(maxAttempts, delayMs).then(function (session) {
            if (session && session.access_token) return session;
            return new Promise(function (resolve) {
                var finished = false;
                var sub = null;
                function done(nextSession) {
                    if (finished) return;
                    finished = true;
                    try {
                        if (sub && typeof sub.unsubscribe === 'function') sub.unsubscribe();
                    } catch (e) { /* ignore */ }
                    resolve((nextSession && nextSession.access_token) ? nextSession : null);
                }
                try {
                    var listener = sb.auth.onAuthStateChange(function (_event, currentSession) {
                        if (currentSession && currentSession.access_token) done(currentSession);
                    });
                    sub = (listener && listener.data && listener.data.subscription)
                        ? listener.data.subscription
                        : ((listener && listener.subscription) ? listener.subscription : null);
                } catch (e2) {
                    done(null);
                    return;
                }
                setTimeout(function () { done(null); }, Math.max(600, Number(eventTimeoutMs) || 3000));
            });
        });
    }

    function _pmShouldRetryStatus(status) {
        return status === 408 || status === 425 || status === 429 || status === 500 || status === 502 || status === 503 || status === 504;
    }

    function _pmRetryDelayMs(attempt, baseDelayMs) {
        var base = Math.max(80, Number(baseDelayMs) || 220);
        var jitter = Math.floor(Math.random() * 70);
        return Math.min(1400, (base * Math.pow(1.8, attempt)) + jitter);
    }

    function _pmAccessTokenFromFallbacks() {
        if (window.__ACCESS_TOKEN__) return String(window.__ACCESS_TOKEN__);
        var cached = _pmReadCachedAuthSession();
        return cached && cached.access_token ? String(cached.access_token) : '';
    }

    async function _pmBuildHeaders(existingHeaders, opts) {
        var headers = Object.assign({}, existingHeaders || {});
        var hasAuth = !!(headers.Authorization || headers.authorization);
        if (hasAuth) return headers;
        var session = await _pmWaitForSession(
            opts && opts.waitAttempts != null ? opts.waitAttempts : 14,
            opts && opts.waitDelayMs != null ? opts.waitDelayMs : 140
        );
        var token = session && session.access_token ? String(session.access_token) : _pmAccessTokenFromFallbacks();
        if (token) {
            headers.Authorization = 'Bearer ' + token;
        }
        return headers;
    }

    async function _pmFetchWithRetry(url, opts, retryOpts) {
        var options = opts || {};
        var ro = retryOpts || {};
        var retries = Math.max(0, Number(ro.retries) || 0);
        var retryAuth = ro.retryAuth !== false;
        var method = String(options.method || 'GET').toUpperCase();
        var allowRetry = method === 'GET' || method === 'HEAD' || method === 'OPTIONS' || ro.allowRetryOnWrite === true;
        var lastNetworkErr = null;
        for (var attempt = 0; attempt <= retries; attempt += 1) {
            var merged = Object.assign({}, options);
            merged.headers = await _pmBuildHeaders(options.headers, ro);
            try {
                var res = await fetch(url, merged);
                if (res.ok) return res;
                if (!allowRetry || attempt >= retries) return res;
                if (retryAuth && res.status === 401) {
                    try { await sb.auth.refreshSession(); } catch (e) { /* best effort */ }
                    await _pmSleep(_pmRetryDelayMs(attempt, ro.baseDelayMs));
                    continue;
                }
                if (_pmShouldRetryStatus(res.status)) {
                    await _pmSleep(_pmRetryDelayMs(attempt, ro.baseDelayMs));
                    continue;
                }
                return res;
            } catch (err) {
                lastNetworkErr = err;
                if (!allowRetry || attempt >= retries) break;
                await _pmSleep(_pmRetryDelayMs(attempt, ro.baseDelayMs));
            }
        }
        throw lastNetworkErr || new Error('Network request failed');
    }

    async function _pmFetchJsonWithRetry(url, opts, retryOpts) {
        var res = await _pmFetchWithRetry(url, opts, retryOpts);
        var text = '';
        try { text = await res.text(); } catch (e) { text = ''; }
        var data = null;
        try { data = text ? JSON.parse(text) : null; } catch (e2) { data = null; }
        if (!res.ok) {
            var msg = (data && data.error) ? data.error : (text || res.statusText || ('Request failed (' + res.status + ')'));
            var err = new Error(msg);
            err.status = res.status;
            err.payload = data;
            throw err;
        }
        return data;
    }

    // Shared API helpers for pages with list-heavy CRUD UI.
    window.pmApi = window.pmApi || {};
    window.pmApi.waitForSession = _pmWaitForSession;
    window.pmApi.getAuthHeaders = function (opts) {
        return _pmBuildHeaders((opts && opts.headers) || null, opts || {});
    };
    window.pmApi.fetchWithRetry = _pmFetchWithRetry;
    window.pmApi.fetchJsonWithRetry = _pmFetchJsonWithRetry;

    // ---- Active link highlight based on current URL ----
    var currentPath = window.location.pathname.replace(/\/+$/, '') || '/';

    function isDashboardPath() {
        return currentPath === '/dashboard' || currentPath.indexOf('/dashboard/') === 0;
    }

    function configureCrmNavOpenInNewTab() {
        if (!isDashboardPath()) return;
        var crmLink = document.getElementById('nav-crm');
        if (!crmLink) return;
        crmLink.setAttribute('target', '_blank');
        crmLink.setAttribute('rel', 'noopener noreferrer');
        if (crmLink._crmTabHandler) return;
        crmLink._crmTabHandler = true;
        crmLink.addEventListener('click', function (e) {
            e.preventDefault();
            window.open(crmLink.getAttribute('href') || '/crm', '_blank', 'noopener,noreferrer');
        });
    }
    window.configureCrmNavOpenInNewTab = configureCrmNavOpenInNewTab;
    document.querySelectorAll('.sidebar-link[data-page]').forEach(function (link) {
        if (link.getAttribute('data-coming-soon') === '1') {
            link.classList.remove('active');
            return;
        }
        var href = (link.getAttribute('href') || '').replace(/\/+$/, '') || '/';
        var isSalesToolsAlias = ((href === '/salestools' || href === '/floorplans') && currentPath === '/daynight');
        if (currentPath === href || currentPath.indexOf(href + '/') === 0 || isSalesToolsAlias) {
            link.classList.add('active');
        } else {
            link.classList.remove('active');
        }
    });

    document.querySelectorAll('.sidebar-link[data-coming-soon="1"]').forEach(function (link) {
        link.addEventListener('click', function (e) {
            e.preventDefault();
        });
    });

    // ---- Collapse / expand (collapsed by default) ----
    var toggle = document.getElementById('sidebar-toggle');
    var sidebar = document.getElementById('dashboard-sidebar');
    if (toggle && sidebar) {
        var isCustomerDashboard = currentPath === '/customer-dashboard' || currentPath.indexOf('/customer-dashboard/') === 0;
        if (isCustomerDashboard) {
            localStorage.setItem('dashboard-sidebar-collapsed', '1');
        }
        var expanded = localStorage.getItem('dashboard-sidebar-collapsed') === '0';
        if (!expanded) sidebar.classList.add('sidebar-collapsed');
        toggle.addEventListener('click', function () {
            sidebar.classList.toggle('sidebar-collapsed');
            localStorage.setItem(
                'dashboard-sidebar-collapsed',
                sidebar.classList.contains('sidebar-collapsed') ? '1' : '0'
            );
        });
    }

    // ---- Helper: apply cached sidebar state instantly ----
    function applySidebarState(state) {
        var dashboardLink = document.querySelector('.sidebar-link[data-page="dashboard"]');
        if (dashboardLink) {
            var dashboardText = dashboardLink.querySelector('.sidebar-text');
            var isClientOnly = !state.isAdmin && !!state.isClientMember;
            var isBroker = !!state.isBroker || state.role === 'broker';
            var label = isBroker ? 'Available Plots' : (isClientOnly ? 'Edit Plots' : 'Plotted Development');
            if (dashboardText) dashboardText.textContent = label;
            dashboardLink.setAttribute('data-tooltip', label);
            dashboardLink.style.display = isBroker ? 'none' : '';
        }

        // Avatar initials
        var avatarEl = document.getElementById('sidebar-avatar');
        if (avatarEl && state.avatarText) {
            avatarEl.textContent = state.avatarText;
        }
        // Org name
        var orgNameEl = document.getElementById('org-name');
        var displayOrgName = state.displayOrgName || state.orgName || 'MarketoState';
        if (orgNameEl) orgNameEl.textContent = displayOrgName;
        // User name
        var userNameEl = document.getElementById('sidebar-user-name');
        if (userNameEl) userNameEl.textContent = state.userName || '';
        // Role-based visibility
        show('nav-explore', state.isAdmin);
        show('nav-floorplans', state.isAdmin);
        show('nav-fullview', state.isAdmin);
        show('nav-user-mgmt', state.isAdmin);
        show('nav-orgs', state.role === 'superadmin');
        show('sidebar-upload-wrap', state.isAdmin);
        show('dropdown-client-mgmt', !state.isAdmin && !!state.isClientAdmin && !state.isBroker);
        show('nav-crm', state.showCrm);
        if (state.showCrm) configureCrmNavOpenInNewTab();

        // For admin users, ensure "home"/dashboard links point to normal /dashboard (not customer-dashboard)
        if (state.isAdmin) {
            var adminDashLinks = document.querySelectorAll(
                '#portal-menu-dashboard, #portal-dropdown-dashboard, ' +
                '#sneat-menu-dashboard, #sneat-dropdown-dashboard, ' +
                'a[href="/customer-dashboard"][id*="dashboard"], a[href="/customer-dashboard"].portal-nav-link, ' +
                'a[href="/customer-dashboard"].cd-topbar-title, a[href="/customer-dashboard"]'
            );
            adminDashLinks.forEach(function (link) {
                if (link && link.getAttribute('href') === '/customer-dashboard') {
                    link.setAttribute('href', '/dashboard');
                }
            });
        }
    }

    // ---- Restore cached sidebar immediately (no flash) ----
    var cached = null;
    try { cached = JSON.parse(sessionStorage.getItem(CACHE_KEY)); } catch (e) { /* ignore */ }
    if (cached) {
        applySidebarState(cached);
    } else if (isDashboardPath()) {
        configureCrmNavOpenInNewTab();
    }

    // ---- Auth + role-based nav ----
    var _resolve;
    window.sidebarReady = new Promise(function (resolve) { _resolve = resolve; });

    _pmWaitForSessionOrAuthEvent(30, 200, 3200).then(function (session) {
        if (!session) {
            sessionStorage.removeItem(CACHE_KEY);
            window.location.replace('/login');
            return;
        }
        var accessToken = session.access_token;
        window.__ACCESS_TOKEN__ = accessToken;

        _pmFetchWithRetry('/api/org/me', {}, {
            retries: 1,
            retryAuth: true,
            waitAttempts: 6,
            waitDelayMs: 120,
            baseDelayMs: 180
        })
            .then(function (res) {
                if (res.status === 401 || res.status === 403) {
                    sessionStorage.removeItem(CACHE_KEY);
                    _pmSafeSignOut(function () { window.location.replace('/login'); });
                    return null;
                }
                return res.ok ? res.json() : null;
            })
            .then(function (data) {
                if (!data) {
                    _resolve({ role: '', profile: null, org: null, accessToken: accessToken, isAdmin: false });
                    return;
                }
                var profile = data && data.profile ? data.profile : null;
                var role = profile && profile.role ? String(profile.role).toLowerCase() : '';
                var isAdmin = role === 'admin' || role === 'superadmin';

                // Build avatar text
                var avatarText = '';
                if (profile) {
                    var name = (profile.name || profile.email || '').trim();
                    if (name.length >= 2) {
                        avatarText = (
                            name[0] +
                            (name.indexOf(' ') >= 0
                                ? name[name.indexOf(' ') + 1]
                                : name[1] || '')
                        ).toUpperCase();
                    } else if (name.length === 1) {
                        avatarText = name[0].toUpperCase();
                    }
                }

                var orgName = data && data.org && data.org.name ? String(data.org.name) : '';
                var userName = profile ? (profile.name || profile.email || '') : '';

                // Resolve client membership for every profile role. A client admin can
                // also have a platform admin profile, and client-admin routing wins.
                _pmFetchWithRetry('/api/crm/me', {}, {
                    retries: 1,
                    retryAuth: true,
                    waitAttempts: 6,
                    waitDelayMs: 120,
                    baseDelayMs: 180
                })
                .then(function (r) { return r && r.ok ? r.json() : null; })
                .then(function (crmData) {
                    var hasCrm = isAdmin || !!(crmData && crmData.has_crm_access);
                    var isBroker = !!(crmData && crmData.is_broker) || role === 'broker';
                    var isClientAdmin = !!(crmData && crmData.is_client_admin);
                    var isClientMember = !!(crmData && crmData.is_client_member);
                    var clientGroupName = String((crmData && crmData.client_group_name) || '').trim();
                    var isDashboardPath = currentPath === '/dashboard' || currentPath.indexOf('/dashboard/') === 0;
                    var displayOrgName = (isDashboardPath && isClientMember && clientGroupName) ? clientGroupName : orgName;
                    var state = {
                        role: role, isAdmin: isAdmin, showCrm: hasCrm,
                        isBroker: isBroker,
                        isClientAdmin: isClientAdmin,
                        isClientMember: isClientMember,
                        clientGroupName: clientGroupName,
                        avatarText: avatarText, orgName: orgName, displayOrgName: displayOrgName, userName: userName
                    };
                    applySidebarState(state);
                    try { sessionStorage.setItem(CACHE_KEY, JSON.stringify(state)); } catch (e) { /* ignore */ }
                    finishSidebar(state);
                })
                .catch(function () {
                    var state = {
                        role: role, isAdmin: isAdmin, showCrm: isAdmin,
                        isBroker: role === 'broker',
                        isClientAdmin: !!(profile && profile.is_client_admin),
                        isClientMember: false,
                        clientGroupName: '',
                        avatarText: avatarText, orgName: orgName, displayOrgName: orgName, userName: userName
                    };
                    applySidebarState(state);
                    try { sessionStorage.setItem(CACHE_KEY, JSON.stringify(state)); } catch (e) { /* ignore */ }
                    finishSidebar(state);
                });

                function finishSidebar(state) {
                    var resolved = state || {};
                    _resolve({
                        role: role,
                        profile: profile,
                        org: data && data.org ? data.org : null,
                        accessToken: accessToken,
                        isAdmin: isAdmin,
                        clientGroupName: resolved.clientGroupName || '',
                        isBroker: !!resolved.isBroker,
                        isClientAdmin: !!resolved.isClientAdmin,
                        isClientMember: !!resolved.isClientMember,
                        displayOrgName: resolved.displayOrgName || orgName || ''
                    });
                    var customerPaths = ['/customer-dashboard', '/crm'];
                    if (resolved.isBroker) customerPaths.push('/broker/invites');
                    if (resolved.isClientAdmin && !resolved.isBroker) customerPaths.push('/client-management');
                    var onCustomerPath = customerPaths.indexOf(currentPath) !== -1
                        || (resolved.isBroker && currentPath && currentPath.indexOf('/broker/') === 0);
                    if (((!isAdmin && resolved.isBroker) || resolved.isClientAdmin) && !onCustomerPath) {
                        window.location.replace('/customer-dashboard');
                    }
                }
            })
            .catch(function () {
                _resolve({ role: '', profile: null, org: null, accessToken: accessToken, isAdmin: false });
            });

        // Change password link — prevent scroll on pages without the modal
        var changePwLink = document.getElementById('nav-change-password');
        if (changePwLink) {
            changePwLink.addEventListener('click', function (e) {
                e.preventDefault();
            });
        }

        // Logout handler
        var logoutEl = document.getElementById('nav-logout');
        if (logoutEl) {
            logoutEl.addEventListener('click', function (e) {
                e.preventDefault();
                sessionStorage.removeItem(CACHE_KEY);
                _pmSafeSignOut(function () { window.location.href = '/login'; });
            });
        }
    }).catch(function () {
        sessionStorage.removeItem(CACHE_KEY);
        window.location.replace('/login');
    });

    // ---- User dropdown toggle ----
    var userBtn = document.getElementById('sidebar-user-btn');
    var userDropdown = document.getElementById('sidebar-user-dropdown');
    if (userBtn && userDropdown) {
        userBtn.addEventListener('click', function (e) {
            e.stopPropagation();
            userDropdown.classList.toggle('visible');
        });
        document.addEventListener('click', function (e) {
            if (!userDropdown.contains(e.target) && e.target !== userBtn) {
                userDropdown.classList.remove('visible');
            }
        });
    }

    function show(id, visible) {
        var el = document.getElementById(id);
        if (el) el.style.display = visible ? '' : 'none';
    }
})();
