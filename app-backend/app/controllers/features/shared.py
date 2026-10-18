import json

from flask import request

from app import config as app_config
from app.config import ALLOWED_EXTENSIONS, VIDEO_CONTENT_TYPES


def auth_ctx():
    return {
        'supabase_url': app_config.SUPABASE_URL,
        'supabase_anon_key': app_config.SUPABASE_ANON_KEY,
    }


def json_payload():
    data = request.get_json(silent=True)
    if isinstance(data, dict):
        return data
    raw = request.get_data(cache=True, as_text=True) or ''
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
    return {}


def is_truthy(value):
    if isinstance(value, bool):
        return value
    return str(value or '').strip().lower() in ('1', 'true', 'yes', 'y', 'on')


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def detect_video_ext_from_content_type(content_type):
    content_type = str(content_type or '').split(';', 1)[0].lower().strip()
    for ext, mime in VIDEO_CONTENT_TYPES.items():
        if content_type == mime:
            return ext
    if content_type in ('video/x-m4v',):
        return 'mp4'
    return ''
