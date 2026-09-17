/**
 * Legacy org theme hook — delegates to MarketoState brand theme when config is present.
 */
(function (global) {
    'use strict';
    if (typeof global.applyMarketostateBrandTheme === 'function') {
        global.applyOrgTheme = global.applyMarketostateBrandTheme;
        return;
    }
    global.applyOrgTheme = function applyOrgTheme() {
        return false;
    };
})(window);
