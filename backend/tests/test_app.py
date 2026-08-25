"""Application-foundation tests for STORY-012.

Verifies the app can be imported, instantiated via the factory, and that
routing/bootstrap does not fail — without requiring any external
infrastructure (no live Postgres, Redis, network, or ATS services).
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import app, create_app


def test_create_app_returns_fastapi_instance() -> None:
    application = create_app()

    assert isinstance(application, FastAPI)


def test_create_app_uses_configured_metadata() -> None:
    application = create_app()

    assert application.title == "Job Platform API"
    assert application.version == "0.1.0"


def test_module_level_app_is_importable_and_usable() -> None:
    assert isinstance(app, FastAPI)


def test_test_client_initializes_successfully() -> None:
    client = TestClient(app)

    assert client is not None


def test_factory_produces_independent_app_instances() -> None:
    first = create_app()
    second = create_app()

    assert first is not second


def test_cors_header_present_for_configured_frontend_origin() -> None:
    """STORY-035: the frontend fetches this API cross-origin from the
    browser -- without this header the browser blocks the response
    regardless of frontend correctness."""
    client = TestClient(app)

    response = client.get("/health", headers={"Origin": "http://localhost:3000"})

    assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"


def test_cors_header_absent_for_an_unconfigured_origin() -> None:
    client = TestClient(app)

    response = client.get("/health", headers={"Origin": "http://evil.example.com"})

    assert "access-control-allow-origin" not in response.headers


def test_health_is_never_rate_limited(monkeypatch) -> None:
    """STORY-045: Docker's own healthcheck polls /health every 5 seconds
    continuously -- it must never receive a 429 from this API's own rate
    limiter. Even simulating an already-over-limit Redis counter, /health
    must still succeed, since it has no rate_limit() dependency at all."""
    from unittest.mock import MagicMock

    import app.redis_client as redis_module

    fake_client = MagicMock()
    fake_pipe = MagicMock()
    fake_client.pipeline.return_value = fake_pipe
    fake_pipe.execute.return_value = [999999, True]  # would 429 any limited route
    monkeypatch.setattr(redis_module, "_client", fake_client)

    client = TestClient(app)
    for _ in range(5):
        response = client.get("/health")
        assert response.status_code == 200


def test_health_live_and_ready_are_never_rate_limited(monkeypatch) -> None:
    """STORY-052: the new liveness/readiness routes must be exempt too --
    same reasoning as /health above (Docker's own healthcheck, now
    pointed at /health/ready, must never be blocked by this API's own
    rate limiter)."""
    from unittest.mock import MagicMock, patch

    import app.redis_client as redis_module

    fake_client = MagicMock()
    fake_pipe = MagicMock()
    fake_client.pipeline.return_value = fake_pipe
    fake_pipe.execute.return_value = [999999, True]  # would 429 any limited route
    monkeypatch.setattr(redis_module, "_client", fake_client)

    client = TestClient(app)
    for _ in range(5):
        response = client.get("/health/live")
        assert response.status_code == 200

    with (
        patch("app.api.health.check_database_connection", return_value=True),
        patch("app.api.health.check_redis_connection", return_value=True),
    ):
        for _ in range(5):
            response = client.get("/health/ready")
            assert response.status_code == 200
