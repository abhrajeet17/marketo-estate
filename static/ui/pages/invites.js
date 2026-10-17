/** Broker invites: accept / reject client team invitations. */
(function () {
  'use strict';

  var C = window.Charm;
  var URL = '/api/client-team-invites/mine';
  var region = document.getElementById('invites-region');
  var list = document.getElementById('crm-invite-list');
  var invites = [];

  function render() {
    if (!invites.length) { C.setState(region, 'empty'); return; }
    list.innerHTML = invites.map(function (inv) {
      var client = inv.client_name || 'Client team';
      var expires = inv.expires_at ? 'Expires ' + C.fmt.date(inv.expires_at) : 'No expiry';
      return '<article class="ui-card invite-card" data-invite-id="' + C.esc(inv.id) + '">' +
        '<div class="ui-person"><span class="ui-avatar ui-avatar--lg">' + C.esc(C.fmt.initials(client)) + '</span>' +
          '<div class="ui-grow"><div class="invite-card__title ui-truncate">' + C.esc(client) + '</div>' +
          '<div class="ui-person__sub">' + C.esc(inv.inviter_name ? 'Invited by ' + inv.inviter_name : 'Pending invitation') + '</div></div></div>' +
        '<div class="invite-card__meta"><span class="ui-badge ui-badge--violet">Broker</span>' +
          '<span class="ui-badge ui-badge--outline">' + C.esc(C.fmt.relative(inv.created_at)) + '</span>' +
          '<span class="ui-badge ui-badge--outline">' + C.esc(expires) + '</span></div>' +
        '<div class="invite-card__actions">' +
          '<button type="button" class="ui-btn" data-act="reject">Decline</button>' +
          '<button type="button" class="ui-btn ui-btn--primary" data-act="accept">Accept invite</button>' +
        '</div></article>';
    }).join('');
    C.setState(region, 'ready');
  }

  function load(force) {
    if (!invites.length) C.setState(region, 'loading');
    return C.api.get(URL, { ttl: 10000, swr: !force, force: !!force, onUpdate: function (d) { invites = d || []; render(); } })
      .then(function (data) { invites = Array.isArray(data) ? data : []; render(); })
      .catch(function () { if (!invites.length) C.setState(region, 'error'); });
  }

  function settle(card, btn, request, message) {
    C.action(btn, function () { return request; }, { success: message }).then(function () {
      card.classList.add('is-leaving');
      var id = card.getAttribute('data-invite-id');
      setTimeout(function () {
        invites = invites.filter(function (i) { return String(i.id) !== String(id); });
        render();
      }, 220);
      C.api.invalidate([URL, '/api/crm', '/api/portal']);
    }).catch(function () {});
  }

  list.addEventListener('click', function (e) {
    var btn = e.target.closest('[data-act]');
    if (!btn) return;
    var card = btn.closest('.invite-card');
    var id = card.getAttribute('data-invite-id');
    var inv = invites.filter(function (i) { return String(i.id) === String(id); })[0];
    if (!inv) return;
    if (btn.getAttribute('data-act') === 'accept') {
      settle(card, btn, C.api.post('/api/client-team-invites/accept', { invite_token: inv.invite_token }), 'Joined ' + (inv.client_name || 'the team'));
      try { sessionStorage.removeItem('portal_identity_v1'); } catch (err) { /* ignore */ }
    } else {
      C.confirm({ title: 'Decline this invite?', text: 'The client can invite you again later.', confirmLabel: 'Decline', tone: 'danger', icon: 'x' }).then(function (ok) {
        if (ok) settle(card, btn, C.api.post('/api/client-team-invites/' + encodeURIComponent(id) + '/reject', {}), 'Invite declined');
      });
    }
  });

  var retry = region.querySelector('[data-retry]');
  if (retry) retry.addEventListener('click', function () { load(true); });

  load(false);
})();
