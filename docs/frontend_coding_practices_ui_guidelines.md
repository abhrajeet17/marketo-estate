# Frontend Coding Practices for MarketoState

This project is a Flask/Jinja application with shared CSS, vanilla JavaScript, Supabase-backed auth, and feature-heavy pages such as CRM, dashboard, Full View, and customer portal. The goal is to keep UI work easy to understand, safe to change, accessible, and consistent across the app.

## Core Principles

- Keep screens readable, predictable, responsive, accessible, and fast.
- Preserve existing route URLs, element IDs, and API contracts unless a task explicitly changes them.
- Keep page-specific frontend code close to the page or feature it belongs to.
- Use shared components for repeated UI primitives such as buttons, cards, tables, modals, forms, empty states, and sidebar behavior.
- Prefer clear naming over cleverness, especially in large templates.

## Project Structure

Use feature folders when a page starts growing beyond one small template or stylesheet.

```txt
templates/
  components/
  crm/
    components/
static/
  css/
    components/
  js/
  crm/
docs/
```

For CRM specifically:

- Put CRM-only CSS and JavaScript in `static/crm/`.
- Put CRM template partials in `templates/crm/components/`.
- Keep shared navigation, sidebar, and account UI in `templates/components/`.
- Keep backend behavior in `app/controllers/features/*` when route extraction is needed.

## Components and Templates

- Break large Jinja templates into partials by visible responsibility: tab navigation, filters, tables, modals, drawers, and page shells.
- Keep reusable markup free of business logic where possible.
- Do not duplicate API/auth helper code in every template. Reuse shared helpers such as `window.pmApi` from `static/js/sidebar.js` when available.
- Keep existing IDs stable when JavaScript depends on them.

## State and API Calls

- Keep UI state local unless it is truly shared across unrelated components.
- Avoid storing duplicate state when it can be derived from loaded data.
- Handle loading, empty, error, success, and permission-denied states for data-heavy screens.
- Do not silently swallow API failures that block a user action.
- Avoid repeated fetches during tab switches when cached data is still valid.

## Styling

- Use variables from `static/css/theme.css` and feature-level tokens for page-specific themes.
- Use grid and flex layouts instead of manual positioning.
- Keep cards at modest radius, usually `8px` or less for operational tools.
- Keep CRM and dashboard screens dense, calm, and scan-friendly.
- Avoid one-off colors, one-off spacing, and decorative backgrounds that do not help the workflow.
- Do not let long text overflow buttons, chips, cards, tabs, or table cells.

## Modals and Drawers

- Use modals for focused workflows, quick forms, previews, and confirmations.
- Keep long or comparative workflows in a page or drawer instead of stacking modals.
- Every modal needs a clear title, close control, primary action, secondary action where needed, and visible validation/error state.
- CRM modals should use the simple movable/collapsible window behavior from `static/crm/crm-modals.js`.
- Avoid adding new modal styles outside the CRM feature folder unless the style is reusable globally.

## Forms

- Use labels for important fields, not placeholders alone.
- Show validation errors near the field or action area.
- Disable submit buttons while submitting.
- Preserve user input when validation fails.
- Use helpful messages such as "Password must be at least 8 characters" instead of "Invalid input."

## Tables and Data Views

- Keep table headings short and clear.
- Align text left and numeric values right when practical.
- Show empty states near the table body.
- Keep row actions consistent across CRM, dashboard, and admin pages.
- For mobile, prefer horizontal scroll or compact cards depending on the complexity of the row.

## Accessibility

- Use buttons for actions and links for navigation.
- Keep visible focus states.
- Ensure dropdowns, modals, and drawers are keyboard reachable.
- Add `aria-label` for icon-only buttons.
- Do not rely only on color to communicate status.
- Prefer semantic HTML before adding ARIA.

## Security

- Never put private keys or secrets in frontend code.
- Treat frontend permissions as UI convenience only; backend routes must enforce access.
- Sanitize rendered dynamic text and avoid raw HTML injection.
- Avoid logging sensitive user, customer, token, or invite data.

## Performance

- Keep heavy page behavior scoped to the active page.
- Debounce search inputs when they trigger network requests.
- Paginate or virtualize large lists where needed.
- Avoid loading unused scripts on pages that do not need them.
- Cache data where appropriate and refresh deliberately.

## Review Checklist

- Code is readable, named clearly, and split by responsibility.
- No dead code, unnecessary console logs, or hardcoded secrets.
- Loading, empty, error, success, and permission states are covered.
- Layout works on desktop and mobile.
- Forms validate clearly and preserve input.
- Buttons and links use correct semantic elements.
- Keyboard navigation and focus states are usable.
- API calls are not duplicated unnecessarily.
- Shared auth/session helpers are reused where possible.
- CRM-only frontend files live under `static/crm/` or `templates/crm/`.

## Practical PR Notes

When raising a frontend PR, include:

- Summary of what changed.
- Screenshots or recording for visible UI changes.
- States covered: loading, empty, error, success, permission denied.
- Manual testing done, including responsive checks where relevant.
- Risks or areas reviewers should inspect closely.

The golden rule for this repo: make the UI easy to use, and make the code easy to safely change later.
