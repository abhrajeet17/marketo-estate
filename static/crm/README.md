# CRM Frontend

This folder owns the CRM-specific frontend layer for MarketoState.

- `legacy.css` keeps the existing CRM layout and selector coverage.
- `crm.css` imports the legacy file and applies the current compact workspace visual system.
- `crm-records.css` styles the unified Interests / Deals / Contacts records UI (drawer, kanban, modals).
- `crm-records.js` drives Interests, Deals and Contacts. All three read the single
  `crm_leads` table through `GET /api/crm/leads?status=interest|deal` and share one
  record drawer (view / edit), the Convert-to-Deal modal, the Add Plots modal and the
  Add Interest modal. Markup lives in `templates/crm/components/records_*.html`,
  `record_drawer.html` and `record_modals.html`.
- `crm-modals.js` adds movable and collapsible behavior to CRM dialogs and drawers.
- `crm-pager.js`, `crm-sort.js`, `crm-excel-export.js` are the shared table helpers.

Keep CRM-only CSS and JavaScript here instead of adding new CRM files under the shared `static/css` or `static/js` folders. Shared UI primitives should still live under the global component folders.
