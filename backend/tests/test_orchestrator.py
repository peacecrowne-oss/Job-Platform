"""Tests for app.ingestion.orchestrator (STORY-021) -- the shared
ingestion pipeline wiring STORY-017/022/025/027 together, plus IngestionRun
tracking (STORY-015) and duplicate-run prevention. Real Postgres (the
isolated job_platform_test database), zero live network -- a fake,
registered connector stands in for Greenhouse/Ashby so these tests never
depend on live infrastructure beyond Postgres itself.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

import pytest
from pydantic import BaseModel

from app.connectors.base import BaseConnector, NormalizedJobRecord
from app.connectors.errors import ConnectorTransportError
from app.connectors.registry import register_connector
from app.ingestion.orchestrator import run_all_due_sources, run_source
from app.models.ingestion_run import IngestionRun
from app.models.job import Job
from app.models.source import Source

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


class _FakeConnectorConfig(BaseModel):
    records: list[dict[str, Any]] = []
    fail_times: int = 0
    always_raise: bool = False  # STORY-023: simulates "a connector that always raises"
    sleep_seconds: float = 0.0  # STORY-023: simulates a hung connector


@register_connector("orchestrator_test_fake")
class _FakeConnector(BaseConnector):
    config_model = _FakeConnectorConfig

    def __init__(self, config: dict[str, Any], http_client: Any) -> None:
        super().__init__(config, http_client)
        self._call_count = 0

    def fetch(self):
        self._call_count += 1
        if self.config.always_raise:
            raise RuntimeError("boom -- this connector always raises")
        if self.config.sleep_seconds:
            time.sleep(self.config.sleep_seconds)
        if self._call_count <= self.config.fail_times:
            raise ConnectorTransportError("simulated transient failure")
        return iter(self.config.records)

    def normalize(self, raw_record: dict[str, Any]) -> NormalizedJobRecord:
        return NormalizedJobRecord(**raw_record)


def _make_source(session, **overrides) -> Source:
    defaults: dict[str, Any] = {
        "name": "Acme (fake)",
        "connector_type": "orchestrator_test_fake",
        "config": {"records": []},
        "enabled": True,
    }
    defaults.update(overrides)
    source = Source(**defaults)
    session.add(source)
    session.commit()
    return source


def _record(source_job_id: str, **overrides) -> dict[str, Any]:
    payload = {
        "source_job_id": source_job_id,
        "job_title": "Engineer",
        "company_name": "Acme",
        # STORY-027 requires a well-formed source_url -- omitting it (or
        # setting it None) is a deliberate way to construct an
        # intentionally-invalid record for validation-failure tests.
        "source_url": f"https://example.invalid/jobs/{source_job_id}",
    }
    payload.update(overrides)
    return payload


def test_enabled_due_source_executes(db_session_committing) -> None:
    source = _make_source(
        db_session_committing, config={"records": [_record("1")]}
    )

    runs = run_all_due_sources(db_session_committing)

    assert len(runs) == 1
    assert runs[0].source_id == source.id
    assert runs[0].status == "success"


def test_disabled_source_does_not_execute(db_session_committing) -> None:
    _make_source(db_session_committing, enabled=False, config={"records": [_record("1")]})

    runs = run_all_due_sources(db_session_committing)

    assert runs == []


def test_not_yet_due_source_does_not_execute(db_session_committing) -> None:
    source = _make_source(
        db_session_committing, refresh_interval_minutes=60, config={"records": [_record("1")]}
    )
    run_source(db_session_committing, source)  # first run -- now has recent history

    runs = run_all_due_sources(db_session_committing)  # not due again for 60 minutes

    assert runs == []


def test_successful_refresh_counts_created_and_updated(db_session_committing) -> None:
    source = _make_source(
        db_session_committing,
        config={"records": [_record("1"), _record("2")]},
    )

    run = run_source(db_session_committing, source)

    assert run.status == "success"
    assert run.jobs_seen == 2
    assert run.jobs_created == 2
    assert run.jobs_updated == 0
    assert run.jobs_failed == 0
    assert run.finished_at is not None


def test_empty_source_result_still_succeeds(db_session_committing) -> None:
    source = _make_source(db_session_committing, config={"records": []})

    run = run_source(db_session_committing, source)

    assert run.status == "success"
    assert run.jobs_seen == 0


def test_validation_failure_accounting(db_session_committing) -> None:
    # Missing job_title/company_name/source_url -> STORY-027 rejects it (no
    # source_url at all, an error-level validation failure).
    source = _make_source(
        db_session_committing,
        config={"records": [_record("1", job_title=None, company_name=None, source_url=None)]},
    )

    run = run_source(db_session_committing, source)

    assert run.status == "success"  # a rejected record is not a run failure
    assert run.jobs_failed == 1
    assert run.jobs_created == 0
    assert db_session_committing.query(Job).count() == 0


def test_exact_dedup_rerun_creates_zero_duplicate_jobs(db_session_committing) -> None:
    source = _make_source(
        db_session_committing, config={"records": [_record("1"), _record("2")]}
    )

    first = run_source(db_session_committing, source)
    second = run_source(db_session_committing, source)

    assert first.jobs_created == 2
    assert second.jobs_created == 0
    assert second.jobs_updated == 0  # unchanged content -- not even an update
    assert db_session_committing.query(Job).count() == 2


def test_retryable_transient_failure_recovers(db_session_committing) -> None:
    source = _make_source(
        db_session_committing,
        config={"records": [_record("1")], "fail_times": 1},  # fails once, then succeeds
    )

    run = run_source(db_session_committing, source)

    assert run.status == "success"
    assert run.jobs_created == 1


def test_security_policy_failure_is_not_retried_and_marks_run_failed(db_session_committing) -> None:
    source = _make_source(db_session_committing, enabled=False)  # SourceNotAuthorizedError

    run = run_source(db_session_committing, source)  # called directly -- bypasses the enabled filter

    assert run.status == "failed"
    assert "not authorized" in (run.error_summary or "").lower()


def test_malformed_connector_config_marks_run_failed(db_session_committing) -> None:
    source = _make_source(
        db_session_committing,
        connector_type="greenhouse",
        config={},  # missing required board_token
    )

    run = run_source(db_session_committing, source)

    assert run.status == "failed"
    assert run.error_summary


def test_unknown_connector_type_marks_run_failed(db_session_committing) -> None:
    source = _make_source(db_session_committing, connector_type="does-not-exist")

    run = run_source(db_session_committing, source)

    assert run.status == "failed"
    assert "does-not-exist" in (run.error_summary or "")


def test_ingestion_run_failure_lifecycle_never_left_running(db_session_committing) -> None:
    source = _make_source(db_session_committing, connector_type="does-not-exist")

    run = run_source(db_session_committing, source)

    persisted = db_session_committing.get(IngestionRun, run.id)
    assert persisted.status in ("success", "failed")
    assert persisted.status != "running"
    assert persisted.finished_at is not None


def test_duplicate_concurrent_execution_is_prevented(db_session_committing, _postgres_test_db) -> None:
    from sqlalchemy import create_engine

    from app.ingestion.locking import source_refresh_lock

    source = _make_source(
        db_session_committing, config={"records": [_record("1")]}
    )

    other_engine = create_engine(_postgres_test_db, connect_args={"connect_timeout": 2})
    try:
        with source_refresh_lock(other_engine, source.id) as held_elsewhere:
            assert held_elsewhere is True

            runs = run_all_due_sources(db_session_committing)  # should skip the locked source

            assert runs == []
    finally:
        other_engine.dispose()


# --- STORY-023: per-source failure isolation ---


def test_connector_that_always_raises_does_not_block_other_sources(db_session_committing) -> None:
    broken = _make_source(db_session_committing, name="Broken", config={"always_raise": True})
    healthy = _make_source(
        db_session_committing, name="Healthy", config={"records": [_record("1")]}
    )

    runs = run_all_due_sources(db_session_committing)

    runs_by_source = {run.source_id: run for run in runs}
    assert runs_by_source[broken.id].status == "failed"
    assert "boom" in (runs_by_source[broken.id].error_summary or "")
    assert runs_by_source[healthy.id].status == "success"
    assert runs_by_source[healthy.id].jobs_created == 1


def test_hung_connector_is_abandoned_after_timeout_and_others_still_run(
    db_session_committing, monkeypatch
) -> None:
    from app.config import get_settings

    # Short enough that the abandoned thread's own sleep doesn't meaningfully
    # extend this test file's runtime, long enough to be clearly
    # distinguishable from the shortened timeout below.
    monkeypatch.setattr(get_settings(), "ingestion_source_timeout_seconds", 0.2)

    hung = _make_source(db_session_committing, name="Hung", config={"sleep_seconds": 1.0})
    healthy = _make_source(
        db_session_committing, name="Healthy", config={"records": [_record("1")]}
    )

    start = time.monotonic()
    runs = run_all_due_sources(db_session_committing)
    elapsed = time.monotonic() - start

    assert elapsed < 1.0  # did not wait for the hung connector's full sleep
    runs_by_source = {run.source_id: run for run in runs}
    assert healthy.id in runs_by_source
    assert runs_by_source[healthy.id].status == "success"
    assert hung.id not in runs_by_source  # abandoned -- not returned by this cycle


def test_concurrency_is_bounded_by_max_concurrent_sources(db_session_committing, monkeypatch) -> None:
    """A due-source count larger than the configured worker limit still
    completes all of them -- just not all literally simultaneously."""
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "ingestion_max_concurrent_sources", 1)

    sources = [
        _make_source(db_session_committing, name=f"S{i}", config={"records": [_record(str(i))]})
        for i in range(3)
    ]

    runs = run_all_due_sources(db_session_committing)

    assert len(runs) == 3
    assert all(run.status == "success" for run in runs)
    assert {run.source_id for run in runs} == {s.id for s in sources}


# --- STORY-028: freshness/auto-closure, end-to-end via run_source() ---


def test_job_missing_from_enough_successful_runs_is_closed_end_to_end(db_session_committing) -> None:
    source = _make_source(
        db_session_committing,
        freshness_threshold_runs=2,
        config={"records": [_record("stays"), _record("disappears")]},
    )

    run_source(db_session_committing, source)  # both records present

    source.config = {"records": [_record("stays")]}  # "disappears" no longer returned
    db_session_committing.commit()
    run_source(db_session_committing, source)  # 1st successful run without it
    run_source(db_session_committing, source)  # 2nd successful run without it -- threshold met

    stays = db_session_committing.query(Job).filter(Job.source_job_id == "stays").one()
    disappears = db_session_committing.query(Job).filter(Job.source_job_id == "disappears").one()
    assert stays.closed_at is None
    assert disappears.closed_at is not None
