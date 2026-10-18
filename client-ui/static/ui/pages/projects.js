/**
 * Projects — the client team's panoramas (client admins, sales agents, brokers).
 *
 * One request (GET /api/dashboard) returns visible panoramas and their projects.
 * Client access opens the plot editor; broker / viewer access opens the customer view.
 */
(function () {
  'use strict';

  var C = window.Charm;
  var URL = '/api/dashboard';
  var region = document.getElementById('proj-region');
  var list = document.getElementById('proj-list');
  var search = document.getElementById('proj-search');
  var filter = document.getElementById('proj-filter');
  var data = { panoramas: [], projects: [] };
  var identity = {};

  var OPEN = {
    owner: { mode: 'admin', label: 'Open editor', tone: 'brand' },
    client: { mode: 'client', label: 'Edit plots', tone: 'brand' },
    broker: { mode: 'customer', label: 'Customer view', tone: 'violet' },
    viewer: { mode: 'customer', label: 'View', tone: 'info' }
  };
  var ACCESS_LABEL = { owner: 'Owner', client: 'Client team', broker: 'Broker', viewer: 'View only', admin: 'Admin' };

  function access(p) { return OPEN[p.access_type] ? p.access_type : 'viewer'; }
  function thumb(p) { return '/uploads/' + encodeURIComponent(p.filename || '') + '?size=thumb'; }
  function byRecent(a, b) { return (Date.parse(b.updated_at) || 0) - (Date.parse(a.updated_at) || 0); }

  function groups() {
    var q = search.value.trim().toLowerCase();
    var only = filter.value;
    var byProject = {};
    data.projects.forEach(function (p) { byProject[p.id] = { project: p, items: [] }; });
    var loose = { project: { id: '', name: 'Other panoramas' }, items: [] };
    data.panoramas.slice().sort(byRecent).forEach(function (p) {
      var g = (p.workspace_id && byProject[p.workspace_id]) || loose;
      if (only && g.project.id !== only) return;
      if (q && (p.name || '').toLowerCase().indexOf(q) === -1 && g.project.name.toLowerCase().indexOf(q) === -1) return;
      g.items.push(p);
    });
    return Object.keys(byProject).map(function (k) { return byProject[k]; })
      .concat([loose])
      .filter(function (g) { return g.items.length; });
  }

  function card(p) {
    var a = OPEN[access(p)];
    var plots = Number(p.plot_count || 0);
    return '<article class="ui-card proj-card">' +
      '<img class="proj-card__thumb" src="' + C.esc(thumb(p)) + '" alt="" loading="lazy" decoding="async" onload="this.classList.add(\'is-loaded\')">' +
      '<div class="proj-card__body">' +
        '<div class="proj-card__name ui-truncate" title="' + C.esc(p.name || 'Untitled') + '">' + C.esc(p.name || 'Untitled') + '</div>' +
        '<div class="proj-card__meta">' +
          '<span class="ui-badge ui-badge--outline">' + C.esc(C.fmt.plural(plots, 'plot')) + '</span>' +
          '<span class="ui-badge ui-badge--outline">' + (p.is_360 ? '360°' : 'Flat') + '</span>' +
          '<span class="ui-badge ui-badge--' + a.tone + '">' + C.esc(ACCESS_LABEL[access(p)]) + '</span>' +
        '</div>' +
        '<div class="proj-card__actions"><button type="button" class="ui-btn ui-btn--sm' + (a.mode === 'customer' ? '' : ' ui-btn--primary') + '" data-open="' + C.esc(p.id) + '">' + C.esc(a.label) + '</button></div>' +
      '</div></article>';
  }

  function canShare(g) {
    var p = g.project;
    return p.id && p.main_panorama_id && (p.access_type === 'client' || p.access_type === 'broker');
  }

  function render() {
    var gs = groups();
    if (!data.panoramas.length) { C.setState(region, 'empty'); return; }
    if (!gs.length) {
      list.innerHTML = '<div class="ui-empty"><div class="ui-empty__title">No matches</div><p class="ui-empty__text">Try a different search or project.</p></div>';
      C.setState(region, 'ready');
      return;
    }
    list.innerHTML = gs.map(function (g) {
      return '<section class="proj-section">' +
        '<div class="proj-section__head"><h2 class="proj-section__title">' + C.esc(g.project.name) +
          '<span class="proj-section__meta">' + C.esc(C.fmt.plural(g.items.length, 'panorama')) + '</span></h2>' +
          (canShare(g) ? '<button type="button" class="ui-btn ui-btn--sm" data-share="' + C.esc(g.project.id) + '">Copy share link</button>' : '') +
        '</div>' +
        '<div class="proj-grid">' + g.items.map(card).join('') + '</div></section>';
    }).join('');
    C.setState(region, 'ready');
  }

  function renderFilter() {
    var current = filter.value;
    filter.innerHTML = '<option value="">All projects</option>' + data.projects.map(function (p) {
      return '<option value="' + C.esc(p.id) + '">' + C.esc(p.name) + '</option>';
    }).join('');
    filter.value = data.projects.some(function (p) { return p.id === current; }) ? current : '';
  }

  function apply(next) {
    data = { panoramas: (next && next.panoramas) || [], projects: (next && next.projects) || [] };
    renderFilter();
    render();
  }

  function load(force) {
    if (!data.panoramas.length) C.setState(region, 'loading');
    return C.api.get(URL, { ttl: 15000, swr: !force, force: !!force, persist: true, onUpdate: apply })
      .then(apply)
      .catch(function () { if (!data.panoramas.length) C.setState(region, 'error'); });
  }

  function open(btn, id) {
    var p = data.panoramas.filter(function (x) { return String(x.id) === String(id); })[0];
    if (!p) return;
    var mode = OPEN[access(p)].mode;
    var path = '/' + mode + '/' + (p.is_360 ? '3d/' : '') + encodeURIComponent(p.id);
    if (mode === 'customer') { window.location.href = path; return; }
    C.action(btn, function () {
      return C.api.post('/api/panoramas/' + encodeURIComponent(p.id) + '/page-token', { mode: mode }).then(function (res) {
        if (!res || !res.token) throw new Error('Access denied');
        window.location.href = path + '?pt=' + encodeURIComponent(res.token);
        return new Promise(function () {}); // keep the button busy while the editor loads
      });
    }).catch(function () {});
  }

  function share(btn, projectId) {
    C.action(btn, function () {
      return C.api.get('/api/workspaces/' + encodeURIComponent(projectId) + '/share-endpoint', { force: true }).then(function (res) {
        var s = (res && res.share) || {};
        var base = s.effective_url || s.default_url;
        if (!base) throw new Error('Share link is not available for this project yet');
        var link = new window.URL(base, window.location.origin);
        if (identity.user_id) link.searchParams.set('ref_user_id', identity.user_id);
        return C.copy(link.toString(), 'Share link');
      });
    }).catch(function () {});
  }

  list.addEventListener('click', function (e) {
    var openBtn = e.target.closest('[data-open]');
    if (openBtn) { open(openBtn, openBtn.getAttribute('data-open')); return; }
    var shareBtn = e.target.closest('[data-share]');
    if (shareBtn) share(shareBtn, shareBtn.getAttribute('data-share'));
  });
  search.addEventListener('input', C.debounce(render, 120));
  filter.addEventListener('change', render);
  region.addEventListener('click', function (e) { if (e.target.closest('[data-retry]')) load(true); });
  // Returning via the back button restores this page from the bfcache: release busy buttons.
  window.addEventListener('pageshow', function (e) {
    if (e.persisted) list.querySelectorAll('[data-open][data-busy]').forEach(function (b) { C.busy(b, false); });
  });

  window.Portal.ready.then(function (ctx) { identity = (ctx && ctx.identity) || {}; });
  load(false);
})();
