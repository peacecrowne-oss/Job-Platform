"""Tests for the Data Quality Validation layer (STORY-027). No live
infrastructure or network access required -- pure function tests against
`NormalizedJobRecord` instances, including realistic Greenhouse/Ashby
shapes matching what those connectors actually produce.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from app.connectors.base import NormalizedJobRecord
from app.validation.data_quality import (
    ValidationSeverity,
    validate_batch,
    validate_record,
)


def _minimal_valid_record(**overrides) -> NormalizedJobRecord:
    """A record with zero validation issues by default -- every field that
    would otherwise raise a warning (e.g. a blank description) is filled
    in, so tests can override exactly the field they're exercising without
    an unrelated warning leaking into the result."""
    defaults = dict(
        source_job_id="123",
        job_title="Software Engineer",
        source_url="https://example.invalid/jobs/123",
        description_full="Do interesting things.",
    )
    defaults.update(overrides)
    return NormalizedJobRecord(**defaults)


def test_valid_minimal_record_with_source_company_name() -> None:
    record = _minimal_valid_record()
    result = validate_record(record, source_company_name="Acme")
    assert result.is_valid is True
    assert result.issues == []


def test_valid_rich_record_has_no_issues() -> None:
    record = NormalizedJobRecord(
        source_job_id="1",
        job_title="Engineer",
        company_name="Acme",
        source_url="https://example.invalid/jobs/1",
        application_url="https://example.invalid/jobs/1/apply",
        description_full="Do things.",
        location_raw="Remote",
        department="Engineering",
        work_mode="remote",
        employment_type="full_time",
        compensation_min=Decimal("100000"),
        compensation_max=Decimal("150000"),
        compensation_currency="USD",
        compensation_period="yearly",
        posting_date=date(2026, 1, 1),
        closing_date=date(2026, 2, 1),
        source_updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    result = validate_record(record)
    assert result.is_valid is True
    assert result.issues == []


def test_missing_title_is_error() -> None:
    record = _minimal_valid_record(job_title=None)
    result = validate_record(record, source_company_name="Acme")
    assert result.is_valid is False
    assert any(i.code == "missing_title" and i.severity == ValidationSeverity.ERROR for i in result.issues)


def test_blank_title_is_error() -> None:
    record = _minimal_valid_record(job_title="   ")
    result = validate_record(record, source_company_name="Acme")
    assert result.is_valid is False
    assert any(i.code == "missing_title" for i in result.issues)


def test_missing_source_url_is_error() -> None:
    record = _minimal_valid_record(source_url=None)
    result = validate_record(record, source_company_name="Acme")
    assert result.is_valid is False
    assert any(i.code == "missing_source_url" for i in result.issues)


def test_malformed_source_url_is_error() -> None:
    record = _minimal_valid_record(source_url="not-a-url")
    result = validate_record(record, source_company_name="Acme")
    assert result.is_valid is False
    assert any(i.code == "malformed_source_url" for i in result.issues)


def test_missing_company_on_both_record_and_parameter_is_error() -> None:
    record = _minimal_valid_record()  # company_name defaults to None
    result = validate_record(record)  # no source_company_name either
    assert result.is_valid is False
    assert any(i.code == "missing_company" for i in result.issues)


def test_company_present_via_source_company_name_only_is_valid() -> None:
    record = _minimal_valid_record()  # record.company_name is None
    result = validate_record(record, source_company_name="Acme")
    assert result.is_valid is True


def test_company_present_via_record_only_is_valid() -> None:
    record = _minimal_valid_record(company_name="Acme")
    result = validate_record(record)  # no source_company_name
    assert result.is_valid is True


def test_compensation_min_greater_than_max_is_error() -> None:
    record = _minimal_valid_record(
        company_name="Acme", compensation_min=Decimal("200000"), compensation_max=Decimal("100000")
    )
    result = validate_record(record)
    assert result.is_valid is False
    assert any(i.code == "compensation_min_gt_max" for i in result.issues)


def test_negative_compensation_is_error() -> None:
    record = _minimal_valid_record(company_name="Acme", compensation_min=Decimal("-1"))
    result = validate_record(record)
    assert result.is_valid is False
    assert any(i.code == "negative_compensation" for i in result.issues)


def test_closing_date_before_posting_date_is_error() -> None:
    record = _minimal_valid_record(
        company_name="Acme", posting_date=date(2026, 2, 1), closing_date=date(2026, 1, 1)
    )
    result = validate_record(record)
    assert result.is_valid is False
    assert any(i.code == "closing_date_before_posting_date" for i in result.issues)


def test_empty_description_is_warning_only_still_valid() -> None:
    record = _minimal_valid_record(company_name="Acme", description_full=None)
    result = validate_record(record)
    assert result.is_valid is True
    assert any(
        i.code == "empty_description" and i.severity == ValidationSeverity.WARNING
        for i in result.issues
    )


def test_malformed_application_url_is_warning_only_still_valid() -> None:
    record = _minimal_valid_record(company_name="Acme", application_url="not-a-url")
    result = validate_record(record)
    assert result.is_valid is True
    assert any(i.code == "malformed_application_url" for i in result.issues)


def test_naive_source_updated_at_is_warning_only_still_valid() -> None:
    record = _minimal_valid_record(
        company_name="Acme", source_updated_at=datetime(2026, 1, 1)  # no tzinfo
    )
    result = validate_record(record)
    assert result.is_valid is True
    assert any(i.code == "naive_source_updated_at" for i in result.issues)


def test_unrecognized_work_mode_is_warning_only_still_valid() -> None:
    record = _minimal_valid_record(company_name="Acme", work_mode="underwater")
    result = validate_record(record)
    assert result.is_valid is True
    assert any(i.code == "unrecognized_work_mode" for i in result.issues)


def test_unrecognized_employment_type_is_warning_only_still_valid() -> None:
    record = _minimal_valid_record(company_name="Acme", employment_type="freelance")
    result = validate_record(record)
    assert result.is_valid is True
    assert any(i.code == "unrecognized_employment_type" for i in result.issues)


def test_missing_optional_fields_produce_zero_issues() -> None:
    """Per requirement.md's own edge case: partial data (missing
    compensation, benefits, department, skills, closing_date,
    application_url) is valid -- not even a warning."""
    record = _minimal_valid_record(company_name="Acme")
    result = validate_record(record)
    assert result.is_valid is True
    assert result.issues == []


def test_multiple_simultaneous_errors_all_reported() -> None:
    record = _minimal_valid_record(job_title=None, source_url=None)
    result = validate_record(record)  # also missing company
    assert result.is_valid is False
    codes = {i.code for i in result.errors}
    assert codes == {"missing_title", "missing_source_url", "missing_company"}


def test_greenhouse_shaped_fixture_requires_source_company_name() -> None:
    """Mirrors what GreenhouseConnector.normalize() actually produces --
    company_name is always None (STORY-018)."""
    record = NormalizedJobRecord(
        source_job_id="12345",
        job_title="Software Engineer",
        source_url="https://boards.greenhouse.io/acme/jobs/12345",
        application_url="https://boards.greenhouse.io/acme/jobs/12345",
        description_full="<p>Build things.</p>",
        location_raw="Remote - US",
        department="Engineering",
        source_updated_at=datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc),
        raw_metadata={"id": 12345, "title": "Software Engineer"},
    )
    assert record.company_name is None

    without_source_company = validate_record(record)
    assert without_source_company.is_valid is False
    assert any(i.code == "missing_company" for i in without_source_company.issues)

    with_source_company = validate_record(record, source_company_name="Acme")
    assert with_source_company.is_valid is True


def test_ashby_shaped_fixture_requires_source_company_name() -> None:
    """Mirrors what AshbyConnector.normalize() actually produces --
    company_name is always None (STORY-019)."""
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
    assert record.company_name is None

    without_source_company = validate_record(record)
    assert without_source_company.is_valid is False
    assert any(i.code == "missing_company" for i in without_source_company.issues)

    with_source_company = validate_record(record, source_company_name="Ashby")
    assert with_source_company.is_valid is True


def test_raw_metadata_preserved_untouched_by_validation() -> None:
    raw = {"id": 1, "nested": {"a": 1, "b": [1, 2, 3]}}
    record = _minimal_valid_record(company_name="Acme", raw_metadata=raw)
    validate_record(record)
    assert record.raw_metadata == raw


def test_no_mutation_of_input_record() -> None:
    record = _minimal_valid_record(company_name="Acme")
    before = record.model_dump()
    validate_record(record)
    after = record.model_dump()
    assert before == after


def test_validate_batch_one_broken_record_does_not_prevent_others() -> None:
    valid_record = _minimal_valid_record(company_name="Acme")
    broken_record = _minimal_valid_record(source_job_id="2", job_title=None, source_url=None)
    outcomes = validate_batch([valid_record, broken_record], source_company_name="Fallback Co")

    assert len(outcomes) == 2
    assert outcomes[0].result.is_valid is True
    assert outcomes[1].result.is_valid is False
    assert outcomes[1].record.source_job_id == "2"


def test_validation_result_shape_is_tally_compatible_with_ingestion_run_counters() -> None:
    """Proves the result shape is directly usable for IngestionRun's
    jobs_failed counter without further translation -- no database touched."""
    records = [
        _minimal_valid_record(source_job_id=str(i), company_name="Acme") for i in range(3)
    ] + [_minimal_valid_record(source_job_id="bad", job_title=None)]
    outcomes = validate_batch(records)

    jobs_seen = len(outcomes)
    jobs_failed = sum(1 for o in outcomes if not o.result.is_valid)

    assert jobs_seen == 4
    assert jobs_failed == 1
