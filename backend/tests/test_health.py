"""Tests for the /health endpoint required by STORY-012's acceptance criteria."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_returns_200() -> None:
    response = client.get("/health")

    assert response.status_code == 200


def test_health_reports_service_status() -> None:
    response = client.get("/health")
    body = response.json()

    assert body["status"] == "ok"
    assert "service" in body
    assert "environment" in body
