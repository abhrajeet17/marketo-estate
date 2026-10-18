"""
Token serializers for upload and page-access tokens.
Secret key is passed so this module does not depend on Flask app at import time.
"""
from itsdangerous import URLSafeTimedSerializer


def panorama_upload_serializer(secret_key):
    return URLSafeTimedSerializer(secret_key, salt='panorama-upload')


def plot_upload_serializer(secret_key):
    return URLSafeTimedSerializer(secret_key, salt='plot-image-upload')


def marker_upload_serializer(secret_key):
    return URLSafeTimedSerializer(secret_key, salt='marker-image-upload')


def daynight_upload_serializer(secret_key):
    return URLSafeTimedSerializer(secret_key, salt='daynight-video-upload')


def page_access_serializer(secret_key):
    return URLSafeTimedSerializer(secret_key, salt='page-access')


def issue_page_access_token(secret_key, user_id, panorama_id, mode):
    return page_access_serializer(secret_key).dumps({
        'uid': str(user_id),
        'pid': int(panorama_id),
        'mode': str(mode or '').strip().lower(),
    })
