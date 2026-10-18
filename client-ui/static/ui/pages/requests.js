/** Join requests (Client Admin): approve or decline people asking to join the client group. */
(function () {
  'use strict';

  var C = window.Charm;
  var ROLE_LABELS = { client_user: 'Sales Agent', broker: 'Broker' };
  var STATUS_BADGES = {
    approved: '<span class="ui-badge ui-badge--success">Approved</span>',
    rejected: '<span class="ui-badge ui-badge--danger">Declined</span>',
    cancelled: '<span class="ui-badge ui-badge--outline">Withdrawn</span>'
  };

  var region = document.getElementById('rq-region');
  var list = document.getElementById('rq-list');
  var countEl = document.getElementById('rq-pending-count');
  var tabs = Array.prototype.slice.call(document.querySelectorAll('[data-status]'));
  var status = 'pending';
  var rows = [];
  var run = C.latest();

  function url() { return '/api/join-requests?status=' + status; }

  function cardHtml(r) {
    var name = r.display_name || r.email || 'New user';
    var pending = r.status === 'pending';
    var roleOptions = Object.keys(ROLE_LABELS).map(function (k) {
      return '<option value="' + k + '"' + (k === r.member_role ? ' selected' : '') + '>' + ROLE_LABELS[k] + '</option>';
    }).join('');
    return '<article class="ui-card rq-card" data-id="' + C.esc(r.id) + '">' +
      '<div class="ui-person rq-card__who"><span class="ui-avatar">' + C.esc(C.fmt.initials(name)) + '</span>' +
        '<div class="ui-grow"><div class="ui-person__name ui-truncate">' + C.esc(name) + '</div>' +
        '<div class="ui-person__sub ui-truncate">' + C.esc(r.email && r.email !== name ? r.email : '') + '</div></div></div>' +
      '<div class="rq-card__what">' +
        '<div>Wants to join <strong>' + C.esc(r.client_name) + '</strong> as <strong>' + C.esc(ROLE_LABELS[r.member_role] || r.member_role) + '</strong></div>' +
        (r.message ? '<p class="rq-card__msg">“' + C.esc(r.message) + '”</p>' : '') +
        '<div class="rq-card__time">' + C.esc(C.fmt.relative(r.created_at)) + '</div>' +
      '</div>' +
      (pending
        ? '<div class="rq-card__actions">' +
            '<select class="ui-select ui-select--sm" aria-label="Join as" data-role>' + roleOptions + '</select>' +
            '<button type="button" class="ui-btn ui-btn--sm" data-act="reject">Decline</button>' +
            '<button type="button" class="ui-btn ui-btn--sm ui-btn--primary" data-act="approve">Approve</button>' +
          '</div>'
        : '<div class="rq-card__actions">' + (STATUS_BADGES[r.status] || '') + '</div>') +
      '</article>';
  }

  function render() {
    if (!rows.length) {
      C.setState(region, 'empty');
      region.querySelector('.ui-empty__title').textContent = status === 'pending' ? 'No pending requests' : 'No requests yet';
      return;
    }
    list.innerHTML = rows.map(cardHtml).join('');
    C.setState(region, 'ready');
  }

  function setCount(n) { countEl.textContent = n ? String(n) : ''; }

  function load(force) {
    C.setState(region, 'loading');
    return run(C.api.get(url(), { force: !!force })).then(function (data) {
      rows = Array.isArray(data) ? data : [];
      if (status === 'pending') setCount(rows.length);
      render();
    }).catch(function () { C.setState(region, 'error'); });
  }

  function removeCard(card, id) {
    card.classList.add('is-leaving');
    setTimeout(function () {
      rows = rows.filter(function (r) { return String(r.id) !== String(id); });
      setCount(rows.length);
      render();
    }, 200);
    C.api.invalidate(['/api/join-requests', '/api/clients']);
  }

  list.addEventListener('click', function (e) {
    var btn = e.target.closest('[data-act]');
    if (!btn) return;
    var card = btn.closest('.rq-card');
    var id = card.getAttribute('data-id');
    var req = rows.filter(function (r) { return String(r.id) === String(id); })[0];
    if (!req) return;
    var who = req.display_name || req.email || 'this person';
    if (btn.getAttribute('data-act') === 'approve') {
      var role = card.querySelector('[data-role]').value;
      C.action(btn, function () {
        return C.api.post('/api/join-requests/' + encodeURIComponent(id) + '/approve', { member_role: role });
      }, { success: who + ' joined ' + req.client_name + ' as ' + ROLE_LABELS[role] }).then(function () { removeCard(card, id); }).catch(function () {});
    } else {
      C.confirm({ title: 'Decline ' + who + '?', text: 'They can send a new request later.', confirmLabel: 'Decline', tone: 'danger', icon: 'x' }).then(function (ok) {
        if (!ok) return;
        C.action(btn, function () {
          return C.api.post('/api/join-requests/' + encodeURIComponent(id) + '/reject', {});
        }, { success: 'Request declined' }).then(function () { removeCard(card, id); }).catch(function () {});
      });
    }
  });

  tabs.forEach(function (tab) {
    tab.addEventListener('click', function () {
      if (tab.getAttribute('data-status') === status) return;
      status = tab.getAttribute('data-status');
      tabs.forEach(function (t) {
        var on = t === tab;
        t.classList.toggle('is-active', on);
        t.setAttribute('aria-selected', on ? 'true' : 'false');
      });
      load(true);
    });
  });

  var retry = region.querySelector('[data-retry]');
  if (retry) retry.addEventListener('click', function () { load(true); });

  window.Portal.ready.then(function () { load(false); });
})();
