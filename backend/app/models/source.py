"""Source Registry model (STORY-014).

Implements exactly what requirement.md's functional requirements name: name,
connector type, config, enabled flag, last-run summary. `company_id` is a
deliberate, explicitly-approved *extension* beyond that literal list (see
the model docstring below for why) — everything else some implementers might
expect (`base_url`) is intentionally absent:

- Per-connector identifying info (board tokens, org slugs, feed URLs) belongs
  inside `config` (JSONB) — the Technical note says config is "validated per
  connector," which only makes sense if different connector types can store
  different shapes there, not a single fixed `base_url` column.

`refresh_interval_minutes` (STORY-021) is nullable: `NULL` means "use the
platform's configured `default_refresh_interval_minutes`" (STORY-021's own
technical note: "per-source interval override; default global interval").
Not derived/cached anywhere else — the orchestrator reads it directly.

`connector_type` is a permissive string, not a native enum or a
CHECK-constrained closed set: requirement.md only names `greenhouse`
(STORY-018) and `ashby` (STORY-019) as concrete planned connectors, and gives
no closed list for this field (unlike STORY-010's `work_mode`/
`employment_type`, which did). A closed set here would force a migration
every time a new connector type is added — exactly what a source *registry*
should avoid. Whether a given `connector_type` string corresponds to an
actually-implemented connector is STORY-016's job (the real connector
registry/lookup), not this schema's.

`last_run_summary` is one nullable JSONB field, not separate
`last_attempt_at`/`last_success_at`/`consecutive_failures` columns:
requirement.md says "last-run summary" — read as one field, not three. Its
internal shape is deliberately undefined here: STORY-024 (Source Health
Monitoring) says health is derived from `IngestionRun` *history*
(STORY-015), not from a cached field on `Source`, which signals this column
is a lightweight display cache for the "admin-visible listing," not a source
of truth STORY-014 should be pre-designing.
"""

from __future__ import annotations

import datetime
import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Source(Base):
    """A registered ingestion source (e.g. one company's Greenhouse board).

    `company_id` is nullable and deliberately not part of requirement.md's
    literal STORY-014 field list — proposed and explicitly approved as an
    extension, since the Story's own purpose ("a single place that lists
    every ingestion source... and its status") implies most sources
    represent one company's board, and STORY-011 already provides the table
    to point at. Nullable so a hypothetical multi-company/generic feed isn't
    forced into a single-company shape; per-job company resolution already
    happens independently via `Job.company_id`/`company_name` regardless of
    whether a `Source` has a `company_id` set.
    """

    __tablename__ = "sources"
    __table_args__ = (
        CheckConstraint("name <> ''", name="ck_sources_name_not_empty"),
        CheckConstraint(
            "connector_type <> ''", name="ck_sources_connector_type_not_empty"
        ),
        CheckConstraint(
            "refresh_interval_minutes IS NULL OR refresh_interval_minutes > 0",
            name="ck_sources_refresh_interval_minutes_positive",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    connector_type: Mapped[str] = mapped_column(String(50), nullable=False)

    company_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "companies.id",
            ondelete="SET NULL",
            name="fk_sources_company_id_companies",
        ),
        nullable=True,
        index=True,
    )

    config: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))

    # STORY-021: NULL means "use Settings.default_refresh_interval_minutes".
    refresh_interval_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    last_run_summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
