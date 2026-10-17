/**
 * User management (platform admins).
 *
 *   Users          GET /api/admin/org-users · invite · edit details / password / role · delete
 *   Invites        GET /api/admin/invites (loaded the first time the tab opens)
 *   Client groups  /api/clients CRUD · members · invites · project access
 *
 * Every region has an explicit state (loading/ready/empty/error); responses for
 * a client group that is no longer selected are dropped (C.latest guards).
 */
(function () {
  'use strict';

  var C = window.Charm;
  var api = C.api;
  var esc = C.esc;

  var PLATFORM_ROLE = { superadmin: 'Super admin', admin: 'Admin', user: 'User', broker: 'Broker' };
  var PLATFORM_TONE = { superadmin: 'violet', admin: 'brand', user: 'info', broker: 'success' };
  var MEMBER_ROLE = { client_admin: 'Client admin', client_user: 'Sales agent', broker: 'Broker' };
  var MEMBER_TONE = { client_admin: 'brand', client_user: 'info', broker: 'violet' };
  var INVITE_TONE = { accepted: 'success', pending: 'warning', expired: 'outline', revoked: 'danger' };

  var state = {
    me: { role: '', userId: '' },
    users: [],
    usersLoaded: false,
    invitesLoaded: false,
    userFilter: { q: '', role: '' },
    edit: null,                    // user being edited
    clients: [],
    clientsLoaded: false,
    clientQuery: '',
    selectedId: null,
    members: [],
    accessTarget: '',
    grantPool: null,               // { workspaces, panoramas } granted to the group
    allResources: null,            // { workspaces, panoramas } across the org (admins)
    grantType: 'workspace'
  };

  var membersRun = C.latest();
  var accessRun = C.latest();

  function byId(id) { return document.getElementById(id); }
  function setAlert(id, text) { var el = byId(id); if (el) el.textContent = text || ''; }
  function isSuper() { return state.me.role === 'superadmin'; }
  function roleKey(r) { return String(r || '').trim().toLowerCase(); }
  function memberRoleChoices() {
    // Platform admins assign client admins and brokers; sales agents are
    // managed by each client's own admin team (from My team).
    return ['client_admin', 'broker'];
  }

  // ── Tabs ───────────────────────────────────────────────────────────────
  var tabs = byId('um-tabs');
  C.tabs.watch(tabs);
  function activateTab(name) {
    tabs.querySelectorAll('.ui-tab').forEach(function (t) { t.classList.toggle('active', t.getAttribute('data-tab') === name); t.setAttribute('aria-selected', t.getAttribute('data-tab') === name ? 'true' : 'false'); });
    document.querySelectorAll('.tab-panel').forEach(function (p) { p.classList.toggle('active', p.id === 'tab-' + name); });
    if (name === 'invites' && !state.invitesLoaded) loadInvites();
    if (name === 'clients' && !state.clientsLoaded) loadClients();
    if (window.history.replaceState) window.history.replaceState(null, '', name === 'users' ? window.location.pathname : '#' + name);
  }
  tabs.addEventListener('click', function (e) {
    var t = e.target.closest('.ui-tab');
    if (t) activateTab(t.getAttribute('data-tab'));
  });

  // ── Users ──────────────────────────────────────────────────────────────
  var SVG_EDIT = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>';
  var SVG_TRASH = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6"/></svg>';

  function roleBadge(role, map, tones) {
    var r = roleKey(role);
    return '<span class="ui-badge ui-badge--' + (tones[r] || 'outline') + '">' + esc(map[r] || r || '—') + '</span>';
  }

  function renderUsers() {
    var region = byId('users-region');
    var f = state.userFilter;
    var q = f.q.toLowerCase();
    var rows = state.users.filter(function (u) {
      if (!isSuper() && roleKey(u.role) === 'superadmin') return false;
      if (f.role && roleKey(u.role) !== f.role) return false;
      return !q || (String(u.display_name || '') + ' ' + String(u.email || '')).toLowerCase().indexOf(q) !== -1;
    });
    byId('users-meta').textContent = state.usersLoaded ? C.fmt.plural(rows.length, 'user') : '';
    var body = byId('users-body');
    if (!rows.length) {
      body.innerHTML = '';
      C.setState(region, 'empty');
      return;
    }
    body.className = 'ui-rows-enter';
    body.innerHTML = rows.map(function (u) {
      var self = !!u.is_self;
      var canEdit = self || !!u.can_manage;
      return '<tr data-uid="' + esc(u.user_id) + '">' +
        '<td><div class="ui-person"><span class="ui-avatar">' + esc(C.fmt.initials(u.display_name, u.email)) + '</span>' +
          '<div class="ui-grow"><div class="ui-person__name ui-truncate">' + esc(u.display_name || '—') + (self ? ' <span class="ui-badge ui-badge--outline">You</span>' : '') + '</div>' +
          '<div class="ui-person__sub ui-truncate">' + esc(u.email || '—') + '</div></div></div></td>' +
        '<td>' + roleBadge(u.role, PLATFORM_ROLE, PLATFORM_TONE) + '</td>' +
        '<td title="' + esc(C.fmt.dateTime(u.created_at)) + '">' + esc(C.fmt.date(u.created_at)) + '</td>' +
        '<td class="um-col-actions"><div class="ui-table__actions">' +
          (canEdit ? '<button type="button" class="ui-icon-btn" data-edit-user title="' + (self ? 'Edit your profile' : 'Edit user') + '" aria-label="Edit ' + esc(u.display_name || u.email || 'user') + '">' + SVG_EDIT + '</button>'
                   : '<span class="ui-hint" title="Only a super admin can manage other admins">Admin</span>') +
        '</div></td></tr>';
    }).join('');
    C.setState(region, 'ready');
  }

  function loadUsers(force) {
    var region = byId('users-region');
    if (!state.usersLoaded) C.setState(region, 'loading');
    return api.get('/api/admin/org-users', { ttl: 15000, force: !!force, swr: !force, persist: true, onUpdate: function (d) { state.users = d || []; renderUsers(); } })
      .then(function (data) { state.users = Array.isArray(data) ? data : []; state.usersLoaded = true; renderUsers(); })
      .catch(function (err) {
        if (state.usersLoaded) { C.toast(err.message || 'Could not refresh users', 'error'); return; }
        byId('users-body').innerHTML = '';
        C.setState(region, 'error');
        if (err.status === 403) setAlert('um-banner', err.message || 'Admin access required.');
      });
  }
  function reloadUsers() { api.invalidate('/api/admin/org-users'); return loadUsers(true); }

  function findUser(uid) { return state.users.filter(function (u) { return String(u.user_id) === String(uid); })[0] || null; }

  // Invite user
  function openInvite() {
    byId('invite-form').reset();
    setAlert('invite-error', '');
    C.modal.open('modal-invite');
  }
  byId('btn-invite-user').addEventListener('click', openInvite);
  byId('invite-form').addEventListener('submit', function (e) {
    e.preventDefault();
    var name = byId('invite-name').value.trim();
    var email = byId('invite-email').value.trim();
    var role = byId('invite-role').value;
    if (!name) { setAlert('invite-error', 'Display name is required.'); byId('invite-name').focus(); return; }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) { setAlert('invite-error', 'Enter a valid email address.'); byId('invite-email').focus(); return; }
    setAlert('invite-error', '');
    C.action(byId('confirm-invite'), function () {
      return api.post('/api/admin/invite-user', { display_name: name, email: email, role: role });
    }, { success: 'Invitation sent to ' + email, onError: function (err) { setAlert('invite-error', err.message || 'Failed to send invite'); } }).then(function () {
      C.modal.close('modal-invite');
      reloadUsers();
      state.invitesLoaded = false;
      api.invalidate('/api/admin/invites');
    }).catch(function () {});
  });

  // Edit user
  function openEdit(uid) {
    var u = findUser(uid);
    if (!u) return;
    state.edit = u;
    var self = !!u.is_self;
    var role = roleKey(u.role) || 'user';
    ['edit-error', 'pw-error', 'role-error'].forEach(function (id) { setAlert(id, ''); });
    byId('modal-edit-title').textContent = self ? 'Edit your profile' : 'Edit ' + (u.display_name || u.email || 'user');
    byId('modal-edit-subtitle').textContent = self ? 'Update your name and email.' : (u.email || '');
    byId('edit-name').value = u.display_name || '';
    byId('edit-email').value = u.email || '';
    byId('password-form').reset();
    byId('edit-section-password').hidden = self;
    byId('edit-section-delete').hidden = self;
    var canChangeRole = !self && (role !== 'admin' && role !== 'superadmin' || isSuper());
    byId('edit-section-role').hidden = !canChangeRole;
    byId('edit-role-select').value = PLATFORM_ROLE[role] ? role : 'user';
    byId('edit-role-label').textContent = 'Currently ' + (PLATFORM_ROLE[role] || role) + '. Admins manage the whole organisation; brokers share customer links; users work inside their client teams.';
    C.modal.open('modal-edit');
  }
  byId('users-body').addEventListener('click', function (e) {
    var b = e.target.closest('[data-edit-user]');
    if (b) openEdit(b.closest('tr').getAttribute('data-uid'));
  });

  byId('details-form').addEventListener('submit', function (e) {
    e.preventDefault();
    var u = state.edit;
    var name = byId('edit-name').value.trim();
    var email = byId('edit-email').value.trim();
    if (!name) { setAlert('edit-error', 'Display name cannot be empty.'); return; }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) { setAlert('edit-error', 'Enter a valid email address.'); return; }
    setAlert('edit-error', '');
    var url = u.is_self ? '/api/profile/me' : '/api/admin/users/' + encodeURIComponent(u.user_id) + '/details';
    C.action(byId('btn-save-details'), function () {
      return api.put(url, { display_name: name, email: email });
    }, { success: 'Details saved', onError: function (err) { setAlert('edit-error', err.message || 'Failed to save'); } }).then(function () {
      u.display_name = name;
      u.email = email;
      renderUsers();
      reloadUsers();
      if (u.is_self) { try { sessionStorage.removeItem('portal_identity_v1'); } catch (er) { /* ignore */ } }
    }).catch(function () {});
  });

  byId('password-form').addEventListener('submit', function (e) {
    e.preventDefault();
    var pw = byId('edit-pw-new').value;
    var pwc = byId('edit-pw-confirm').value;
    if (!pw || pw.length < 6) { setAlert('pw-error', 'Password must be at least 6 characters.'); return; }
    if (pw !== pwc) { setAlert('pw-error', 'Passwords do not match.'); return; }
    setAlert('pw-error', '');
    C.action(byId('btn-save-password'), function () {
      return api.put('/api/admin/users/' + encodeURIComponent(state.edit.user_id) + '/password', { password: pw });
    }, { success: 'Password updated', onError: function (err) { setAlert('pw-error', err.message || 'Failed to update password'); } })
      .then(function () { byId('password-form').reset(); }).catch(function () {});
  });

  byId('role-form').addEventListener('submit', function (e) {
    e.preventDefault();
    var u = state.edit;
    var next = byId('edit-role-select').value;
    if (next === roleKey(u.role)) { C.toast('Role is already ' + (PLATFORM_ROLE[next] || next), 'info'); return; }
    setAlert('role-error', '');
    C.action(byId('btn-save-role'), function () {
      return api.put('/api/admin/users/' + encodeURIComponent(u.user_id) + '/role', { role: next });
    }, { success: 'Role changed to ' + (PLATFORM_ROLE[next] || next), onError: function (err) { setAlert('role-error', err.message || 'Failed to change role'); } }).then(function () {
      u.role = next;
      renderUsers();
      openEdit(u.user_id);
      reloadUsers();
    }).catch(function () {});
  });

  byId('btn-delete-user').addEventListener('click', function () {
    var u = state.edit;
    var label = u.display_name || u.email || 'this user';
    C.confirm({ title: 'Delete ' + label + '?', text: 'Their account, profile and associated data are removed permanently. This cannot be undone.', confirmLabel: 'Delete permanently', tone: 'danger' }).then(function (ok) {
      if (!ok) return;
      C.action(byId('btn-delete-user'), function () {
        return api.del('/api/admin/users/' + encodeURIComponent(u.user_id));
      }, { success: label + ' deleted' }).then(function () {
        C.modal.close('modal-edit');
        state.users = state.users.filter(function (x) { return x !== u; });
        renderUsers();
        reloadUsers();
      }).catch(function () {});
    });
  });

  var userSearch = byId('user-search');
  userSearch.addEventListener('input', C.debounce(function () { state.userFilter.q = userSearch.value.trim(); renderUsers(); }, 120));
  byId('user-role-filter').addEventListener('change', function (e) { state.userFilter.role = e.target.value; renderUsers(); });

  // ── Invites ────────────────────────────────────────────────────────────
  function loadInvites() {
    var region = byId('invites-region');
    C.setState(region, 'loading');
    return api.get('/api/admin/invites', { ttl: 15000 }).then(function (data) {
      var rows = Array.isArray(data) ? data : [];
      state.invitesLoaded = true;
      var body = byId('invites-body');
      if (!rows.length) { body.innerHTML = ''; C.setState(region, 'empty'); return; }
      body.className = 'ui-rows-enter';
      body.innerHTML = rows.map(function (inv) {
        var status = roleKey(inv.status) || 'pending';
        return '<tr><td><div class="ui-person"><span class="ui-avatar ui-avatar--muted">' + esc(C.fmt.initials(inv.display_name, inv.email)) + '</span>' +
          '<div class="ui-grow"><div class="ui-person__name ui-truncate">' + esc(inv.display_name || '—') + '</div><div class="ui-person__sub ui-truncate">' + esc(inv.email || '—') + '</div></div></div></td>' +
          '<td>' + roleBadge(inv.role, PLATFORM_ROLE, PLATFORM_TONE) + '</td>' +
          '<td><span class="ui-badge ui-badge--dot ui-badge--' + (INVITE_TONE[status] || 'outline') + '">' + esc(status.charAt(0).toUpperCase() + status.slice(1)) + '</span></td>' +
          '<td title="' + esc(C.fmt.dateTime(inv.created_at)) + '">' + esc(C.fmt.relative(inv.created_at)) + '</td></tr>';
      }).join('');
      C.setState(region, 'ready');
    }, function () { C.setState(region, 'error'); });
  }

  // ── Client groups ──────────────────────────────────────────────────────
  function seats(c) { var v = parseInt(c && c.members_allowed, 10); return v > 0 ? v : 10; }
  function used(c) {
    var v = parseInt(c && c.occupied_count, 10);
    return v >= 0 ? v : (parseInt(c && c.member_count, 10) || 0) + (parseInt(c && c.pending_invite_count, 10) || 0);
  }
  function selected() {
    return state.clients.filter(function (c) { return String(c.id) === String(state.selectedId); })[0] || null;
  }

  function renderClientList() {
    var region = byId('clients-region');
    var q = state.clientQuery.toLowerCase();
    var rows = state.clients.filter(function (c) { return !q || String(c.name || '').toLowerCase().indexOf(q) !== -1; });
    if (!rows.length) {
      byId('clients-empty-text').textContent = state.clients.length ? 'No client groups match “' + state.clientQuery + '”.' : 'No client groups yet. Create one to start adding members.';
      C.setState(region, 'empty');
      return;
    }
    byId('clients-list').innerHTML = rows.map(function (c) {
      var active = String(c.id) === String(state.selectedId);
      var members = parseInt(c.member_count, 10) || 0;
      var pending = parseInt(c.pending_invite_count, 10) || 0;
      var full = used(c) >= seats(c);
      return '<button type="button" class="um-client' + (active ? ' is-selected' : '') + '" role="option" aria-selected="' + active + '" data-cid="' + esc(c.id) + '">' +
        '<span class="ui-avatar">' + esc(C.fmt.initials(c.name, 'Client')) + '</span>' +
        '<span class="ui-grow"><span class="um-client__name ui-truncate">' + esc(c.name || 'Client group') + '</span>' +
        '<span class="um-client__meta">' + C.fmt.plural(members, 'member') + (pending ? ' · ' + pending + ' pending' : '') + '</span></span>' +
        '<span class="um-client__seats' + (full ? ' is-full' : '') + '">' + used(c) + '/' + seats(c) + '</span></button>';
    }).join('');
    C.setState(region, 'ready');
  }

  function loadClients(force) {
    var region = byId('clients-region');
    if (!state.clientsLoaded) C.setState(region, 'loading');
    return api.get('/api/clients', { ttl: 10000, force: !!force }).then(function (data) {
      state.clients = Array.isArray(data) ? data : [];
      state.clientsLoaded = true;
      renderClientList();
      if (state.selectedId && !selected()) selectClient(null);
      else if (state.selectedId) renderDetailHead();
    }, function (err) {
      if (state.clientsLoaded) { C.toast(err.message || 'Could not refresh client groups', 'error'); return; }
      C.setState(region, 'error');
    });
  }
  function reloadClients() { api.invalidate('/api/clients'); return loadClients(true); }

  function renderDetailHead() {
    var c = selected();
    if (!c) return;
    byId('client-detail-avatar').textContent = C.fmt.initials(c.name, 'Client');
    byId('client-detail-name').textContent = c.name || 'Client group';
    byId('client-detail-desc').textContent = c.description || '';
    var total = seats(c);
    var u = used(c);
    var full = u >= total;
    byId('client-capacity-text').textContent = u + ' / ' + total;
    byId('client-capacity-bar').style.width = Math.min(100, Math.round((u / total) * 100)) + '%';
    byId('client-capacity').classList.toggle('is-full', full);
    byId('client-capacity').title = (parseInt(c.member_count, 10) || 0) + ' active, ' + (parseInt(c.pending_invite_count, 10) || 0) + ' pending';
    ['btn-add-member', 'btn-invite-member'].forEach(function (id) {
      byId(id).disabled = full;
      byId(id).title = full ? 'All ' + total + ' seats are used. Raise the seat limit to add more.' : '';
    });
  }

  function selectClient(id) {
    state.selectedId = id ? String(id) : null;
    state.members = [];
    state.accessTarget = '';
    state.grantPool = null;
    renderClientList();
    var detail = byId('client-detail');
    if (!state.selectedId) { C.setState(detail, 'empty'); return; }
    C.setState(detail, 'ready');
    renderDetailHead();
    loadMembers();
    loadAccess();
  }

  byId('clients-list').addEventListener('click', function (e) {
    var b = e.target.closest('[data-cid]');
    if (b) selectClient(b.getAttribute('data-cid'));
  });
  byId('client-search').addEventListener('input', C.debounce(function (e) { state.clientQuery = e.target.value.trim(); renderClientList(); }, 120));

  // Members
  function renderMembers() {
    var region = byId('members-region');
    var body = byId('members-body');
    byId('members-subtitle').textContent = state.members.length ? C.fmt.plural(state.members.length, 'member') + ' in this group' : 'People in this client group and their roles';
    renderAccessTargets();
    if (!state.members.length) { body.innerHTML = ''; C.setState(region, 'empty'); return; }
    var choices = memberRoleChoices();
    body.className = 'ui-rows-enter';
    body.innerHTML = state.members.map(function (m) {
      var uid = String(m.user_id || '');
      var role = roleKey(m.member_role);
      var self = uid === state.me.userId;
      var editable = !self && choices.indexOf(role) !== -1;
      var opts = (choices.indexOf(role) === -1 ? [role].concat(choices) : choices).map(function (r) {
        return '<option value="' + esc(r) + '"' + (r === role ? ' selected' : '') + '>' + esc(MEMBER_ROLE[r] || r) + '</option>';
      }).join('');
      var title = self ? 'You cannot change your own role' : (editable ? 'Change role' : 'Sales agents are managed by the client admin team');
      return '<tr data-uid="' + esc(uid) + '"><td><div class="ui-person"><span class="ui-avatar">' + esc(C.fmt.initials(m.display_name, m.email)) + '</span>' +
        '<div class="ui-grow"><div class="ui-person__name ui-truncate">' + esc(m.display_name || '—') + '</div><div class="ui-person__sub ui-truncate">' + esc(m.email || '—') + '</div></div></div></td>' +
        '<td><select class="member-role-select" data-member-role title="' + esc(title) + '"' + (editable ? '' : ' disabled') + '>' + opts + '</select></td>' +
        '<td title="' + esc(C.fmt.dateTime(m.created_at)) + '">' + esc(C.fmt.relative(m.created_at)) + '</td>' +
        '<td class="um-col-actions"><div class="ui-table__actions">' + (self ? '' : '<button type="button" class="ui-icon-btn ui-icon-btn--danger" data-remove-member title="Remove from group" aria-label="Remove ' + esc(m.display_name || m.email || 'member') + '">' + SVG_TRASH + '</button>') + '</div></td></tr>';
    }).join('');
    C.setState(region, 'ready');
  }

  function loadMembers() {
    var cid = state.selectedId;
    var region = byId('members-region');
    C.setState(region, 'loading');
    byId('members-body').innerHTML = C.skeleton.rows(4, 3);
    return membersRun(api.get('/api/clients/' + encodeURIComponent(cid) + '/members', { ttl: 0, force: true, quiet: true })).then(function (data) {
      if (cid !== state.selectedId) return;
      state.members = Array.isArray(data) ? data : [];
      renderMembers();
    }, function (err) {
      if (cid !== state.selectedId) return;
      byId('members-body').innerHTML = '';
      byId('members-error').textContent = err.message || 'Could not load members.';
      C.setState(region, 'error');
    });
  }

  byId('members-body').addEventListener('change', function (e) {
    var sel = e.target.closest('[data-member-role]');
    if (!sel) return;
    var uid = sel.closest('tr').getAttribute('data-uid');
    var cid = state.selectedId;
    var prev = (state.members.filter(function (m) { return String(m.user_id) === uid; })[0] || {}).member_role;
    sel.disabled = true;
    api.patch('/api/clients/' + encodeURIComponent(cid) + '/members/' + encodeURIComponent(uid), { member_role: sel.value }).then(function () {
      C.toast('Role updated');
      state.members.forEach(function (m) { if (String(m.user_id) === uid) m.member_role = sel.value; });
      renderMembers();
    }, function (err) {
      C.toast(err.message || 'Failed to update role', 'error');
      sel.value = prev || sel.value;
      sel.disabled = false;
    });
  });

  byId('members-body').addEventListener('click', function (e) {
    var b = e.target.closest('[data-remove-member]');
    if (!b) return;
    var uid = b.closest('tr').getAttribute('data-uid');
    var m = state.members.filter(function (x) { return String(x.user_id) === uid; })[0] || {};
    var label = m.display_name || m.email || 'this member';
    C.confirm({ title: 'Remove ' + label + '?', text: 'They lose access to this client group and its projects.', confirmLabel: 'Remove', tone: 'danger' }).then(function (ok) {
      if (!ok) return;
      var cid = state.selectedId;
      C.action(b, function () {
        return api.del('/api/clients/' + encodeURIComponent(cid) + '/members/' + encodeURIComponent(uid));
      }, { success: label + ' removed' }).then(function () {
        state.members = state.members.filter(function (x) { return String(x.user_id) !== uid; });
        renderMembers();
        reloadClients();
      }).catch(function () {});
    });
  });

  function fillRoleSelect(sel, preferred) {
    var choices = memberRoleChoices();
    sel.innerHTML = choices.map(function (r) { return '<option value="' + r + '">' + esc(MEMBER_ROLE[r]) + '</option>'; }).join('');
    sel.value = choices.indexOf(preferred) !== -1 ? preferred : choices[0];
  }

  // Add existing user
  byId('btn-add-member').addEventListener('click', function () {
    var existing = {};
    state.members.forEach(function (m) { existing[String(m.user_id)] = true; });
    var start = state.usersLoaded ? Promise.resolve() : loadUsers();
    start.then(function () {
      var options = state.users.filter(function (u) { return !existing[String(u.user_id)] && !u.is_self; });
      if (!options.length) { C.toast('Everyone in your organisation is already in this group.', 'info'); return; }
      byId('add-member-user').innerHTML = options.map(function (u) {
        return '<option value="' + esc(u.user_id) + '">' + esc((u.display_name || u.email || u.user_id) + (u.email && u.display_name ? ' — ' + u.email : '')) + '</option>';
      }).join('');
      fillRoleSelect(byId('add-member-role'), 'client_admin');
      setAlert('add-member-error', '');
      C.modal.open('modal-add-member');
    });
  });
  byId('add-member-form').addEventListener('submit', function (e) {
    e.preventDefault();
    var uid = byId('add-member-user').value;
    if (!uid) { setAlert('add-member-error', 'Select a user.'); return; }
    var cid = state.selectedId;
    C.action(byId('confirm-add-member'), function () {
      return api.post('/api/clients/' + encodeURIComponent(cid) + '/members', { user_id: uid, member_role: byId('add-member-role').value });
    }, { success: 'Member added', onError: function (err) { setAlert('add-member-error', err.message || 'Failed to add member'); } }).then(function () {
      C.modal.close('modal-add-member');
      loadMembers();
      reloadClients();
    }).catch(function () {});
  });

  // Invite member
  byId('btn-invite-member').addEventListener('click', function () {
    byId('invite-member-form').reset();
    fillRoleSelect(byId('invite-member-role'), 'client_admin');
    setAlert('invite-member-error', '');
    setAlert('invite-member-success', '');
    var c = selected();
    byId('modal-invite-member-subtitle').textContent = 'Send an invitation to join ' + ((c && c.name) || 'this client group') + '.';
    C.modal.open('modal-invite-member');
  });
  byId('invite-member-form').addEventListener('submit', function (e) {
    e.preventDefault();
    var name = byId('invite-member-name').value.trim();
    var email = byId('invite-member-email').value.trim();
    setAlert('invite-member-success', '');
    if (!name) { setAlert('invite-member-error', 'Display name is required.'); return; }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) { setAlert('invite-member-error', 'Enter a valid email address.'); return; }
    setAlert('invite-member-error', '');
    var cid = state.selectedId;
    C.action(byId('confirm-invite-member'), function () {
      return api.post('/api/clients/' + encodeURIComponent(cid) + '/invite', { display_name: name, email: email, member_role: byId('invite-member-role').value });
    }, { onError: function (err) { setAlert('invite-member-error', err.message || 'Failed to send invite'); } }).then(function (res) {
      var link = res && res.invite_link ? String(res.invite_link) : '';
      setAlert('invite-member-success', res && res.email_sent === false
        ? 'Invite created, but the email could not be sent' + (res.email_error ? ' (' + res.email_error + ')' : '') + '. The link is copied — share it manually.'
        : 'Invitation sent to ' + email + '.');
      if (link) C.copy(link, 'Invite link');
      byId('invite-member-name').value = '';
      byId('invite-member-email').value = '';
      reloadClients();
    }).catch(function () {});
  });

  // Edit / delete group
  function openClientModal(c) {
    byId('client-form').reset();
    byId('client-form').setAttribute('data-id', c ? c.id : '');
    byId('modal-client-title').textContent = c ? 'Edit client group' : 'New client group';
    byId('client-modal-name').value = c ? (c.name || '') : '';
    byId('client-modal-desc').value = c ? (c.description || '') : '';
    byId('client-modal-seats').value = String(c ? seats(c) : 10);
    setAlert('client-modal-error', '');
    C.modal.open('modal-client');
  }
  byId('btn-new-client').addEventListener('click', function () { openClientModal(null); });
  byId('btn-edit-client').addEventListener('click', function () { openClientModal(selected()); });
  byId('client-form').addEventListener('submit', function (e) {
    e.preventDefault();
    var id = byId('client-form').getAttribute('data-id');
    var name = byId('client-modal-name').value.trim();
    var seatsVal = parseInt(byId('client-modal-seats').value, 10);
    if (!name) { setAlert('client-modal-error', 'Name is required.'); return; }
    if (!seatsVal || seatsVal < 1) { setAlert('client-modal-error', 'Seats must be at least 1.'); return; }
    var body = { name: name, description: byId('client-modal-desc').value.trim(), members_allowed: seatsVal };
    C.action(byId('confirm-client-modal'), function () {
      return id ? api.patch('/api/clients/' + encodeURIComponent(id), body) : api.post('/api/clients', body);
    }, { success: id ? 'Client group updated' : 'Client group created', onError: function (err) { setAlert('client-modal-error', err.message || 'Failed to save'); } }).then(function (res) {
      C.modal.close('modal-client');
      return reloadClients().then(function () {
        var newId = id || (res && (res.id || (res.client && res.client.id)));
        if (newId) selectClient(newId);
      });
    }).catch(function () {});
  });
  byId('btn-delete-client').addEventListener('click', function () {
    var c = selected();
    if (!c) return;
    C.confirm({ title: 'Delete “' + (c.name || 'this group') + '”?', text: 'All members lose group access. This cannot be undone.', confirmLabel: 'Delete group', tone: 'danger' }).then(function (ok) {
      if (!ok) return;
      C.action(byId('btn-delete-client'), function () {
        return api.del('/api/clients/' + encodeURIComponent(c.id));
      }, { success: 'Client group deleted' }).then(function () {
        state.clients = state.clients.filter(function (x) { return x !== c; });
        selectClient(null);
        reloadClients();
      }).catch(function () {});
    });
  });

  // Project access
  function renderAccessTargets() {
    var sel = byId('access-target');
    var opts = ['<option value="">Whole group</option>'].concat(state.members.map(function (m) {
      var label = (m.display_name || m.email || m.user_id) + ' · ' + (MEMBER_ROLE[roleKey(m.member_role)] || m.member_role || '');
      return '<option value="' + esc(m.user_id) + '">' + esc(label) + '</option>';
    }));
    sel.innerHTML = opts.join('');
    sel.value = state.accessTarget;
    if (sel.value !== state.accessTarget) { state.accessTarget = ''; sel.value = ''; }
  }

  function loadAccess() {
    var cid = state.selectedId;
    var target = state.accessTarget;
    var region = byId('access-region');
    C.setState(region, 'loading');
    var base = '/api/clients/' + encodeURIComponent(cid) + '/access';
    return accessRun(api.get(target ? base + '?target_user_id=' + encodeURIComponent(target) : base, { ttl: 0, force: true, quiet: true })).then(function (data) {
      if (cid !== state.selectedId || target !== state.accessTarget) return;
      if (!target) state.grantPool = data || {};
      var rows = [];
      ((data && data.workspaces) || []).forEach(function (w) { rows.push({ type: 'workspace', id: w.workspace_id, name: w.name, access: w.access_type }); });
      ((data && data.panoramas) || []).forEach(function (p) { rows.push({ type: 'panorama', id: p.panorama_id, name: p.name, access: p.access_type }); });
      if (!rows.length) { C.setState(region, 'empty'); return; }
      byId('access-list').innerHTML = rows.map(function (r) {
        return '<div class="access-row"><span class="ui-badge ui-badge--outline">' + (r.type === 'workspace' ? 'Project' : 'Panorama') + '</span>' +
          '<span class="um-access-name ui-truncate">' + esc(r.name || r.id) + '</span>' +
          '<span class="ui-badge ui-badge--brand">' + esc(r.access || '') + '</span>' +
          '<button type="button" class="ui-btn ui-btn--sm ui-btn--danger-soft" data-revoke-type="' + esc(r.type) + '" data-revoke-id="' + esc(r.id) + '">Revoke</button></div>';
      }).join('');
      C.setState(region, 'ready');
    }, function (err) {
      if (cid !== state.selectedId) return;
      byId('access-error').textContent = err.message || 'Could not load project access.';
      C.setState(region, 'error');
    });
  }

  byId('access-target').addEventListener('change', function (e) {
    state.accessTarget = e.target.value;
    loadAccess();
  });

  byId('access-list').addEventListener('click', function (e) {
    var b = e.target.closest('[data-revoke-id]');
    if (!b) return;
    var type = b.getAttribute('data-revoke-type');
    C.confirm({ title: 'Revoke access?', text: 'Access to this ' + (type === 'workspace' ? 'project' : 'panorama') + ' will be removed' + (state.accessTarget ? ' for this member.' : ' for the group.'), confirmLabel: 'Revoke', tone: 'danger' }).then(function (ok) {
      if (!ok) return;
      var payload = { resource_type: type, resource_id: b.getAttribute('data-revoke-id') };
      if (state.accessTarget) payload.target_user_id = state.accessTarget;
      C.action(b, function () {
        return api.del('/api/clients/' + encodeURIComponent(state.selectedId) + '/access', payload);
      }, { success: 'Access revoked' }).then(loadAccess).catch(function () {});
    });
  });

  function targetIsBroker() {
    var m = state.members.filter(function (x) { return String(x.user_id) === state.accessTarget; })[0];
    return !!m && roleKey(m.member_role) === 'broker';
  }

  function ensureAllResources() {
    if (state.allResources) return Promise.resolve(state.allResources);
    return Promise.all([api.get('/api/workspaces', { ttl: 60000 }), api.get('/api/panoramas', { ttl: 60000 })]).then(function (res) {
      state.allResources = { workspaces: res[0] || [], panoramas: res[1] || [] };
      return state.allResources;
    });
  }

  function grantOptions() {
    // Members (and brokers in particular) can only receive what the group already has.
    var restricted = state.accessTarget !== '' || targetIsBroker();
    var pool = restricted ? (state.grantPool || {}) : (state.allResources || {});
    var list = state.grantType === 'workspace' ? (pool.workspaces || []) : (pool.panoramas || []);
    var sel = byId('grant-resource-id');
    sel.innerHTML = list.length ? list.map(function (r) {
      var id = String(r.id || r.workspace_id || r.panorama_id || '');
      return '<option value="' + esc(id) + '">' + esc(r.name || id) + '</option>';
    }).join('') : '<option value="">' + (restricted ? 'Grant this to the whole group first' : 'Nothing available') + '</option>';
    byId('confirm-grant-access').disabled = !list.length;
  }

  byId('btn-grant-access').addEventListener('click', function () {
    var btn = byId('btn-grant-access');
    setAlert('grant-access-error', '');
    state.grantType = 'workspace';
    byId('grant-type').querySelectorAll('[data-type]').forEach(function (b) { b.setAttribute('aria-pressed', b.getAttribute('data-type') === 'workspace' ? 'true' : 'false'); });
    var target = state.members.filter(function (m) { return String(m.user_id) === state.accessTarget; })[0];
    byId('grant-target-label').textContent = target ? (target.display_name || target.email) + ' (' + (MEMBER_ROLE[roleKey(target.member_role)] || '') + ')' : 'Whole group — ' + ((selected() || {}).name || '');
    var level = byId('grant-access-type');
    level.value = targetIsBroker() ? 'broker' : 'client';
    var needsPool = state.accessTarget !== '' && !state.grantPool;
    C.action(btn, function () {
      var base = '/api/clients/' + encodeURIComponent(state.selectedId) + '/access';
      return Promise.all([
        ensureAllResources(),
        needsPool ? api.get(base, { ttl: 0, force: true, quiet: true }).then(function (d) { state.grantPool = d || {}; }) : null
      ]);
    }, { error: 'Could not load projects' }).then(function () {
      grantOptions();
      C.modal.open('modal-grant-access');
    }).catch(function () {});
  });

  byId('grant-type').addEventListener('click', function (e) {
    var b = e.target.closest('[data-type]');
    if (!b) return;
    state.grantType = b.getAttribute('data-type');
    this.querySelectorAll('[data-type]').forEach(function (x) { x.setAttribute('aria-pressed', x === b ? 'true' : 'false'); });
    grantOptions();
  });

  byId('grant-form').addEventListener('submit', function (e) {
    e.preventDefault();
    var rid = byId('grant-resource-id').value;
    if (!rid) { setAlert('grant-access-error', 'Select a project or panorama.'); return; }
    var payload = { resource_type: state.grantType, resource_id: rid, access_type: byId('grant-access-type').value };
    if (state.accessTarget) payload.target_user_id = state.accessTarget;
    C.action(byId('confirm-grant-access'), function () {
      return api.post('/api/clients/' + encodeURIComponent(state.selectedId) + '/access', payload);
    }, { success: 'Access granted', onError: function (err) { setAlert('grant-access-error', err.message || 'Failed to grant access'); } }).then(function () {
      C.modal.close('modal-grant-access');
      if (!state.accessTarget) state.grantPool = null;
      loadAccess();
    }).catch(function () {});
  });

  // Retry buttons inside error states
  document.addEventListener('click', function (e) {
    var r = e.target.closest('[data-retry]');
    if (!r) return;
    if (r.closest('#users-region')) loadUsers(true);
    else if (r.closest('#invites-region')) loadInvites();
    else if (r.closest('#clients-region')) loadClients(true);
  });

  // ── Boot ───────────────────────────────────────────────────────────────
  loadUsers(false);  // starts before identity resolves; the API enforces admin access
  window.Portal.ready.then(function (ctx) {
    state.me.role = String(ctx.role || '').toLowerCase();
    state.me.userId = ctx.profile ? String(ctx.profile.user_id || '') : '';
    if (state.me.role !== 'admin' && state.me.role !== 'superadmin') {
      setAlert('um-banner', 'User management is available to platform admins. Manage your team from My team.');
    }
    renderUsers();
    var hash = String(window.location.hash || '').replace('#', '');
    if (hash === 'invites' || hash === 'clients') activateTab(hash);
    try {
      var open = new URLSearchParams(window.location.search).get('open');
      if (open === 'invite') { openInvite(); window.history.replaceState(null, '', window.location.pathname); }
    } catch (e) { /* ignore */ }
  });
})();
