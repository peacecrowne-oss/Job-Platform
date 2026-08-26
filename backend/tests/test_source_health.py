"""Tests for app.ingestion.health (STORY-024) -- health derived from real
IngestionRun history, against real Postgres (the isolated
job_platform_test database). `started_at` is always set explicitly (never
relying on the server default) so ordering is deterministic regardless of
how fast rows are inserted.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from app.ingestion.health import compute_source_health, list_all_source_health
from app.models.ingestion_run import IngestionRun
from app.models.source import Source

pytestmark = [pytest.mark.integration, pytest.mark.postgres]

_NOW = datetime(2026, 1, 15, tzinfo=timezone.utc)


def _make_source(session, **overrides) -> Source:
    defaults: dict[str, Any] = {
        "name": "Acme",
        "connector_type": "greenhouse",
        "config": {},
        "enabled": True,
    }
    defaults.update(overrides)
    source = Source(**defaults)
    session.add(source)
    session.commit()
    return source


def _make_run(session, source: Source, *, status: str, minutes_ago: int) -> IngestionRun:
    run = IngestionRun(
        source_id=source.id,
        status=status,
        started_at=_NOW - timedelta(minutes=minutes_ago),
        finished_at=_NOW - timedelta(minutes=minutes_ago) if status != "running" else None,
    )
    session.add(run)
    session.commit()
    return run


def test_no_runs_yields_unknown(db_session_committing) -> None:
    source = _make_source(db_session_committing)

    health = compute_source_health(db_session_committing, source)

    assert health.status == "unknown"
    assert health.success_rate is None
    assert health.consecutive_failures == 0
    assert health.runs_considered == 0


def test_all_success_history_is_healthy(db_session_committing) -> None:
    source = _make_source(db_session_committing)
    for i in range(3):
        _make_run(db_session_committing, source, status="success", minutes_ago=i * 10)

    health = compute_source_health(db_session_committing, source)

    assert health.status == "healthy"
    assert health.consecutive_failures == 0
    assert health.success_rate == 1.0
    assert health.last_success_at is not None


def test_threshold_consecutive_failures_is_unhealthy(db_session_committing) -> None:
    source = _make_source(db_session_committing)
    for i in range(3):  # default threshold is 3
        _make_run(db_session_committing, source, status="failed", minutes_ago=i * 10)

    health = compute_source_health(db_session_committing, source)

    assert health.status == "unhealthy"
    assert health.consecutive_failures == 3


def test_fewer_than_threshold_consecutive_failures_stays_healthy(db_session_committing) -> None:
    source = _make_source(db_session_committing)
    for i in range(2):  # below the default threshold of 3
        _make_run(db_session_committing, source, status="failed", minutes_ago=i * 10)

    health = compute_source_health(db_session_committing, source)

    assert health.status == "healthy"
    assert health.consecutive_failures == 2


def test_a_success_resets_the_consecutive_failure_streak(db_session_committing) -> None:
    source = _make_source(db_session_committing)
    # Newest-first: 2 failures, then (older) a success, then more failures.
    _make_run(db_session_committing, source, status="failed", minutes_ago=0)
    _make_run(db_session_committing, source, status="failed", minutes_ago=10)
    _make_run(db_session_committing, source, status="success", minutes_ago=20)
    _make_run(db_session_committing, source, status="failed", minutes_ago=30)
    _make_run(db_session_committing, source, status="failed", minutes_ago=40)

    health = compute_source_health(db_session_committing, source)

    assert health.consecutive_failures == 2  # stops at the success 20 minutes ago
    assert health.status == "healthy"


def test_last_success_at_reflects_the_true_most_recent_success(db_session_committing) -> None:
    source = _make_source(db_session_committing)
    old_success = _make_run(db_session_committing, source, status="success", minutes_ago=500)
    for i in range(3):
        _make_run(db_session_committing, source, status="failed", minutes_ago=i * 10)

    health = compute_source_health(db_session_committing, source)

    assert health.last_success_at == old_success.started_at
    assert health.status == "unhealthy"  # 3 consecutive failures more recent than the old success


def test_running_runs_never_count_toward_health(db_session_committing) -> None:
    source = _make_source(db_session_committing)
    _make_run(db_session_committing, source, status="running", minutes_ago=0)
    _make_run(db_session_committing, source, status="success", minutes_ago=10)

    health = compute_source_health(db_session_committing, source)

    assert health.runs_considered == 1  # the running row is excluded
    assert health.status == "healthy"
    assert health.last_run_at == _NOW - timedelta(minutes=10)


def test_list_all_source_health_includes_disabled_sources(db_session_committing) -> None:
    enabled = _make_source(db_session_committing, name="Enabled", enabled=True)
    disabled = _make_source(db_session_committing, name="Disabled", enabled=False)
    _make_run(db_session_committing, enabled, status="success", minutes_ago=0)

    results = list_all_source_health(db_session_committing)

    source_ids = {h.source_id for h in results}
    assert enabled.id in source_ids
    assert disabled.id in source_ids  # disabled sources are still shown
