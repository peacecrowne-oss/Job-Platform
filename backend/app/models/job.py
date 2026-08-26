"""Canonical Job Listing model (STORY-010; company_id added by STORY-011).

Implements the fields in requirement.md §2. `company_id` (STORY-011) is
purely additive — `company_name` is untouched, still the raw source-provided
text, preserved exactly as STORY-010 left it. Nothing resolves `company_id`
automatically here; that's STORY-016's job per STORY-011's own technical
note. `company_id` is nullable: a job can exist with no resolved company.

Nullability follows STORY-010's own literal text only, per explicit human
direction on this Story: `source` and `source_job_id` are NOT NULL because
the acceptance criterion's unique constraint is literally `(source,
source_job_id)` and would not actually prevent duplicates if either column
allowed NULL (Postgres treats NULL as distinct from NULL in unique
constraints — a NULL source_job_id could repeat indefinitely without ever
violating the constraint). Every other field — including `source_url`,
`company_name`, and `job_title` — is nullable: STORY-010's functional
requirements loosely group `source_url` in with the "provenance fields," but
the acceptance criteria only names two columns for the actual constraint, and
per explicit direction that ambiguity is resolved toward nullable rather than
borrowing NOT NULL reasoning from other, not-yet-approved Stories (STORY-027,
STORY-029) — later ingestion-quality validation owns that enforcement, not
this schema.

`unknown` is deliberately NOT used as an enum member anywhere here: the only
occurrence of the word "unknown" in requirement.md is STORY-024's unrelated
source-health edge case, not any job field. NULL is used throughout for
absent/unclassified data, per STORY-010's own edge case ("must store NULL,
not fabricated values").
"""

from __future__ import annotations

import datetime
import decimal
import enum
import uuid

