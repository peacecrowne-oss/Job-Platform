"""Source Health Monitoring (STORY-024).

Health is *derived* from `IngestionRun` history (STORY-015) -- never a
cached field on `Source`, consistent with `Source`'s own STORY-014
docstring ("last_run_summary... is a lightweight display cache... not a
source of truth STORY-014 should be pre-designing") and this Story's own
literal FR ("health status derived from recent IngestionRun history").

Locking to prevent overlapping runs -- the ambiguity this Story's own
technical note left open ("lives here or in STORY-021") -- was already
resolved in STORY-021's own approved plan; nothing here duplicates it.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.ingestion_run import IngestionRun
from app.models.source import Source

SourceHealthStatus = Literal["healthy", "unhealthy", "unknown"]


class SourceHealth(BaseModel):
    source_id: uuid.UUID
    source_name: str
    connector_type: str
    status: SourceHealthStatus
    consecutive_failures: int
    success_rate: float | None
    last_success_at: datetime.datetime | None
    last_run_at: datetime.datetime | None
    runs_considered: int


def compute_source_health(session: Session, source: Source) -> SourceHealth:
    settings = get_settings()

    # Most recent *finished* runs only -- an in-flight `running` row hasn't
    # succeeded or failed yet and must never count toward either the
    # success rate or the consecutive-failure streak.
    recent_runs = (
        session.execute(
            select(IngestionRun)
            .where(IngestionRun.source_id == source.id, IngestionRun.status != "running")
            .order_by(IngestionRun.started_at.desc())
            .limit(settings.source_health_recent_run_count)
        )
        .scalars()
        .all()
    )

    if not recent_runs:
        return SourceHealth(
            source_id=source.id,
            source_name=source.name,
            connector_type=source.connector_type,
            status="unknown",
            consecutive_failures=0,
            success_rate=None,
            last_success_at=None,
            last_run_at=None,
            runs_considered=0,
        )

    consecutive_failures = 0
    for run in recent_runs:  # already newest-first
        if run.status == "failed":
            consecutive_failures += 1
        else:
            break

    success_count = sum(1 for run in recent_runs if run.status == "success")
    success_rate = success_count / len(recent_runs)

    # The true most recent success ever -- not bounded by the recent-N
    # window above, which is only for the success-rate/streak calculation.
    last_success = session.execute(
        select(IngestionRun)
        .where(IngestionRun.source_id == source.id, IngestionRun.status == "success")
        .order_by(IngestionRun.started_at.desc())
        .limit(1)
    ).scalar_one_or_none()

    status: SourceHealthStatus = (
        "unhealthy"
        if consecutive_failures >= settings.source_unhealthy_consecutive_failures_threshold
        else "healthy"
    )

    return SourceHealth(
        source_id=source.id,
        source_name=source.name,
        connector_type=source.connector_type,
        status=status,
        consecutive_failures=consecutive_failures,
        success_rate=success_rate,
        last_success_at=last_success.started_at if last_success else None,
        last_run_at=recent_runs[0].started_at,
        runs_considered=len(recent_runs),
    )


def list_all_source_health(session: Session) -> list[SourceHealth]:
    """Every Source, not filtered to enabled=True -- a disabled source's
    history is still worth seeing on a health view."""
    sources = session.execute(select(Source).order_by(Source.name)).scalars().all()
    return [compute_source_health(session, source) for source in sources]
