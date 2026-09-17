(function (global) {
  'use strict';

  var ARC_LENGTH = 314.159;

  function PortalTabLoader(config) {
    this.shellId = config.shellId || null;
    this.loaderId = config.loaderId;
    this.shellLoadingClass = config.shellLoadingClass || 'portal-page-shell--loading';
    this.stepOrder = config.stepOrder || [];
    this.progress = config.initialProgress || 12;
    this.progressTarget = this.progress;
    this.progressRaf = null;
    this.ids = {
      percent: config.ids && config.ids.percent,
      steps: config.ids && config.ids.steps,
      caption: config.ids && config.ids.caption,
      label: config.ids && config.ids.label,
      arc: config.ids && config.ids.arc
    };
    this.finalStep = config.finalStep || (this.stepOrder[this.stepOrder.length - 1] || '');
    this.exitMs = config.exitMs || 450;
  }

  PortalTabLoader.prototype.el = function (id) {
    return id ? document.getElementById(id) : null;
  };

  PortalTabLoader.prototype.setText = function (id, value) {
    var node = this.el(id);
    if (node) node.textContent = value;
  };

  PortalTabLoader.prototype.renderProgress = function (value) {
    this.progress = value;
    if (this.ids.percent) this.setText(this.ids.percent, String(Math.round(value)));
    var arc = this.el(this.ids.arc);
    if (arc) arc.style.strokeDashoffset = String(ARC_LENGTH * (1 - value / 100));
  };

  PortalTabLoader.prototype.animateProgress = function (target) {
    var self = this;
    this.progressTarget = Math.max(this.progressTarget, Math.min(100, target));
    if (this.progressRaf) return;
    function tick() {
      var delta = self.progressTarget - self.progress;
      if (Math.abs(delta) < 0.4) {
        self.renderProgress(self.progressTarget);
        self.progressRaf = null;
        return;
      }
      self.renderProgress(self.progress + delta * 0.18);
      self.progressRaf = requestAnimationFrame(tick);
    }
    this.progressRaf = requestAnimationFrame(tick);
  };

  PortalTabLoader.prototype.setStep = function (step, srCaption, progress, label) {
    var loader = this.el(this.loaderId);
    if (srCaption) {
      if (this.ids.caption) this.setText(this.ids.caption, srCaption);
      if (loader) loader.setAttribute('aria-label', srCaption);
    }
    if (label && this.ids.label) this.setText(this.ids.label, label);
    if (typeof progress === 'number') this.animateProgress(progress);

    var steps = this.el(this.ids.steps);
    if (steps && step) {
      var activeIndex = this.stepOrder.indexOf(step);
      steps.querySelectorAll('li').forEach(function (li, index) {
        li.classList.toggle('is-active', index === activeIndex);
        li.classList.toggle('is-done', index < activeIndex);
      });
    }
    if (loader && step) loader.setAttribute('data-phase', step);
  };

  PortalTabLoader.prototype.setLoading = function (isLoading, options) {
    var shell = this.shellId ? this.el(this.shellId) : null;
    var loader = this.el(this.loaderId);
    var opts = options || {};

    if (!isLoading) {
      var finalStep = opts.finalStep || this.finalStep;
      var finalCaption = opts.finalCaption || 'Ready';
      var finalLabel = opts.finalLabel || finalCaption;
      this.setStep(finalStep, finalCaption, 100, finalLabel);
      if (loader) loader.classList.add('portal-tab-loader--exiting');
      if (shell) shell.classList.remove(this.shellLoadingClass);
      var self = this;
      window.setTimeout(function () {
        if (loader) {
          loader.setAttribute('hidden', '');
          loader.classList.remove('portal-tab-loader--exiting');
          loader.setAttribute('aria-busy', 'false');
        }
      }, this.exitMs);
      return;
    }

    if (shell) shell.classList.add(this.shellLoadingClass);
    if (loader) {
      loader.classList.remove('portal-tab-loader--exiting');
      loader.removeAttribute('hidden');
      loader.setAttribute('aria-busy', 'true');
    }
  };

  PortalTabLoader.prototype.boot = function (step, caption, progress, label) {
    this.renderProgress(this.progress);
    this.setStep(step, caption, progress, label);
  };

  PortalTabLoader.sectionMarkup = function (label) {
    var text = String(label == null ? 'Loading' : label);
    return (
      '<div class="portal-tab-loader portal-tab-loader--section" role="status" aria-live="polite" aria-busy="true" aria-label="' + text.replace(/"/g, '&quot;') + '">' +
        '<div class="portal-tab-loader__panel">' +
          '<div class="portal-tab-loader__visual" aria-hidden="true">' +
            '<svg class="portal-tab-loader__svg" viewBox="0 0 120 120" focusable="false">' +
              '<g class="portal-tab-loader__rings" transform="rotate(-90 60 60)">' +
                '<circle class="portal-tab-loader__track" cx="60" cy="60" r="50"></circle>' +
                '<circle class="portal-tab-loader__idle" cx="60" cy="60" r="50">' +
                  '<animateTransform attributeName="transform" type="rotate" from="0 60 60" to="360 60 60" dur="1.35s" repeatCount="indefinite"></animateTransform>' +
                '</circle>' +
                '<circle class="portal-tab-loader__progress" cx="60" cy="60" r="50"></circle>' +
              '</g>' +
              '<g class="portal-tab-loader__icon" transform="translate(60 62)">' +
                '<path d="M-13 12 0-16 13 12"></path>' +
                '<rect x="-10.5" y="12" width="21" height="15" rx="1.5"></rect>' +
                '<path d="M-4.5 19.5h9v7.5h-9z"></path>' +
                '<path d="M-16.5 27h33"></path>' +
              '</g>' +
            '</svg>' +
          '</div>' +
          '<div class="portal-tab-loader__meta">' +
            '<div class="portal-tab-loader__percent-wrap">' +
              '<span class="portal-tab-loader__percent">18</span>' +
              '<span class="portal-tab-loader__suffix">%</span>' +
            '</div>' +
            '<p class="portal-tab-loader__label">' + text + '</p>' +
          '</div>' +
          '<p class="portal-tab-loader__sr">' + text + '</p>' +
        '</div>' +
      '</div>'
    );
  };

  PortalTabLoader.bindSectionLoader = function (rootEl) {
    if (!rootEl) return null;
    if (rootEl._portalSectionLoader) return rootEl._portalSectionLoader;

    var inner = rootEl.querySelector('.portal-tab-loader') || rootEl;
    var arc = inner.querySelector('.portal-tab-loader__progress');
    var percent = inner.querySelector('.portal-tab-loader__percent');
    var labelEl = inner.querySelector('.portal-tab-loader__label');
    var captionEl = inner.querySelector('.portal-tab-loader__sr');
    var progress = 18;
    var progressTarget = 18;
    var progressRaf = null;
    var pulseTimer = null;
    var exitMs = 420;

    function renderProgress(value) {
      progress = value;
      if (percent) percent.textContent = String(Math.round(value));
      if (arc) arc.style.strokeDashoffset = String(ARC_LENGTH * (1 - value / 100));
    }

    function animateProgress(target) {
      progressTarget = Math.max(progressTarget, Math.min(100, target));
      if (progressRaf) return;
      function tick() {
        var delta = progressTarget - progress;
        if (Math.abs(delta) < 0.4) {
          renderProgress(progressTarget);
          progressRaf = null;
          return;
        }
        renderProgress(progress + delta * 0.18);
        progressRaf = requestAnimationFrame(tick);
      }
      progressRaf = requestAnimationFrame(tick);
    }

    function setLabel(text) {
      var value = String(text == null ? '' : text);
      if (!value) return;
      if (labelEl) labelEl.textContent = value;
      if (captionEl) captionEl.textContent = value;
      if (inner) inner.setAttribute('aria-label', value);
    }

    function setSectionBusy(isBusy) {
      var section = rootEl.closest('.crm-section');
      if (section) section.classList.toggle('is-tab-loading', !!isBusy);
    }

    var controller = {
      setLoading: function (isLoading, label) {
        if (label) setLabel(label);

        if (!isLoading) {
          if (pulseTimer) {
            clearInterval(pulseTimer);
            pulseTimer = null;
          }
          animateProgress(100);
          rootEl.classList.add('portal-section-loader--exiting');
          setSectionBusy(false);
          window.setTimeout(function () {
            rootEl.hidden = true;
            rootEl.style.display = 'none';
            rootEl.classList.remove('portal-section-loader--exiting');
            if (inner) inner.setAttribute('aria-busy', 'false');
          }, exitMs);
          return;
        }

        rootEl.hidden = false;
        rootEl.style.display = '';
        rootEl.classList.remove('portal-section-loader--exiting');
        if (inner) inner.setAttribute('aria-busy', 'true');
        progress = 18;
        progressTarget = 18;
        renderProgress(18);
        setSectionBusy(true);
        if (pulseTimer) clearInterval(pulseTimer);
        pulseTimer = window.setInterval(function () {
          if (progressTarget < 90) animateProgress(progressTarget + 3);
        }, 280);
      },
      setLabel: setLabel
    };

    rootEl._portalSectionLoader = controller;
    return controller;
  };

  global.PortalTabLoader = PortalTabLoader;
})(window);