"""Data Quality Validation (STORY-027).

Sits between a connector's normalized output and any later persistence/
dedup/provenance step:

    Connector.normalize() -> NormalizedJobRecord -> validate_record() ->
    ValidationResult -> (future) persistence/dedup/provenance

`validate_record()` is a pure function: no I/O, never mutates its input,
never raises for malformed *data* (only a genuine programming error would
raise) -- it always returns a `ValidationResult`, even for a maximally
broken record. This is what guarantees a batch of records can be validated
without one bad record aborting the rest (see `validate_batch()`).

Required fields, per requirement.md's literal AC, are exactly: title,
company, source_url. Everything else missing/absent raises no issue at
all -- not even a warning -- per requirement.md's own edge case ("Partial
data (e.g. missing compensation) is valid"). Warnings are reserved for
fields that are *present but questionable* (a malformed application_url, a
naive timestamp, an unrecognized controlled value), never for fields that
are simply absent.

"Company" resolution (flagged, approved decision): NormalizedJobRecord's
`company_name` is never populated by either implemented connector
(Greenhouse/Ashby don't reliably expose a per-job company name) -- so
checking `company_name` alone would hard-fail every real record either
connector can currently produce. `validate_record()` accepts an optional
`source_company_name` parameter (intended to be the linked `Source`'s
`Company.name`, once an orchestrator exists to supply it); the "company"
requirement is satisfied if *either* value is present.

No IngestionRun/persistence wiring happens here -- no orchestrator exists
yet to drive it (same boundary STORY-016/017 respected for their own
interfaces). `ValidationResult`'s shape is designed to be directly
tally-compatible with `IngestionRun`'s `jobs_failed` counter and
`error_summary` text field once one exists.
"""

from __future__ import annotations

import enum
from collections.abc import Iterable
from urllib.parse import urlsplit

from pydantic import BaseModel

from app.connectors.base import NormalizedJobRecord

_VALID_WORK_MODES = {"remote", "hybrid", "on_site"}
_VALID_EMPLOYMENT_TYPES = {
    "full_time",
    "part_time",
    "contract",
    "temporary",
    "internship",
    "apprenticeship",
    "other",
}


class ValidationSeverity(str, enum.Enum):
    ERROR = "error"
    WARNING = "warning"


class ValidationIssue(BaseModel):
    field: str
    code: str
    message: str
    severity: ValidationSeverity


class ValidationResult(BaseModel):
    is_valid: bool
    issues: list[ValidationIssue]

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == ValidationSeverity.ERROR]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == ValidationSeverity.WARNING]


class BatchValidationOutcome(BaseModel):
    record: NormalizedJobRecord
    result: ValidationResult


def _is_blank(value: str | None) -> bool:
    return value is None or not value.strip()


def _is_well_formed_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def validate_record(
    record: NormalizedJobRecord, *, source_company_name: str | None = None
) -> ValidationResult:
    issues: list[ValidationIssue] = []

    def error(field: str, code: str, message: str) -> None:
        issues.append(
            ValidationIssue(field=field, code=code, message=message, severity=ValidationSeverity.ERROR)
        )

    def warning(field: str, code: str, message: str) -> None:
        issues.append(
            ValidationIssue(
                field=field, code=code, message=message, severity=ValidationSeverity.WARNING
            )
        )

    # -- Required fields (requirement.md's literal AC) -------------------
    if _is_blank(record.job_title):
        error("job_title", "missing_title", "Job title is missing or blank.")

    if _is_blank(record.company_name) and _is_blank(source_company_name):
        error(
            "company_name",
            "missing_company",
            "No company name available on the record or its source.",
        )

    if record.source_url is None:
        error("source_url", "missing_source_url", "source_url is missing.")
    elif not _is_well_formed_url(record.source_url):
        error("source_url", "malformed_source_url", "source_url is not a well-formed http(s) URL.")

    # -- Sanity checks (warnings only, per requirement.md's edge case) ---
    if _is_blank(record.description_full):
        warning("description_full", "empty_description", "Description is missing or blank.")

    if record.application_url is not None and not _is_well_formed_url(record.application_url):
        warning(
            "application_url",
            "malformed_application_url",
            "application_url is present but not a well-formed http(s) URL.",
        )

    if record.source_updated_at is not None and record.source_updated_at.tzinfo is None:
        warning(
            "source_updated_at",
            "naive_source_updated_at",
            "source_updated_at is present but has no timezone information.",
        )

    if record.work_mode is not None and record.work_mode not in _VALID_WORK_MODES:
        warning("work_mode", "unrecognized_work_mode", f"Unrecognized work_mode: {record.work_mode!r}")

    if record.employment_type is not None and record.employment_type not in _VALID_EMPLOYMENT_TYPES:
        warning(
            "employment_type",
            "unrecognized_employment_type",
            f"Unrecognized employment_type: {record.employment_type!r}",
        )

    # -- Structural impossibilities --------------------------------------
    if record.compensation_min is not None and record.compensation_min < 0:
        error("compensation_min", "negative_compensation", "compensation_min is negative.")
    if record.compensation_max is not None and record.compensation_max < 0:
        error("compensation_max", "negative_compensation", "compensation_max is negative.")
    if (
        record.compensation_min is not None
        and record.compensation_max is not None
        and record.compensation_min > record.compensation_max
    ):
        error(
            "compensation_min",
            "compensation_min_gt_max",
            "compensation_min is greater than compensation_max.",
        )

    if (
        record.posting_date is not None
        and record.closing_date is not None
        and record.closing_date < record.posting_date
    ):
        error(
            "closing_date",
            "closing_date_before_posting_date",
            "closing_date is before posting_date.",
        )

    is_valid = not any(i.severity == ValidationSeverity.ERROR for i in issues)
    return ValidationResult(is_valid=is_valid, issues=issues)


def validate_batch(
    records: Iterable[NormalizedJobRecord], *, source_company_name: str | None = None
) -> list[BatchValidationOutcome]:
    """Validates every record independently -- one malformed record can
    never prevent the rest of the batch from being validated, since
    validate_record() never raises."""
    return [
        BatchValidationOutcome(
            record=record, result=validate_record(record, source_company_name=source_company_name)
        )
        for record in records
    ]
