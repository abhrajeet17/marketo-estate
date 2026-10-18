/**
 * Customer dashboard (brokers + client admins).
 *
 * Data requests start immediately, in parallel with identity resolution.
 * Each region renders only when both its data and the identity are known,
 * and every region owns an explicit state (loading/ready/empty/error), so a
 * chart or table can never render "empty" while its data is still in flight.
 */
(function () {
  'use strict';

  var C = window.Charm;
  var api = C.api;
  var esc = C.esc;

  var STAGE_COLORS = {
    new: '#a8a29e',
    contacted: '#60a5fa',
    site_visit: '#a78bfa',
    negotiation: '#ffa300',
    won: '#16a34a',
    lost: '#ef4444'
  };
  var DAYS_DEFAULT = 14;
  var days = DAYS_DEFAULT;

  var ROLE_COPY = {
    client_admin: {
      eyebrow: 'Client admin',
      subtitle: 'Track plots, interests and contacts across your client groups.',
      kpis: [
        ['Sold plots', 'Across your client groups'],
        ['Pending plots', 'Reserved or on hold'],
        ['Interests', 'Across your client groups'],
        ['Contacts', 'Unique interested contacts']
      ]
    },
    broker: {
      eyebrow: 'Broker',
      subtitle: 'Your allotted clients, projects and leads in one place.',
      kpis: [
        ['Clients', 'Allotted to you'],
        ['Projects', 'Across clients'],
        ['Interests', 'From your referrals'],
        ['Contacts', 'Unique contacts']
      ]
    }
  };

  // ── Kick off data immediately (does not wait for identity) ─────────────
  var clientsReq = api.get('/api/crm/allotted-clients', { ttl: 20000, swr: true, persist: true, onUpdate: function (rows) { identityReady.then(function (id) { renderClients(rows, id); }); } });
  var statsRun = C.latest();

  var identityReady = window.Portal.ready.then(function (ctx) {
    var identity = ctx.identity || {};
    if (!identity.is_broker && !identity.is_client_admin) {
      window.location.replace('/crm');
      return new Promise(function () {});
    }
    return identity;
  });

  // ── Identity-dependent copy ────────────────────────────────────────────
  identityReady.then(function (identity) {
    var copy = identity.is_client_admin ? ROLE_COPY.client_admin : ROLE_COPY.broker;
    var name = String(identity.display_name || identity.email || '').trim();
    var first = name ? name.split(/\s+/)[0] : '';
    document.title = (identity.is_client_admin ? 'Client admin dashboard' : 'Broker dashboard') + ' · MarketoState';
    byId('dash-role-eyebrow').textContent = copy.eyebrow + (identity.client_group_name ? ' · ' + identity.client_group_name : '');
    byId('welcome-headline').textContent = first ? 'Welcome back, ' + first : 'Welcome back';
    byId('welcome-subtitle').textContent = copy.subtitle;
    ['kpi-clients', 'kpi-projects', 'kpi-leads', 'kpi-contacts'].forEach(function (id, i) {
      byId(id + '-label').textContent = copy.kpis[i][0];
      byId(id + '-meta').textContent = copy.kpis[i][1];
    });
    var search = byId('dashboard-search-wrap');
    if (search) search.hidden = !identity.is_client_admin;
    if (identity.is_client_admin) bindPlotSearch();
  });

  function byId(id) { return document.getElementById(id); }

  // ── KPIs + clients table ───────────────────────────────────────────────
  function sum(rows, keys) {
    return rows.reduce(function (total, row) {
      for (var i = 0; i < keys.length; i += 1) {
        if (row[keys[i]] != null) return total + Number(row[keys[i]] || 0);
      }
      return total;
    }, 0);
  }

  function renderKpis(rows, identity) {
    var values = identity.is_client_admin
      ? [sum(rows, ['sold_plot_count']), sum(rows, ['pending_plot_count']), sum(rows, ['interest_count', 'lead_count']), sum(rows, ['contact_count'])]
      : [rows.length, sum(rows, ['project_count']), sum(rows, ['interest_count', 'lead_count']), sum(rows, ['contact_count'])];
    ['kpi-clients', 'kpi-projects', 'kpi-leads', 'kpi-contacts'].forEach(function (id, i) {
      var el = byId(id);
      if (el.querySelector('.ui-skel')) el.textContent = '0';
      C.countUp(el, values[i]);
    });
  }

  function renderClients(rows, identity) {
    var list = Array.isArray(rows) ? rows : [];
    var card = byId('dash-clients');
    renderKpis(list, identity);
    var body = byId('dash-clients-body');
    byId('dash-clients-error').hidden = true;
    byId('dash-clients-empty').hidden = list.length > 0;
    card.setAttribute('data-state', list.length ? 'ready' : 'empty');
    card.setAttribute('aria-busy', 'false');
    byId('dash-clients-subtitle').textContent = list.length
      ? C.fmt.plural(list.length, 'client group') + ' in your scope'
      : 'Projects, plots and leads per client group';
    body.className = 'ui-rows-enter';
    body.innerHTML = list.map(function (row) {
      var name = row.client_name || 'Client';
      return '<tr>' +
        '<td><div class="ui-person"><span class="ui-avatar ui-avatar--sm">' + esc(C.fmt.initials(name)) + '</span>' +
          '<div><div class="ui-person__name">' + esc(name) + '</div>' +
          '<div class="ui-person__sub">' + esc(row.member_role === 'client_admin' ? 'Client admin' : (row.member_role === 'broker' ? 'Broker' : 'Member')) + '</div></div></div></td>' +
        '<td class="is-num">' + C.fmt.number(row.project_count) + '</td>' +
        '<td class="is-num">' + C.fmt.number(row.plot_count) + '</td>' +
        '<td class="is-num"><span class="ui-badge ui-badge--success">' + C.fmt.number(row.sold_plot_count) + '</span></td>' +
        '<td class="is-num">' + C.fmt.number(row.interest_count != null ? row.interest_count : row.lead_count) + '</td>' +
        '<td class="is-num">' + C.fmt.number(row.deal_count) + '</td>' +
        '<td class="is-num">' + C.fmt.number(row.contact_count) + '</td>' +
      '</tr>';
    }).join('');
  }

  function showClientsSkeleton() {
    byId('dash-clients-body').innerHTML = C.skeleton.rows(7, 3);
  }

  function loadClients(force) {
    showClientsSkeleton();
    var card = byId('dash-clients');
    card.setAttribute('data-state', 'loading');
    var req = force ? api.get('/api/crm/allotted-clients', { force: true, persist: true }) : clientsReq;
    return Promise.all([req, identityReady]).then(function (r) { renderClients(r[0], r[1]); }).catch(function () {
      byId('dash-clients-body').innerHTML = '';
      byId('dash-clients-empty').hidden = true;
      byId('dash-clients-error').hidden = false;
      card.setAttribute('data-state', 'error');
      ['kpi-clients', 'kpi-projects', 'kpi-leads', 'kpi-contacts'].forEach(function (id) {
        var el = byId(id);
        if (el.querySelector('.ui-skel')) el.textContent = '—';
      });
    });
  }

  // ── Charts ─────────────────────────────────────────────────────────────
  function chartCard(kind) { return document.querySelector('[data-dash-chart="' + kind + '"]'); }

  function renderStages(stats) {
    var card = chartCard('stages');
    var rows = Array.isArray(stats.deals_by_stage) ? stats.deals_by_stage : [];
    var total = rows.reduce(function (s, r) { return s + Number(r.count || 0); }, 0);
    if (!total) { C.setState(card, 'empty'); return; }
    C.setState(card, 'ready');
    var max = Math.max.apply(null, rows.map(function (r) { return Number(r.count || 0); }));
    window.CharmCharts.donut(byId('dash-deal-stage-chart'), {
      centerLabel: total === 1 ? 'Deal' : 'Deals',
      ariaLabel: 'Deal pipeline: ' + total + ' deals',
      segments: rows.map(function (r) { return { label: r.label || r.key, value: Number(r.count || 0), color: STAGE_COLORS[r.key] || '#a8a29e' }; })
    });
    var totals = stats.totals || {};
    byId('dash-deal-totals').innerHTML = [['Open', totals.open], ['Won', totals.won], ['Interests', totals.interests]].map(function (t) {
      return '<div class="dash-total"><div class="dash-total__value">' + C.fmt.number(t[1]) + '</div><div class="dash-total__label">' + t[0] + '</div></div>';
    }).join('');
    byId('dash-stage-legend').innerHTML = rows.map(function (r) {
      var count = Number(r.count || 0);
      var color = STAGE_COLORS[r.key] || '#a8a29e';
      var pct = max ? Math.round((count / max) * 100) : 0;
      return '<li class="dash-legend__item' + (count ? '' : ' is-zero') + '">' +
        '<span class="dash-legend__swatch" style="background:' + color + '"></span>' +
        '<span class="dash-legend__label">' + esc(r.label || r.key) + '</span>' +
        '<span class="dash-legend__bar"><i style="width:' + pct + '%;background:' + color + '"></i></span>' +
        '<span class="dash-legend__count">' + count + '</span></li>';
    }).join('');
  }

  function parseDay(iso) {
    var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(iso || ''));
    return m ? new Date(Date.UTC(+m[1], +m[2] - 1, +m[3])) : null;
  }
  function dayLabel(iso, long) {
    var d = parseDay(iso);
    if (!d) return String(iso || '');
    return d.toLocaleDateString(undefined, long ? { weekday: 'short', day: 'numeric', month: 'short', timeZone: 'UTC' } : { day: 'numeric', month: 'short', timeZone: 'UTC' });
  }

  var lastInterestRows = null;
  function renderInterests(stats) {
    var card = chartCard('interests');
    var rows = Array.isArray(stats.interests_per_day) ? stats.interests_per_day : [];
    var total = rows.reduce(function (s, r) { return s + Number(r.count || 0); }, 0);
    var windowDays = (stats.window && stats.window.days) || rows.length || days;
    byId('dash-interests-subtitle').textContent = C.fmt.plural(total, 'interest') + ' in the last ' + windowDays + ' days';
    lastInterestRows = rows;
    if (!total) { C.setState(card, 'empty'); return; }
    C.setState(card, 'ready');
    drawInterests();
  }

  function drawInterests() {
    if (!lastInterestRows) return;
    var rows = lastInterestRows;
    window.CharmCharts.bars(byId('dash-interests-chart'), {
      labels: rows.map(function (r) { return r.date; }),
      values: rows.map(function (r) { return Number(r.count || 0); }),
      formatLabel: function (d) { return dayLabel(d); },
      ariaLabel: 'Interests per day',
      tooltip: function (i, v) {
        return '<span class="ui-chart-tip__dot" style="background:var(--ui-brand)"></span><strong>' + v + '</strong><span>' + (v === 1 ? 'interest' : 'interests') + ' · ' + esc(dayLabel(rows[i].date, true)) + '</span>';
      }
    });
  }

  function loadStats(kinds) {
    var targets = kinds || ['stages', 'interests'];
    targets.forEach(function (k) {
      var card = chartCard(k);
      // Keep a rendered chart visible while switching windows; just show the refresh bar.
      if (card.getAttribute('data-state') === 'ready') card.classList.add('is-refreshing');
      else C.setState(card, 'loading');
    });
    return statsRun(api.get('/api/crm/dashboard-stats?days=' + days, { ttl: 20000, swr: true, persist: true })).then(function (stats) {
      targets.forEach(function (k) {
        chartCard(k).classList.remove('is-refreshing');
        try {
          if (k === 'stages') renderStages(stats || {});
          else renderInterests(stats || {});
        } catch (e) {
          C.setState(chartCard(k), 'error');
        }
      });
    }, function () {
      targets.forEach(function (k) {
        chartCard(k).classList.remove('is-refreshing');
        C.setState(chartCard(k), 'error');
      });
    });
  }

  function bindCharts() {
    var group = byId('dash-interests-window');
    group.addEventListener('click', function (e) {
      var btn = e.target.closest('[data-days]');
      if (!btn) return;
      var next = Number(btn.getAttribute('data-days')) || DAYS_DEFAULT;
      if (next === days) return;
      days = next;
      group.querySelectorAll('[data-days]').forEach(function (b) { b.setAttribute('aria-pressed', b === btn ? 'true' : 'false'); });
      loadStats(['interests']);
    });
    document.querySelectorAll('[data-dash-chart] [data-retry]').forEach(function (btn) {
      btn.addEventListener('click', function () { loadStats(); });
    });
    var retryClients = document.querySelector('#dash-clients-error [data-retry]');
    if (retryClients) retryClients.addEventListener('click', function () { loadClients(true); });
    var host = byId('dash-interests-chart');
    if (window.ResizeObserver && host) {
      var width = 0;
      new ResizeObserver(C.debounce(function () {
        var w = host.clientWidth;
        if (Math.abs(w - width) > 24) { width = w; drawInterests(); }
      }, 140)).observe(host);
    }
  }

  // ── Plot search (client admins) ────────────────────────────────────────
  function plotHref(q) { return '/crm?plot_q=' + encodeURIComponent(q) + '#plots'; }

  function bindPlotSearch() {
    var input = byId('navbar-client-search');
    var pop = byId('navbar-plot-search-dropdown');
    var list = byId('navbar-plot-search-list');
    var empty = byId('navbar-plot-search-empty');
    if (!input || input._bound) return;
    input._bound = true;
    var run = C.latest();
    var active = -1;

    function items() { return Array.prototype.slice.call(list.querySelectorAll('[data-href]')); }
    function hide() { pop.hidden = true; input.setAttribute('aria-expanded', 'false'); active = -1; }
    function show() { pop.hidden = false; input.setAttribute('aria-expanded', 'true'); }
    function highlight(i) {
      var all = items();
      active = all.length ? (i + all.length) % all.length : -1;
      all.forEach(function (el, idx) { el.classList.toggle('is-active', idx === active); });
      if (all[active]) all[active].scrollIntoView({ block: 'nearest' });
    }
    function statusBadge(status) {
      var s = String(status || '').toLowerCase().replace(/[^a-z]/g, '');
      if (s === 'sold') return '<span class="ui-badge ui-badge--danger">Sold</span>';
      if (s === 'hold' || s === 'onhold' || s === 'pending' || s === 'reserved') return '<span class="ui-badge ui-badge--warning">Hold</span>';
      return '<span class="ui-badge ui-badge--success">Available</span>';
    }

    var search = C.debounce(function () {
      var q = input.value.trim();
      if (q.length < 2) { hide(); return; }
      list.innerHTML = '<div class="ui-search-pop__empty"><span class="ui-spinner ui-spinner--sm"></span></div>';
      empty.hidden = true;
      show();
      run(api.get('/api/crm/plots?q=' + encodeURIComponent(q) + '&limit=8&page=1', { ttl: 30000, quiet: true })).then(function (data) {
        var rows = Array.isArray(data) ? data : (data && Array.isArray(data.items) ? data.items : []);
        empty.textContent = 'No plots match “' + q + '”';
        empty.hidden = rows.length > 0;
        list.innerHTML = rows.map(function (p) {
          var sub = [p.workspace_name, p.panorama_name, p.area].filter(Boolean).map(esc).join(' · ');
          return '<button type="button" class="ui-search-pop__item" role="option" data-href="' + esc(plotHref(p.name || q)) + '">' +
            '<span class="ui-row ui-row--between"><span class="ui-search-pop__title">' + esc(p.name || 'Unnamed plot') + '</span>' + statusBadge(p.status) + '</span>' +
            (sub ? '<span class="ui-search-pop__sub">' + sub + '</span>' : '') + '</button>';
        }).join('') + (rows.length ? '<a class="ui-search-pop__all" data-href="' + esc(plotHref(q)) + '" href="' + esc(plotHref(q)) + '">See all results in CRM →</a>' : '');
        active = -1;
        show();
      }, function (err) {
        list.innerHTML = '';
        empty.textContent = (err && err.message) || 'Search failed — try again';
        empty.hidden = false;
        show();
      });
    }, 220);

    input.addEventListener('input', search);
    input.addEventListener('focus', function () { if (input.value.trim().length >= 2) search(); });
    input.addEventListener('keydown', function (e) {
      if (e.key === 'ArrowDown') { e.preventDefault(); if (pop.hidden) search(); else highlight(active + 1); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); highlight(active - 1); }
      else if (e.key === 'Enter') {
        e.preventDefault();
        var target = items()[active];
        var q = input.value.trim();
        if (target) window.location.href = target.getAttribute('data-href');
        else if (q) window.location.href = plotHref(q);
      } else if (e.key === 'Escape') { hide(); input.blur(); }
    });
    pop.addEventListener('mousedown', function (e) {
      var item = e.target.closest('[data-href]');
      if (item) { e.preventDefault(); window.location.href = item.getAttribute('data-href'); }
    });
    document.addEventListener('mousedown', function (e) {
      if (!byId('dashboard-search-wrap').contains(e.target)) hide();
    });
  }

  bindCharts();
  loadClients(false);
  loadStats();
})();
