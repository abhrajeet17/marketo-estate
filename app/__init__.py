"""
Application factory. Creates Flask app, loads config, registers blueprints.
"""
import os
import sys
import traceback

from flask import Flask

# Load .env from project root
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DOTENV = os.path.join(_ROOT, '.env')
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


def create_app():
    try:
        from app import config as app_config

        app = Flask(
            __name__,
            static_folder=os.path.join(_ROOT, 'static'),
            template_folder=os.path.join(_ROOT, 'templates'),
        )
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
        os.makedirs(os.path.join(_ROOT, 'templates'), exist_ok=True)
        os.makedirs(os.path.join(_ROOT, 'static'), exist_ok=True)

        # Register all routes (controllers)
        from app.controllers.register import register_routes
        register_routes(app)

        return app
    except Exception:
        traceback.print_exc(file=sys.stderr)
        sys.stderr.flush()
        raise


# Expose app for gunicorn: "gunicorn app:app" loads the app package and needs this attribute
app = create_app()
