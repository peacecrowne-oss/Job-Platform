"""Tests for structured error responses required by STORY-012, plus a
STORY-043 regression proving an unhandled exception never leaks its
message/stack trace to the client -- only a fixed generic message.

search_rate_limit (STORY-045) is overridden to a no-op here too, for the
same reason test_search_api.py does it -- this file also calls the real
GET /jobs/search, which would otherwise attempt a real (failing) Redis
connection.
"""

from fastapi.testclient import TestClient

from app.api.search import search_rate_limit
from app.db import get_db
from app.main import app

client = TestClient(app, raise_server_exceptions=False)


def setup_module(module) -> None:
    app.dependency_overrides[search_rate_limit] = lambda: None


def teardown_module(module) -> None:
    app.dependency_overrides.pop(search_rate_limit, None)


def test_unknown_route_returns_structured_404() -> None:
    response = client.get("/this-route-does-not-exist")

    assert response.status_code == 404
    body = response.json()
    assert "error" in body
    assert body["error"]["status_code"] == 404


def test_unhandled_exception_returns_generic_message_only() -> None:
    """STORY-043: a real internal exception (a secret-looking message, to
    prove it's genuinely never echoed back) must never reach the client."""

    def _raise_secret():
        raise RuntimeError("db password is hunter2, connection string leaked")
        yield  # pragma: no cover -- unreachable, keeps this a generator

    app.dependency_overrides[get_db] = _raise_secret
    try:
        response = client.get("/jobs/search")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 500
    body = response.json()
    assert body == {"error": {"message": "Internal server error"}}
    assert "hunter2" not in response.text
    assert "RuntimeError" not in response.text
    assert "Traceback" not in response.text
