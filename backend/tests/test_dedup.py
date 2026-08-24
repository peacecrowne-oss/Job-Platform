"""Tests for exact deduplication (STORY-025) and provenance preservation
(STORY-029). No live infrastructure required -- these cover the pure-logic
functions (`compute_content_hash`, `classify_upsert`, `build_job_fields`)
fully offline, plus `upsert_job()`'s UPDATE-path branching logic via a
minimal fake `Session` (below) -- not a real database, just enough surface
for `session.execute(...).scalar_one_or_none()`/`.add()`/`.flush()` to run
against a `Job` instance built directly in Python. `upsert_job()`'s
original CREATE-path database behavior was validated manually against a
real Postgres during STORY-025's implementation (see progress.md),
matching this repo's established convention (STORY-010/011/014/015)
rather than requiring live infrastructure in the committed suite.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

import app.models.company  # noqa: F401 -- needed for Job.company relationship resolution
from app.connectors.base import NormalizedJobRecord
from app.ingestion.dedup import (
    UpsertOutcome,
    build_job_fields,
    classify_upsert,
    compute_content_hash,
    upsert_job,
)
from app.models.job import Job


class _FakeSession:
    """Minimal stand-in for sqlalchemy.orm.Session -- just enough surface
    for upsert_job()'s UPDATE path to run against a pre-built Job
    instance, with zero real database access."""

    def __init__(self, existing_job: Job | None = None) -> None:
        self._existing_job = existing_job
        self.added: list[Job] = []

    def execute(self, _statement):
        return self

    def scalar_one_or_none(self) -> Job | None:
        return self._existing_job

    def add(self, obj: Job) -> None:
        self.added.append(obj)

    def flush(self) -> None:
        pass


def _existing_job(**overrides) -> Job:
    """A Job row as it would exist after a prior successful upsert --
    built directly in Python, no database required."""
    defaults = dict(
        source="greenhouse",
        source_job_id="123",
        job_title="Software Engineer",
        company_name="Acme",
        source_url="https://example.invalid/jobs/123",
        application_url="https://example.invalid/jobs/123/apply",
        description_full="Do things.",
        raw_metadata={"id": 123, "title": "Software Engineer"},
        source_updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        content_hash=compute_content_hash(_record()),
        first_seen_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        last_seen_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return Job(**defaults)


def _record(**overrides) -> NormalizedJobRecord:
    defaults = dict(
        source_job_id="123",
        job_title="Software Engineer",
        company_name="Acme",
        source_url="https://example.invalid/jobs/123",
        description_full="Do things.",
    )
    defaults.update(overrides)
    return NormalizedJobRecord(**defaults)


# -- compute_content_hash ------------------------------------------------


def test_identical_records_produce_identical_hash() -> None:
    a = _record()
    b = _record()
    assert compute_content_hash(a) == compute_content_hash(b)


def test_changed_title_produces_different_hash() -> None:
    a = _record(job_title="Engineer")
    b = _record(job_title="Senior Engineer")
    assert compute_content_hash(a) != compute_content_hash(b)


def test_changed_source_updated_at_does_not_change_hash() -> None:
    a = _record(source_updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    b = _record(source_updated_at=datetime(2026, 6, 1, tzinfo=timezone.utc))
    assert compute_content_hash(a) == compute_content_hash(b)


def test_changed_raw_metadata_does_not_change_hash() -> None:
    a = _record(raw_metadata={"id": 1, "internal_counter": 1})
    b = _record(raw_metadata={"id": 1, "internal_counter": 999})
    assert compute_content_hash(a) == compute_content_hash(b)


def test_hash_is_stable_across_dict_construction_order() -> None:
    """Field-order independence -- json.dumps(sort_keys=True) guarantees
    this regardless of how the record's fields were assigned."""
    a = NormalizedJobRecord(
        source_job_id="1", job_title="Engineer", location_raw="Remote", department="Eng"
    )
    b = NormalizedJobRecord(
        department="Eng", location_raw="Remote", job_title="Engineer", source_job_id="1"
    )
    assert compute_content_hash(a) == compute_content_hash(b)