from sqlalchemy import (
    ARRAY,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class WorkMode(str, enum.Enum):
    """Matches requirement.md §2's `work_mode` values literally
    ("remote / hybrid / on-site") — `on_site` uses an underscore to stay a
    valid identifier while preserving §2's exact wording.
    """

    REMOTE = "remote"
    HYBRID = "hybrid"
    ON_SITE = "on_site"


class EmploymentType(str, enum.Enum):
    """§2 lists "full-time / part-time / contract / internship / etc." — the
    "etc." is an explicit open-ended hedge, so `OTHER` is included as a
    distinct, meaningful value (source gave a value that doesn't fit our set)
    separate from NULL (source gave no value at all).
    """

    FULL_TIME = "full_time"
    PART_TIME = "part_time"
    CONTRACT = "contract"
    TEMPORARY = "temporary"
    INTERNSHIP = "internship"
    APPRENTICESHIP = "apprenticeship"
    OTHER = "other"


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("source", "source_job_id", name="uq_jobs_source_source_job_id"),
        CheckConstraint(
            "work_mode IS NULL OR work_mode IN ('remote', 'hybrid', 'on_site')",
            name="ck_jobs_work_mode",
        ),
        CheckConstraint(
            "employment_type IS NULL OR employment_type IN "
            "('full_time', 'part_time', 'contract', 'temporary', 'internship', "
            "'apprenticeship', 'other')",
            name="ck_jobs_employment_type",
        ),
        # --- STORY-057: Database Indexing Strategy. Partial indexes on
        # work_mode/employment_type exclude NULL rows -- Greenhouse (a real,
        # live connector) never populates either field, so a large fraction
        # of rows would otherwise bloat a full index with entries no filter
        # query would ever match. ---
        Index(
            "ix_jobs_work_mode",
            "work_mode",
            postgresql_where=text("work_mode IS NOT NULL"),
        ),
        Index(
            "ix_jobs_employment_type",
            "employment_type",
            postgresql_where=text("employment_type IS NOT NULL"),
        ),
        # Composite, broadest-to-narrowest: serves country-only,
        # country+region, and country+region+city lookups via the leading-
        # column-prefix property of a composite B-tree index.
        Index(
            "ix_jobs_location_country_region_city",
            "location_country",
            "location_region",
            "location_city",
        ),
        # Serves STORY-032's "newest jobs first" sort; a B-tree index scans
        # efficiently in either direction, so no separate DESC index needed.
        Index("ix_jobs_posting_date", "posting_date"),
        # GIN expression index over exactly STORY-030's literal full-text
        # field list (title, company, description, skills). No new stored
        # column -- an expression index only. STORY-030 owns the actual
        # search query/ranking/API that uses this; this Story only builds
        # the index, per requirement.md's own literal text for STORY-057.
        # Routed through jobs_search_vector_english(), an IMMUTABLE SQL
        # wrapper created by this Story's migration: to_tsvector() (both
        # overloads) and array_to_string() are only STABLE in Postgres, not
        # IMMUTABLE (confirmed empirically via two separate failed CREATE
        # INDEX attempts), and CREATE INDEX rejects any non-IMMUTABLE
        # function anywhere in an index expression. Wrapping the entire
        # coalesce/concatenation/to_tsvector logic inside one custom
        # function explicitly labeled IMMUTABLE is the standard, documented
        # Postgres workaround: Postgres trusts a function's declared
        # volatility rather than inspecting what it calls internally. Safe
        # here because the language config ('english') is a hardcoded
        # literal, never a column value.
        # Casts (::text/::text[]) are spelled out explicitly to match
        # Postgres's own catalog reflection of this expression exactly
        # (varchar columns passed to a text-typed function parameter are
        # implicitly cast, and pg_get_indexdef() always renders that cast
        # explicitly) -- without this, `alembic check` reports a spurious
        # diff against a functionally-identical, already-correct index.
        Index(
            "ix_jobs_search_vector",
            text(
                "jobs_search_vector_english(job_title::text, company_name::text, "
                "description_full, skills::text[])"
            ),
            postgresql_using="gin",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )

    # --- Provenance ---
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    source_job_id: Mapped[str] = mapped_column(String(255), nullable=False)

    # --- Identity ---
    company_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    job_title: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # --- Canonical company link (STORY-011). Nullable: a job may exist with
    # no resolved company yet, per STORY-011's own "unresolvable... doesn't
    # block ingestion" edge case. ON DELETE SET NULL: deleting a Company must
    # never cascade-delete job listings. ---
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "companies.id",
            ondelete="SET NULL",
            name="fk_jobs_company_id_companies",
        ),
        nullable=True,
        index=True,
    )
    company = relationship("Company", back_populates="jobs")

    # --- Description sections (long text; STORY-007's "long text fields" note) ---
    description_full: Mapped[str | None] = mapped_column(Text, nullable=True)
    responsibilities: Mapped[str | None] = mapped_column(Text, nullable=True)
    requirements: Mapped[str | None] = mapped_column(Text, nullable=True)
    preferred_requirements: Mapped[str | None] = mapped_column(Text, nullable=True)
    qualifications: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Skills: normalized + raw retained alongside (STORY-010 technical note) ---
    skills: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    skills_raw: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Location: free text + normalized components (STORY-010 technical note) ---
    location_raw: Mapped[str | None] = mapped_column(String(500), nullable=True)
    location_city: Mapped[str | None] = mapped_column(String(255), nullable=True)
    location_region: Mapped[str | None] = mapped_column(String(255), nullable=True)
    location_country: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # --- Controlled-value fields (CHECK-constrained strings, not native PG enums) ---
    work_mode: Mapped[str | None] = mapped_column(String(20), nullable=True)
    employment_type: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # --- Not an enum: §2 says "e.g." — an open-ended example list, not a closed set ---
    seniority: Mapped[str | None] = mapped_column(String(100), nullable=True)

    department: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # --- Compensation (explicitly optional per STORY-010's own edge case) ---
    compensation_min: Mapped[decimal.Decimal | None] = mapped_column(Numeric, nullable=True)
    compensation_max: Mapped[decimal.Decimal | None] = mapped_column(Numeric, nullable=True)
    compensation_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    compensation_period: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # --- Benefits (explicitly optional per STORY-010's own edge case) ---
    benefits: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)

    posting_date: Mapped[datetime.date | None] = mapped_column(Date, nullable=True)
    closing_date: Mapped[datetime.date | None] = mapped_column(Date, nullable=True)
    application_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    # --- Ingestion-domain timestamps (our own observation record) ---
    first_seen_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    source_updated_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # STORY-028: our own inferred-from-absence closure timestamp -- distinct
    # from `closing_date` above, which is the source's own stated closing
    # date (a fact from the source, not an inference). NULL = active. Reset
    # to NULL by upsert_job() if a "closed" job reappears in a later run.
    closed_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # --- Provenance/dedup support (schema hooks only; no logic implemented here) ---
    raw_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # --- Generic row audit columns (distinct in meaning from first/last_seen_at) ---
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
