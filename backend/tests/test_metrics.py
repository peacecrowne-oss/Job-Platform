"""Tests for GET /metrics and MetricsMiddleware (STORY-051). No live
database required. `prometheus_client`'s registry is a process-global
singleton, so assertions check *relative* increases (delta before/after),
never absolute values -- other tests in the same process may have already
incremented the same counters.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import app.redis_client as redis_module
from app.main import app
from app.metrics import http_requests_total

client = TestClient(app)


def test_metrics_endpoint_returns_prometheus_text_format() -> None:
    response = client.get("/metrics")

    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    body = response.text
    assert "# HELP http_requests_total" in body
    assert "# TYPE http_requests_total counter" in body
    assert "# TYPE ingestion_runs_total counter" in body
    assert "# TYPE scheduler_due_sources gauge" in body


def test_metrics_endpoint_is_not_rate_limited() -> None:
    """Mirrors test_app.py's own test_health_is_never_rate_limited pattern
    -- /metrics is exempted from rate limiting the same way /health is,
    since a scraper polls it continuously (STORY-045's own exemption
    reasoning, applied here by direct analogy)."""
    fake_client = MagicMock()
    fake_pipe = MagicMock()
    fake_client.pipeline.return_value = fake_pipe
    fake_pipe.execute.return_value = [999999, True]  # would 429 any rate-limited route

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(redis_module, "_client", fake_client)
        for _ in range(5):
            response = client.get("/metrics")
            assert response.status_code == 200


def test_http_requests_total_increments_on_real_request() -> None:
    before = http_requests_total.labels(
        method="GET", path="/health", status_code=200
    )._value.get()

    client.get("/health")

    after = http_requests_total.labels(method="GET", path="/health", status_code=200)._value.get()
    assert after == before + 1


def test_metrics_scrape_itself_is_counted() -> None:
    """A known, accepted, flagged characteristic (per the approved plan):
    a scrape of /metrics is not excluded from its own request metrics."""
    before = http_requests_total.labels(
        method="GET", path="/metrics", status_code=200
    )._value.get()

    client.get("/metrics")

    after = http_requests_total.labels(
        method="GET", path="/metrics", status_code=200
    )._value.get()
    assert after == before + 1
