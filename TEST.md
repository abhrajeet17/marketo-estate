# Testing

Run the full test suite **after every change and before every deployment**. One command runs
everything and writes a summary:

```bash
cd app-backend
python tests/run_all.py --write
```

It exits with code 0 only when every suite passed. The result is in `app-backend/tests/reports/summary.md`.

## One-time setup

```bash
pip install -r requirements-dev.txt     # from the repository root: app deps + pytest + playwright
```

* Browser tests use the **Google Chrome** installed on the machine. No browser download is needed.
  Without Chrome, run `python -m playwright install chromium` and they fall back to Playwright's Chromium.
* The API and browser tests use the Supabase project in `.env`, the same one the app uses.
  No password is needed: they sign in as the first platform admin with a short-lived token
  signed by `SUPABASE_JWT_SECRET`.

## What runs

| Suite | Command | Needs | Time | Writes data? |
|---|---|---|---|---|
| Backend unit tests | `python -m pytest tests/unit -q` | nothing (offline) | ~10 s | never |
| API tests | `python -m pytest tests/perf -q` | `.env` database | ~1 min | never (GET only) |
| End-to-end in Chrome | `python -m pytest tests/e2e -q` | `.env` database, Chrome | ~6 min | only with `E2E_WRITE=1` |

Run each command from `app-backend/`. `run_all.py` runs all three in that order.

### Backend unit tests: `app-backend/tests/unit/`
Hermetic. Any attempt to reach the network fails the test.
* **Auth**:
  * Missing, invalid, expired or wrong-secret tokens are rejected.
  * Roles come from the profile, never from the token.
  * Admin and superadmin gates work.
  * **Every private `/api/` route rejects anonymous calls.** This sweep covers all ~250 route/method pairs, and new routes are picked up automatically.
* **Routes**: no duplicate routes.
* **Pages**:
  * All admin pages render.
  * `/projectselection` has no Workspace links, no sidebar upload and no project rail, but has the share-link dialogs.
  * Workspace pages render the project rail left of the sidebar.
  * Per-page project pickers are hidden.
  * Admins land on `/projectselection`.
* **Static files**:
  * Brotli or gzip compression is lossless.
  * `ETag` returns 304 when unchanged.
  * A deploy-token URL is cached for a year as immutable.
  * Path traversal is blocked.
* **Concurrency and timing**:
  * Parallel reads keep call order and strict-mode errors.
  * Request timing follows reads into worker threads.
  * The `Server-Timing` header is present.
* **Storage**: signed URLs are reused until half their lifetime and dropped after a delete.
* **Page tokens**: they round-trip, expire, and can't be reused across secrets or salts.
* **SEO** (`test_seo.py`):
  * The landing page has its title, description, canonical, Open Graph tags and a single keyword H1.
  * Its JSON-LD (Organization, WebSite, SoftwareApplication, FAQPage) matches the visible FAQ.
  * `robots.txt` welcomes search and AI crawlers and lists the sitemap; `sitemap.xml` and `llms.txt` are served.
  * `SITE_URL` and proxy https set the canonical domain.
  * Only `/` and `/explore` are indexable; every app page sends `X-Robots-Tag: noindex`.

### API tests: `app-backend/tests/perf/`
* Calls every GET route as admin, superadmin, broker, user and public.
* Fails on any 5xx, or on a warm response slower than `PERF_BUDGET_MS` (500 ms).
* Report: `tests/perf/reports/api_timings.md`, with query counts and a projected production time.
* `PERF_TRACE=1` lists every query.
* `python tests/perf/snapshot_responses.py` records all API responses so you can compare them before and after a refactor.

### End-to-end in Chrome: `app-backend/tests/e2e/`
Starts the app on port 5055 if nothing is listening there, then drives real Chrome.
* **`test_project_selection.py`**:
  * A Workspace page with no project redirects to `/projectselection`.
  * Cards show the right projects; the sidebar has no Workspace links and no upload.
  * The 3-dots menu has all project actions and share links.
  * **Copy Full View link**: the copied link opens for a visitor who isn't signed in.
  * Open Full View opens a new tab.
  * The Create custom link and Share reference link dialogs open.
  * Edit details loads the project.
  * The New project and Upload dialogs open.
  * Search filters the cards.
  * Picking a project opens its dashboard and marks it as current.
* **`test_project_scope.py`**, the global project filter:
  * The dashboard shows exactly that project's panoramas.
  * The rail highlights the project and shows names only on hover.
  * Each page loads only that project's data: Sales Tools (all 6 lists + the Day/Night embed), Building Plans, Full View (opens the builder) and Day/Night. The test checks the `workspace_id` on each page's API calls.
  * Switching projects from the rail keeps you on the same page.
  * A `?workspace_id=` link becomes the active project.
  * A deleted project sends you back to selection.
  * There's no sideways scrolling at phone width.
* **`test_dashboard.py`**:
  * The 360°/Flat filter works, and search stays inside the project.
  * The panorama menu has its actions.
  * Clicking a panorama opens the editor.
  * Upload defaults to the current project.
  * The unlinked panoramas view works.
* **`test_all_pages.py`**:
  * Every page of the product opens: about 44 admin, editor and public customer/share pages.
  * The page must return HTTP < 400, raise no uncaught JS errors and get no 5xx API answers.
  * A signed-in admin is never sent to the login page.
* **`test_write_flows.py`** (`E2E_WRITE=1` or `--write`):
  * Through the UI: create a project, rename it, check the rail shows the new name, then delete it.
  * The project is named `[e2e] …` and is always deleted, even when the test fails. No existing data is touched.

Failed browser tests save a full-page screenshot to `tests/e2e/reports/FAIL_<test>.png`.

## Useful options

```bash
python tests/run_all.py --quick                    # skip the API suite (unit + browser)
python tests/run_all.py --only unit                # one suite (unit | api | e2e)
python tests/run_all.py --headed                   # watch Chrome while it runs
python tests/run_all.py --base-url http://localhost:5000   # test a server you already run
python -m pytest tests/e2e -q -k rail              # pick browser tests by name
E2E_HEADED=1 python -m pytest tests/e2e/test_dashboard.py -q
python tests/perf/ui_smoke.py http://127.0.0.1:5055        # page-by-page timing report (no assertions)
```

## Before deploying

1. `python tests/run_all.py --write` passes, and `summary.md` says **ALL PASSED**.
2. Database changes are additive scripts in `app-backend/db/` and have been applied.
3. After deploying, open `/projectselection` and one Workspace page in production as a final check.

## Known limits

* The test login is accepted by the backend but not by Supabase's own REST API. The editor's direct
  `plot_markers` reads (supabase-js) therefore can't be tested here; check them with a real login.
* File uploads to storage aren't exercised (the dialogs are). Test a real upload manually when changing upload code.
* The tests share the configured database, so counts follow your real data. A test that needs data
  that doesn't exist, such as unlinked panoramas or a second project, is skipped, not failed.
