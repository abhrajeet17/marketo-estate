"""
Fixtures for the backend unit tests.

Unit tests are hermetic: they never reach Supabase, storage or any other host. The Flask app is
imported as usual (so routes and templates are the real ones), but every outbound connection is
refused by `no_network`, and the database client is replaced where a test needs one.
"""
import os
import socket
import sys

import pytest

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Fail loudly if code under test tries to open a connection to another machine."""
    real_connect = socket.socket.connect

    def guarded(sock, address):
        host = address[0] if isinstance(address, tuple) else address
        if host in ('127.0.0.1', 'localhost', '::1'):
            return real_connect(sock, address)
        raise AssertionError(f'unit test tried to reach the network: {address!r}')

    monkeypatch.setattr(socket.socket, 'connect', guarded)


@pytest.fixture(scope='session')
def flask_app():
    from app import app
    app.config.update(TESTING=True)
    return app


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


@pytest.fixture
def offline_auth(monkeypatch):
    """Token checks without any remote verification: only locally signed HS256 tokens count."""
    import app.core.auth as auth
    monkeypatch.setattr(auth, 'SUPABASE_URL', '')
    monkeypatch.setattr(auth, 'CLERK_ISSUER', '')
    monkeypatch.setattr(auth, 'CLERK_JWKS_URL', '')
    return auth


class FakeQuery:
    """Just enough of the supabase-py query builder for profile lookups."""

    def __init__(self, rows):
        self._rows = list(rows)

    def select(self, *_a, **_k):
        return self

    def eq(self, column, value):
        self._rows = [r for r in self._rows if str(r.get(column)) == str(value)]
        return self

    def limit(self, n):
        self._rows = self._rows[:n]
        return self

    def upsert(self, *_a, **_k):
        return self

    def insert(self, *_a, **_k):
        return self

    def update(self, *_a, **_k):
        return self

    def execute(self):
        return type('Result', (), {'data': self._rows, 'count': len(self._rows)})()


class FakeSupabase:
    def __init__(self, tables=None):
        self.tables = tables or {}

    def table(self, name):
        return FakeQuery(self.tables.get(name, []))


@pytest.fixture
def fake_sb():
    return FakeSupabase


@pytest.fixture
def world(flask_app, monkeypatch, tmp_path):
    """A seeded in-memory database and storage behind the real app (see world.py)."""
    from world import World
    return World(flask_app, monkeypatch, tmp_path)


@pytest.fixture
def make_world(flask_app, monkeypatch, tmp_path):
    """Factory for fresh worlds inside one test (each call re-seeds everything)."""
    from world import World
    return lambda: World(flask_app, monkeypatch, tmp_path)


@pytest.fixture(autouse=True)
def no_leaked_flask_context():
    """Every test must leave Flask's app/request context stack empty; a leak breaks later tests."""
    from flask.globals import _cv_app, _cv_request
    assert _cv_app.get(None) is None and _cv_request.get(None) is None, 'a previous test leaked a Flask context'
    yield
    assert _cv_app.get(None) is None and _cv_request.get(None) is None, 'this test leaked a Flask context'
