/**
 * Section skeleton loader (Charm UI).
 *
 * Drop-in replacement for the old percentage-ring PortalTabLoader: same API
 * (sectionMarkup / bindSectionLoader / constructor), but it renders a
 * skeleton of the content that is about to appear. While a section is in its
 * first load, its real content is hidden (`.is-tab-loading`), so a table can
 * never show up empty before its data has arrived.
 */
(function (global) {
  'use strict';

  function skeletonMarkup(label, opts) {
    var o = opts || {};
    var cols = o.cols || 6;
    var rows = o.rows || 6;
    var text = String(label == null ? 'Loading' : label).replace(/"/g, '&quot;');
    var table = global.Charm ? global.Charm.skeleton.rows(cols, rows) : '';
    return '<div class="ui-section-skel" role="status" aria-live="polite" aria-busy="true" aria-label="' + text + '">' +
      (o.compact ? '' :
        '<div class="ui-section-skel__bar" aria-hidden="true">' +
          '<span class="ui-skel" style="width:92px"></span><span class="ui-skel" style="width:240px"></span>' +
          '<span class="ui-section-skel__spacer"></span><span class="ui-skel" style="width:140px"></span>' +
        '</div>') +
      '<div class="ui-section-skel__card" aria-hidden="true"><table class="ui-table"><tbody>' + table + '</tbody></table></div>' +
      '<span class="sr-only">' + text + '</span>' +
    '</div>';
  }

  function PortalTabLoader(config) {
    this.config = config || {};
  }
  PortalTabLoader.prototype.boot = function () {};
  PortalTabLoader.prototype.setStep = function () {};
  PortalTabLoader.prototype.setLoading = function (isLoading) {
    var c = this.config;
    var shell = c.shellId ? document.getElementById(c.shellId) : null;
    var loader = c.loaderId ? document.getElementById(c.loaderId) : null;
    if (shell && c.shellLoadingClass) shell.classList.toggle(c.shellLoadingClass, !!isLoading);
    if (loader) loader.hidden = !isLoading;
  };

  PortalTabLoader.sectionMarkup = function (label, opts) { return skeletonMarkup(label, opts); };

  PortalTabLoader.bindSectionLoader = function (rootEl) {
    if (!rootEl) return null;
    if (rootEl._portalSectionLoader) return rootEl._portalSectionLoader;
    if (!rootEl.querySelector('.ui-section-skel')) {
      var compact = rootEl.classList.contains('portal-section-loader--inline');
      rootEl.innerHTML = skeletonMarkup('Loading', { compact: compact, rows: compact ? 4 : 6, cols: compact ? 4 : 6 });
    }
    function section() { return rootEl.closest('.crm-section'); }
    var controller = {
      setLoading: function (isLoading, label) {
        if (label) controller.setLabel(label);
        rootEl.hidden = !isLoading;
        rootEl.style.display = isLoading ? '' : 'none';
        var s = section();
        if (s && rootEl.parentNode === s) s.classList.toggle('is-tab-loading', !!isLoading);
      },
      setLabel: function (text) {
        var sk = rootEl.querySelector('.ui-section-skel');
        var sr = rootEl.querySelector('.sr-only');
        if (sk) sk.setAttribute('aria-label', String(text));
        if (sr) sr.textContent = String(text);
      }
    };
    rootEl._portalSectionLoader = controller;
    return controller;
  };

  global.PortalTabLoader = PortalTabLoader;
})(window);
