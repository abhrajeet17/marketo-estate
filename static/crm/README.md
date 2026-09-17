# CRM Frontend

This folder owns the CRM-specific frontend layer for MarketoState.

- `legacy.css` keeps the existing CRM layout and selector coverage.
- `crm.css` imports the legacy file and applies the current compact workspace visual system.
- `crm-modals.js` adds movable and collapsible behavior to CRM dialogs and drawers.

Keep CRM-only CSS and JavaScript here instead of adding new CRM files under the shared `static/css` or `static/js` folders. Shared UI primitives should still live under the global component folders.
