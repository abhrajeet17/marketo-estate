"""
Application factory. Creates Flask app, loads config, registers blueprints.
"""
import os
import sys
import traceback

from flask import Flask, abort, request
from jinja2 import ChoiceLoader, FileSystemLoader

from app import paths

_DOTENV = paths.DOTENV_PATH
try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=_DOTENV)
except Exception:
    pass

# SSL / cert fix for Supabase
if os.environ.get('SUPABASE_SSL_VERIFY', 'true').lower() in ('false', '0', 'no'):
    import ssl
    ssl._create_default_https_context = ssl._create_unverified_context
try:
    import certifi
    os.environ.setdefault('SSL_CERT_FILE', certifi.where())
    os.environ.setdefault('REQUESTS_CA_BUNDLE', certifi.where())
except ImportError:
    pass


def _register_error_handlers(app):
    from flask import jsonify, request
    from postgrest.exceptions import APIError

    @app.errorhandler(APIError)
    def _postgrest_error(exc):
        # 22P02: a malformed id (e.g. a mistyped share link) is a missing resource, not a crash.
        status = 404 if getattr(exc, 'code', None) == '22P02' else 500
        message = 'Not found' if status == 404 else 'Database request failed'
        if request.path.startswith('/api/'):
            return jsonify({'error': message}), status
        return message, status


def _warm_up_clients():
    """Build the Supabase and storage clients when the worker starts, not on its first request.

    Importing the SDK and loading the TLS trust store costs ~2s; a background query then opens
    the pooled connection so the first real request does not pay the handshake either.
    """
    import threading

    from app.core.database import get_supabase
    from app.services.storage_service import get_s3_client

    sb = get_supabase()
    get_s3_client()

    def open_pool():
        try:
            sb.table('profiles').select('user_id').limit(1).execute()
        except Exception:
            pass

    if sb is not None:
        threading.Thread(target=open_pool, name='supabase-warmup', daemon=True).start()


def create_app():
    try:
        from app import config as app_config
        from app.core.static_assets import send_static_file

        # Templates and static assets live in the UI folders (see app/paths.py).
        app = Flask(__name__, static_folder=None)
        app.jinja_loader = ChoiceLoader([FileSystemLoader(d) for d in paths.TEMPLATE_DIRS])

        @app.route('/static/<path:filename>', endpoint='static')
        def serve_static(filename):
            root = paths.find_static_dir(filename)
            if not root:
                abort(404)
            # ES modules import each other without version query strings: always revalidate them.
            if filename.startswith(paths.UNVERSIONED_MODULE_DIRS):
                return send_static_file(root, filename, max_age=0)
            return send_static_file(root, filename, immutable=request.args.get('v') == ui_asset_v)

        app.secret_key = app_config.SECRET_KEY or os.urandom(24).hex()
        app.config['UPLOAD_FOLDER'] = app_config.UPLOAD_FOLDER
        app.config['MAX_CONTENT_LENGTH'] = app_config.MAX_CONTENT_LENGTH
        app.config['SEND_FILE_MAX_AGE_DEFAULT'] = getattr(app_config, 'SEND_FILE_MAX_AGE_DEFAULT', 86400)
        app.config['JSON_SORT_KEYS'] = getattr(app_config, 'JSON_SORT_KEYS', False)
        app.config['COMPRESS_MIN_SIZE'] = getattr(app_config, 'COMPRESS_MIN_SIZE', 500)
        app.config['COMPRESS_LEVEL'] = getattr(app_config, 'COMPRESS_LEVEL', 6)
        app.config['COMPRESS_MIMETYPES'] = getattr(app_config, 'COMPRESS_MIMETYPES', [
            'text/html', 'text/css', 'text/xml', 'application/json',
            'application/javascript', 'text/javascript', 'image/svg+xml',
        ])

        try:
            from flask_compress import Compress
            Compress(app)
        except ImportError:
            pass

        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

        # Cache-busting token ({{ ui_asset_v }}): newest mtime of the UI code folders, so every
        # deploy that touches them invalidates browser caches.
        ui_dirs = [os.path.join(root, sub) for root in paths.STATIC_DIRS for sub in ('ui', 'crm', 'css', 'js')]

        def _compute_ui_asset_v():
            try:
                return str(int(max(
                    os.path.getmtime(os.path.join(dirpath, name))
                    for ui_dir in ui_dirs
                    for dirpath, _dirs, files in os.walk(ui_dir) for name in files
                )))
            except ValueError:
                return '1'

        ui_asset_v = _compute_ui_asset_v()

        @app.context_processor
        def _ui_asset_version():
            # Recompute while developing so edited CSS/JS is never served stale.
            return {'ui_asset_v': _compute_ui_asset_v() if app.debug else ui_asset_v}

        from app.core import perf
        perf.init_app(app)

        # Register all routes (controllers)
        from app.controllers.register import register_routes
        register_routes(app)
        _register_error_handlers(app)
        _warm_up_clients()

        return app
    except Exception:
        traceback.print_exc(file=sys.stderr)
        sys.stderr.flush()
        raise


# Expose app for gunicorn: "gunicorn app:app" loads the app package and needs this attribute
app = create_app()
