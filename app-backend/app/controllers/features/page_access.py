from flask import jsonify, request

from app import config as app_config
from app.config import PAGE_ACCESS_TOKEN_TTL
from app.core.auth import require_auth
from app.core.database import get_supabase
from app.core.serializers import issue_page_access_token
from app.services.panorama_service import get_panorama_with_access
from app.services.uam_reference_service import user_is_client_admin


def register_page_access_routes(app):
    @app.route('/api/panoramas/<int:panorama_id>/page-token', methods=['POST'])
    @require_auth
    def create_panorama_page_token(user_id, role, panorama_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503

        payload = request.get_json(silent=True) or {}
        mode = str(payload.get('mode') or '').strip().lower()
        if mode not in ('admin', 'client'):
            return jsonify({'error': 'mode must be admin or client'}), 400

        panorama, access_type = get_panorama_with_access(sb, panorama_id, user_id)
        if not panorama:
            return jsonify({'error': 'Panorama not found'}), 404

        if mode == 'admin':
            if access_type != 'owner':
                return jsonify({'error': 'Only owner can open admin mode'}), 403
        elif access_type not in ('owner', 'client'):
            if not user_is_client_admin(sb, user_id):
                return jsonify({'error': 'Only owner or client can open client mode'}), 403

        secret_key = app.secret_key or app_config.SECRET_KEY
        token = issue_page_access_token(secret_key, user_id, panorama_id, mode)
        return jsonify({
            'token': token,
            'mode': mode,
            'panorama_id': int(panorama_id),
            'expires_in': int(PAGE_ACCESS_TOKEN_TTL),
        })
