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

STORY-023: `run_all_due_sources()` submits each due source's refresh to a
`ThreadPoolExecutor` -- a "task boundary" (the FR's own textual
alternative to a full OS process), not just an in-process try/except.
Each worker thread opens its *own* DB session (a SQLAlchemy Session isn't
thread-safe to share) and acquires the STORY-021 advisory lock itself,
inside that thread -- functionally identical to before, just relocated to
whichever connection is actually doing the work, since Postgres advisory
locks are inherently multi-connection-safe. `run_source()` itself is
unchanged: it already does exactly what "caught, logged, and recorded
against that source's run only" requires. A per-source
`future.result(timeout=ingestion_source_timeout_seconds)` additionally
isolates a hung connector, not just an unhandled exception -- the FR's own
"boundary" wording implies this even though the literal AC only tests an
exception. A timed-out thread is abandoned, not killed (Python can't force
-interrupt one); its own IngestionRun row (already created as `running` by
`run_source()`'s first action) may still be updated later if the thread
eventually finishes, or may remain `running` if it's genuinely hung -- the
same accepted trade-off already used by STORY-052's health-check timeout,
not a new policy invented here. Real process-crash isolation
(ProcessPoolExecutor) was evaluated and explicitly not chosen -- see the
approved plan's Architecture Decision.

`source=source.connector_type` passed to upsert_batch() reuses the exact
convention already established by STORY-010/025's own tests (a Job's
`source` column holds the connector type string, e.g. "greenhouse") --
not invented here.
"""

from __future__ import annotations

import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

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
from app.ingestion.freshness import close_stale_jobs
from app.ingestion.locking import source_refresh_lock
from app.ingestion.retry import RetryPolicy, with_retry
from app.logging_config import correlation_id_var
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

    # STORY-050: reuses the IngestionRun's own id as the correlation ID for
    # every log line emitted during this source's run -- no new ID needed.
    # Each STORY-023 worker thread calls run_source() independently, so
    # each thread binds its own value; no cross-thread propagation needed.
    correlation_token = correlation_id_var.set(str(run.id))

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

        # STORY-028: only after a successful run is marked and committed
        # (so this run counts toward the "N successful runs" window) --
        # never on the failed path, per this Story's own edge case. Its
        # own try/except is deliberately separate from the outer one: a
        # bug here must never retroactively mark an otherwise-successful
        # ingestion run as failed.
        try:
            close_stale_jobs(session, source)
            session.commit()
        except Exception:  # noqa: BLE001 -- see comment above
            session.rollback()
            logger.exception("Freshness closure failed for source %s", source.id)

    except Exception as exc:  # noqa: BLE001 -- deliberate: any failure still completes the run
        session.rollback()
        run.status = "failed"
        run.error_summary = str(exc)
        run.finished_at = datetime.now(timezone.utc)
        session.commit()
        logger.warning(
            "Ingestion run failed for source %s (%s): %s", source.id, source.connector_type, exc
        )

    finally:
        correlation_id_var.reset(correlation_token)

    return run


def _run_isolated(engine: Engine, source_id: uuid.UUID) -> IngestionRun | None:
    """The STORY-023 task boundary: runs one source's refresh on its own
    session/connection, in its own thread. `expire_on_commit=False` so the
    already-committed, returned IngestionRun's attributes stay readable
    from the caller's thread after this worker's own session closes.
    Returns None if the source is already locked by another run in
    progress (skipped, not queued or retried)."""
    worker_session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        source = worker_session.get(Source, source_id)
        with source_refresh_lock(engine, source_id) as acquired:
            if not acquired:
                logger.info("Skipping source %s -- refresh already in progress", source_id)
                return None
            return run_source(worker_session, source)
    finally:
        worker_session.close()


def run_all_due_sources(session: Session) -> list[IngestionRun]:
    """Runs every enabled, due source once, each in its own thread (STORY-
    023's task boundary) -- an unhandled exception, or a hang past
    `ingestion_source_timeout_seconds`, in one source's connector never
    prevents the others from running. Concurrency is bounded by
    `ingestion_max_concurrent_sources`."""
    engine = session.get_bind()
    sources = session.execute(select(Source).where(Source.enabled.is_(True))).scalars().all()
    due_source_ids = [source.id for source in sources if _is_due(session, source)]

    if not due_source_ids:
        return []

    settings = get_settings()
    runs: list[IngestionRun] = []
    # Not `with ThreadPoolExecutor(...) as pool:` -- that context manager's
    # own __exit__ calls shutdown(wait=True), which would block here until
    # even an abandoned, timed-out thread finishes, defeating the whole
    # point of the per-source timeout below (the same pool-shutdown pitfall
    # already solved once in app/api/health.py's STORY-052 readiness check).
    pool = ThreadPoolExecutor(max_workers=settings.ingestion_max_concurrent_sources)
    try:
        futures = {
            pool.submit(_run_isolated, engine, source_id): source_id
            for source_id in due_source_ids
        }
        for future, source_id in futures.items():
            try:
                result = future.result(timeout=settings.ingestion_source_timeout_seconds)
                if result is not None:
                    runs.append(result)
            except FutureTimeoutError:
                logger.warning(
                    "Source %s exceeded %ss and was abandoned -- its "
                    "IngestionRun may still be updated later by the "
                    "still-running thread, or may remain 'running' if it's "
                    "genuinely hung",
                    source_id,
                    settings.ingestion_source_timeout_seconds,
                )
            except Exception:  # noqa: BLE001 -- one source's unexpected error must not stop the rest
                logger.exception("Unexpected error isolating source %s", source_id)
    finally:
        pool.shutdown(wait=False)

    return runs
