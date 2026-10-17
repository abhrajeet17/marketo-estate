/**
 * Charm UI runtime — shared behaviour for every portal page.
 *
 *   Charm.api        cached + de-duplicated JSON client (stale-while-revalidate)
 *   Charm.toast      toast notifications
 *   Charm.modal      open/close .ui-modal dialogs (esc, backdrop, focus, scroll lock)
 *   Charm.confirm    promise-based confirm dialog (replaces window.confirm)
 *   Charm.menu       [data-ui-menu] dropdowns
 *   Charm.tabs       sliding indicator for .ui-tabs
 *   Charm.skeleton   skeleton markup for tables / lists / cards
 *   Charm.progress   thin top progress bar for slow requests
 *   Charm.fmt        date / number / initials formatting
 *   Charm.countUp    animated KPI numbers
 *   Charm.loadScript lazy third-party scripts (e.g. SheetJS on export)
 */
(function (global) {
  'use strict';

  var doc = global.document;
  var reduceMotion = false;
  try { reduceMotion = global.matchMedia('(prefers-reduced-motion: reduce)').matches; } catch (e) { /* ignore */ }

  // ── Small helpers ──────────────────────────────────────────────────────
  function esc(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function byId(id) { return doc.getElementById(id); }

  function debounce(fn, wait) {
    var timer = null;
    return function () {
      var args = arguments;
      var self = this;
      if (timer) clearTimeout(timer);
      timer = setTimeout(function () { timer = null; fn.apply(self, args); }, wait || 200);
    };
  }

  function idle(fn) {
    if (global.requestIdleCallback) return global.requestIdleCallback(fn, { timeout: 1200 });
    return setTimeout(fn, 60);
  }

  function readStore(store, key) {
    try { return JSON.parse(store.getItem(key) || 'null'); } catch (e) { return null; }
  }

  function writeStore(store, key, value) {
    try { store.setItem(key, JSON.stringify(value)); } catch (e) { /* quota / private mode */ }
  }

  // ── Icons (inline, stroke) ─────────────────────────────────────────────
  var ICONS = {
    check: '<path d="M20 6 9 17l-5-5"/>',
    x: '<path d="M18 6 6 18M6 6l12 12"/>',
    info: '<circle cx="12" cy="12" r="9"/><path d="M12 8h.01M11 12h1v4h1"/>',
    alert: '<path d="M12 9v4M12 17h.01"/><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"/>',
    trash: '<path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6"/>',
    search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    users: '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/>',
    inbox: '<path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11Z"/>',
    refresh: '<path d="M21 12a9 9 0 1 1-2.64-6.36L21 8"/><path d="M21 3v5h-5"/>'
  };

  function icon(name, size) {
    var s = size || 16;
    return '<svg width="' + s + '" height="' + s + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + (ICONS[name] || '') + '</svg>';
  }

  // ── Formatting ─────────────────────────────────────────────────────────
  var fmt = {
    date: function (iso) {
      if (!iso) return '—';
      var d = new Date(iso);
      if (isNaN(d.getTime())) return String(iso);
      return d.toLocaleDateString(undefined, { day: '2-digit', month: 'short', year: 'numeric' });
    },
    dateTime: function (iso) {
      if (!iso) return '—';
      var d = new Date(iso);
      if (isNaN(d.getTime())) return String(iso);
      return d.toLocaleString(undefined, { day: '2-digit', month: 'short', year: 'numeric', hour: 'numeric', minute: '2-digit' });
    },
    relative: function (iso) {
      if (!iso) return '—';
      var d = new Date(iso);
      var diff = Date.now() - d.getTime();
      if (!isFinite(diff)) return '—';
      var mins = Math.floor(diff / 60000);
      if (mins < 1) return 'Just now';
      if (mins < 60) return mins + 'm ago';
      var hrs = Math.floor(mins / 60);
      if (hrs < 24) return hrs + 'h ago';
      var days = Math.floor(hrs / 24);
      if (days < 30) return days + 'd ago';
      return fmt.date(iso);
    },
    number: function (value) {
      var n = Number(value || 0);
      try { return n.toLocaleString(); } catch (e) { return String(n); }
    },
    initials: function (name, fallback) {
      var text = String(name || fallback || '').trim();
      if (!text) return '··';
      if (text.indexOf('@') > 0 && text.indexOf(' ') < 0) text = text.split('@')[0].replace(/[._-]+/g, ' ');
      var parts = text.split(/\s+/).filter(Boolean);
      if (parts.length > 1) return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
      return text.slice(0, 2).toUpperCase();
    },
    plural: function (n, one, many) { return n + ' ' + (n === 1 ? one : (many || one + 's')); }
  };

  // ── Top progress bar ───────────────────────────────────────────────────
  var progress = (function () {
    var bar = null;
    var active = 0;
    var value = 0;
    var timer = null;
    var showTimer = null;

    function el() {
      if (bar) return bar;
      bar = doc.createElement('div');
      bar.className = 'ui-topbar-progress';
      bar.setAttribute('aria-hidden', 'true');
      doc.body.appendChild(bar);
      return bar;
    }

    function render() { el().style.transform = 'scaleX(' + value + ')'; }

    function trickle() {
      value = Math.min(0.92, value + (1 - value) * 0.08);
      render();
    }

    return {
      start: function () {
        active += 1;
        if (active > 1) return;
        // Only show for requests slower than ~180ms, so fast calls never flash.
        clearTimeout(showTimer);
        showTimer = setTimeout(function () {
          if (!active) return;
          value = 0.08;
          el().classList.add('is-active');
          render();
          clearInterval(timer);
          timer = setInterval(trickle, 260);
        }, 180);
      },
      done: function () {
        active = Math.max(0, active - 1);
        if (active) return;
        clearTimeout(showTimer);
        clearInterval(timer);
        if (!bar || !bar.classList.contains('is-active')) return;
        value = 1;
        render();
        setTimeout(function () {
          if (active) return;
          bar.classList.remove('is-active');
          setTimeout(function () { if (!active) { value = 0; render(); } }, 260);
        }, 200);
      }
    };
  })();

  // ── API client ─────────────────────────────────────────────────────────
  var memCache = Object.create(null);   // key -> { t, data }
  var inflight = Object.create(null);   // key -> Promise
  var CACHE_PREFIX = 'charm.api.v1:';

  function getSupabase() { return global._supabase || null; }

  function authHeaders() {
    if (global.pmApi && typeof global.pmApi.getAuthHeaders === 'function') {
      return Promise.resolve(global.pmApi.getAuthHeaders({}));
    }
    var sb = getSupabase();
    if (!sb || !sb.auth) return Promise.resolve({});
    return sb.auth.getSession().then(function (r) {
      var token = r && r.data && r.data.session && r.data.session.access_token;
      return token ? { Authorization: 'Bearer ' + token } : {};
    }).catch(function () { return {}; });
  }

  function cacheIdentity() {
    // Cache entries are scoped to the signed-in user so a shared browser
    // never shows one account's data to another.
    var cached = readStore(global.localStorage, 'marketostate_auth_session_v1');
    var uid = cached && cached.user && cached.user.id;
    return uid ? String(uid) : 'anon';
  }

  function cacheKey(url) { return CACHE_PREFIX + cacheIdentity() + ':' + url; }

  function readCache(url) {
    var key = cacheKey(url);
    if (memCache[key]) return memCache[key];
    var stored = readStore(global.sessionStorage, key);
    if (stored && stored.t) memCache[key] = stored;
    return stored;
  }

  function writeCache(url, data, persist) {
    var key = cacheKey(url);
    var entry = { t: Date.now(), data: data };
    memCache[key] = entry;
    if (persist) writeStore(global.sessionStorage, key, entry);
  }

  function invalidate(prefixes) {
    var list = Array.isArray(prefixes) ? prefixes : [prefixes];
    var base = CACHE_PREFIX + cacheIdentity() + ':';
    Object.keys(memCache).forEach(function (key) {
      if (list.some(function (p) { return key.indexOf(base + p) === 0; })) delete memCache[key];
    });
    try {
      for (var i = global.sessionStorage.length - 1; i >= 0; i -= 1) {
        var k = global.sessionStorage.key(i);
        if (k && list.some(function (p) { return k.indexOf(base + p) === 0; })) global.sessionStorage.removeItem(k);
      }
    } catch (e) { /* ignore */ }
  }

  function ApiError(message, status, payload) {
    var err = new Error(message || 'Request failed');
    err.status = status || 0;
    err.payload = payload || null;
    return err;
  }

  function isRetryable(status) { return !status || status === 408 || status === 429 || status >= 502; }

  function wait(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

  function request(method, url, body, opts) {
    var o = opts || {};
    var attempts = o.retries != null ? o.retries + 1 : (method === 'GET' ? 3 : 1);
    var quiet = !!o.quiet;
    if (!quiet) progress.start();

    function attempt(n) {
      return authHeaders().then(function (headers) {
        var init = { method: method, headers: Object.assign({ Accept: 'application/json' }, headers || {}, o.headers || {}) };
        if (body !== undefined && body !== null) {
          if (global.FormData && body instanceof global.FormData) {
            init.body = body;
          } else {
            init.headers['Content-Type'] = 'application/json';
            init.body = typeof body === 'string' ? body : JSON.stringify(body);
          }
        }
        if (o.signal) init.signal = o.signal;
        return fetch(url, init);
      }).then(function (res) {
        if (!res.ok && n < attempts && isRetryable(res.status)) {
          return wait(Math.min(1600, 160 * Math.pow(2, n - 1)) + Math.random() * 80).then(function () { return attempt(n + 1); });
        }
        if (res.status === 401 && n < attempts) {
          var sb = getSupabase();
          var refresh = sb && sb.auth && sb.auth.refreshSession ? sb.auth.refreshSession().catch(function () {}) : Promise.resolve();
          return refresh.then(function () { return attempt(n + 1); });
        }
        return res.text().then(function (text) {
          var data = null;
          try { data = text ? JSON.parse(text) : null; } catch (e) { data = null; }
          if (!res.ok) {
            var msg = (data && (data.error || data.message)) || res.statusText || ('Request failed (' + res.status + ')');
            throw ApiError(msg, res.status, data);
          }
          return data;
        });
      }).catch(function (err) {
        if (err && err.name === 'AbortError') throw err;
        if (err && err.status) throw err;
        if (n < attempts) return wait(220 * n).then(function () { return attempt(n + 1); });
        throw ApiError((err && err.message) || 'Network error — check your connection.', 0, null);
      });
    }

    return attempt(1).then(function (data) {
      if (!quiet) progress.done();
      return data;
    }, function (err) {
      if (!quiet) progress.done();
      throw err;
    });
  }

  /**
   * GET with caching.
   *   ttl      ms a cached value counts as fresh (default 15s)
   *   swr      resolve stale data immediately and revalidate in background
   *   persist  keep in sessionStorage so the next page load paints instantly
   *   onUpdate called with fresh data after a background revalidation
   */
  function get(url, opts) {
    var o = opts || {};
    var ttl = o.ttl != null ? o.ttl : 15000;
    var cached = o.force ? null : readCache(url);
    var fresh = cached && (Date.now() - cached.t) < ttl;

    function load() {
      if (inflight[url]) return inflight[url];
      var p = request('GET', url, null, { quiet: o.quiet || !!cached, signal: o.signal }).then(function (data) {
        writeCache(url, data, o.persist);
        delete inflight[url];
        return data;
      }, function (err) {
        delete inflight[url];
        throw err;
      });
      inflight[url] = p;
      return p;
    }

    if (fresh) return Promise.resolve(cached.data);
    if (cached && o.swr) {
      load().then(function (data) {
        if (typeof o.onUpdate === 'function' && JSON.stringify(data) !== JSON.stringify(cached.data)) o.onUpdate(data);
      }).catch(function () { /* keep stale data on screen */ });
      return Promise.resolve(cached.data);
    }
    return load();
  }

  function mutate(method) {
    return function (url, body, opts) {
      var o = opts || {};
      return request(method, url, body, o).then(function (data) {
        if (o.invalidate) invalidate(o.invalidate);
        return data;
      });
    };
  }

  var api = {
    get: get,
    post: mutate('POST'),
    patch: mutate('PATCH'),
    put: mutate('PUT'),
    del: mutate('DELETE'),
    request: request,
    invalidate: invalidate,
    peek: function (url) { var c = readCache(url); return c ? c.data : undefined; },
    prefetch: function (url, opts) { idle(function () { get(url, Object.assign({ quiet: true }, opts || {})).catch(function () {}); }); }
  };

  // ── Toasts ─────────────────────────────────────────────────────────────
  function toastStack() {
    var el = byId('ui-toasts');
    if (!el) {
      el = doc.createElement('div');
      el.id = 'ui-toasts';
      el.className = 'ui-toasts';
      el.setAttribute('role', 'region');
      el.setAttribute('aria-label', 'Notifications');
      doc.body.appendChild(el);
    }
    return el;
  }

  function toast(message, type, opts) {
    var kind = type === 'error' || type === 'danger' ? 'error' : (type === 'info' ? 'info' : 'success');
    var o = opts || {};
    var el = doc.createElement('div');
    el.className = 'ui-toast ui-toast--' + kind;
    el.setAttribute('role', kind === 'error' ? 'alert' : 'status');
    el.innerHTML = '<span class="ui-toast__icon">' + icon(kind === 'error' ? 'x' : (kind === 'info' ? 'info' : 'check'), 13) + '</span>' +
      '<span class="ui-toast__msg"></span>' +
      '<button class="ui-toast__close" type="button" aria-label="Dismiss">' + icon('x', 14) + '</button>';
    el.querySelector('.ui-toast__msg').textContent = String(message || '');
    var stack = toastStack();
    stack.appendChild(el);
    while (stack.children.length > 4) stack.removeChild(stack.firstChild);
    var timer = null;
    function dismiss() {
      clearTimeout(timer);
      el.classList.add('is-leaving');
      setTimeout(function () { if (el.parentNode) el.parentNode.removeChild(el); }, 240);
    }
    el.querySelector('.ui-toast__close').addEventListener('click', dismiss);
    timer = setTimeout(dismiss, o.duration || (kind === 'error' ? 5200 : 3200));
    el.addEventListener('mouseenter', function () { clearTimeout(timer); });
    el.addEventListener('mouseleave', function () { timer = setTimeout(dismiss, 1800); });
    return dismiss;
  }

  // ── Modals ─────────────────────────────────────────────────────────────
  var openStack = [];

  function focusFirst(root) {
    var target = root.querySelector('[autofocus], input:not([type=hidden]):not([disabled]), select:not([disabled]), textarea:not([disabled]), .ui-dialog__foot .ui-btn--primary, button:not([disabled])');
    if (target) setTimeout(function () { try { target.focus({ preventScroll: true }); } catch (e) { target.focus(); } }, 60);
  }

  var modal = {
    open: function (el) {
      if (typeof el === 'string') el = byId(el);
      if (!el || el.classList.contains('is-open')) return;
      el._returnFocus = doc.activeElement;
      el.classList.add('is-open');
      el.setAttribute('aria-hidden', 'false');
      openStack.push(el);
      doc.body.classList.add('ui-scroll-lock');
      focusFirst(el);
      el.dispatchEvent(new CustomEvent('ui:open'));
    },
    close: function (el) {
      if (typeof el === 'string') el = byId(el);
      if (!el || !el.classList.contains('is-open')) return;
      el.classList.remove('is-open');
      el.setAttribute('aria-hidden', 'true');
      openStack = openStack.filter(function (m) { return m !== el; });
      if (!openStack.length) doc.body.classList.remove('ui-scroll-lock');
      if (el._returnFocus && el._returnFocus.focus) { try { el._returnFocus.focus({ preventScroll: true }); } catch (e) { /* ignore */ } }
      el.dispatchEvent(new CustomEvent('ui:close'));
    },
    isOpen: function (el) { if (typeof el === 'string') el = byId(el); return !!(el && el.classList.contains('is-open')); }
  };

  doc.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape' || !openStack.length) return;
    var top = openStack[openStack.length - 1];
    if (top && top.getAttribute('data-ui-static') !== 'true') modal.close(top);
  });

  doc.addEventListener('mousedown', function (e) {
    var target = e.target;
    if (target && target.classList && target.classList.contains('ui-modal') && target.classList.contains('is-open') && target.getAttribute('data-ui-static') !== 'true') {
      target._downOnBackdrop = true;
    }
  });
  doc.addEventListener('click', function (e) {
    var target = e.target;
    if (target && target.classList && target.classList.contains('ui-modal') && target._downOnBackdrop) {
      target._downOnBackdrop = false;
      modal.close(target);
      return;
    }
    var closer = target && target.closest ? target.closest('[data-ui-close]') : null;
    if (closer) {
      var host = closer.closest('.ui-modal');
      if (host) modal.close(host);
    }
    var opener = target && target.closest ? target.closest('[data-ui-open]') : null;
    if (opener) modal.open(opener.getAttribute('data-ui-open'));
  });

  function confirmDialog(options) {
    var o = options || {};
    return new Promise(function (resolve) {
      var host = doc.createElement('div');
      host.className = 'ui-modal';
      host.setAttribute('role', 'presentation');
      var tone = o.tone === 'danger' ? 'danger' : 'primary';
      host.innerHTML =
        '<div class="ui-dialog ui-dialog--sm" role="alertdialog" aria-modal="true" aria-labelledby="ui-confirm-title">' +
          '<div class="ui-dialog__head"><div>' +
            (tone === 'danger' ? '<div class="ui-dialog__icon">' + icon(o.icon || 'trash', 20) + '</div>' : '') +
            '<h2 class="ui-dialog__title" id="ui-confirm-title"></h2>' +
            '<p class="ui-dialog__text"></p>' +
          '</div></div>' +
          '<div class="ui-dialog__foot">' +
            '<button type="button" class="ui-btn" data-act="cancel"></button>' +
            '<button type="button" class="ui-btn ui-btn--' + tone + '" data-act="ok"></button>' +
          '</div>' +
        '</div>';
      host.querySelector('.ui-dialog__title').textContent = o.title || 'Are you sure?';
      host.querySelector('.ui-dialog__text').textContent = o.text || '';
      host.querySelector('[data-act=cancel]').textContent = o.cancelLabel || 'Cancel';
      host.querySelector('[data-act=ok]').textContent = o.confirmLabel || 'Confirm';
      doc.body.appendChild(host);
      var settled = false;
      function finish(value) {
        if (settled) return;
        settled = true;
        modal.close(host);
        resolve(value);
        setTimeout(function () { if (host.parentNode) host.parentNode.removeChild(host); }, 400);
      }
      host.addEventListener('ui:close', function () { finish(false); });
      host.querySelector('[data-act=cancel]').addEventListener('click', function () { finish(false); });
      host.querySelector('[data-act=ok]').addEventListener('click', function () { finish(true); });
      requestAnimationFrame(function () {
        modal.open(host);
        var ok = host.querySelector('[data-act=ok]');
        setTimeout(function () { ok.focus(); }, 80);
      });
    });
  }

  // ── Menus ──────────────────────────────────────────────────────────────
  function closeMenus(except) {
    doc.querySelectorAll('.ui-menu.is-open').forEach(function (m) {
      if (m === except) return;
      m.classList.remove('is-open');
      var t = doc.querySelector('[data-ui-menu="' + m.id + '"]');
      if (t) t.setAttribute('aria-expanded', 'false');
    });
  }

  doc.addEventListener('click', function (e) {
    var toggle = e.target && e.target.closest ? e.target.closest('[data-ui-menu]') : null;
    if (toggle) {
      e.preventDefault();
      var menuEl = byId(toggle.getAttribute('data-ui-menu'));
      if (!menuEl) return;
      var open = !menuEl.classList.contains('is-open');
      closeMenus(menuEl);
      menuEl.classList.toggle('is-open', open);
      toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
      if (open) {
        var first = menuEl.querySelector('.ui-menu__item');
        if (first && e.detail === 0) first.focus();
      }
      return;
    }
    if (!(e.target && e.target.closest && e.target.closest('.ui-menu'))) closeMenus(null);
    else if (e.target.closest('.ui-menu__item')) closeMenus(null);
  });
  doc.addEventListener('keydown', function (e) { if (e.key === 'Escape') closeMenus(null); });

  // ── Tabs indicator ─────────────────────────────────────────────────────
  var tabs = {
    sync: function (root) {
      if (!root) return;
      var indicator = root.querySelector('.ui-tabs__indicator');
      if (!indicator) {
        indicator = doc.createElement('span');
        indicator.className = 'ui-tabs__indicator';
        indicator.setAttribute('aria-hidden', 'true');
        root.insertBefore(indicator, root.firstChild);
        root.classList.add('has-indicator');
      }
      var active = root.querySelector('.ui-tab.is-active, .ui-tab.active, .ui-tab[aria-selected="true"], .crm-tab.active');
      if (!active || active.offsetParent === null) { indicator.style.width = '0px'; return; }
      indicator.style.width = active.offsetWidth + 'px';
      indicator.style.transform = 'translateX(' + (active.offsetLeft) + 'px)';
    },
    watch: function (root) {
      if (!root || root._uiTabsWatched) return;
      root._uiTabsWatched = true;
      var sync = function () { tabs.sync(root); };
      if (global.ResizeObserver) new global.ResizeObserver(sync).observe(root);
      if (global.MutationObserver) {
        new global.MutationObserver(sync).observe(root, { subtree: true, attributes: true, attributeFilter: ['class', 'aria-selected', 'style'] });
      }
      if (doc.fonts && doc.fonts.ready) doc.fonts.ready.then(sync);
      sync();
    }
  };

  // ── Skeletons ──────────────────────────────────────────────────────────
  var WIDTHS = ['72%', '54%', '86%', '40%', '64%', '48%', '78%', '58%'];
  var skeleton = {
    rows: function (cols, count) {
      var n = count || 6;
      var html = '';
      for (var r = 0; r < n; r += 1) {
        html += '<tr class="ui-skel-row" aria-hidden="true">';
        for (var c = 0; c < cols; c += 1) {
          if (c === 0) {
            html += '<td><div class="ui-row"><span class="ui-skel ui-skel--avatar"></span><span class="ui-skel ui-skel--line" style="width:' + WIDTHS[(r + c) % WIDTHS.length] + '"></span></div></td>';
          } else {
            html += '<td><span class="ui-skel ui-skel--line" style="width:' + WIDTHS[(r * 3 + c) % WIDTHS.length] + '"></span></td>';
          }
        }
        html += '</tr>';
      }
      return html;
    },
    lines: function (count) {
      var html = '<div class="ui-skel-group" aria-hidden="true">';
      for (var i = 0; i < (count || 3); i += 1) html += '<span class="ui-skel ui-skel--line" style="width:' + WIDTHS[i % WIDTHS.length] + '"></span>';
      return html + '</div>';
    },
    block: function (height) {
      return '<span class="ui-skel ui-skel--block" style="height:' + (height || 160) + 'px" aria-hidden="true"></span>';
    }
  };

  // ── Count-up numbers ───────────────────────────────────────────────────
  function countUp(el, target, opts) {
    if (!el) return;
    var to = Number(target || 0);
    var from = Number(el.getAttribute('data-value') || 0);
    el.setAttribute('data-value', String(to));
    if (reduceMotion || from === to || !isFinite(to)) { el.textContent = fmt.number(to); return; }
    var duration = (opts && opts.duration) || 700;
    var start = null;
    var run = (el._countRun || 0) + 1;
    el._countRun = run;
    function step(ts) {
      if (el._countRun !== run) return;
      if (start === null) start = ts;
      var p = Math.min(1, (ts - start) / duration);
      var eased = 1 - Math.pow(1 - p, 3);
      el.textContent = fmt.number(Math.round(from + (to - from) * eased));
      if (p < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
    // rAF is paused in background tabs; always land on the real value.
    setTimeout(function () { if (el._countRun === run) el.textContent = fmt.number(to); }, duration + 80);
  }

  // ── Lazy scripts ───────────────────────────────────────────────────────
  var scriptCache = Object.create(null);
  function loadScript(src) {
    if (scriptCache[src]) return scriptCache[src];
    scriptCache[src] = new Promise(function (resolve, reject) {
      var s = doc.createElement('script');
      s.src = src;
      s.async = true;
      s.onload = function () { resolve(); };
      s.onerror = function () { delete scriptCache[src]; reject(new Error('Failed to load ' + src)); };
      doc.head.appendChild(s);
    });
    return scriptCache[src];
  }

  // ── Busy buttons ───────────────────────────────────────────────────────
  function busy(btn, isBusy) {
    if (!btn) return;
    if (isBusy) { btn.setAttribute('data-busy', ''); btn.setAttribute('aria-busy', 'true'); btn.disabled = true; }
    else { btn.removeAttribute('data-busy'); btn.removeAttribute('aria-busy'); btn.disabled = false; }
  }

  /** Run an async action with the button in a busy state; surfaces errors as toasts. */
  function action(btn, fn, opts) {
    var o = opts || {};
    busy(btn, true);
    return Promise.resolve().then(fn).then(function (value) {
      if (o.success) toast(o.success, 'success');
      return value;
    }, function (err) {
      if (o.onError) o.onError(err);
      else toast((err && err.message) || o.error || 'Something went wrong', 'error');
      throw err;
    }).finally(function () { busy(btn, false); });
  }

  function copy(text, label) {
    var value = String(text || '');
    if (!value) return Promise.resolve(false);
    var p = global.navigator.clipboard && global.navigator.clipboard.writeText
      ? global.navigator.clipboard.writeText(value)
      : new Promise(function (resolve, reject) {
        var ta = doc.createElement('textarea');
        ta.value = value;
        ta.style.position = 'fixed';
        ta.style.opacity = '0';
        doc.body.appendChild(ta);
        ta.select();
        try { doc.execCommand('copy') ? resolve() : reject(); } catch (e) { reject(e); }
        doc.body.removeChild(ta);
      });
    return p.then(function () { toast((label || 'Link') + ' copied to clipboard', 'success'); return true; })
      .catch(function () { toast('Copy failed — select and copy manually', 'error'); return false; });
  }

  /**
   * View state for a region: shows exactly one `[data-for="<state>"]` child
   * (loading | ready | empty | error) and mirrors it on data-state/aria-busy.
   */
  function setState(root, state) {
    if (typeof root === 'string') root = byId(root);
    if (!root) return;
    root.setAttribute('data-state', state);
    root.setAttribute('aria-busy', state === 'loading' ? 'true' : 'false');
    root.querySelectorAll('[data-for]').forEach(function (el) {
      if (el.closest('[data-state]') !== root) return;
      el.hidden = el.getAttribute('data-for') !== state;
    });
  }

  /**
   * Latest-wins request guard. `const run = Charm.latest();` then
   * `run(promise).then(...)` — results of superseded calls never resolve,
   * so an older, slower response can never overwrite newer data.
   */
  function latest() {
    var token = 0;
    return function (promise) {
      var mine = ++token;
      return new Promise(function (resolve, reject) {
        Promise.resolve(promise).then(function (v) { if (mine === token) resolve(v); },
          function (e) { if (mine === token) reject(e); });
      });
    };
  }

  global.Charm = {
    setState: setState,
    latest: latest,
    esc: esc,
    icon: icon,
    debounce: debounce,
    idle: idle,
    fmt: fmt,
    api: api,
    toast: toast,
    modal: modal,
    confirm: confirmDialog,
    tabs: tabs,
    skeleton: skeleton,
    progress: progress,
    countUp: countUp,
    loadScript: loadScript,
    busy: busy,
    action: action,
    copy: copy,
    reduceMotion: reduceMotion
  };
})(window);
