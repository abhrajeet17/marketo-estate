# Scaling Coding Practices (Modular Monolith)

This project will stay monolithic, but it must stay modular as we grow.

## 1. Core Rules

- Keep domain logic in `app/services/*`.
- Keep route handlers thin and focused on request/response shape.
- Keep database access centralized through service functions.
- Prefer small feature files over one giant controller file.

## 2. Mandatory `register.py` Extraction Rule

`app/controllers/register.py` is currently oversized. To reduce it safely over time, follow this rule on every change:

1. If you touch any API route in `register.py`, move the touched route(s) into a feature controller file in the same change.
2. If no suitable file exists, create a new one under `app/controllers/features/` (for example `client_access.py`, `crm_contacts.py`, `workspaces.py`).
3. Register that feature module through `app/controllers/features/__init__.py`.
4. Wire it from `register.py` using `register_<feature>_routes(app)`.
5. Keep behavior and response shape backward-compatible unless the task explicitly requires a breaking change.

### Enforcement intent

- No new API routes should be added directly to `register.py` unless they are temporary bootstrap routes that will be extracted immediately.
- Every edit should reduce or keep stable the `register.py` route count.

## 3. Folder-by-Domain Structure

- Controllers: `app/controllers/features/<domain>.py`
- Services: `app/services/<domain>_service.py`
- Templates/CSS/JS: grouped by domain name where possible
- SQL migrations: single responsibility per migration file

## 4. API Quality Standards

- Validate input at the boundary.
- Return consistent error payloads.
- Keep auth/permission checks explicit near each route.
- Reuse shared helpers instead of redefining utility functions.

## 5. Database and Migration Standards

- One migration per schema change theme.
- Use reversible/defensive SQL (`if exists`, safe guards).
- Never mix unrelated schema changes in one migration.

## 6. Testing and Safety

- Add or update tests for every moved route and behavior-sensitive change.
- Verify no route path/method regressions after extraction.
- Keep extraction PRs small and scoped to one domain when possible.

## 7. PR Checklist

- [ ] Any touched `register.py` API was extracted to `app/controllers/features/*`.
- [ ] `app/controllers/features/__init__.py` updated if a new feature module was created.
- [ ] Service-layer reuse added instead of copy/paste logic.
- [ ] Manual smoke check done for affected APIs and templates.
