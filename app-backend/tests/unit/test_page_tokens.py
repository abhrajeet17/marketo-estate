import pytest
from itsdangerous import BadSignature, SignatureExpired

from app.core.serializers import issue_page_access_token, page_access_serializer, panorama_upload_serializer


def test_round_trip():
    token = issue_page_access_token('secret', 'user-1', '57', 'Admin ')
    assert page_access_serializer('secret').loads(token, max_age=60) == {'uid': 'user-1', 'pid': 57, 'mode': 'admin'}


def test_other_secret_rejected():
    token = issue_page_access_token('secret', 'user-1', 57, 'admin')
    with pytest.raises(BadSignature):
        page_access_serializer('other').loads(token)


def test_salts_do_not_mix():
    token = issue_page_access_token('secret', 'user-1', 57, 'admin')
    with pytest.raises(BadSignature):
        panorama_upload_serializer('secret').loads(token)


def test_expiry(monkeypatch):
    token = issue_page_access_token('secret', 'user-1', 57, 'admin')
    import time
    real = time.time
    monkeypatch.setattr(time, 'time', lambda: real() + 3600)
    with pytest.raises(SignatureExpired):
        page_access_serializer('secret').loads(token, max_age=60)
