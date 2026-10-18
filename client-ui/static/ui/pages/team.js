/**
 * My team — client-admin team management.
 *
 * One request (GET /api/clients/mine/roster) returns every team with its
 * members and invites. State lives in `state`; `render()` is the only thing
 * that writes the roster DOM, and all row buttons use delegated handlers.
 */
(function () {
  'use strict';

  var C = window.Charm;
  var api = C.api;
  var esc = C.esc;
  var ROSTER_URL = '/api/clients/mine/roster';
  var PAGE_SIZES = [10, 25, 50];
  var ROLE_LABEL = { client_admin: 'Admin', client_user: 'Sales agent', broker: 'Broker' };
  var ROLE_TONE = { client_admin: 'brand', client_user: 'info', broker: 'violet' };

  var state = {
    groups: [],
    filters: { q: '', role: '', status: '' },
    pager: {},            // groupId -> { page, size }
    invite: null,         // { groupId }
    roleEdit: null,       // { groupId, userId, role }
    access: null          // { groupId, userId, role, group: {}, member: {} }
  };

  function byId(id) { return document.getElementById(id); }
  function roleKey(role) { return String(role || '').trim().toLowerCase(); }
  function setAlert(id, text) { var el = byId(id); if (el) el.textContent = text || ''; }

  // ── Derived data ───────────────────────────────────────────────────────
  function activeInvite(inv) {
    if (String(inv.status || '').toLowerCase() !== 'pending') return false;
    if (!inv.expires_at) return true;
    var t = new Date(inv.expires_at).getTime();
    return !isFinite(t) || t >= Date.now();
  }

  function pendingInvites(group) {
    var emails = {};
    (group.members || []).forEach(function (m) { if (m.email) emails[String(m.email).toLowerCase()] = true; });
    return (group.invites || []).filter(function (inv) {
      return String(inv.status || '').toLowerCase() === 'pending' && inv.email && !emails[String(inv.email).toLowerCase()];
    });
  }

  function capacity(group) {
    var allowed = parseInt(group.members_allowed, 10);
    if (!allowed || allowed < 1) allowed = 10;
    var members = (group.members || []).length;
    var pending = (group.invites || []).filter(activeInvite).length;
    return { allowed: allowed, members: members, pending: pending, used: members + pending, full: members + pending >= allowed };
  }

  function rosterRows(group) {
    var rows = (group.members || []).map(function (m) {
      return { kind: 'member', id: m.user_id, name: m.display_name || m.email || 'Member', email: m.email || '', role: roleKey(m.member_role), at: m.created_at, raw: m };
    });
    pendingInvites(group).forEach(function (inv) {
      rows.push({ kind: 'invite', id: inv.id, name: inv.display_name || inv.email || 'Invitee', email: inv.email || '', role: roleKey(inv.member_role), at: inv.created_at, link: inv.invite_link || '', raw: inv });
    });
    var f = state.filters;
    var q = f.q.toLowerCase();
    return rows.filter(function (r) {
      if (q && (r.name + ' ' + r.email).toLowerCase().indexOf(q) === -1) return false;
      if (f.role && r.role !== f.role) return false;
      if (f.status === 'active' && r.kind !== 'member') return false;
      if (f.status === 'pending' && r.kind !== 'invite') return false;
      return true;
    });
  }

  function pagerFor(groupId) {
    if (!state.pager[groupId]) state.pager[groupId] = { page: 1, size: PAGE_SIZES[0] };
    return state.pager[groupId];
  }

  // ── Rendering ──────────────────────────────────────────────────────────
  function renderKpis() {
    var totals = { members: 0, agents: 0, brokers: 0, pending: 0 };
    state.groups.forEach(function (g) {
      (g.members || []).forEach(function (m) {
        totals.members += 1;
        if (roleKey(m.member_role) === 'client_user') totals.agents += 1;
        if (roleKey(m.member_role) === 'broker') totals.brokers += 1;
      });
      totals.pending += pendingInvites(g).length;
    });
    [['team-total-members', totals.members], ['team-sales-agents', totals.agents], ['team-brokers', totals.brokers], ['team-pending-invites', totals.pending]].forEach(function (pair) {
      var el = byId(pair[0]);
      if (el.querySelector('.ui-skel')) el.textContent = '0';
      C.countUp(el, pair[1]);
    });
  }

  function actionBtn(action, label, svg, extra, danger) {
    return '<button type="button" class="ui-icon-btn' + (danger ? ' ui-icon-btn--danger' : '') + '" data-action="' + action + '" title="' + label + '" aria-label="' + label + '"' + (extra || '') + '>' + svg + '</button>';
  }

  var SVG = {
    edit: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>',
    view: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2.06 12.35a1 1 0 0 1 0-.7C3.41 7.84 7.36 5 12 5s8.59 2.84 9.94 6.65a1 1 0 0 1 0 .7C20.59 16.16 16.64 19 12 19s-8.59-2.84-9.94-6.65Z"/><circle cx="12" cy="12" r="3"/></svg>',
    access: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="10" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>',
    trash: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6"/></svg>',
    resend: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-2.64-6.36L21 8"/><path d="M21 3v5h-5"/></svg>',
    link: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>',
    plus: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg>'
  };

  function rowHtml(groupId, r) {
    var attrs = ' data-group="' + esc(groupId) + '" data-id="' + esc(r.id) + '"';
    var roleBadge = '<span class="ui-badge ui-badge--' + (ROLE_TONE[r.role] || 'outline') + '">' + esc(ROLE_LABEL[r.role] || r.role || '—') + '</span>';
    var actions;
    if (r.kind === 'member') {
      var manageable = r.role === 'client_user' || r.role === 'broker';
      actions = actionBtn('edit-role', 'Edit role', SVG.edit) +
        actionBtn('view', 'View member', SVG.view) +
        (manageable ? actionBtn('access', 'Project access', SVG.access) : '') +
        actionBtn('remove', 'Remove from team', SVG.trash, '', true);
    } else {
      actions = actionBtn('resend', 'Resend invite', SVG.resend) +
        (r.link ? actionBtn('copy-link', 'Copy invite link', SVG.link) : '');
    }
    return '<tr class="team-row' + (r.kind === 'invite' ? ' team-row--pending' : '') + '"' + attrs + ' data-kind="' + r.kind + '">' +
      '<td><div class="ui-person"><span class="ui-avatar' + (r.kind === 'invite' ? ' ui-avatar--muted' : '') + '">' + esc(C.fmt.initials(r.name, r.email)) + '</span>' +
        '<div class="ui-grow"><div class="ui-person__name ui-truncate">' + esc(r.name) + '</div><div class="ui-person__sub ui-truncate">' + esc(r.email || '—') + '</div></div></div></td>' +
      '<td>' + roleBadge + '</td>' +
      '<td title="' + esc(C.fmt.dateTime(r.at)) + '">' + esc(C.fmt.relative(r.at)) + '</td>' +
      '<td>' + (r.kind === 'member' ? '<span class="ui-badge ui-badge--success ui-badge--dot">Active</span>' : '<span class="ui-badge ui-badge--warning ui-badge--dot">Invite pending</span>') + '</td>' +
      '<td class="team-col-actions"><div class="ui-table__actions">' + actions + '</div></td></tr>';
  }

  function groupHtml(group) {
    var gid = String(group.id);
    var cap = capacity(group);
    var rows = rosterRows(group);
    var pager = pagerFor(gid);
    var pages = Math.max(1, Math.ceil(rows.length / pager.size));
    pager.page = Math.min(pager.page, pages);
    var start = (pager.page - 1) * pager.size;
    var visible = rows.slice(start, start + pager.size);
    var hasAny = (group.members || []).length || pendingInvites(group).length;
    var pct = Math.min(100, Math.round((cap.used / cap.allowed) * 100));
    var limitMsg = cap.full ? 'Restricted to ' + cap.allowed + ' users. Contact your admin to unlock more.' : '';

    var body;
    if (!visible.length) {
      body = '<tr class="team-empty-row"><td colspan="5"><div class="ui-empty"><span class="ui-empty__icon">' + C.icon(hasAny ? 'search' : 'users', 22) + '</span>' +
        '<div class="ui-empty__title">' + (hasAny ? 'No members match your filters' : 'No members yet') + '</div>' +
        '<p class="ui-empty__text">' + (hasAny ? 'Try a different search, role or status.' : 'Invite your sales agents and brokers to start collaborating.') + '</p></div></td></tr>';
    } else {
      body = visible.map(function (r) { return rowHtml(gid, r); }).join('');
    }

    var pagerHtml = rows.length > PAGE_SIZES[0]
      ? '<div class="ui-pager" data-group="' + esc(gid) + '"><span>' + (start + 1) + '–' + Math.min(rows.length, start + pager.size) + ' of ' + rows.length + '</span>' +
        '<div class="ui-pager__nav"><select class="ui-select ui-select--sm" data-page-size aria-label="Rows per page">' +
        PAGE_SIZES.map(function (n) { return '<option value="' + n + '"' + (n === pager.size ? ' selected' : '') + '>' + n + ' / page</option>'; }).join('') + '</select>' +
        '<button type="button" class="ui-btn ui-btn--sm" data-page="-1"' + (pager.page <= 1 ? ' disabled' : '') + '>Previous</button>' +
        '<span>Page ' + pager.page + ' of ' + pages + '</span>' +
        '<button type="button" class="ui-btn ui-btn--sm" data-page="1"' + (pager.page >= pages ? ' disabled' : '') + '>Next</button></div></div>'
      : '';

    return '<section class="ui-card ui-card--flush team-card" data-group-id="' + esc(gid) + '">' +
      '<header class="team-card__head">' +
        '<div class="ui-person"><span class="ui-avatar ui-avatar--lg">' + esc(C.fmt.initials(group.name, 'Team')) + '</span><div>' +
          '<div class="team-card__title"><h3>' + esc(group.name || 'Client team') + '</h3><span class="ui-badge ui-badge--brand">Client team</span></div>' +
          '<p class="team-card__desc">' + esc(group.description || 'Manage this team and its project permissions.') + '</p></div></div>' +
        '<div class="team-card__actions">' +
          '<div class="team-capacity' + (cap.full ? ' is-full' : '') + '" title="' + esc(cap.members + ' active, ' + cap.pending + ' pending') + '">' +
            '<div class="team-capacity__label"><span>Seats</span><strong>' + cap.used + ' / ' + cap.allowed + '</strong></div>' +
            '<div class="team-capacity__bar"><i style="width:' + pct + '%"></i></div></div>' +
          '<span title="' + esc(limitMsg) + '"><button type="button" class="ui-btn ui-btn--primary" data-action="invite" data-group="' + esc(gid) + '"' + (cap.full ? ' disabled' : '') + '>' + SVG.plus + ' Add member</button></span>' +
        '</div>' +
      '</header>' +
      '<div class="ui-table-wrap"><table class="ui-table"><thead><tr><th>Member</th><th>Role</th><th>Joined / invited</th><th>Status</th><th class="team-col-actions"><span class="sr-only">Actions</span></th></tr></thead>' +
      '<tbody>' + body + '</tbody></table></div>' + pagerHtml +
    '</section>';
  }

  function render() {
    var root = byId('groups-container');
    renderKpis();
    if (!state.groups.length) { C.setState(root, 'empty'); return; }
    byId('groups-list').innerHTML = state.groups.map(groupHtml).join('');
    C.setState(root, 'ready');
  }

  function findGroup(gid) {
    for (var i = 0; i < state.groups.length; i += 1) if (String(state.groups[i].id) === String(gid)) return state.groups[i];
    return null;
  }
  function findMember(gid, uid) {
    var g = findGroup(gid);
    return g ? (g.members || []).filter(function (m) { return String(m.user_id) === String(uid); })[0] || null : null;
  }

  // ── Data ───────────────────────────────────────────────────────────────
  function setGroups(list) {
    var seen = {};
    state.groups = (Array.isArray(list) ? list : []).filter(function (g) {
      var id = String((g && g.id) || '');
      if (!id || seen[id]) return false;
      seen[id] = true;
      return true;
    });
    render();
  }

  function load(force) {
    var root = byId('groups-container');
    if (!state.groups.length) C.setState(root, 'loading');
    else root.classList.add('is-refreshing');
    return api.get(ROSTER_URL, { ttl: 15000, swr: !force, force: !!force, persist: true, onUpdate: setGroups })
      .then(setGroups, function (err) {
        if (state.groups.length) { C.toast(err.message || 'Could not refresh teams', 'error'); return; }
        C.setState(root, 'error');
      })
      .finally(function () { root.classList.remove('is-refreshing'); });
  }

  function reload() { api.invalidate(ROSTER_URL); return load(true); }

  // ── Invite ─────────────────────────────────────────────────────────────
  function openInvite(gid) {
    var g = findGroup(gid);
    if (!g) return;
    if (capacity(g).full) { C.toast('This team is full. Contact your admin to unlock more seats.', 'error'); return; }
    state.invite = { groupId: String(gid) };
    byId('invite-member-form').reset();
    byId('invite-member-role').value = 'client_user';
    setAlert('invite-member-error', '');
    setAlert('invite-member-success', '');
    byId('modal-invite-member-subtitle').textContent = 'Send an invitation to join ' + (g.name || 'this team') + '.';
    C.modal.open('modal-invite-member');
  }

  function submitInvite(e) {
    e.preventDefault();
    var name = byId('invite-member-name').value.trim();
    var email = byId('invite-member-email').value.trim();
    var role = byId('invite-member-role').value;
    setAlert('invite-member-success', '');
    if (!name) { setAlert('invite-member-error', 'Display name is required.'); byId('invite-member-name').focus(); return; }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) { setAlert('invite-member-error', 'Enter a valid email address.'); byId('invite-member-email').focus(); return; }
    setAlert('invite-member-error', '');
    var gid = state.invite.groupId;
    C.action(byId('confirm-invite-member'), function () {
      return api.post('/api/clients/' + encodeURIComponent(gid) + '/invite', { display_name: name, email: email, member_role: role });
    }, { onError: function (err) { setAlert('invite-member-error', err.message || 'Failed to send invite'); } }).then(function (res) {
      var link = res && res.invite_link ? String(res.invite_link) : '';
      var msg = res && res.email_sent === false
        ? 'Invite created, but the email could not be sent' + (res.email_error ? ' (' + res.email_error + ')' : '') + '. Share the link manually.'
        : 'Invitation sent to ' + email + '.';
      setAlert('invite-member-success', msg);
      if (link) C.copy(link, 'Invite link');
      byId('invite-member-name').value = '';
      byId('invite-member-email').value = '';
      reload();
    }).catch(function () {});
  }

  // ── Role edit ──────────────────────────────────────────────────────────
  function openRoleEdit(gid, uid) {
    var m = findMember(gid, uid);
    if (!m) return;
    state.roleEdit = { groupId: String(gid), userId: String(uid), role: roleKey(m.member_role) };
    byId('edit-member-role-name').textContent = m.display_name || m.email || 'Member';
    byId('edit-member-role-avatar').textContent = C.fmt.initials(m.display_name, m.email);
    byId('edit-member-role-select').value = state.roleEdit.role || 'client_user';
    setAlert('edit-member-role-error', '');
    C.modal.open('modal-edit-member-role');
  }

  function submitRoleEdit(e) {
    e.preventDefault();
    var edit = state.roleEdit;
    var next = byId('edit-member-role-select').value;
    if (!edit) return;
    if (next === edit.role) { C.modal.close('modal-edit-member-role'); return; }
    C.action(byId('confirm-edit-member-role'), function () {
      return api.patch('/api/clients/' + encodeURIComponent(edit.groupId) + '/members/' + encodeURIComponent(edit.userId), { member_role: next });
    }, { success: 'Role updated', onError: function (err) { setAlert('edit-member-role-error', err.message || 'Failed to update role'); } }).then(function () {
      var m = findMember(edit.groupId, edit.userId);
      if (m) m.member_role = next;
      render();
      C.modal.close('modal-edit-member-role');
      reload();
    }).catch(function () {});
  }

  // ── View ───────────────────────────────────────────────────────────────
  function openView(gid, uid) {
    var m = findMember(gid, uid);
    if (!m) return;
    byId('member-view-avatar').textContent = C.fmt.initials(m.display_name, m.email);
    byId('member-view-name').textContent = m.display_name || '—';
    byId('member-view-email').textContent = m.email || '—';
    byId('member-view-role').textContent = ROLE_LABEL[roleKey(m.member_role)] || m.member_role || '—';
    byId('member-view-joined').textContent = C.fmt.dateTime(m.created_at);
    C.modal.open('modal-member-view');
  }

  // ── Remove / resend / copy ─────────────────────────────────────────────
  function removeMember(btn, gid, uid) {
    var m = findMember(gid, uid);
    var name = (m && (m.display_name || m.email)) || 'this member';
    C.confirm({ title: 'Remove ' + name + '?', text: 'They will lose access to this team and its projects. You can invite them again later.', confirmLabel: 'Remove member', tone: 'danger' }).then(function (ok) {
      if (!ok) return;
      C.action(btn, function () {
        return api.del('/api/clients/' + encodeURIComponent(gid) + '/members/' + encodeURIComponent(uid));
      }, { success: name + ' removed' }).then(function () {
        var g = findGroup(gid);
        if (g) g.members = (g.members || []).filter(function (x) { return String(x.user_id) !== String(uid); });
        render();
        reload();
      }).catch(function () {});
    });
  }

  function resendInvite(btn, gid, inviteId) {
    C.action(btn, function () {
      return api.post('/api/clients/' + encodeURIComponent(gid) + '/invites/' + encodeURIComponent(inviteId) + '/resend', {});
    }).then(function (res) {
      if (res && res.email_sent) C.toast('Invitation email resent');
      else C.toast('Invite refreshed, but the email could not be sent' + (res && res.email_error ? ': ' + res.email_error : ''), 'error');
      var g = findGroup(gid);
      if (g && res && res.invite_link) {
        (g.invites || []).forEach(function (inv) { if (String(inv.id) === String(inviteId)) inv.invite_link = res.invite_link; });
        render();
      }
    }).catch(function () {});
  }

  function copyInvite(gid, inviteId) {
    var g = findGroup(gid);
    var inv = g && (g.invites || []).filter(function (x) { return String(x.id) === String(inviteId); })[0];
    if (inv && inv.invite_link) C.copy(inv.invite_link, 'Invite link');
  }

  // ── Project access ─────────────────────────────────────────────────────
  var accessRun = C.latest();

  function renderAccess() {
    var a = state.access;
    var sel = byId('member-access-resource-id');
    var projects = (a.group && a.group.workspaces) || [];
    sel.innerHTML = projects.length
      ? projects.map(function (w) { return '<option value="' + esc(w.workspace_id) + '">' + esc(w.name || w.workspace_id) + '</option>'; }).join('')
      : '<option value="">No projects available</option>';
    byId('confirm-member-access').disabled = !projects.length;
    var rows = [];
    ((a.member && a.member.workspaces) || []).forEach(function (w) { rows.push({ type: 'workspace', id: w.workspace_id, name: w.name, access: w.access_type }); });
    ((a.member && a.member.panoramas) || []).forEach(function (p) { rows.push({ type: 'panorama', id: p.panorama_id, name: p.name, access: p.access_type }); });
    var region = byId('member-access-region');
    if (!rows.length) { C.setState(region, 'empty'); return; }
    byId('member-access-list').innerHTML = rows.map(function (r) {
      return '<div class="team-access__row"><span class="ui-badge ui-badge--outline">' + esc(r.type === 'workspace' ? 'Project' : 'Panorama') + '</span>' +
        '<span class="team-access__name ui-truncate">' + esc(r.name || r.id) + '</span>' +
        '<span class="ui-badge ui-badge--brand">' + esc(r.access || '') + '</span>' +
        '<button type="button" class="ui-btn ui-btn--sm ui-btn--danger-soft" data-revoke-type="' + esc(r.type) + '" data-revoke-id="' + esc(r.id) + '">Revoke</button></div>';
    }).join('');
    C.setState(region, 'ready');
  }

  function loadAccess() {
    var a = state.access;
    var region = byId('member-access-region');
    if (!a.loaded) C.setState(region, 'loading');
    var base = '/api/clients/' + encodeURIComponent(a.groupId) + '/access';
    return accessRun(Promise.all([
      api.get(base, { ttl: 0, quiet: true, force: true }),
      api.get(base + '?target_user_id=' + encodeURIComponent(a.userId), { ttl: 0, quiet: true, force: true })
    ])).then(function (res) {
      a.group = res[0] || {};
      a.member = res[1] || {};
      a.loaded = true;
      renderAccess();
    }, function (err) {
      byId('member-access-load-error').textContent = err.message || 'Failed to load access';
      C.setState(region, 'error');
    });
  }

  function openAccess(gid, uid) {
    var m = findMember(gid, uid);
    if (!m) return;
    var role = roleKey(m.member_role);
    state.access = { groupId: String(gid), userId: String(uid), role: role, loaded: false };
    byId('modal-member-access-subtitle').textContent = 'Choose which projects ' + (m.display_name || m.email || 'this member') + ' can work on.';
    var level = byId('member-access-level');
    level.value = role === 'broker' ? 'broker' : 'client';
    level.disabled = role === 'broker';
    setAlert('member-access-error', '');
    byId('member-access-resource-id').innerHTML = '<option value="">Loading projects…</option>';
    C.modal.open('modal-member-access');
    loadAccess();
  }

  function grantAccess(e) {
    e.preventDefault();
    var a = state.access;
    var rid = byId('member-access-resource-id').value;
    if (!rid) { setAlert('member-access-error', 'Select a project first.'); return; }
    var level = a.role === 'broker' ? 'broker' : byId('member-access-level').value;
    setAlert('member-access-error', '');
    C.action(byId('confirm-member-access'), function () {
      return api.post('/api/clients/' + encodeURIComponent(a.groupId) + '/access', { resource_type: 'workspace', resource_id: rid, access_type: level, target_user_id: a.userId });
    }, { success: 'Access granted', onError: function (err) { setAlert('member-access-error', err.message || 'Failed to grant access'); } })
      .then(loadAccess).catch(function () {});
  }

  function revokeAccess(btn) {
    var a = state.access;
    var type = btn.getAttribute('data-revoke-type');
    var id = btn.getAttribute('data-revoke-id');
    C.confirm({ title: 'Revoke access?', text: 'This member will no longer see this ' + (type === 'workspace' ? 'project' : 'panorama') + '.', confirmLabel: 'Revoke', tone: 'danger' }).then(function (ok) {
      if (!ok) return;
      C.action(btn, function () {
        return api.del('/api/clients/' + encodeURIComponent(a.groupId) + '/access', { resource_type: type, resource_id: id, target_user_id: a.userId });
      }, { success: 'Access revoked' }).then(loadAccess).catch(function () {});
    });
  }

  // ── Events ─────────────────────────────────────────────────────────────
  function bind() {
    byId('groups-list').addEventListener('click', function (e) {
      var btn = e.target.closest('[data-action]');
      if (btn) {
        var row = btn.closest('tr');
        var gid = btn.getAttribute('data-group') || (row && row.getAttribute('data-group'));
        var id = row && row.getAttribute('data-id');
        switch (btn.getAttribute('data-action')) {
          case 'invite': openInvite(gid); break;
          case 'edit-role': openRoleEdit(gid, id); break;
          case 'view': openView(gid, id); break;
          case 'access': openAccess(gid, id); break;
          case 'remove': removeMember(btn, gid, id); break;
          case 'resend': resendInvite(btn, gid, id); break;
          case 'copy-link': copyInvite(gid, id); break;
        }
        return;
      }
      var pageBtn = e.target.closest('[data-page]');
      if (pageBtn) {
        var pg = pagerFor(pageBtn.closest('.ui-pager').getAttribute('data-group'));
        pg.page = Math.max(1, pg.page + Number(pageBtn.getAttribute('data-page')));
        render();
      }
    });
    byId('groups-list').addEventListener('change', function (e) {
      if (!e.target.matches('[data-page-size]')) return;
      var pg = pagerFor(e.target.closest('.ui-pager').getAttribute('data-group'));
      pg.size = Number(e.target.value) || PAGE_SIZES[0];
      pg.page = 1;
      render();
    });

    function resetPages() { Object.keys(state.pager).forEach(function (k) { state.pager[k].page = 1; }); }
    byId('team-search-input').addEventListener('input', C.debounce(function (e) {
      state.filters.q = e.target.value.trim();
      resetPages();
      render();
    }, 120));
    byId('team-role-filter').addEventListener('change', function (e) {
      state.filters.role = e.target.value;
      resetPages();
      render();
    });
    byId('team-status-filter').addEventListener('click', function (e) {
      var b = e.target.closest('[data-status]');
      if (!b) return;
      state.filters.status = b.getAttribute('data-status');
      this.querySelectorAll('[data-status]').forEach(function (x) { x.setAttribute('aria-pressed', x === b ? 'true' : 'false'); });
      resetPages();
      render();
    });

    byId('invite-member-form').addEventListener('submit', submitInvite);
    byId('edit-role-form').addEventListener('submit', submitRoleEdit);
    byId('member-access-form').addEventListener('submit', grantAccess);
    byId('member-access-list').addEventListener('click', function (e) {
      var b = e.target.closest('[data-revoke-id]');
      if (b) revokeAccess(b);
    });
    var retry = document.querySelector('#groups-container [data-retry]');
    if (retry) retry.addEventListener('click', function () { load(true); });
  }

  bind();
  // The roster request starts immediately, in parallel with identity resolution
  // (portal.js handles role-based routing for this page).
  load(false);
})();
