"""
Filesystem layout of the repository.

    <repo>/app-backend          Flask application (this package)
    <repo>/admin-dashboard-ui   builder back-office pages and assets
    <repo>/client-ui            client team, broker and customer-facing pages and assets
    <repo>/shared-ui            base layout, auth pages and assets used by both UIs

Every UI folder has a `templates/` and a `static/` directory. They are merged at
runtime, so template names and `/static/...` URLs are the same as before the split.
"""
import os

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(BACKEND_DIR)

# Lookup order matters only for name collisions, which the layout forbids.
UI_PACKAGES = ('admin-dashboard-ui', 'client-ui', 'shared-ui')
UI_DIRS = tuple(os.path.join(REPO_ROOT, name) for name in UI_PACKAGES)
TEMPLATE_DIRS = tuple(os.path.join(d, 'templates') for d in UI_DIRS)
STATIC_DIRS = tuple(os.path.join(d, 'static') for d in UI_DIRS)

# Static folders holding ES modules (served with revalidation instead of a 1-day cache).
UNVERSIONED_MODULE_DIRS = ('js/dashboard/',)

DOTENV_PATH = os.path.join(REPO_ROOT, '.env')
UPLOADS_DIR = os.path.join(REPO_ROOT, 'uploads')


def find_static_dir(filename):
    """Return the static root that contains `filename`, or None."""
    rel = os.path.normpath(filename)
    if rel.startswith('..') or os.path.isabs(rel):
        return None
    for root in STATIC_DIRS:
        if os.path.isfile(os.path.join(root, rel)):
            return root
    return None


def static_file_path(filename):
    root = find_static_dir(filename)
    return os.path.join(root, filename) if root else None


def static_module_urls(directory):
    """Public URLs of every ES module under a static directory (for <link rel="modulepreload">)."""
    root = find_static_dir(os.path.join(directory, 'main.js'))
    if not root:
        return []
    base = os.path.join(root, directory)
    urls = []
    for dp, _dirs, files in os.walk(base):
        for name in sorted(files):
            if name.endswith('.js') and name != 'main.js':
                rel = os.path.relpath(os.path.join(dp, name), root).replace(os.sep, '/')
                urls.append('/static/' + rel)
    return sorted(urls)
