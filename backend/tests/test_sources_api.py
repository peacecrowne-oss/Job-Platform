"""Tests for GET /sources/health (STORY-024). No live database required --
`get_db` is overridden with a fake session and `list_all_source_health()`
is monkeypatched, matching this repo's established `test_search_api.py`
pattern exactly. Real end-to-end computation against a live database is
covered separately by test_source_health.py.

`sources_health_rate_limit` (STORY-045-style) is overridden to a no-op by
default for the same reason `search_rate_limit` is in test_search_api.py.
"""

from __future__ import annotations

import datetime
import uuid

import pytest
from fastapi.testclient import TestClient

import app.api.sources as sources_module
from app.api.sources import sources_health_rate_limit
from app.db import get_db
from app.ingestion.health import SourceHealth
from app.main import app


class _FakeSession:
    pass


def _override_get_db():
    yield _FakeSession()


client = TestClient(app)


def setup_module(module) -> None:
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[sources_health_rate_limit] = lambda: None


def teardown_module(module) -> None:
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(sources_health_rate_limit, None)


def _health(**overrides) -> SourceHealth:
    defaults = dict(
        source_id=uuid.uuid4(),
        source_name="Acme",
        connector_type="greenhouse",
        status="healthy",
        consecutive_failures=0,
        success_rate=1.0,
        last_success_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc),
        last_run_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc),
        runs_considered=5,
    )
    defaults.update(overrides)
    return SourceHealth(**defaults)


def test_sources_health_endpoint_reachable(monkeypatch) -> None:
    monkeypatch.setattr(sources_module, "list_all_source_health", lambda session: [])

    response = client.get("/sources/health")

    assert response.status_code == 200
    assert response.json() == {"sources": []}


def test_sources_health_returns_expected_shape(monkeypatch) -> None:
    monkeypatch.setattr(
        sources_module, "list_all_source_health", lambda session: [_health()]
    )

    response = client.get("/sources/health")

    assert response.status_code == 200
    body = response.json()["sources"][0]
    assert body["status"] == "healthy"
    assert body["consecutive_failures"] == 0
    assert body["success_rate"] == 1.0


def test_sources_health_surfaces_unhealthy_and_unknown(monkeypatch) -> None:
    monkeypatch.setattr(
        sources_module,
        "list_all_source_health",
        lambda session: [
            _health(status="unhealthy", consecutive_failures=5, success_rate=0.1),
            _health(status="unknown", success_rate=None, last_success_at=None, runs_considered=0),
        ],
    )

    response = client.get("/sources/health")

    statuses = [s["status"] for s in response.json()["sources"]]
    assert statuses == ["unhealthy", "unknown"]


def test_sources_health_is_rate_limited_like_search(monkeypatch) -> None:
    """Restores the real rate-limit dependency (mocked Redis) for this one
    test only, matching test_search_api.py's own established pattern."""
    from unittest.mock import MagicMock

    import app.redis_client as redis_module

    monkeypatch.setattr(sources_module, "list_all_source_health", lambda session: [])

    fake_client = MagicMock()
    fake_pipe = MagicMock()
    fake_client.pipeline.return_value = fake_pipe
    fake_pipe.execute.return_value = [999999, True]  # already over any limit
    monkeypatch.setattr(redis_module, "_client", fake_client)

    app.dependency_overrides.pop(sources_health_rate_limit, None)
    try:
        response = client.get("/sources/health")
        assert response.status_code == 429
    finally:
        app.dependency_overrides[sources_health_rate_limit] = lambda: None