def test_compensation_participates_in_hash() -> None:
    a = _record(compensation_min=Decimal("100000"))
    b = _record(compensation_min=Decimal("200000"))
    assert compute_content_hash(a) != compute_content_hash(b)


# -- classify_upsert -------------------------------------------------------


def test_classify_no_existing_hash_is_created() -> None:
    assert classify_upsert(None, "abc") == UpsertOutcome.CREATED


def test_classify_equal_hashes_is_unchanged() -> None:
    assert classify_upsert("abc", "abc") == UpsertOutcome.UNCHANGED


def test_classify_different_hashes_is_updated() -> None:
    assert classify_upsert("abc", "def") == UpsertOutcome.UPDATED


# -- build_job_fields -------------------------------------------------------


def test_build_job_fields_includes_source_and_identity() -> None:
    record = _record()
    fields = build_job_fields("greenhouse", record)
    assert fields["source"] == "greenhouse"
    assert fields["source_job_id"] == "123"


def test_build_job_fields_maps_every_normalized_field() -> None:
    record = NormalizedJobRecord(
        source_job_id="1",
        job_title="Engineer",
        company_name="Acme",
        source_url="https://example.invalid/1",
        application_url="https://example.invalid/1/apply",
        description_full="Desc",
        responsibilities="Resp",
        requirements="Req",
        preferred_requirements="Pref",
        qualifications="Qual",
        skills=["python"],
        skills_raw="python",
        location_raw="Remote",
        location_city="City",
        location_region="Region",
        location_country="Country",
        work_mode="remote",
        employment_type="full_time",
        seniority="senior",
        department="Engineering",
        compensation_min=Decimal("1"),
        compensation_max=Decimal("2"),
        compensation_currency="USD",
        compensation_period="yearly",
        benefits=["health"],
        posting_date=date(2026, 1, 1),
        closing_date=date(2026, 2, 1),
        source_updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        raw_metadata={"raw": True},
    )
    fields = build_job_fields("ashby", record)
    for name in (
        "source_url", "company_name", "job_title", "description_full", "responsibilities",
        "requirements", "preferred_requirements", "qualifications", "skills", "skills_raw",
        "location_raw", "location_city", "location_region", "location_country", "work_mode",
        "employment_type", "seniority", "department", "compensation_min", "compensation_max",
        "compensation_currency", "compensation_period", "benefits", "posting_date",
        "closing_date", "application_url", "source_updated_at", "raw_metadata",
    ):
        assert fields[name] == getattr(record, name)


# -- Connector compatibility -------------------------------------------------


def test_greenhouse_shaped_fixture_hashes_and_maps_without_error() -> None:
    record = NormalizedJobRecord(
        source_job_id="12345",
        job_title="Software Engineer",
        source_url="https://boards.greenhouse.io/acme/jobs/12345",
        application_url="https://boards.greenhouse.io/acme/jobs/12345",
        description_full="<p>Build things.</p>",
        location_raw="Remote - US",
        department="Engineering",
        source_updated_at=datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc),
        raw_metadata={"id": 12345},
    )
    fields = build_job_fields("greenhouse", record)
    assert fields["source_job_id"] == "12345"
    assert compute_content_hash(record)  # does not raise, produces a hash


def test_ashby_shaped_fixture_hashes_and_maps_without_error() -> None:
    record = NormalizedJobRecord(
        source_job_id="7458d4e9-da2e-47bd-98cb-adfda43d42b2",
        job_title="Engineering Manager - EU",
        source_url="https://jobs.ashbyhq.com/acme/7458d4e9",
        application_url="https://jobs.ashbyhq.com/acme/7458d4e9/application",
        description_full="<p>Do things.</p>",
        location_raw="Remote - European Union",
        department="Engineering, EMEA Engineering",
        work_mode="remote",
        employment_type="full_time",
        posting_date=date(2026, 7, 1),
        raw_metadata={"id": "7458d4e9-da2e-47bd-98cb-adfda43d42b2"},
    )
    fields = build_job_fields("ashby", record)
    assert fields["source_job_id"] == "7458d4e9-da2e-47bd-98cb-adfda43d42b2"
    assert compute_content_hash(record)


