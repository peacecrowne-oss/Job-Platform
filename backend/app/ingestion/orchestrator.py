"""Scheduled-refresh orchestration (STORY-021).

The "shared ingestion pipeline" prior connector-related Stories already
anticipated but explicitly left unbuilt ("no orchestrator exists yet to
call it automatically" -- app/connectors/policy.py; "no orchestrator
exists yet to drive a real run" -- app/ingestion/retry.py). Wires
together, in order, exactly the primitives those Stories already built:
STORY-017 authorization -> STORY-016 connector construction (through
STORY-017/046's policy-enforcing HTTP client) -> STORY-022 retry ->
STORY-027 validation -> STORY-025 dedup/upsert -> STORY-015 IngestionRun
tracking. No new business logic -- STORY-021's own job is only this glue.

`run_source()` is the reusable, sleep-loop-free core: it processes exactly
one Source and returns the IngestionRun it created. `run_all_due_sources()`
iterates every enabled, due Source and calls it. Neither function sleeps
or loops indefinitely -- that's app/ingestion/scheduler.py's job, kept
separate specifically so this module stays trivially testable and usable
from a one-off CLI command (backend/scripts/run_ingestion.py) or a future
external scheduler.

STORY-023 boundary (flagged in the approved plan, not silently absorbed):
`run_all_due_sources()` catches exceptions per-source only so one broken
source can't stop the loop from reaching the next one -- it does not
implement STORY-023's own literal ask for a real, separate task/process
boundary. That remains STORY-023's job.

`source=source.connector_type` passed to upsert_batch() reuses the exact
convention already established by STORY-010/025's own tests (a Job's
`source` column holds the connector type string, e.g. "greenhouse") --
not invented here.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

# Imported for their registration side effect only (mirrors alembic/env.py's
# own model-import pattern) -- nothing here calls Greenhouse/Ashby directly.
# app.models.company is needed too: Source.company_id and Job.company are
# both FK/relationship targets that fail to resolve at flush/commit time if
# Company was never imported anywhere in the process (a real bug caught
# during live Docker validation -- it only "worked" in the test suite
# because other test modules happened to import it first in the same
# process; a standalone `python -m app.ingestion.scheduler` process has no
# such accidental import to rely on).
import app.connectors.ashby  # noqa: F401
import app.connectors.greenhouse  # noqa: F401
import app.models.company  # noqa: F401
from app.config import get_settings
from app.connectors.http_client import PolicyEnforcingHttpClient, SsrfSafeTransport
from app.connectors.policy import require_source_authorized
from app.connectors.registry import registry
from app.ingestion.dedup import UpsertOutcome, upsert_batch
from app.ingestion.locking import source_refresh_lock
from app.ingestion.retry import RetryPolicy, with_retry
from app.models.ingestion_run import IngestionRun
from app.models.source import Source
from app.validation.data_quality import validate_batch

logger = logging.getLogger(__name__)


def _effective_interval_minutes(source: Source) -> int:
    return source.refresh_interval_minutes or get_settings().default_refresh_interval_minutes


def _is_due(session: Session, source: Source) -> bool:
    """A source is due if it has no prior run, or its most recent run
    started at least its effective interval ago. Deliberately queries
    IngestionRun history rather than a cached "last refreshed" column --
    consistent with STORY-024's own stated design (health/history derived
    from IngestionRun, not a cached Source field). The advisory lock, not
    this check, is what actually prevents overlap with a still-in-flight
    run -- this is only a cheap pre-filter."""
    last_run = session.execute(
        select(IngestionRun)
        .where(IngestionRun.source_id == source.id)
        .order_by(IngestionRun.started_at.desc())
        .limit(1)
    ).scalar_one_or_none()

    if last_run is None:
        return True

    elapsed = datetime.now(timezone.utc) - last_run.started_at
    return elapsed.total_seconds() >= _effective_interval_minutes(source) * 60


def run_source(session: Session, source: Source) -> IngestionRun:
    """Runs exactly one source's refresh, unconditionally (callers decide
    whether it's due/enabled/lockable). Always returns a completed
    IngestionRun -- success or failed, never left `running`."""
    run = IngestionRun(source_id=source.id, status="running")
    session.add(run)
    session.commit()

    try:
        require_source_authorized(source)

        connector_cls = registry.get(source.connector_type)
        transport = SsrfSafeTransport()
        http_client = PolicyEnforcingHttpClient(transport, get_settings().ingestion_user_agent)
        connector = connector_cls(source.config, http_client)

        raw_records = with_retry(
            lambda: list(connector.fetch()),
            policy=RetryPolicy(),
            context={"source_id": str(source.id), "connector_type": source.connector_type},
        )

        jobs_seen = len(raw_records)
        jobs_failed = 0
        normalized = []
        for raw in raw_records:
            record = connector.normalize(raw)
            if not connector.validate(record):
                jobs_failed += 1
                continue
            normalized.append(record)

        outcomes = validate_batch(normalized, source_company_name=source.name)
        valid_records = [o.record for o in outcomes if o.result.is_valid]
        jobs_failed += sum(1 for o in outcomes if not o.result.is_valid)

        results = upsert_batch(session, source.connector_type, valid_records)
        session.commit()

        jobs_created = sum(1 for _, outcome in results if outcome is UpsertOutcome.CREATED)
        jobs_updated = sum(1 for _, outcome in results if outcome is UpsertOutcome.UPDATED)

        run.status = "success"
        run.jobs_seen = jobs_seen
        run.jobs_created = jobs_created
        run.jobs_updated = jobs_updated
        run.jobs_failed = jobs_failed
        run.finished_at = datetime.now(timezone.utc)
        session.commit()

    except Exception as exc:  # noqa: BLE001 -- deliberate: any failure still completes the run
        session.rollback()
        run.status = "failed"
        run.error_summary = str(exc)
        run.finished_at = datetime.now(timezone.utc)
        session.commit()
        logger.warning(
            "Ingestion run failed for source %s (%s): %s", source.id, source.connector_type, exc
        )

    return run


def run_all_due_sources(session: Session) -> list[IngestionRun]:
    """Runs every enabled, due source once. A source already locked by
    another process (concurrent run in progress) is skipped, not queued or
    retried. One broken source's exception never stops the others from
    running (STORY-021's own minimum need -- not STORY-023's real task/
    process isolation, see module docstring)."""
    engine = session.get_bind()
    sources = session.execute(select(Source).where(Source.enabled.is_(True))).scalars().all()

    runs: list[IngestionRun] = []
    for source in sources:
        if not _is_due(session, source):
            continue

        with source_refresh_lock(engine, source.id) as acquired:
            if not acquired:
                logger.info("Skipping source %s -- refresh already in progress", source.id)
                continue
            runs.append(run_source(session, source))

    return runs
