"""Tests for app.ingestion.freshness (STORY-028) -- auto-closure derived
purely from IngestionRun/Job timestamps already maintained, against real
Postgres (the isolated job_platform_test database). `started_at` is
always set explicitly for deterministic ordering.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

import app.models.company  # noqa: F401 -- resolves Job.company relationship
from app.ingestion.freshness import close_stale_jobs
from app.models.ingestion_run import IngestionRun
from app.models.job import Job
from app.models.source import Source

pytestmark = [pytest.mark.integration, pytest.mark.postgres]

_NOW = datetime(2026, 2, 1, tzinfo=timezone.utc)


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
    started_at = _NOW - timedelta(minutes=minutes_ago)
    run = IngestionRun(
        source_id=source.id,
        status=status,
        started_at=started_at,
        finished_at=started_at if status != "running" else None,
    )
    session.add(run)
    session.commit()
    return run


def _make_job(session, source: Source, *, last_seen_minutes_ago: int, **overrides) -> Job:
    defaults: dict[str, Any] = {
        "source": source.connector_type,
        "source_job_id": str(uuid.uuid4()),
        "last_seen_at": _NOW - timedelta(minutes=last_seen_minutes_ago),
    }
    defaults.update(overrides)
    job = Job(**defaults)
    session.add(job)
    session.commit()
    return job


def test_job_not_seen_in_threshold_successful_runs_is_closed(db_session_committing) -> None:
    source = _make_source(db_session_committing, freshness_threshold_runs=3)
    for i in range(3):
        _make_run(db_session_committing, source, status="success", minutes_ago=i * 10)
    stale_job = _make_job(db_session_committing, source, last_seen_minutes_ago=100)

    closed_count = close_stale_jobs(db_session_committing, source)
    db_session_committing.commit()

    assert closed_count == 1
    db_session_committing.refresh(stale_job)
    assert stale_job.closed_at is not None


def test_job_seen_within_threshold_runs_stays_open(db_session_committing) -> None:
    source = _make_source(db_session_committing, freshness_threshold_runs=3)
    for i in range(3):
        _make_run(db_session_committing, source, status="success", minutes_ago=i * 10)
    recent_job = _make_job(db_session_committing, source, last_seen_minutes_ago=5)

    closed_count = close_stale_jobs(db_session_committing, source)

    assert closed_count == 0
    db_session_committing.refresh(recent_job)
    assert recent_job.closed_at is None


def test_fewer_than_threshold_successful_runs_closes_nothing(db_session_committing) -> None:
    source = _make_source(db_session_committing, freshness_threshold_runs=3)
    _make_run(db_session_committing, source, status="success", minutes_ago=0)  # only 1, need 3
    stale_job = _make_job(db_session_committing, source, last_seen_minutes_ago=1000)

    closed_count = close_stale_jobs(db_session_committing, source)

    assert closed_count == 0
    db_session_committing.refresh(stale_job)
    assert stale_job.closed_at is None


def test_repeated_failed_runs_never_trigger_closure(db_session_committing) -> None:
    """The literal edge case: a source-wide outage (all failed runs) must
    never mass-close jobs -- only successful runs count toward the
    threshold, so a permanently-failing source accumulates zero eligible
    runs, no matter how many failed attempts pile up."""
    source = _make_source(db_session_committing, freshness_threshold_runs=3)
    for i in range(10):
        _make_run(db_session_committing, source, status="failed", minutes_ago=i * 10)
    stale_job = _make_job(db_session_committing, source, last_seen_minutes_ago=1000)

    closed_count = close_stale_jobs(db_session_committing, source)

    assert closed_count == 0
    db_session_committing.refresh(stale_job)
    assert stale_job.closed_at is None


def test_per_source_threshold_override_beats_global_default(db_session_committing) -> None:
    source = _make_source(db_session_committing, freshness_threshold_runs=1)
    _make_run(db_session_committing, source, status="success", minutes_ago=0)
    stale_job = _make_job(db_session_committing, source, last_seen_minutes_ago=100)

    closed_count = close_stale_jobs(db_session_committing, source)

    assert closed_count == 1  # threshold of 1 -- a single successful run is already enough
    db_session_committing.refresh(stale_job)
    assert stale_job.closed_at is not None


def test_reappearing_job_is_reopened_by_upsert(db_session_committing) -> None:
    from app.connectors.base import NormalizedJobRecord
    from app.ingestion.dedup import upsert_job

    source = _make_source(db_session_committing)
    job = _make_job(db_session_committing, source, last_seen_minutes_ago=1000)
    job.closed_at = _NOW - timedelta(minutes=500)
    db_session_committing.commit()

    upsert_job(
        db_session_committing,
        source.connector_type,
        NormalizedJobRecord(source_job_id=job.source_job_id, job_title="Still here"),
    )
    db_session_committing.commit()

    db_session_committing.refresh(job)
    assert job.closed_at is None


def test_closed_job_is_not_reclosed_or_double_counted(db_session_committing) -> None:
    source = _make_source(db_session_committing, freshness_threshold_runs=1)
    _make_run(db_session_committing, source, status="success", minutes_ago=0)
    already_closed = _make_job(
        db_session_committing,
        source,
        last_seen_minutes_ago=1000,
        closed_at=_NOW - timedelta(minutes=500),
    )

    closed_count = close_stale_jobs(db_session_committing, source)

    assert closed_count == 0  # already closed -- not re-selected
    db_session_committing.refresh(already_closed)
    assert already_closed.closed_at == _NOW - timedelta(minutes=500)  # untouched
