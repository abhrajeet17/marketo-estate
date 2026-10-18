/**
 * Admin shell: session, shared API helpers, role-based sidebar navigation.
 * Loaded by every page that includes templates/components/sidebar.html.
 *
 * Globals for page scripts:
 *   window._supabase       Supabase client
 *   window.pmApi           { waitForSession, getAuthHeaders, fetchWithRetry, fetchJsonWithRetry }
 *   window.sessionReady    Promise<accessToken> as soon as the session is known (use it to load data)
 *   window.sidebarReady    Promise<{ role, profile, org, accessToken, isAdmin, isBroker,
 *                                    isClientAdmin, isClientMember, clientGroupName, displayOrgName }>
 */
(function () {
    'use strict';

    var AUTH_FALLBACK_KEY = 'marketostate_auth_session_v1';
    var STATE_KEY_PREFIX = 'sidebar_state_v3:';
    var COLLAPSE_KEY = 'dashboard-sidebar-collapsed';
    var PLATFORM_ADMIN_ROLES = ['admin', 'superadmin'];

    var url = window.__SUPABASE_URL__;
    var key = window.__SUPABASE_ANON_KEY__;
    if (!url || !key || !window.supabase) return;

    var sb = window.supabase.createClient(url, key);
    window._supabase = sb;

    function readJson(store, k) {
        try { return JSON.parse(store.getItem(k) || 'null'); } catch (e) { return null; }
    }
    function writeJson(store, k, value) {
        try { store.setItem(k, JSON.stringify(value)); } catch (e) { /* storage unavailable */ }
    }
    function removeKey(store, k) {
        try { store.removeItem(k); } catch (e) { /* storage unavailable */ }
    }
    function sleep(ms) {
        return new Promise(function (resolve) { setTimeout(resolve, Number(ms) || 0); });
    }

    // ── Session ────────────────────────────────────────────────────────────
    function cacheSession(session) {
        if (!session || !session.access_token) return;
        writeJson(localStorage, AUTH_FALLBACK_KEY, {
            access_token: session.access_token,
            refresh_token: session.refresh_token || '',
            expires_at: session.expires_at || 0,
            user: session.user ? { id: session.user.id, email: session.user.email } : null,
            ts: Date.now()
        });
    }

    function readCachedSession() {
        var cached = readJson(localStorage, AUTH_FALLBACK_KEY);
        if (!cached || !cached.access_token) return null;
        var expiresAtMs = Number(cached.expires_at || 0) * 1000;
        if (expiresAtMs && expiresAtMs < Date.now() + 30000) {
            removeKey(localStorage, AUTH_FALLBACK_KEY);
            return null;
        }
        return cached;
    }

    function getSessionOnce() {
        return sb.auth.getSession().then(function (r) {
            var session = r && r.data && r.data.session;
            if (session) {
                cacheSession(session);
                return session;
            }
            var cached = readCachedSession();
            if (!cached || !cached.refresh_token) return cached;
            return sb.auth.setSession({ access_token: cached.access_token, refresh_token: cached.refresh_token })
                .then(function (res) {
                    var hydrated = res && res.data && res.data.session;
                    if (hydrated) cacheSession(hydrated);
                    return hydrated || cached;
                })
                .catch(function () { return cached; });
        }).catch(readCachedSession);
    }

    function waitForSession(maxAttempts, delayMs) {
        var left = Math.max(0, Number(maxAttempts) || 0);
        var wait = Math.max(40, Number(delayMs) || 120);
        function step() {
            return getSessionOnce().then(function (session) {
                if (session || left <= 0) return session;
                left -= 1;
                return sleep(wait).then(step);
            });
        }
        return step();
    }

    // After polling, give a late OAuth/magic-link sign-in a moment to land.
    function waitForSessionOrAuthEvent() {
        return waitForSession(30, 200).then(function (session) {
            if (session && session.access_token) return session;
            return new Promise(function (resolve) {
                var sub = null;
                var done = function (next) {
                    if (sub) sub.unsubscribe();
                    sub = null;
                    resolve(next && next.access_token ? next : null);
                };
                var listener = sb.auth.onAuthStateChange(function (_event, current) {
                    if (current && current.access_token) done(current);
                });
                sub = listener && listener.data ? listener.data.subscription : null;
                setTimeout(function () { done(null); }, 3200);
            });
        });
    }

    sb.auth.onAuthStateChange(function (_event, session) { cacheSession(session); });

    // ── Fetch helpers ──────────────────────────────────────────────────────
    function shouldRetryStatus(status) {
        return [408, 425, 429, 500, 502, 503, 504].indexOf(status) >= 0;
    }

    function retryDelayMs(attempt, baseDelayMs) {
        var base = Math.max(80, Number(baseDelayMs) || 220);
        return Math.min(1400, base * Math.pow(1.8, attempt) + Math.floor(Math.random() * 70));
    }

    async function buildHeaders(existing, opts) {
        var headers = Object.assign({}, existing || {});
        if (headers.Authorization || headers.authorization) return headers;
        var o = opts || {};
        var session = await waitForSession(o.waitAttempts != null ? o.waitAttempts : 14, o.waitDelayMs != null ? o.waitDelayMs : 140);
        var token = (session && session.access_token) || window.__ACCESS_TOKEN__ || (readCachedSession() || {}).access_token;
        if (token) headers.Authorization = 'Bearer ' + token;
        return headers;
    }

    async function fetchWithRetry(path, opts, retryOpts) {
        var options = opts || {};
        var ro = retryOpts || {};
        var retries = Math.max(0, Number(ro.retries) || 0);
        var method = String(options.method || 'GET').toUpperCase();
        var canRetry = method === 'GET' || method === 'HEAD' || ro.allowRetryOnWrite === true;
        var lastError = null;
        for (var attempt = 0; attempt <= retries; attempt += 1) {
            var request = Object.assign({}, options, { headers: await buildHeaders(options.headers, ro) });
            try {
                var res = await fetch(path, request);
                if (res.ok || !canRetry || attempt >= retries) return res;
                if (res.status === 401 && ro.retryAuth !== false) {
                    await sb.auth.refreshSession().catch(function () { return null; });
                } else if (!shouldRetryStatus(res.status)) {
                    return res;
                }
            } catch (err) {
                lastError = err;
                if (!canRetry || attempt >= retries) break;
            }
            await sleep(retryDelayMs(attempt, ro.baseDelayMs));
        }
        throw lastError || new Error('Network request failed');
    }

    async function fetchJsonWithRetry(path, opts, retryOpts) {
        var res = await fetchWithRetry(path, opts, retryOpts);
        var text = await res.text().catch(function () { return ''; });
        var data = null;
        try { data = text ? JSON.parse(text) : null; } catch (e) { data = null; }
        if (!res.ok) {
            var err = new Error((data && data.error) || text || ('Request failed (' + res.status + ')'));
            err.status = res.status;
            err.payload = data;
            throw err;
        }
        return data;
    }

    window.pmApi = {
        waitForSession: waitForSession,
        getAuthHeaders: function (opts) { return buildHeaders((opts && opts.headers) || null, opts || {}); },
        fetchWithRetry: fetchWithRetry,
        fetchJsonWithRetry: fetchJsonWithRetry
    };

    // ── Navigation chrome ──────────────────────────────────────────────────
    var currentPath = window.location.pathname.replace(/\/+$/, '') || '/';

    document.querySelectorAll('.sidebar-link[data-page]').forEach(function (link) {
        var href = (link.getAttribute('href') || '').replace(/\/+$/, '') || '/';
        var isSalesToolsAlias = href === '/salestools' && currentPath === '/daynight';
        var active = currentPath === href || currentPath.indexOf(href + '/') === 0 || isSalesToolsAlias;
        link.classList.toggle('active', active);
    });

    var sidebar = document.getElementById('dashboard-sidebar');
    var toggle = document.getElementById('sidebar-toggle');
    if (sidebar && toggle) {
        var expanded = false;
        try { expanded = localStorage.getItem(COLLAPSE_KEY) === '0'; } catch (e) { /* default collapsed */ }
        sidebar.classList.toggle('sidebar-collapsed', !expanded);
        toggle.setAttribute('aria-label', expanded ? 'Collapse sidebar' : 'Expand sidebar');
        toggle.title = expanded ? 'Collapse sidebar' : 'Expand sidebar';
        toggle.addEventListener('click', function () {
            var collapsed = sidebar.classList.toggle('sidebar-collapsed');
            var label = collapsed ? 'Expand sidebar' : 'Collapse sidebar';
            toggle.setAttribute('aria-label', label);
            toggle.title = label;
            try { localStorage.setItem(COLLAPSE_KEY, collapsed ? '1' : '0'); } catch (e) { /* ignore */ }
        });
    }

    // ── Active project ─────────────────────────────────────────────────────
    // The project picked on /projectselection is a global filter: Workspace pages (those that
    // render #project-rail) always carry ?workspace_id=<active project>, which every page
    // already uses to load only that project's resources. Stored per user in localStorage.
    var ACTIVE_PROJECT_PREFIX = 'ms_active_project_v1:';
    var PROJECT_LIST_PREFIX = 'ms_projects_v1:';
    var PROJECT_LIST_TTL_MS = 5 * 60 * 1000;
    var rail = document.getElementById('project-rail');
    var railList = document.getElementById('project-rail-list');
    var projectUserId = ((readCachedSession() || {}).user || {}).id || '';
    var projectList = null;

    function getActiveProject() {
        if (!projectUserId) return null;
        var p = readJson(localStorage, ACTIVE_PROJECT_PREFIX + projectUserId);
        return p && p.id ? p : null;
    }

    function setActiveProject(project) {
        if (!projectUserId || !project || !project.id) return;
        writeJson(localStorage, ACTIVE_PROJECT_PREFIX + projectUserId, {
            id: String(project.id), name: project.name || '', thumb: project.thumb || '', fallback: project.fallback || ''
        });
        renderRail();
    }

    function clearActiveProject() {
        if (projectUserId) removeKey(localStorage, ACTIVE_PROJECT_PREFIX + projectUserId);
        renderRail();
    }

    function findListedProject(id) {
        var list = projectList || [];
        for (var i = 0; i < list.length; i++) if (list[i].id === String(id)) return list[i];
        return null;
    }

    /** Same page, other project: only workspace_id is kept, page-specific ids would not match. */
    function projectPageUrl(id) {
        var base = '/' + (currentPath.split('/')[1] || 'dashboard');
        return base + '?workspace_id=' + encodeURIComponent(id);
    }

    function openProject(id) {
        var project = findListedProject(id) || { id: id };
        setActiveProject(project);
        window.location.href = rail ? projectPageUrl(id) : '/dashboard?workspace_id=' + encodeURIComponent(id);
    }

    /** Builder-visible projects (as the dashboard lists them) with a cover thumbnail each. */
    function projectsFromSnapshot(data) {
        var panoramas = (data && data.panoramas) || [];
        var byProject = Object.create(null);
        panoramas.forEach(function (p) {
            if (!p.workspace_id) return;
            var key = String(p.workspace_id);
            (byProject[key] = byProject[key] || []).push(p);
        });
        return ((data && data.projects) || []).filter(function (p) {
            return (p.access_type || 'owner') === 'owner' || byProject[String(p.id)];
        }).map(function (p) {
            var own = byProject[String(p.id)] || [];
            var cover = null;
            for (var i = 0; i < own.length && !cover; i++) if (Number(own[i].id) === Number(p.main_panorama_id)) cover = own[i];
            for (var j = 0; j < own.length && !cover; j++) if (own[j].is_360) cover = own[j];
            cover = cover || own[0] || null;
            var fallback = cover && cover.filename ? '/uploads/' + encodeURIComponent(cover.filename) + '?size=thumb' : '';
            return {
                id: String(p.id), name: p.name || 'Project',
                thumb: (cover && cover.thumb_url) || fallback, fallback: fallback
            };
        });
    }

    function railInitials(name) {
        var words = String(name || '').trim().split(/\s+/).filter(Boolean);
        return ((words[0] || '?')[0] + (words[1] ? words[1][0] : '')).toUpperCase();
    }

    function escapeHtml(value) {
        return String(value == null ? '' : value).replace(/[&<>"']/g, function (ch) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch];
        });
    }

    function renderRail() {
        if (!railList) return;
        var active = getActiveProject();
        var activeId = active ? active.id : '';
        var unlinkedView = new URLSearchParams(window.location.search).get('unlinked') === '1';
        var list = projectList || (active ? [active] : []);
        railList.innerHTML = list.map(function (p) {
            var isActive = !unlinkedView && p.id === activeId;
            var thumb = p.thumb ? '<img src="' + escapeHtml(p.thumb) + '" alt="" loading="lazy" decoding="async"'
                + (p.fallback && p.fallback !== p.thumb ? ' data-fallback="' + escapeHtml(p.fallback) + '"' : '') + '>' : '';
            return '<a class="project-rail__item' + (isActive ? ' is-active' : '') + '" href="' + escapeHtml(projectPageUrl(p.id)) + '"'
                + ' data-project-id="' + escapeHtml(p.id) + '" data-tooltip="' + escapeHtml(p.name) + '" aria-label="' + escapeHtml(p.name) + '"'
                + (isActive ? ' aria-current="true"' : '') + '>'
                + '<span class="project-rail__initials" aria-hidden="true">' + escapeHtml(railInitials(p.name)) + '</span>' + thumb + '</a>';
        }).join('');
    }

    /**
     * Called with /api/dashboard data (by the dashboard and project selection pages, or by the
     * rail itself). `fresh` = straight from the server: a stale active project is then dropped.
     */
    function setProjectsFromSnapshot(data, fresh) {
        projectList = projectsFromSnapshot(data);
        if (projectUserId) writeJson(localStorage, PROJECT_LIST_PREFIX + projectUserId, { ts: Date.now(), projects: projectList });
        var active = getActiveProject();
        var current = active && findListedProject(active.id);
        if (active && !current && fresh) {
            // Deleted, or no longer shared with this user: pick again.
            clearActiveProject();
            if (rail) window.location.replace('/projectselection');
            return;
        }
        if (current && (current.name !== active.name || current.thumb !== active.thumb)) setActiveProject(current);
        renderRail();
    }

    /** Puts the active project into this Workspace page's URL, or sends the user to pick one. */
    function scopeToActiveProject(navigate) {
        var qs = new URLSearchParams(window.location.search);
        var urlId = (qs.get('workspace_id') || '').trim();
        var active = getActiveProject();
        if (urlId) {
            if (!active || active.id !== urlId) setActiveProject(findListedProject(urlId) || { id: urlId });
            return true;
        }
        if (currentPath.indexOf('/dashboard') === 0 && qs.get('unlinked') === '1') return true;
        if (!active) {
            window.location.replace('/projectselection');
            return false;
        }
        qs.set('workspace_id', active.id);
        var next = window.location.pathname + '?' + qs.toString() + window.location.hash;
        if (navigate) window.location.replace(next);
        else window.history.replaceState(window.history.state, '', next);
        return !navigate;
    }

    function readCachedProjectList() {
        var cached = readJson(localStorage, PROJECT_LIST_PREFIX + projectUserId);
        if (cached && Array.isArray(cached.projects)) projectList = cached.projects;
    }

    if (projectUserId) {
        readCachedProjectList();
        if (rail) scopeToActiveProject(false);
    }

    if (rail) {
        renderRail();
        // A cover that cannot load falls back to the server thumbnail, then to the initials.
        rail.addEventListener('error', function (e) {
            var img = e.target;
            if (img.tagName !== 'IMG') return;
            var fallback = img.getAttribute('data-fallback');
            if (fallback) {
                img.removeAttribute('data-fallback');
                img.src = fallback;
            } else {
                img.remove();
            }
        }, true);
        var tip = document.createElement('div');
        tip.className = 'project-rail__tip';
        tip.setAttribute('role', 'tooltip');
        tip.hidden = true;
        document.body.appendChild(tip);
        var showTip = function (e) {
            var target = e.target.closest && e.target.closest('[data-tooltip]');
            if (!target || !rail.contains(target)) return;
            var r = target.getBoundingClientRect();
            tip.textContent = target.getAttribute('data-tooltip');
            tip.style.left = (r.right + 12) + 'px';
            tip.style.top = (r.top + r.height / 2) + 'px';
            tip.hidden = false;
        };
        var hideTip = function () { tip.hidden = true; };
        rail.addEventListener('mouseover', showTip);
        rail.addEventListener('focusin', showTip);
        rail.addEventListener('mouseleave', hideTip);
        rail.addEventListener('focusout', hideTip);
        railList.addEventListener('scroll', hideTip);
        rail.addEventListener('click', function (e) {
            var item = e.target.closest('[data-project-id]');
            if (!item || e.ctrlKey || e.metaKey || e.shiftKey || e.button !== 0) return;
            e.preventDefault();
            openProject(item.getAttribute('data-project-id'));
        });
    }

    function loadRailProjects() {
        if (!rail || rail.hasAttribute('data-self-load')) return;
        var cached = projectUserId ? readJson(localStorage, PROJECT_LIST_PREFIX + projectUserId) : null;
        if (cached && cached.ts && Date.now() - cached.ts < PROJECT_LIST_TTL_MS) return;
        fetchJsonWithRetry('/api/dashboard', {}, { retries: 1 })
            .then(function (data) { setProjectsFromSnapshot(data, true); })
            .catch(function () { /* keep the cached rail */ });
    }

    window.msProjects = {
        active: getActiveProject,
        setActive: setActiveProject,
        clear: clearActiveProject,
        open: openProject,
        fromSnapshot: setProjectsFromSnapshot
    };

    function show(id, visible) {
        var el = document.getElementById(id);
        if (el) el.style.display = visible ? '' : 'none';
    }

    function initials(name) {
        var text = String(name || '').trim();
        if (!text) return '--';
        var space = text.indexOf(' ');
        return (text[0] + (space > 0 ? text[space + 1] : (text[1] || ''))).toUpperCase();
    }

    function applySidebarState(state) {
        var avatar = document.getElementById('sidebar-avatar');
        if (avatar) avatar.textContent = initials(state.userName);
        var userName = document.getElementById('sidebar-user-name');
        if (userName) userName.textContent = state.userName || '';
        var userRole = document.getElementById('sidebar-user-role');
        if (userRole) userRole.textContent = state.role === 'superadmin' ? 'Super admin' : (state.isAdmin ? 'Admin' : '');
        var orgName = document.getElementById('org-name');
        if (orgName) orgName.textContent = state.orgName || 'MarketoState';

        show('nav-explore', state.isAdmin);
        show('nav-floorplans', state.isAdmin);
        show('nav-building-plans', state.isAdmin);
        show('nav-fullview', state.isAdmin);
        show('nav-user-mgmt', state.isAdmin);
        show('nav-orgs', state.role === 'superadmin');
        show('sidebar-upload-wrap', state.isAdmin);
        show('nav-crm', state.showCrm);
    }

    function stateFromIdentity(identity) {
        var role = String(identity.role || '').toLowerCase();
        var isAdmin = PLATFORM_ADMIN_ROLES.indexOf(role) >= 0;
        return {
            role: role,
            isAdmin: isAdmin,
            showCrm: isAdmin || !!identity.has_crm_access,
            isBroker: !!identity.is_broker || role === 'broker',
            isClientAdmin: !!identity.is_client_admin,
            isClientMember: !!identity.is_client_member,
            clientGroupName: String(identity.client_group_name || '').trim(),
            orgName: (identity.org && identity.org.name) || '',
            userName: identity.display_name || identity.email || ''
        };
    }

    // Every page using this shell is a creator tool. Client admins, sales agents, brokers and
    // other non-admin users work in the client portal instead.
    function redirectPortalOnlyUsers(state) {
        if (state.isAdmin && !state.isClientAdmin) return false;
        window.location.replace('/customer-dashboard');
        return true;
    }

    function signOut(next) {
        removeKey(localStorage, AUTH_FALLBACK_KEY);
        return sb.auth.signOut().catch(function () { return null; }).finally(function () {
            window.location.replace(next || '/login');
        });
    }

    var cachedUser = (readCachedSession() || {}).user;
    var stateKey = STATE_KEY_PREFIX + ((cachedUser && cachedUser.id) || 'anon');
    var cachedState = readJson(sessionStorage, stateKey);
    if (cachedState) applySidebarState(cachedState);

    var resolveReady;
    window.sidebarReady = new Promise(function (resolve) { resolveReady = resolve; });

    var sessionPromise = waitForSessionOrAuthEvent();
    window.sessionReady = sessionPromise.then(function (session) {
        if (session) window.__ACCESS_TOKEN__ = session.access_token;
        return session ? session.access_token : '';
    });

    sessionPromise.then(function (session) {
        if (!session) {
            window.location.replace('/login');
            return;
        }
        // No cached user at load time (first visit after sign-in): scope the page now.
        if (!projectUserId && session.user && session.user.id) {
            projectUserId = session.user.id;
            readCachedProjectList();
            if (rail && !scopeToActiveProject(true)) return;
        }
        loadRailProjects();
        return fetchWithRetry('/api/portal/me', {}, { retries: 1, waitAttempts: 6, waitDelayMs: 120, baseDelayMs: 180 })
            .then(function (res) {
                if (res.status === 401 || res.status === 403) {
                    removeKey(sessionStorage, stateKey);
                    signOut();
                    return null;
                }
                return res.ok ? res.json() : null;
            })
            .catch(function () { return null; })
            .then(function (identity) {
                if (!identity) {
                    resolveReady({ role: '', profile: null, org: null, accessToken: session.access_token, isAdmin: false });
                    return;
                }
                var state = stateFromIdentity(identity);
                applySidebarState(state);
                writeJson(sessionStorage, STATE_KEY_PREFIX + (session.user ? session.user.id : 'anon'), state);
                if (redirectPortalOnlyUsers(state)) return;
                resolveReady({
                    role: state.role,
                    profile: identity,
                    org: identity.org || null,
                    accessToken: session.access_token,
                    isAdmin: state.isAdmin,
                    isBroker: state.isBroker,
                    isClientAdmin: state.isClientAdmin,
                    isClientMember: state.isClientMember,
                    clientGroupName: state.clientGroupName,
                    displayOrgName: state.orgName
                });
            });
    });

    // ── Account menu ───────────────────────────────────────────────────────
    var userBtn = document.getElementById('sidebar-user-btn');
    var userDropdown = document.getElementById('sidebar-user-dropdown');
    if (userBtn && userDropdown) {
        userBtn.addEventListener('click', function (e) {
            e.stopPropagation();
            userDropdown.classList.toggle('visible');
        });
        document.addEventListener('click', function (e) {
            if (!userDropdown.contains(e.target)) userDropdown.classList.remove('visible');
        });
    }

    var logout = document.getElementById('nav-logout');
    if (logout) {
        logout.addEventListener('click', function (e) {
            e.preventDefault();
            removeKey(sessionStorage, stateKey);
            signOut('/login');
        });
    }

    // Pages without the change-password modal must not jump to "#".
    var changePassword = document.getElementById('nav-change-password');
    if (changePassword && !document.getElementById('change-password-modal')) {
        changePassword.addEventListener('click', function (e) { e.preventDefault(); });
    }
})();
