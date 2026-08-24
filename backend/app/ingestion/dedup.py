"""Exact Deduplication (STORY-025) -- the "shared ingestion pipeline" the
Story's own technical note names ("Upsert logic in the shared ingestion
pipeline, not per connector"). Extended by STORY-029 (Provenance
Preservation) -- see `_PROVENANCE_FIELDS_PRESERVE_ON_MISSING` below.

Identity is exactly `(source, source_job_id)` -- requirement.md's literal
functional requirement -- the same composite unique constraint already
created on `Job` in STORY-010 (`uq_jobs_source_source_job_id`). No new
schema, no new table: `Job` already carries every field exact
deduplication needs (`source`, `source_job_id`, `content_hash`,
`first_seen_at`, `last_seen_at`, `raw_metadata`) as "schema hooks... no
logic implemented" per STORY-010's own docstring -- this module is exactly
that logic.

No fuzzy/cross-source matching anywhere: the only lookup key ever used is
the exact identity tuple. Two records with identical title/company/
location but different `source` values are never compared to each other by
anything in this file.

`upsert_job()`/`upsert_batch()` do not call STORY-027's `validate_record()`
internally -- they assume they're given an already-validated
`NormalizedJobRecord`; validation is a separate concern, not reimplemented
here. They also never touch `Job.company_id` -- company resolution belongs
to a later, not-yet-built Story.

STORY-029's own edge case: "If a source's raw payload becomes unavailable
later, provenance metadata already stored remains intact." Before
STORY-029, the UPDATE path blindly overwrote every non-identity field with
whatever the new observation provided -- including `None` -- which would
have silently destroyed a previously-good `source_url`/`application_url`/
`raw_metadata`/`source_updated_at` if a later observation happened to lack
one. `_PROVENANCE_FIELDS_PRESERVE_ON_MISSING` fixes exactly that, and only
that: ordinary content fields (title, description, compensation, etc.)
still fully overwrite on every change, including to `None`, per STORY-025's
original "newest wins" design -- that behavior is correct for content and
is deliberately left unchanged.
"""

from __future__ import annotations

import enum
import hashlib
import json
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors.base import NormalizedJobRecord
from app.models.job import Job

_HASHED_FIELDS = (
    "job_title",
    "company_name",
    "description_full",
    "responsibilities",
    "requirements",
    "preferred_requirements",
    "qualifications",
    "skills",
    "location_raw",
    "location_city",
    "location_region",
    "location_country",
    "work_mode",
    "employment_type",
    "seniority",
    "department",
    "compensation_min",
    "compensation_max",
    "compensation_currency",
    "compensation_period",
    "benefits",
    "posting_date",
    "closing_date",
    "source_url",
    "application_url",
)
# Deliberately excluded: source_job_id (identity, not content),
# source_updated_at (a source-provided timestamp signal, not content --
# including it would make the hash change whenever a source merely
# touches its own bookkeeping timestamp), raw_metadata (too volatile/
# verbose -- would make "unchanged" detection equivalent to "did the raw
# API response change at all").


class UpsertOutcome(str, enum.Enum):
    CREATED = "created"
    UPDATED = "updated"
    UNCHANGED = "unchanged"


def _hashable_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool, list)):
        return value
    return str(value)  # Decimal, date -> stable string form


def compute_content_hash(record: NormalizedJobRecord) -> str:
    payload = {field: _hashable_value(getattr(record, field)) for field in _HASHED_FIELDS}
    serialized = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def classify_upsert(existing_hash: str | None, new_hash: str) -> UpsertOutcome:
    if existing_hash is None:
        return UpsertOutcome.CREATED
    return UpsertOutcome.UNCHANGED if existing_hash == new_hash else UpsertOutcome.UPDATED


def build_job_fields(source: str, record: NormalizedJobRecord) -> dict[str, Any]:
    return {
        "source": source,
        "source_job_id": record.source_job_id,
        "source_url": record.source_url,
        "company_name": record.company_name,
        "job_title": record.job_title,
        "description_full": record.description_full,
        "responsibilities": record.responsibilities,
        "requirements": record.requirements,
        "preferred_requirements": record.preferred_requirements,
        "qualifications": record.qualifications,
        "skills": record.skills,
        "skills_raw": record.skills_raw,
        "location_raw": record.location_raw,
        "location_city": record.location_city,
        "location_region": record.location_region,
        "location_country": record.location_country,
        "work_mode": record.work_mode,
        "employment_type": record.employment_type,
        "seniority": record.seniority,
        "department": record.department,
        "compensation_min": record.compensation_min,
        "compensation_max": record.compensation_max,
        "compensation_currency": record.compensation_currency,
        "compensation_period": record.compensation_period,
        "benefits": record.benefits,
        "posting_date": record.posting_date,
        "closing_date": record.closing_date,
        "application_url": record.application_url,
        "source_updated_at": record.source_updated_at,
        "raw_metadata": record.raw_metadata,
    }


# Fields that are only ever set at creation -- identity is immutable once
# a Job row exists.
_IDENTITY_FIELDS = ("source", "source_job_id")

# STORY-029: a later observation missing one of these must never destroy a
# previously-preserved value -- distinct from ordinary content fields,
# which legitimately update to None when a source stops providing them
# (STORY-025's original "newest wins" behavior, left unchanged for
# everything not listed here).
_PROVENANCE_FIELDS_PRESERVE_ON_MISSING = (
    "source_url",
    "application_url",
    "raw_metadata",
    "source_updated_at",
)


def upsert_job(session: Session, source: str, record: NormalizedJobRecord) -> tuple[Job, UpsertOutcome]:
    """Creates, updates, or no-ops (bumping last_seen_at) a Job row keyed
    on the exact (source, source_job_id) identity. Does not commit -- the
    caller controls the transaction boundary."""
    if not source:
        raise ValueError("source must be a non-empty string")

    new_hash = compute_content_hash(record)
    fields = build_job_fields(source, record)

    existing = session.execute(
        select(Job).where(Job.source == source, Job.source_job_id == record.source_job_id)
    ).scalar_one_or_none()

    if existing is None:
        job = Job(content_hash=new_hash, **fields)
        session.add(job)
        session.flush()
        return job, UpsertOutcome.CREATED

    existing.last_seen_at = datetime.now(timezone.utc)
    outcome = classify_upsert(existing.content_hash, new_hash)

    if outcome is UpsertOutcome.UPDATED:
        for field, value in fields.items():
            if field in _IDENTITY_FIELDS:
                continue
            if field in _PROVENANCE_FIELDS_PRESERVE_ON_MISSING and value is None:
                continue  # STORY-029: preserve existing provenance rather than overwrite with None
            setattr(existing, field, value)
        existing.content_hash = new_hash

    return existing, outcome


def upsert_batch(
    session: Session, source: str, records: Iterable[NormalizedJobRecord]
) -> list[tuple[Job, UpsertOutcome]]:
    """Upserts every record independently and sequentially -- a duplicate
    source_job_id within the same batch is handled correctly (the second
    occurrence finds the first, now-persisted, row rather than attempting
    a double-insert)."""
    return [upsert_job(session, source, record) for record in records]
