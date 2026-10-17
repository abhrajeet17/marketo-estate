# CRM Frontend

The CRM page (`templates/crm.html`) runs on the shared Charm UI layer:

- `static/ui/charm.css` / `charm.js` — design tokens, components, cached API client, toasts, modals, skeletons.
- `static/ui/shell.css` / `portal.js` — portal shell (rail, top bar, identity via `GET /api/portal/me`).
- `static/ui/pages/crm.css` — all CRM styling (tabs, toolbars, filter rail, tables, kanban, drawer, modals).
- `static/ui/tab-loader.js` — section skeleton loader (`PortalTabLoader` API).

Scripts in this folder:

- `crm-records.js` drives Interests, Deals and Contacts. All three read the single
  `crm_leads` table through `GET /api/crm/leads?status=interest|deal` and share one
  record drawer (view / edit), the Convert-to-Deal modal, the Add Plots modal and the
  Add Interest modal. Markup lives in `templates/crm/components/records_*.html`,
  `record_drawer.html` and `record_modals.html`.
- `crm-pager.js`, `crm-sort.js`, `crm-excel-export.js` are the shared table helpers
  (SheetJS is lazy-loaded the first time someone exports).
- `admin-masters.js` renders the Masters tab.

`crm.css` / `legacy.css` remain only for the 3D admin editor (`admin_3d.html`).

Loading rules: a table is always in exactly one state — skeleton, rows, empty, or error
with retry. Server-rendered skeleton rows cover the first paint; reloads keep data on
screen and show a thin refresh bar.
