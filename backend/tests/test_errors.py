"""Tests for structured error responses required by STORY-012."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_unknown_route_returns_structured_404() -> None:
    response = client.get("/this-route-does-not-exist")

    assert response.status_code == 404
    body = response.json()
    assert "error" in body
    assert body["error"]["status_code"] == 404
