"""Freshness Tracking & Auto-Closure (STORY-028).

A job "not seen in N consecutive runs of its source" is determined purely
from timestamps already maintained -- `Job.last_seen_at` (STORY-025) and
`IngestionRun.started_at` (STORY-015) -- no new join table linking runs to
jobs is needed. If `job.last_seen_at` predates the *Nth-most-recent
successful* run's `started_at` for that job's source, the job wasn't part
of any of the last N successful runs (being seen in any of them would have
bumped `last_seen_at` to that run's time or later).

Only **successful** runs advance the "N consecutive runs" count -- this is
what satisfies the Story's own edge case ("a source-wide outage must not
mass-close every job... distinguish 'source failed to run' from 'source
ran and job is gone'"): a source stuck failing never accumulates enough
successful runs to trigger any closure at all. If a source has fewer than
N successful runs ever, nothing is closed yet -- there isn't enough
history to conclude a job is actually gone rather than just not-yet-seen.

Called from `app/ingestion/orchestrator.py`'s `run_source()`, only on the
success path -- never after a failed run, for the same edge-case reason.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.ingestion_run import IngestionRun
from app.models.job import Job
from app.models.source import Source


def _effective_threshold_runs(source: Source) -> int:
    return source.freshness_threshold_runs or get_settings().default_freshness_threshold_runs


def close_stale_jobs(session: Session, source: Source) -> int:
    """Closes (sets `closed_at`) every currently-open job for this source
    last seen before the Nth-most-recent successful run started. Returns
    the number of jobs closed. Does not commit -- the caller controls the
    transaction boundary, matching `upsert_job()`'s own convention."""
    threshold_runs = _effective_threshold_runs(source)

    successful_runs = (
        session.execute(
            select(IngestionRun.started_at)
            .where(IngestionRun.source_id == source.id, IngestionRun.status == "success")
            .order_by(IngestionRun.started_at.desc())
            .limit(threshold_runs)
        )
        .scalars()
        .all()
    )

    if len(successful_runs) < threshold_runs:
        return 0  # not enough successful-run history yet to conclude anything

    threshold_time = successful_runs[-1]  # the Nth-most-recent successful run's start time

    result = session.execute(
        update(Job)
        .where(
            Job.source == source.connector_type,
            Job.closed_at.is_(None),
            Job.last_seen_at < threshold_time,
        )
        # The actual detection moment, not threshold_time -- closed_at
        # records "when we determined this was closed," not the run that
        # happened to establish the threshold.
        .values(closed_at=datetime.now(timezone.utc))
    )
    return result.rowcount
