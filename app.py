"""
Real Estate Panorama Plot Marker - Flask Application
Entry point: creates app via app package (controller/service structure).
"""
import os

from app import app

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_ENV', 'development') != 'production'
    # Keep debug mode, but allow tighter control over auto-reloader behavior.
    use_reloader = os.environ.get('FLASK_USE_RELOADER', '1').strip().lower() not in ('0', 'false', 'no')
    reloader_type = os.environ.get('FLASK_RELOADER_TYPE', 'stat').strip() or 'stat'
    # Windows path list is semicolon-separated; skip empty values.
    raw_excludes = os.environ.get('FLASK_RELOAD_EXCLUDE', '').strip()
    exclude_patterns = [p.strip() for p in raw_excludes.split(';') if p.strip()]
    app.run(
        debug=debug,
        host='0.0.0.0',
        port=port,
        use_reloader=(debug and use_reloader),
        reloader_type=reloader_type,
        exclude_patterns=exclude_patterns,
    )