# -- Critical test: no fuzzy merge by title/company/location similarity ----


def test_same_title_company_location_different_source_never_merged() -> None:
    """Critical test: nothing in this module ever looks up or compares by
    title/company/location -- only the exact (source, source_job_id) key.
    Two records with identical title/company/location but different
    `source` values remain fully independent."""
    record_a = _record(source_job_id="1")
    record_b = _record(source_job_id="1")  # same source_job_id, different source below

    fields_a = build_job_fields("greenhouse", record_a)
    fields_b = build_job_fields("ashby", record_b)

    assert fields_a["job_title"] == fields_b["job_title"]
    assert fields_a["company_name"] == fields_b["company_name"]
    assert fields_a["source"] != fields_b["source"]
    # Nothing in build_job_fields/compute_content_hash/classify_upsert
    # ever reads "source" when computing content -- confirmed by the fact
    # the two hashes ARE equal (same content) despite different sources;
    # merging decisions are made solely by the (source, source_job_id)
    # database lookup in upsert_job, never by content similarity.
    assert compute_content_hash(record_a) == compute_content_hash(record_b)


# -- Malformed input handling -------------------------------------------------


def test_upsert_job_rejects_empty_source_before_touching_session() -> None:
    with pytest.raises(ValueError):
        upsert_job(None, "", _record())  # type: ignore[arg-type]


def test_upsert_job_rejects_none_source_before_touching_session() -> None:
    with pytest.raises(ValueError):
        upsert_job(None, None, _record())  # type: ignore[arg-type]


# -- Provenance preservation (STORY-029) -------------------------------------


def test_source_url_preserved_when_missing_on_update() -> None:
    existing = _existing_job()
    session = _FakeSession(existing)
    new_record = _record(job_title="Senior Software Engineer", source_url=None)

    job, outcome = upsert_job(session, "greenhouse", new_record)

    assert outcome == UpsertOutcome.UPDATED
    assert job.job_title == "Senior Software Engineer"  # content field updates normally
    assert job.source_url == "https://example.invalid/jobs/123"  # preserved, not nulled


def test_application_url_preserved_when_missing_on_update() -> None:
    existing = _existing_job()
    session = _FakeSession(existing)
    new_record = _record(job_title="Senior Software Engineer", application_url=None)

    job, outcome = upsert_job(session, "greenhouse", new_record)

    assert outcome == UpsertOutcome.UPDATED
    assert job.application_url == "https://example.invalid/jobs/123/apply"


def test_raw_metadata_preserved_when_missing_on_update() -> None:
    """The Story's own literal edge case: 'If a source's raw payload
    becomes unavailable later, provenance metadata already stored remains
    intact.'"""
    existing = _existing_job()
    session = _FakeSession(existing)
    new_record = _record(job_title="Senior Software Engineer", raw_metadata=None)

    job, outcome = upsert_job(session, "greenhouse", new_record)

    assert outcome == UpsertOutcome.UPDATED
    assert job.raw_metadata == {"id": 123, "title": "Software Engineer"}


def test_source_updated_at_preserved_when_missing_on_update() -> None:
    existing = _existing_job()
    session = _FakeSession(existing)
    new_record = _record(job_title="Senior Software Engineer", source_updated_at=None)

    job, outcome = upsert_job(session, "greenhouse", new_record)

    assert outcome == UpsertOutcome.UPDATED
    assert job.source_updated_at == datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_provenance_fields_update_normally_when_new_value_present() -> None:
    """The protection only guards against regressing to None -- a genuine
    new value still updates normally."""
    existing = _existing_job()
    session = _FakeSession(existing)
    new_record = _record(
        job_title="Senior Software Engineer",
        source_url="https://example.invalid/jobs/123-renamed",
        application_url="https://example.invalid/jobs/123-renamed/apply",
        raw_metadata={"id": 123, "title": "Senior Software Engineer"},
        source_updated_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )

    job, outcome = upsert_job(session, "greenhouse", new_record)

    assert outcome == UpsertOutcome.UPDATED
    assert job.source_url == "https://example.invalid/jobs/123-renamed"
    assert job.application_url == "https://example.invalid/jobs/123-renamed/apply"
    assert job.raw_metadata == {"id": 123, "title": "Senior Software Engineer"}
    assert job.source_updated_at == datetime(2026, 6, 1, tzinfo=timezone.utc)


