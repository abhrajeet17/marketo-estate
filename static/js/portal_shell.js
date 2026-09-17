/**
 * MarketoState portal shell — Preline sidebar, role nav, change password, sign out.
 */
(function () {
  'use strict';

  var SIDEBAR_KEY = 'portal_sidebar_collapsed';
  var BROKER_KEY = 'portal_is_broker';
  var CACHE_KEY = 'sidebar_cache_v2_client_admin';

  function qs(id) {
    return document.getElementById(id);
  }

  function setText(id, value) {
    var el = qs(id);
    if (el) el.textContent = value;
  }

  function showEl(id, visible) {
    var el = qs(id);
    if (!el) return;
    if (!visible) {
      el.style.display = 'none';
      return;
    }
    if (el.tagName === 'LI') el.style.display = 'list-item';
    else if ((el.className || '').indexOf('flex') >= 0) el.style.display = 'flex';
    else el.style.display = '';
  }

  function initials(name) {
    var text = String(name || '').trim();
    if (!text) return '--';
    var parts = text.split(/\s+/).filter(Boolean);
    return ((parts[0] || '')[0] || '') + ((parts[1] || '')[0] || (parts[0] || '')[1] || '');
  }

  function resolveCrmSidebarOffset(collapsed) {
    var merged = document.documentElement.classList.contains('portal-crm-merged')
      || !!(document.getElementById('portal-main') && document.getElementById('portal-main').classList.contains('portal-main--crm-merged'));
    if (collapsed) {
      return 'var(--portal-sidebar-collapsed, 5.25rem)';
    }
    if (merged) {
      return 'var(--portal-sidebar-width, 16.25rem)';
    }
    return 'calc(var(--portal-sidebar-width, 16.25rem) + var(--ms-sidebar-content-gap, 1.25rem))';
  }

  window.applyPortalSidebarCollapse = function applySidebarCollapse(collapsed) {
    var html = document.documentElement;
    html.classList.toggle('portal-sidebar-collapsed', collapsed);
    html.classList.toggle('portal-sidebar-expanded', !collapsed);
    var offset = resolveCrmSidebarOffset(collapsed);
    if (window.innerWidth < 1024) {
      offset = '0px';
    }
    html.style.setProperty('--crm-sidebar-offset', offset);
    try {
      localStorage.setItem(SIDEBAR_KEY, collapsed ? '1' : '0');
    } catch (e) { /* ignore */ }
    if (typeof window.syncCrmSidebarLayout === 'function') {
      window.syncCrmSidebarLayout();
    }
  };

  function initSidebarCollapse() {
    var btn = qs('portal-sidebar-collapse-btn');
    var toggleMobile = qs('portal-mobile-menu-toggle');
    var collapsed = true;
    try {
      if (localStorage.getItem(SIDEBAR_KEY) == null) {
        localStorage.setItem(SIDEBAR_KEY, '1');
      }
      collapsed = localStorage.getItem(SIDEBAR_KEY) === '1';
    } catch (e) { /* ignore */ }

    if (window.innerWidth >= 1024) {
      window.applyPortalSidebarCollapse(collapsed);
    } else {
      window.applyPortalSidebarCollapse(true);
    }

    if (btn) {
      btn.addEventListener('click', function () {
        if (window.innerWidth < 1024) return;
        var isCollapsed = document.documentElement.classList.contains('portal-sidebar-collapsed');
        window.applyPortalSidebarCollapse(!isCollapsed);
      });
    }

    if (toggleMobile) {
      toggleMobile.addEventListener('click', function () {
        var sidebar = qs('portal-sidebar');
        if (sidebar && window.HSOverlay) {
          window.HSOverlay.open(sidebar);
        }
      });
    }

    window.addEventListener('resize', function () {
      var collapsed = document.documentElement.classList.contains('portal-sidebar-collapsed');
      if (window.innerWidth < 1024) {
        document.documentElement.style.setProperty('--crm-sidebar-offset', '0px');
      } else {
        window.applyPortalSidebarCollapse(collapsed);
      }
      if (typeof window.syncCrmSidebarLayout === 'function') {
        window.syncCrmSidebarLayout();
      }
    });
  }

  function signOut() {
    var sb = window._supabase;
    var finish = function () { window.location.href = '/login'; };
    if (sb && sb.auth && typeof sb.auth.signOut === 'function') {
      Promise.resolve(sb.auth.signOut()).catch(function () {}).finally(finish);
    } else {
      finish();
    }
  }

  function bindSignOut() {
    ['menu-signout', 'dropdown-signout'].forEach(function (id) {
      var el = qs(id);
      if (el) el.addEventListener('click', function (e) {
        e.preventDefault();
        signOut();
      });
    });
  }

  var changePwModal = null;

  function getChangePwModal() {
    if (changePwModal) return changePwModal;
    var el = qs('change-password-modal');
    if (!el || !window.HSOverlay) return null;
    changePwModal = new window.HSOverlay(el);
    return changePwModal;
  }

  function openChangePwModal() {
    var modal = getChangePwModal();
    if (modal) modal.open();
  }

  function closeChangePwModal() {
    if (changePwModal) changePwModal.close();
  }

  function bindChangePassword() {
    var dropChangePw = qs('dropdown-change-password');
    if (dropChangePw) {
      dropChangePw.addEventListener('click', function (e) {
        e.preventDefault();
        var err = qs('change-password-error');
        if (err) { err.classList.add('hidden'); err.textContent = ''; }
        openChangePwModal();
      });
    }

    var confirmBtn = qs('confirm-change-password');
    if (confirmBtn) {
      confirmBtn.addEventListener('click', function () {
        var newPw = (qs('new-password-input') || {}).value || '';
        var confirmPw = (qs('confirm-password-input') || {}).value || '';
        var errEl = qs('change-password-error');
        if (newPw.length < 6) {
          if (errEl) { errEl.textContent = 'Password must be at least 6 characters.'; errEl.classList.remove('hidden'); }
          return;
        }
        if (newPw !== confirmPw) {
          if (errEl) { errEl.textContent = 'Passwords do not match.'; errEl.classList.remove('hidden'); }
          return;
        }
        var sb = window._supabase;
        if (!sb || !sb.auth) return;
        confirmBtn.disabled = true;
        sb.auth.updateUser({ password: newPw })
          .then(function (r) {
            if (r.error) throw r.error;
            closeChangePwModal();
            if (errEl) errEl.style.display = 'none';
          })
          .catch(function (err) {
            if (errEl) {
              errEl.textContent = (err && err.message) || 'Failed to update password';
              errEl.classList.remove('hidden');
            }
          })
          .finally(function () { confirmBtn.disabled = false; });
      });
    }

    ['change-password-close', 'cancel-change-password'].forEach(function (id) {
      var el = qs(id);
      if (el) el.addEventListener('click', closeChangePwModal);
    });
  }

  window.configurePortalShell = function configurePortalShell(profile, isBroker, isAdmin, isClientAdmin) {
    var displayName = String((profile && (profile.display_name || profile.name || profile.email)) || 'User').trim() || 'User';
    var roleLabel = String((profile && profile.role) || 'user');
    var letters = initials(displayName);
    setText('navbar-user-name', displayName);
    setText('navbar-user-role', roleLabel.charAt(0).toUpperCase() + roleLabel.slice(1));
    setText('navbar-user-avatar', letters);
    setText('navbar-user-avatar-2', letters);
    var home = isAdmin ? '/dashboard' : '/customer-dashboard';
    ['portal-menu-dashboard', 'portal-dropdown-dashboard'].forEach(function (id) {
      var el = qs(id);
      if (el) el.setAttribute('href', home);
    });
    var showInvites = !!isBroker;
    ['portal-nav-invites', 'portal-dropdown-invites-wrap'].forEach(function (id) {
      showEl(id, showInvites);
    });
    var showTeam = !!isClientAdmin && !isBroker;
    ['portal-nav-team', 'portal-dropdown-team-wrap'].forEach(function (id) {
      showEl(id, showTeam);
    });

    try {
      localStorage.setItem(BROKER_KEY, isBroker ? '1' : '0');
    } catch (e) { /* ignore */ }
  };

  window.configureSneatShell = window.configurePortalShell;

  function primeNavFromCache() {
    try {
      var cached = JSON.parse(sessionStorage.getItem(CACHE_KEY) || 'null');
      var brokerFlag = localStorage.getItem(BROKER_KEY) || localStorage.getItem('sneat_is_broker');
      if ((cached && cached.isBroker) || brokerFlag === '1') {
        document.documentElement.classList.add('portal-broker-cached');
        ['portal-nav-invites', 'portal-dropdown-invites-wrap'].forEach(function (id) {
          showEl(id, true);
        });
      }
      if (cached && cached.isClientAdmin && !cached.isBroker) {
        document.documentElement.classList.add('portal-client-admin-cached');
        ['portal-nav-team', 'portal-dropdown-team-wrap'].forEach(function (id) {
          showEl(id, true);
        });
      }
    } catch (e) { /* ignore */ }
  }

  window.mountCrmHeaderTabs = function mountCrmHeaderTabs() {
    var merged = document.documentElement.classList.contains('portal-crm-merged')
      || !!(document.getElementById('portal-main') && document.getElementById('portal-main').classList.contains('portal-main--crm-merged'));
    if (!merged) return;
    var slot = qs('portal-page-header');
    var tabs = qs('crm-tabs');
    if (!slot || !tabs || slot.contains(tabs)) return;
    slot.appendChild(tabs);
  };

  function initPortalShell() {
    primeNavFromCache();
    window.mountCrmHeaderTabs();
    initSidebarCollapse();
    bindSignOut();
    bindChangePassword();
    if (window.HSStaticMethods && typeof window.HSStaticMethods.autoInit === 'function') {
      window.HSStaticMethods.autoInit();
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initPortalShell);
  } else {
    initPortalShell();
  }
})();