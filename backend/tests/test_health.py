"""Tests for /health (STORY-012's acceptance criteria) and the STORY-052
liveness/readiness routes it grew alongside."""

from unittest.mock import patch

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


# --- STORY-052: liveness ---


def test_health_live_returns_200() -> None:
    response = client.get("/health/live")

    assert response.status_code == 200


def test_health_live_matches_health_response_shape() -> None:
    """/health and /health/live are the same check under two names --
    STORY-052 keeps /health as a permanent, unchanged alias."""
    live_body = client.get("/health/live").json()
    health_body = client.get("/health").json()

    assert live_body == health_body


def test_health_live_never_checks_postgres_or_redis() -> None:
    """The literal AC: liveness does not report unhealthy for a
    dependency -- proven here by confirming it never even calls either
    check, not just that it happens to return 200."""
    with (
        patch("app.api.health.check_database_connection") as pg_check,
        patch("app.api.health.check_redis_connection") as redis_check,
    ):
        response = client.get("/health/live")

    assert response.status_code == 200
    pg_check.assert_not_called()
    redis_check.assert_not_called()


# --- STORY-052: readiness ---


def test_health_ready_returns_200_when_both_dependencies_ok() -> None:
    with (
        patch("app.api.health.check_database_connection", return_value=True),
        patch("app.api.health.check_redis_connection", return_value=True),
    ):
        response = client.get("/health/ready")

    assert response.status_code == 200
    body = response.json()
    assert body == {"status": "ready", "checks": {"postgres": "ok", "redis": "ok"}}


def test_health_ready_returns_503_when_postgres_unreachable() -> None:
    with (
        patch("app.api.health.check_database_connection", return_value=False),
        patch("app.api.health.check_redis_connection", return_value=True),
    ):
        response = client.get("/health/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["checks"]["postgres"] == "unreachable"
    assert body["checks"]["redis"] == "ok"


def test_health_ready_returns_503_when_redis_unreachable() -> None:
    with (
        patch("app.api.health.check_database_connection", return_value=True),
        patch("app.api.health.check_redis_connection", return_value=False),
    ):
        response = client.get("/health/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["checks"]["postgres"] == "ok"
    assert body["checks"]["redis"] == "unreachable"


def test_health_ready_returns_503_when_both_unreachable() -> None:
    with (
        patch("app.api.health.check_database_connection", return_value=False),
        patch("app.api.health.check_redis_connection", return_value=False),
    ):
        response = client.get("/health/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["checks"] == {"postgres": "unreachable", "redis": "unreachable"}


def test_health_ready_handles_unexpected_exception_without_leaking_it() -> None:
    """STORY-052: a malformed-configuration-style failure (some exception
    other than the specific type each helper already catches) must never
    produce a raw 500 or leak exception text -- caught broadly, reported
    as "unreachable" like any other failure."""
    with (
        patch(
            "app.api.health.check_database_connection",
            side_effect=RuntimeError("unexpected: password=hunter2"),
        ),
        patch("app.api.health.check_redis_connection", return_value=True),
    ):
        response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["checks"]["postgres"] == "unreachable"
    assert "hunter2" not in response.text
    assert "RuntimeError" not in response.text
    assert "Traceback" not in response.text


def test_health_ready_response_never_contains_connection_details() -> None:
    with (
        patch("app.api.health.check_database_connection", return_value=False),
        patch("app.api.health.check_redis_connection", return_value=False),
    ):
        response = client.get("/health/ready")

    text = response.text
    assert "postgresql" not in text.lower()
    assert "redis://" not in text
    assert "changeme" not in text.lower()
