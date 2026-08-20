"""Ingestion Run Tracking model (STORY-015).

Implements exactly what requirement.md's functional requirements name:
source, started_at, finished_at, status, jobs_seen, jobs_created,
jobs_updated, jobs_failed, error_summary. `jobs_discovered`/`jobs_unchanged`/
`jobs_closed`/`worker_id` are NOT columns here — none of those names appear
in requirement.md; the literal counter name is `jobs_seen`, and a worker
identifier belongs to scheduler/worker infrastructure (STORY-021/054), not
this Story.

`source_id` (not `source`) to match this codebase's FK-naming convention
(`company_id`, not `company` — see Job/Source). Nullable with `ON DELETE
SET NULL`: a run is always created against a real source in practice, but
the column stays nullable so deleting a `Source` never deletes its
ingestion history (approved STORY-015 constraint #3), mirroring
`Job.company_id`/`Source.company_id`.

No `created_at` column: `started_at` already IS the creation timestamp for
this row (a run record is created exactly when it starts) — a separate
`created_at` would be redundant. `updated_at` is kept, matching every other
table's audit-column convention, and is useful later for detecting stalled
runs (STORY-024) since it changes whenever status/counters are written.

requirement.md's technical note also says runs are "linked to affected job
rows where feasible for auditability." No column or join table is added for
that here — no concrete field/mechanism is named, and nothing persists real
`Job` rows during ingestion yet (that's STORY-016). Deferred to whichever
Story actually writes jobs during ingestion, per the approved plan.

No service/repository layer exists in this module (approved STORY-015
constraint #2) — this Story's own acceptance criterion ("every connector
execution produces exactly one run record, including failed runs") is
satisfiable by the schema shape alone; nothing in it requires operational
helper functions, and no caller of such helpers exists yet (STORY-016 is
what would call them).
"""

from __future__ import annotations

import datetime
import uuid

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class IngestionRun(Base):
    """One record per connector execution attempt for a given `Source`.

    Three `status` values only, matching what requirement.md's own edge
    cases name: `running` (initial), `success` (terminal), `failed`
    (terminal — covers both exhausted retries per STORY-022's edge case and
    a crash mid-run per this Story's own edge case, which are not given
    distinct status values in requirement.md). The CHECK constraint below
    restricts the *value*, not the *transition* — nothing in this Story
    enforces valid status transitions (e.g. blocking `success` -> `running`),
    since no service layer exists here to enforce it and requirement.md
    doesn't ask for transition logic in STORY-015.
    """

    __tablename__ = "ingestion_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'success', 'failed')",
            name="ck_ingestion_runs_status",
        ),
        CheckConstraint("jobs_seen >= 0", name="ck_ingestion_runs_jobs_seen_non_negative"),
        CheckConstraint(
            "jobs_created >= 0", name="ck_ingestion_runs_jobs_created_non_negative"
        ),
        CheckConstraint(
            "jobs_updated >= 0", name="ck_ingestion_runs_jobs_updated_non_negative"
        ),
        CheckConstraint(
            "jobs_failed >= 0", name="ck_ingestion_runs_jobs_failed_non_negative"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )

    source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "sources.id",
            ondelete="SET NULL",
            name="fk_ingestion_runs_source_id_sources",
        ),
        nullable=True,
        index=True,
    )

    started_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'running'")
    )

    jobs_seen: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    jobs_created: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    jobs_updated: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    jobs_failed: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))

    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
