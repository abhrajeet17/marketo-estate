"""
Application configuration from environment.
"""
import os

DEFAULT_MAX_UPLOAD_BYTES = 50 * 1024 * 1024
MAX_DAYNIGHT_VIDEO_BYTES = int(os.environ.get('MAX_DAYNIGHT_VIDEO_BYTES', str(200 * 1024 * 1024)))
MAX_UPLOAD_OVERHEAD_BYTES = int(os.environ.get('MAX_UPLOAD_OVERHEAD_BYTES', str(5 * 1024 * 1024)))
CONFIGURED_MAX_UPLOAD_BYTES = int(os.environ.get('MAX_UPLOAD_BYTES', '0') or 0)

# Flask
SECRET_KEY = os.environ.get('FLASK_SECRET_KEY', '')
UPLOAD_FOLDER = 'uploads'
# Keep Flask's request-body cap aligned with the largest supported upload
# plus multipart overhead so large day/night videos aren't rejected early.
MAX_CONTENT_LENGTH = max(
    DEFAULT_MAX_UPLOAD_BYTES,
    CONFIGURED_MAX_UPLOAD_BYTES,
    MAX_DAYNIGHT_VIDEO_BYTES + MAX_UPLOAD_OVERHEAD_BYTES,
)
# Performance: cache static files (seconds); 1 day default
SEND_FILE_MAX_AGE_DEFAULT = int(os.environ.get('SEND_FILE_MAX_AGE_DEFAULT', str(86400)))
# Slightly faster JSON responses (no key sorting)
JSON_SORT_KEYS = False
# Compression: min size in bytes to compress (Flask-Compress)
COMPRESS_MIN_SIZE = int(os.environ.get('COMPRESS_MIN_SIZE', '500'))
COMPRESS_LEVEL = int(os.environ.get('COMPRESS_LEVEL', '6'))
COMPRESS_MIMETYPES = [
    'text/html', 'text/css', 'text/xml', 'application/json',
    'application/javascript', 'text/javascript', 'image/svg+xml',
]

# Supabase
SUPABASE_URL = os.environ.get('SUPABASE_URL', '').rstrip('/')
SUPABASE_ANON_KEY = os.environ.get('SUPABASE_ANON_KEY', '')
SUPABASE_SERVICE_ROLE_KEY = os.environ.get('SUPABASE_SERVICE_ROLE_KEY', '')
SUPABASE_JWT_SECRET = os.environ.get('SUPABASE_JWT_SECRET', '')

# Clerk (for authenticating requests from Clerk-powered frontend)
CLERK_ISSUER = os.environ.get('CLERK_ISSUER', '').strip()
CLERK_JWKS_URL = os.environ.get('CLERK_JWKS_URL', '').strip()

