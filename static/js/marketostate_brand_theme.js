/**
 * Apply MarketoState brand colors to the current page via CSS custom properties.
 * Requires marketostate_brand_theme_config.js to be loaded first.
 */
(function (global) {
    'use strict';

    function applyMarketostateBrandTheme() {
        var theme = global.MARKETOSTATE_BRAND_THEME;
        if (!theme || !theme.colors) return false;

        var c = theme.colors;
        var root = global.document && global.document.documentElement;
        if (!root) return false;

        root.classList.add('ms-brand-theme');

        var vars = {
            '--ms-brand-primary': c.primary,
            '--ms-brand-primary-hover': c.primaryHover,
            '--ms-brand-primary-strong': c.primaryStrong,
            '--ms-brand-primary-dark': c.primaryHover,
            '--ms-brand-primary-rgb': c.primaryRgb,
            '--ms-brand-dark': c.dark,
            '--ms-brand-dark-soft': c.darkSoft,
            '--ms-brand-dark-deep': c.darkDeep,
            '--ms-brand-dark-rgb': c.darkRgb,
            '--ms-brand-ink': c.ink,
            '--ms-brand-surface': c.surface,
            '--ms-brand-surface-warm': c.surfaceWarm,
            '--ms-brand-surface-card': c.surfaceCard,
            '--ms-brand-surface-muted': c.surfaceMuted,
            '--ms-brand-canvas': c.canvas,
            '--ms-brand-canvas-tint': c.canvasTint,
            '--ms-brand-border-warm': c.borderWarm,
            '--ms-brand-on-dark': c.onDark,
            '--ms-brand-on-dark-muted': c.onDarkMuted,
            '--bs-primary': c.primary,
            '--bs-primary-rgb': c.primaryRgb,
            '--bs-link-color': c.primary,
            '--bs-link-hover-color': c.primaryHover,
            '--bs-primary-bg-subtle': c.primaryBgSubtle,
            '--bs-primary-border-subtle': c.primaryBorderSubtle,
            '--bs-primary-text-emphasis': c.primaryTextEmphasis,
            '--bs-body-bg': c.surface,
            '--bs-body-bg-rgb': '247, 240, 228',
            '--bs-paper-bg': c.surfaceCard,
            '--bs-paper-bg-rgb': '255, 252, 247',
            '--bs-border-color': c.borderWarm,
            '--bs-menu-bg': c.dark,
            '--bs-menu-bg-rgb': c.darkRgb,
            '--bs-menu-color': c.onDark,
            '--bs-menu-hover-bg': 'rgba(' + c.primaryRgb + ', 0.14)',
            '--bs-menu-hover-color': c.primary,
            '--bs-menu-active-bg': 'rgba(' + c.primaryRgb + ', 0.2)',
            '--bs-menu-active-color': c.primary,
            '--bs-menu-sub-active-bg': 'rgba(' + c.primaryRgb + ', 0.16)',
            '--bs-menu-sub-active-color': c.primary,
            '--color-brand-pill-bg': c.dark,
            '--color-brand-pill-text': '#ffffff',
            '--bs-success': c.primary,
            '--bs-success-rgb': c.primaryRgb,
            '--bs-success-bg-subtle': c.primaryBgSubtle,
            '--bs-success-border-subtle': c.primaryBorderSubtle,
            '--bs-success-text-emphasis': c.primaryTextEmphasis,
            '--bs-info': c.dark,
            '--bs-info-rgb': c.darkRgb,
            '--bs-info-bg-subtle': c.darkBgSubtle,
            '--bs-info-border-subtle': c.darkBorderSubtle,
            '--bs-info-text-emphasis': c.dark,
            '--bs-warning': c.primary,
            '--bs-warning-rgb': c.primaryRgb,
            '--bs-warning-bg-subtle': c.primaryBgSubtle,
            '--bs-warning-border-subtle': c.primaryBorderSubtle,
            '--bs-warning-text-emphasis': c.primaryTextEmphasis,
            '--bs-cyan': c.primary,
            '--bs-cyan-rgb': c.primaryRgb,
            '--bs-green': c.primary,
            '--bs-purple': c.primary,
            '--bs-secondary': c.darkSoft,
            '--bs-secondary-rgb': c.darkRgb,
            '--bs-secondary-bg-subtle': c.darkBgSubtle,
            '--bs-secondary-text-emphasis': c.dark,
            '--bs-form-valid-color': c.primary,
            '--bs-form-valid-border-color': c.primary,
        };

        Object.keys(vars).forEach(function (key) {
            root.style.setProperty(key, vars[key]);
        });

        if (global.config && global.config.colors) {
            global.config.colors.primary = c.primary;
            global.config.colors.bodyBg = c.surface;
            global.config.colors.cardColor = c.surfaceCard;
            global.config.colors_label = global.config.colors_label || {};
            global.config.colors_label.primary = c.primaryBgSubtle;
            global.config.colors.success = c.primary;
            global.config.colors.info = c.dark;
            global.config.colors.warning = c.primary;
            global.config.colors_label.success = c.primaryBgSubtle;
            global.config.colors_label.info = c.darkBgSubtle;
            global.config.colors_label.warning = c.primaryBgSubtle;
        }

        return true;
    }

    global.applyMarketostateBrandTheme = applyMarketostateBrandTheme;
    global.applyOrgTheme = applyMarketostateBrandTheme;

    applyMarketostateBrandTheme();
})(window);