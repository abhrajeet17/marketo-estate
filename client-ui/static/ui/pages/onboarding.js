/**
 * Onboarding for users without a client group: join an existing group (request -> Client Admin
 * approval) or create one. While a request is pending this is the only screen the user sees.
 */
(function () {
  'use strict';

  var C = window.Charm;
  var STATE_URL = '/api/onboarding/state';
  var POLL_MS = 15000;
  var ROLE_LABELS = { client_user: 'Sales Agent', broker: 'Broker' };

  var region = document.getElementById('ob-region');
  var groupsEl = document.getElementById('ob-groups');
  var search = document.getElementById('ob-group-search');
  var joinForm = document.getElementById('ob-join-form');
  var sendBtn = document.getElementById('ob-send');
  var selectedEl = document.getElementById('ob-selected');
  var createForm = document.getElementById('ob-create-form');
  var createError = document.getElementById('ob-create-error');

  var groups = null;
  var builders = null;
  var selectedId = '';
  var pollTimer = 0;

  function show(view) {
    C.setState(region, view);
    clearTimeout(pollTimer);
    if (view === 'pending') pollTimer = setTimeout(function () { load(true); }, POLL_MS);
  }

  function enterPortal() {
    try { sessionStorage.removeItem('portal_identity_v1'); } catch (e) { /* ignore */ }
    window.location.replace('/customer-dashboard');
  }

  // ── State ──────────────────────────────────────────────────────────────
  function renderPending(req) {
    document.getElementById('ob-pending-group').textContent = req.client_name || 'the client group';
    document.getElementById('ob-pending-role').textContent = ROLE_LABELS[req.member_role] || 'Sales Agent';
    document.getElementById('ob-pending-sent').textContent = C.fmt.relative(req.created_at);
    var msg = document.getElementById('ob-pending-message');
    msg.textContent = req.message ? '“' + req.message + '”' : '';
    msg.hidden = !req.message;
    show('pending');
  }

  function renderDecision(decision) {
    var el = document.getElementById('ob-decision');
    var declined = decision && decision.status === 'rejected';
    el.hidden = !declined;
    if (declined) el.textContent = 'Your request to join ' + (decision.client_name || 'the client group') + ' was declined. You can ask another group or create your own.';
  }

  function load(force) {
    return C.api.get(STATE_URL, { force: true, quiet: !!force }).then(function (state) {
      if (state.has_client_group) { enterPortal(); return; }
      if (state.pending_request) { renderPending(state.pending_request); return; }
      renderDecision(state.last_decision);
      // Coming back from a decided request (polling): return to the start.
      if (force || region.getAttribute('data-state') === 'loading') show('choose');
    }).catch(function () {
      if (region.getAttribute('data-state') === 'pending') { pollTimer = setTimeout(function () { load(true); }, POLL_MS); return; }
      show('error');
    });
  }

  // ── Join ───────────────────────────────────────────────────────────────
  function groupHtml(g) {
    var meta = [g.organization_name, C.fmt.plural(g.member_count, 'member')].filter(Boolean).join(' · ');
    return '<button type="button" class="ob-group' + (g.id === selectedId ? ' is-selected' : '') + '" role="radio" aria-checked="' + (g.id === selectedId) + '"' +
      ' data-id="' + C.esc(g.id) + '"' + (g.is_full ? ' disabled title="This group has no free seats"' : '') + '>' +
      '<span class="ui-avatar">' + C.esc(C.fmt.initials(g.name)) + '</span>' +
      '<span class="ob-group__meta"><span class="ob-group__name ui-truncate">' + C.esc(g.name) + '</span>' +
      '<span class="ob-group__sub ui-truncate">' + C.esc(meta) + '</span></span>' +
      (g.is_full ? '<span class="ui-badge ui-badge--outline">Full</span>' : '<span class="ob-group__check" aria-hidden="true"></span>') +
      '</button>';
  }

  function renderGroups() {
    var q = search.value.trim().toLowerCase();
    var list = (groups || []).filter(function (g) {
      return !q || g.name.toLowerCase().indexOf(q) !== -1 || g.organization_name.toLowerCase().indexOf(q) !== -1;
    });
    if (!groups.length) {
      groupsEl.innerHTML = '<div class="ob-empty">No client groups yet. <button type="button" class="ui-btn ui-btn--sm" data-go="create">Create the first one</button></div>';
    } else if (!list.length) {
      groupsEl.innerHTML = '<div class="ob-empty">No group matches “' + C.esc(search.value.trim()) + '”. Can\'t find yours? <button type="button" class="ui-btn ui-btn--sm" data-go="create">Create a group</button></div>';
    } else {
      groupsEl.innerHTML = list.map(groupHtml).join('');
    }
    var selected = (groups || []).filter(function (g) { return g.id === selectedId; })[0];
    selectedEl.textContent = selected ? 'Joining ' + selected.name : 'Select a client group above';
    sendBtn.disabled = !selected;
  }

  function openJoin() {
    show('join');
    if (groups) { renderGroups(); search.focus(); return; }
    groupsEl.innerHTML = '<span class="ui-skel" style="height:54px"></span><span class="ui-skel" style="height:54px"></span><span class="ui-skel" style="height:54px"></span>';
    C.api.get('/api/onboarding/client-groups', { force: true }).then(function (data) {
      groups = Array.isArray(data) ? data : [];
      renderGroups();
      search.focus();
    }).catch(function (err) {
      groupsEl.innerHTML = '<div class="ui-alert ui-alert--danger">' + C.esc((err && err.message) || 'Could not load client groups') + '</div>';
    });
  }

  groupsEl.addEventListener('click', function (e) {
    var btn = e.target.closest('.ob-group');
    if (!btn || btn.disabled) return;
    selectedId = btn.getAttribute('data-id');
    renderGroups();
  });
  search.addEventListener('input', C.debounce(renderGroups, 120));

  joinForm.addEventListener('submit', function (e) {
    e.preventDefault();
    if (!selectedId) return;
    var body = {
      client_id: selectedId,
      member_role: joinForm.elements.member_role.value,
      message: joinForm.elements.message.value.trim()
    };
    C.action(sendBtn, function () { return C.api.post('/api/onboarding/join-requests', body); }, { success: 'Join request sent' })
      .then(function (res) { renderPending(res.request); })
      .catch(function () {});
  });

  // ── Create ─────────────────────────────────────────────────────────────
  function openCreate() {
    show('create');
    createError.hidden = true;
    var field = document.getElementById('ob-builder-field');
    var select = document.getElementById('ob-builder');
    var ready = builders ? Promise.resolve(builders) : C.api.get('/api/onboarding/organizations', { force: true }).then(function (data) {
      builders = Array.isArray(data) ? data : [];
      return builders;
    });
    ready.then(function (list) {
      select.innerHTML = (list.length > 1 ? '<option value="">Select a builder…</option>' : '') +
        list.map(function (b) { return '<option value="' + C.esc(b.id) + '">' + C.esc(b.name) + '</option>'; }).join('');
      // A single builder needs no choice.
      field.hidden = list.length <= 1;
      document.getElementById('ob-name').focus();
    }).catch(function () { field.hidden = false; });
  }

  createForm.addEventListener('submit', function (e) {
    e.preventDefault();
    createError.hidden = true;
    var body = {
      name: createForm.elements.name.value.trim(),
      org_id: createForm.elements.org_id.value,
      description: createForm.elements.description.value.trim()
    };
    if (!body.name) { createForm.elements.name.focus(); return; }
    if (!body.org_id) { createError.textContent = 'Choose the builder this group works with.'; createError.hidden = false; return; }
    C.action(document.getElementById('ob-create'), function () { return C.api.post('/api/onboarding/client-groups', body); }, {
      success: 'Client group created',
      onError: function (err) { createError.textContent = (err && err.message) || 'Could not create the group'; createError.hidden = false; }
    }).then(enterPortal).catch(function () {});
  });

  // ── Pending ────────────────────────────────────────────────────────────
  document.getElementById('ob-refresh').addEventListener('click', function () {
    var btn = this;
    C.action(btn, function () { return load(true); }).catch(function () {});
  });
  document.getElementById('ob-withdraw').addEventListener('click', function () {
    var btn = this;
    C.confirm({ title: 'Withdraw your request?', text: 'You can send a new request to any group afterwards.', confirmLabel: 'Withdraw', tone: 'danger', icon: 'x' }).then(function (ok) {
      if (!ok) return;
      C.action(btn, function () { return C.api.del('/api/onboarding/join-requests/mine'); }, { success: 'Request withdrawn' })
        .then(function () { groups = null; selectedId = ''; show('choose'); })
        .catch(function () {});
    });
  });

  // ── Navigation between steps ───────────────────────────────────────────
  region.addEventListener('click', function (e) {
    var go = e.target.closest('[data-go]');
    if (!go) return;
    var view = go.getAttribute('data-go');
    if (view === 'join') openJoin();
    else if (view === 'create') openCreate();
    else show(view);
  });

  var retry = region.querySelector('[data-retry]');
  if (retry) retry.addEventListener('click', function () { show('loading'); load(false); });

  // Re-check as soon as the user comes back to the tab.
  document.addEventListener('visibilitychange', function () {
    if (!document.hidden && region.getAttribute('data-state') === 'pending') load(true);
  });

  window.Portal.ready.then(function () { load(false); });
})();