# Supabase S3
SUPABASE_S3_ENDPOINT = os.environ.get(
    'SUPABASE_S3_ENDPOINT',
    'https://qavugigprqbnslywkmri.storage.supabase.co/storage/v1/s3',
).rstrip('/')
SUPABASE_S3_REGION = os.environ.get('SUPABASE_S3_REGION', 'ap-south-1')
SUPABASE_S3_BUCKET = os.environ.get('SUPABASE_S3_BUCKET', '').strip()
SUPABASE_S3_ACCESS_KEY_ID = (
    os.environ.get('SUPABASE_S3_ACCESS_KEY_ID') or os.environ.get('AWS_ACCESS_KEY_ID', '')
).strip()
SUPABASE_S3_SECRET_ACCESS_KEY = (
    os.environ.get('SUPABASE_S3_SECRET_ACCESS_KEY') or os.environ.get('AWS_SECRET_ACCESS_KEY', '')
).strip()
SUPABASE_S3_PANORAMA_PREFIX = os.environ.get('SUPABASE_S3_PANORAMA_PREFIX', 'panoramas').strip('/')
SUPABASE_S3_SIGNED_URL_TTL = max(60, int(os.environ.get('SUPABASE_S3_SIGNED_URL_TTL', '3600')))
SUPABASE_S3_UPLOAD_URL_TTL = max(60, int(os.environ.get('SUPABASE_S3_UPLOAD_URL_TTL', '900')))
SUPABASE_S3_PLOT_PREFIX = os.environ.get('SUPABASE_S3_PLOT_PREFIX', 'plot-images').strip('/')
SUPABASE_S3_MARKER_PREFIX = os.environ.get('SUPABASE_S3_MARKER_PREFIX', 'marker-images').strip('/')
SUPABASE_S3_VOICEOVER_PREFIX = os.environ.get('SUPABASE_S3_VOICEOVER_PREFIX', 'marker-voiceovers').strip('/')
SUPABASE_S3_PANORAMA_AUDIO_PREFIX = os.environ.get('SUPABASE_S3_PANORAMA_AUDIO_PREFIX', 'panorama-audio').strip('/')
SUPABASE_S3_DAYNIGHT_PREFIX = os.environ.get('SUPABASE_S3_DAYNIGHT_PREFIX', 'daynight').strip('/')
SUPABASE_S3_FLOORPLAN_PREFIX = os.environ.get('SUPABASE_S3_FLOORPLAN_PREFIX', 'floor-plans').strip('/')
SUPABASE_S3_BUILDING_MAP_PREFIX = os.environ.get('SUPABASE_S3_BUILDING_MAP_PREFIX', 'building-maps').strip('/')
SUPABASE_S3_GALLERY_PREFIX = os.environ.get('SUPABASE_S3_GALLERY_PREFIX', 'galleries').strip('/')
SUPABASE_S3_SALES_MAP_PREFIX = os.environ.get('SUPABASE_S3_SALES_MAP_PREFIX', 'sales-route-maps').strip('/')
SUPABASE_S3_SALES_FLAT360_PREFIX = os.environ.get('SUPABASE_S3_SALES_FLAT360_PREFIX', 'sales-flat360').strip('/')

PAGE_ACCESS_TOKEN_TTL = max(60, int(os.environ.get('PAGE_ACCESS_TOKEN_TTL', '900')))

# Allowed file types
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
ALLOWED_AUDIO_EXTENSIONS = {'mp3', 'wav', 'm4a', 'ogg', 'webm'}
ALLOWED_VIDEO_EXTENSIONS = {'mp4', 'webm', 'mov'}
VIDEO_CONTENT_TYPES = {
    'mp4': 'video/mp4', 'webm': 'video/webm', 'mov': 'video/quicktime',
}
AUDIO_CONTENT_TYPES = {
    'mp3': 'audio/mpeg', 'wav': 'audio/wav', 'm4a': 'audio/mp4',
    'ogg': 'audio/ogg', 'webm': 'audio/webm',
}
IMAGE_CONTENT_TYPES = {
    'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg',
    'gif': 'image/gif', 'webp': 'image/webp',
}
CONTENT_TYPE_TO_EXT = {
    'image/png': 'png',
    'image/jpeg': 'jpg',
    'image/gif': 'gif',
    'image/webp': 'webp',
}

# Email (optional SMTP; used for client team invite notifications)
SMTP_HOST = os.environ.get('SMTP_HOST', '').strip()
SMTP_PORT = int(os.environ.get('SMTP_PORT', '587'))
SMTP_USERNAME = os.environ.get('SMTP_USERNAME', '').strip()
SMTP_PASSWORD = os.environ.get('SMTP_PASSWORD', '').strip()
SMTP_USE_TLS = os.environ.get('SMTP_USE_TLS', 'true').strip().lower() not in ('0', 'false', 'no')
SMTP_FROM_EMAIL = os.environ.get('SMTP_FROM_EMAIL', '').strip()
SMTP_FROM_NAME = os.environ.get('SMTP_FROM_NAME', 'MarketoState').strip()

# Brevo transactional API (preferred when API key is present)
BREVO_API_KEY = os.environ.get('BREVO_API_KEY', '').strip()
