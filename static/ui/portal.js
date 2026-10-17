/**
 * Portal runtime: auth session, identity, shell navigation.
 *
 * Boot is a single request (GET /api/portal/me). The identity is cached per
 * user in sessionStorage, so repeat visits resolve `Portal.ready` instantly
 * from cache while the server copy refreshes in the background.
 *
 * Compatibility surface kept for page scripts:
 *   window._supabase, window.pmApi, window.sidebarReady (resolves the legacy
 *   ctx object), window.configurePortalShell, window.ensureAuthenticated.
 */
(function (global) {
  'use strict';

  var doc = global.document;
  var IDENTITY_KEY = 'portal_identity_v1';
  var AUTH_FALLBACK_KEY = 'marketostate_auth_session_v1';
  var RAIL_KEY = 'ui_rail_open';

  var url = global.__SUPABASE_URL__;
  var key = global.__SUPABASE_ANON_KEY__;
  if (!url || !key || !global.supabase) {
    global.location.replace('/login');
    return;
  }
  var sb = global._supabase || global.supabase.createClient(url, key);
  global._supabase = sb;

  function byId(id) { return doc.getElementById(id); }
  function setText(id, value) { var el = byId(id); if (el) el.textContent = value; }
  function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }
  function readJson(store, k) { try { return JSON.parse(store.getItem(k) || 'null'); } catch (e) { return null; } }
  function writeJson(store, k, v) { try { store.setItem(k, JSON.stringify(v)); } catch (e) { /* ignore */ } }

  // ── Session ────────────────────────────────────────────────────────────
  function cacheSession(session) {
    if (!session || !session.access_token) return;
    writeJson(global.localStorage, AUTH_FALLBACK_KEY, {
      access_token: session.access_token,
      refresh_token: session.refresh_token || '',
      expires_at: session.expires_at || 0,
      user: session.user ? { id: session.user.id, email: session.user.email } : null,
      ts: Date.now()
    });
  }

  function readCachedSession() {
    var cached = readJson(global.localStorage, AUTH_FALLBACK_KEY);
    if (!cached || !cached.access_token) return null;
    var exp = Number(cached.expires_at || 0) * 1000;
    if (exp && exp < Date.now() + 30000) return null;
    return cached;
  }

  var sessionPromise = null;
  function getSession() {
    if (sessionPromise) return sessionPromise;
    sessionPromise = sb.auth.getSession().then(function (r) {
      var session = r && r.data && r.data.session;
      if (session) { cacheSession(session); return session; }
      var cached = readCachedSession();
      if (cached && cached.refresh_token) {
        return sb.auth.setSession({ access_token: cached.access_token, refresh_token: cached.refresh_token })
          .then(function (res) {
            var s = res && res.data && res.data.session;
            if (s) cacheSession(s);
            return s || null;
          }).catch(function () { return null; });
      }
      return null;
    }).catch(function () { return readCachedSession(); }).then(function (session) {
      sessionPromise = null;
      return session;
    });
    return sessionPromise;
  }

  // Keep the cached copy fresh when supabase rotates tokens.
  try {
    sb.auth.onAuthStateChange(function (event, session) {
      if (session) cacheSession(session);
      if (event === 'SIGNED_OUT') {
        try { global.localStorage.removeItem(AUTH_FALLBACK_KEY); global.sessionStorage.removeItem(IDENTITY_KEY); } catch (e) { /* ignore */ }
      }
    });
  } catch (e) { /* ignore */ }

  function waitForSession(attempts, delay) {
    var left = Math.max(0, Number(attempts) || 0);
    function step() {
      return getSession().then(function (s) {
        if (s || left <= 0) return s;
        left -= 1;
        return sleep(delay || 120).then(step);
      });
    }
    return step();
  }

  function authHeaders(base) {
    var headers = Object.assign({}, base || {});
    if (headers.Authorization) return Promise.resolve(headers);
    return waitForSession(6, 120).then(function (session) {
      var token = (session && session.access_token) || (readCachedSession() || {}).access_token;
      if (token) headers.Authorization = 'Bearer ' + token;
      return headers;
    });
  }

  function fetchWithRetry(path, opts, retryOpts) {
    var o = opts || {};
    var ro = retryOpts || {};
    var retries = Math.max(0, Number(ro.retries) || 0);
    var method = String(o.method || 'GET').toUpperCase();
    var canRetry = method === 'GET' || ro.allowRetryOnWrite === true;
    function attempt(n) {
      return authHeaders(o.headers).then(function (headers) {
        return fetch(path, Object.assign({}, o, { headers: headers }));
      }).then(function (res) {
        if (res.ok || !canRetry || n >= retries) return res;
        if (res.status === 401) return sb.auth.refreshSession().catch(function () {}).then(function () { return attempt(n + 1); });
        if (res.status === 429 || res.status >= 500) return sleep(180 * Math.pow(1.8, n)).then(function () { return attempt(n + 1); });
        return res;
      }, function (err) {
        if (!canRetry || n >= retries) throw err;
        return sleep(220 * (n + 1)).then(function () { return attempt(n + 1); });
      });
    }
    return attempt(0);
  }

  function fetchJsonWithRetry(path, opts, retryOpts) {
    return fetchWithRetry(path, opts, retryOpts).then(function (res) {
      return res.text().then(function (text) {
        var data = null;
        try { data = text ? JSON.parse(text) : null; } catch (e) { data = null; }
        if (!res.ok) {
          var err = new Error((data && data.error) || res.statusText || ('Request failed (' + res.status + ')'));
          err.status = res.status;
          err.payload = data;
          throw err;
        }
        return data;
      });
    });
  }

  global.pmApi = {
    waitForSession: waitForSession,
    getAuthHeaders: function (opts) { return authHeaders((opts && opts.headers) || null); },
    fetchWithRetry: fetchWithRetry,
    fetchJsonWithRetry: fetchJsonWithRetry
  };
  global.waitForAuthSession = global.waitForAuthSession || waitForSession;
  global.ensureAuthenticated = global.ensureAuthenticated || function () {
    return authHeaders(null).then(function (h) {
      if (!h.Authorization) throw new Error('Not authenticated');
      return h;
    });
  };

  // ── Identity ───────────────────────────────────────────────────────────
  var listeners = [];
  var current = null;

  function roleLabel(identity) {
    if (!identity) return '';
    if (identity.is_admin && !identity.is_client_admin && !identity.is_broker) return identity.role === 'superadmin' ? 'Super admin' : 'Admin';
    if (identity.is_client_admin) return 'Client admin';
    if (identity.is_broker) return 'Broker';
    if (identity.is_client_user) return 'Sales agent';
    var r = String(identity.role || 'user');
    return r.charAt(0).toUpperCase() + r.slice(1);
  }

  function initials(name) {
    return global.Charm ? global.Charm.fmt.initials(name) : String(name || '··').slice(0, 2).toUpperCase();
  }

  function applyIdentity(identity) {
    if (!identity) return;
    var name = identity.display_name || identity.email || 'Account';
    var html = doc.documentElement;
    html.classList.toggle('ui-is-broker', !!identity.is_broker);
    html.classList.toggle('ui-can-team', !!identity.can_manage_team);
    html.classList.toggle('ui-is-admin', !!identity.is_admin);
    setText('navbar-user-name', name);
    setText('navbar-user-short', String(name).split(/\s+/)[0]);
    setText('navbar-user-role', roleLabel(identity) + (identity.client_group_name ? ' · ' + identity.client_group_name : ''));
    setText('navbar-user-avatar', initials(name));
    setText('navbar-user-avatar-2', initials(name));
    var home = identity.home_path || '/customer-dashboard';
    ['portal-menu-dashboard', 'portal-dropdown-dashboard', 'portal-home-link'].forEach(function (id) {
      var el = byId(id);
      if (el) el.setAttribute('href', home);
    });
    try { global.localStorage.setItem('portal_is_broker', identity.is_broker ? '1' : '0'); } catch (e) { /* ignore */ }
  }

  function legacyCtx(identity, session) {
    var i = identity || {};
    return {
      identity: i,
      role: i.role || '',
      profile: {
        user_id: i.user_id,
        role: i.role,
        org_id: i.org_id,
        name: i.display_name,
        display_name: i.display_name,
        email: i.email,
        is_broker: !!i.is_broker,
        is_client_admin: !!i.is_client_admin
      },
      org: i.org || null,
      accessToken: session && session.access_token,
      isAdmin: !!i.is_admin,
      clientGroupName: i.client_group_name || '',
      isBroker: !!i.is_broker,
      isClientAdmin: !!i.is_client_admin,
      isClientMember: !!i.is_client_member,
      displayOrgName: (i.org && i.org.name) || ''
    };
  }

  function enforceRoute(identity) {
    var path = global.location.pathname.replace(/\/+$/, '') || '/';
    var portalOnly = (!identity.is_admin && identity.is_broker) || identity.is_client_admin;
    if (!portalOnly) return false;
    var allowed = ['/customer-dashboard', '/crm'];
    if (identity.is_broker) allowed.push('/broker/invites');
    if (identity.can_manage_team) allowed.push('/client-management');
    if (allowed.indexOf(path) === -1 && path.indexOf('/broker/') !== 0) {
      global.location.replace('/customer-dashboard');
      return true;
    }
    return false;
  }

  function signOut() {
    try {
      global.localStorage.removeItem(AUTH_FALLBACK_KEY);
      global.sessionStorage.removeItem(IDENTITY_KEY);
      global.sessionStorage.removeItem('sidebar_cache_v2_client_admin');
    } catch (e) { /* ignore */ }
    Promise.resolve(sb.auth.signOut()).catch(function () {}).then(function () { global.location.href = '/login'; });
  }

  function fetchIdentity() {
    return fetchJsonWithRetry('/api/portal/me', {}, { retries: 2 });
  }

  var readyResolve;
  var ready = new Promise(function (resolve) { readyResolve = resolve; });

  getSession().then(function (session) {
    if (!session) {
      global.location.replace('/login');
      return;
    }
    global.__ACCESS_TOKEN__ = session.access_token;
    var uid = session.user && session.user.id;
    var cached = readJson(global.sessionStorage, IDENTITY_KEY);
    var useCache = cached && cached.uid === uid && cached.data && (Date.now() - cached.t) < 10 * 60 * 1000;

    function settle(identity) {
      current = identity;
      applyIdentity(identity);
      if (enforceRoute(identity)) return;
      readyResolve(legacyCtx(identity, session));
    }

    var network = fetchIdentity().then(function (identity) {
      writeJson(global.sessionStorage, IDENTITY_KEY, { uid: uid, t: Date.now(), data: identity });
      return identity;
    });

    if (useCache) {
      settle(cached.data);
      network.then(function (fresh) {
        if (JSON.stringify(fresh) === JSON.stringify(cached.data)) return;
        current = fresh;
        applyIdentity(fresh);
        if (enforceRoute(fresh)) return;
        listeners.forEach(function (fn) { try { fn(fresh); } catch (e) { /* ignore */ } });
      }).catch(function () { /* keep cached identity */ });
    } else {
      network.then(settle).catch(function (err) {
        if (err && (err.status === 401 || err.status === 403)) { signOut(); return; }
        settle({ user_id: uid, role: 'user', display_name: (session.user && session.user.email) || '', email: (session.user && session.user.email) || '' });
      });
    }
  });

  global.Portal = {
    ready: ready,
    identity: function () { return current; },
    onChange: function (fn) { listeners.push(fn); },
    signOut: signOut,
    roleLabel: roleLabel
  };
  global.sidebarReady = ready;

  // Legacy hook used by older page scripts; identity now drives the shell.
  global.configurePortalShell = function (profile, isBroker, isAdmin, isClientAdmin) {
    if (!current) return;
    applyIdentity(current);
  };
  global.configureSneatShell = global.configurePortalShell;
  global.applyPortalSidebarCollapse = function (collapsed) { setRail(!collapsed); };
  global.mountCrmHeaderTabs = function () {};

  // ── Shell behaviour ────────────────────────────────────────────────────
  function setRail(open) {
    doc.documentElement.classList.toggle('ui-rail-open', !!open);
    try { global.localStorage.setItem(RAIL_KEY, open ? '1' : '0'); } catch (e) { /* ignore */ }
    if (typeof global.syncCrmSidebarLayout === 'function') global.syncCrmSidebarLayout();
    global.dispatchEvent(new Event('resize'));
  }

  function setMobileRail(open) {
    doc.documentElement.classList.toggle('ui-rail-mobile-open', !!open);
  }

  function bindShell() {
    var toggle = byId('portal-rail-toggle');
    if (toggle) toggle.addEventListener('click', function () { setRail(!doc.documentElement.classList.contains('ui-rail-open')); });
    var mobile = byId('portal-mobile-menu-toggle');
    if (mobile) mobile.addEventListener('click', function () { setMobileRail(true); });
    var scrim = byId('portal-rail-scrim');
    if (scrim) scrim.addEventListener('click', function () { setMobileRail(false); });
    doc.addEventListener('keydown', function (e) { if (e.key === 'Escape') setMobileRail(false); });

    ['menu-signout', 'dropdown-signout'].forEach(function (id) {
      var el = byId(id);
      if (el) el.addEventListener('click', function (e) { e.preventDefault(); signOut(); });
    });

    // Warm the next page's data while the user hovers a nav link.
    doc.querySelectorAll('.ui-rail__link[href], .ui-menu__item[href]').forEach(function (link) {
      link.addEventListener('mouseenter', function () {
        var href = link.getAttribute('href');
        if (!href || link._prefetched || href === global.location.pathname) return;
        link._prefetched = true;
        var hint = doc.createElement('link');
        hint.rel = 'prefetch';
        hint.href = href;
        doc.head.appendChild(hint);
      }, { passive: true });
    });

    var changePw = byId('dropdown-change-password');
    var form = byId('change-password-form');
    if (changePw && global.Charm) {
      changePw.addEventListener('click', function () {
        var err = byId('change-password-error');
        if (err) err.textContent = '';
        if (form) form.reset();
        global.Charm.modal.open('change-password-modal');
      });
    }
    if (form && global.Charm) {
      form.addEventListener('submit', function (e) {
        e.preventDefault();
        var next = byId('new-password-input').value || '';
        var confirmValue = byId('confirm-password-input').value || '';
        var err = byId('change-password-error');
        if (next.length < 6) { err.textContent = 'Password must be at least 6 characters.'; return; }
        if (next !== confirmValue) { err.textContent = 'Passwords do not match.'; return; }
        err.textContent = '';
        var btn = byId('confirm-change-password');
        global.Charm.action(btn, function () {
          return sb.auth.updateUser({ password: next }).then(function (r) { if (r.error) throw r.error; });
        }, { success: 'Password updated', onError: function (e2) { err.textContent = (e2 && e2.message) || 'Failed to update password'; } })
          .then(function () { global.Charm.modal.close('change-password-modal'); }).catch(function () {});
      });
    }
  }

  if (doc.readyState === 'loading') doc.addEventListener('DOMContentLoaded', bindShell);
  else bindShell();
})(window);
