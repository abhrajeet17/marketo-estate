import time

import pytest

from app.services import storage_service


class FakeS3:
    def __init__(self, missing=()):
        self.heads = 0
        self.signs = 0
        self.missing = set(missing)

    def head_object(self, Bucket, Key):
        self.heads += 1
        if Key in self.missing:
            raise KeyError(Key)

    def generate_presigned_url(self, ClientMethod, Params, ExpiresIn):
        self.signs += 1
        return f"https://storage.test/{Params['Key']}?sig={self.signs}&exp={ExpiresIn}"


@pytest.fixture
def s3(monkeypatch):
    fake = FakeS3(missing={'gone.jpg'})
    monkeypatch.setattr(storage_service, 'get_s3_client', lambda: fake)
    monkeypatch.setattr(storage_service.app_config, 'SUPABASE_S3_BUCKET', 'bucket')
    monkeypatch.setattr(storage_service.app_config, 'SUPABASE_S3_SIGNED_URL_TTL', 3600)
    storage_service._s3_signed_url_cache.clear()
    yield fake
    storage_service._s3_signed_url_cache.clear()


def test_url_is_reused_without_new_storage_calls(s3):
    first = storage_service.get_signed_get_url('a.jpg')
    second = storage_service.get_signed_get_url('a.jpg')
    assert first == second
    assert (s3.heads, s3.signs) == (1, 1)


def test_missing_object_gives_none_and_is_not_cached(s3):
    assert storage_service.get_signed_get_url('gone.jpg') is None
    assert 'gone.jpg' not in storage_service._s3_signed_url_cache


def test_reuse_stops_at_half_life(s3, monkeypatch):
    storage_service.get_signed_get_url('a.jpg')
    assert storage_service.signed_url_reuse_seconds() == 1800
    real = time.time
    monkeypatch.setattr(storage_service.time, 'time', lambda: real() + 1801)
    storage_service.get_signed_get_url('a.jpg')
    assert s3.signs == 2


def test_forget_drops_cached_url(s3):
    storage_service.get_signed_get_url('a.jpg')
    storage_service.forget_signed_url('a.jpg', None)
    storage_service.get_signed_get_url('a.jpg')
    assert s3.signs == 2


def test_no_key_or_client(s3, monkeypatch):
    assert storage_service.get_signed_get_url('') is None
    monkeypatch.setattr(storage_service, 'get_s3_client', lambda: None)
    assert storage_service.get_signed_get_url('a.jpg') is None
