/**
 * Sneat sidebar collapse toggle (#sneat-layout-menu-toggle).
 * Desktop: toggles layout-menu-collapsed on <html> (Sneat Helpers skips this).
 * Mobile: delegates to Helpers.toggleCollapsed for overlay menu.
 */
(function () {
  'use strict';

  var KEY = 'sneat_layout_menu_collapsed';
  var root = document.documentElement;
  var toggle = document.getElementById('sneat-layout-menu-toggle');
  if (!toggle) return;

  var icon = toggle.querySelector('i');

  function isSmallScreen() {
    return window.Helpers && typeof window.Helpers.isSmallScreen === 'function' && window.Helpers.isSmallScreen();
  }

  function isCollapsed() {
    if (isSmallScreen() && window.Helpers && typeof window.Helpers.isCollapsed === 'function') {
      return window.Helpers.isCollapsed();
    }
    return root.classList.contains('layout-menu-collapsed');
  }

  function syncIcon() {
    if (!icon) return;
    icon.classList.remove('bx-chevron-left', 'bx-chevron-right');
    icon.classList.add(isCollapsed() ? 'bx-chevron-right' : 'bx-chevron-left');
  }

  function persistState() {
    try {
      window.localStorage.setItem(KEY, isCollapsed() ? '1' : '0');
    } catch (e) { /* ignore */ }
    syncIcon();
  }

  function clearMenuHover() {
    root.classList.remove('layout-menu-hover');
    if (window.Helpers && typeof window.Helpers._setMenuHoverState === 'function') {
      window.Helpers._setMenuHoverState(false);
    }
  }

  function setDesktopCollapsed(collapsed) {
    root.classList.toggle('layout-menu-collapsed', !!collapsed);
    if (collapsed) clearMenuHover();
  }

  function applyCollapsed(collapsed, animate) {
    if (isSmallScreen() && window.Helpers && typeof window.Helpers.setCollapsed === 'function') {
      window.Helpers.setCollapsed(!!collapsed, animate !== false);
    } else {
      setDesktopCollapsed(collapsed);
    }
    syncIcon();
  }

  toggle.addEventListener('click', function (event) {
    event.preventDefault();
    if (isSmallScreen() && window.Helpers && typeof window.Helpers.toggleCollapsed === 'function') {
      window.Helpers.toggleCollapsed();
    } else {
      setDesktopCollapsed(!root.classList.contains('layout-menu-collapsed'));
    }
    window.setTimeout(function () {
      persistState();
      window.dispatchEvent(new Event('resize'));
    }, 10);
  });

  try {
    var saved = window.localStorage.getItem(KEY);
    if (saved === '0' || saved === '1') {
      window.setTimeout(function () {
        applyCollapsed(saved === '1', false);
      }, 0);
    }
  } catch (e) { /* ignore */ }

  new MutationObserver(syncIcon).observe(root, { attributes: true, attributeFilter: ['class'] });
  syncIcon();
})();