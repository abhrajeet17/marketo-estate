import os

from flask import abort, send_from_directory


def register_asset_routes(app):
    lottie_dir = os.path.join(app.root_path, 'lottiefiles')

    @app.route('/app/lottiefiles/<path:filename>', methods=['GET'])
    def serve_app_lottie_file(filename):
        if not filename:
            abort(404)
        lower = filename.lower()
        if not (lower.endswith('.lottie') or lower.endswith('.svg')):
            abort(404)
        return send_from_directory(lottie_dir, filename)