def test_ordinary_content_field_can_become_none_on_update() -> None:
    """Proves the None-preservation protection is scoped only to
    provenance fields -- STORY-025's original "newest wins" behavior for
    ordinary content fields is unchanged."""
    existing = _existing_job(department="Engineering")
    existing.content_hash = compute_content_hash(_record(department="Engineering"))
    session = _FakeSession(existing)
    new_record = _record(job_title="Senior Software Engineer", department=None)

    job, outcome = upsert_job(session, "greenhouse", new_record)

    assert outcome == UpsertOutcome.UPDATED
    assert job.department is None


def test_first_seen_at_never_changes_on_update() -> None:
    original_first_seen = datetime(2025, 1, 1, tzinfo=timezone.utc)
    existing = _existing_job(first_seen_at=original_first_seen)
    session = _FakeSession(existing)
    new_record = _record(job_title="Senior Software Engineer")

    job, outcome = upsert_job(session, "greenhouse", new_record)

    assert outcome == UpsertOutcome.UPDATED
    assert job.first_seen_at == original_first_seen


def test_unchanged_observation_never_touches_provenance_fields() -> None:
    existing = _existing_job()
    session = _FakeSession(existing)
    # Identical to the record _existing_job()'s own content_hash was built from.
    same_record = _record()

    job, outcome = upsert_job(session, "greenhouse", same_record)

    assert outcome == UpsertOutcome.UNCHANGED
    assert job.source_url == "https://example.invalid/jobs/123"
    assert job.raw_metadata == {"id": 123, "title": "Software Engineer"}


def test_greenhouse_shaped_provenance_preserved_on_update() -> None:
    """Realistic Greenhouse-shaped fixture (mirroring STORY-018's real
    output) proves the protection works against real connector shapes."""
    existing_raw = {"id": 12345, "title": "Software Engineer"}
    existing = _existing_job(
        source="greenhouse",
        source_job_id="12345",
        source_url="https://boards.greenhouse.io/acme/jobs/12345",
        application_url="https://boards.greenhouse.io/acme/jobs/12345",
        raw_metadata=existing_raw,
        content_hash=compute_content_hash(
            _record(source_job_id="12345", job_title="Software Engineer")
        ),
    )
    session = _FakeSession(existing)
    new_record = _record(
        source_job_id="12345",
        job_title="Senior Software Engineer",
        source_url=None,
        application_url=None,
        raw_metadata=None,
    )

    job, outcome = upsert_job(session, "greenhouse", new_record)

    assert outcome == UpsertOutcome.UPDATED
    assert job.source_url == "https://boards.greenhouse.io/acme/jobs/12345"
    assert job.application_url == "https://boards.greenhouse.io/acme/jobs/12345"
    assert job.raw_metadata == existing_raw


def test_ashby_shaped_provenance_preserved_on_update() -> None:
    """Realistic Ashby-shaped fixture (mirroring STORY-019's real output)."""
    existing_raw = {"id": "7458d4e9-da2e-47bd-98cb-adfda43d42b2"}
    existing = _existing_job(
        source="ashby",
        source_job_id="7458d4e9-da2e-47bd-98cb-adfda43d42b2",
        source_url="https://jobs.ashbyhq.com/acme/7458d4e9",
        application_url="https://jobs.ashbyhq.com/acme/7458d4e9/application",
        raw_metadata=existing_raw,
        content_hash=compute_content_hash(
            _record(
                source_job_id="7458d4e9-da2e-47bd-98cb-adfda43d42b2",
                job_title="Engineering Manager - EU",
            )
        ),
    )
    session = _FakeSession(existing)
    new_record = _record(
        source_job_id="7458d4e9-da2e-47bd-98cb-adfda43d42b2",
        job_title="Engineering Manager - EU (Updated)",
        raw_metadata=None,
    )

    job, outcome = upsert_job(session, "ashby", new_record)

    assert outcome == UpsertOutcome.UPDATED
    assert job.raw_metadata == existing_raw
