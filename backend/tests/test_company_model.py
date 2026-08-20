"""Structural tests for the Company model and normalize_company_name(), plus
regression checks on Job's new company_id column (STORY-011). No live
database required — table/column/constraint inspection and pure-function
tests only, mirroring the rest of this repo's test convention.
"""

from sqlalchemy import UniqueConstraint

from app.models.company import Company, normalize_company_name
from app.models.job import Job


def _company_column(name: str):
    return Company.__table__.columns[name]


def _job_column(name: str):
    return Job.__table__.columns[name]


def test_company_table_name() -> None:
    assert Company.__tablename__ == "companies"


def test_required_and_optional_columns() -> None:
    assert _company_column("name").nullable is False
    assert _company_column("normalized_name").nullable is False
    assert _company_column("domain").nullable is True
    assert _company_column("company_metadata").nullable is True
    assert _company_column("created_at").nullable is False
    assert _company_column("updated_at").nullable is False


def test_unique_constraint_on_normalized_name() -> None:
    unique_constraints = [
        c for c in Company.__table__.constraints if isinstance(c, UniqueConstraint)
    ]
    assert len(unique_constraints) == 1
    column_names = {col.name for col in unique_constraints[0].columns}
    assert column_names == {"normalized_name"}


def test_no_speculative_metadata_columns_invented() -> None:
    """Only name/normalized_name/domain/company_metadata are named by
    requirement.md — nothing else should exist as a dedicated column."""
    for invented in ("website", "careers_url", "description", "logo_url", "industry"):
        assert invented not in Company.__table__.columns


# --- normalize_company_name() ---


def test_normalize_strips_and_lowercases() -> None:
    assert normalize_company_name("  Acme Corp  ") == "acme corp"


def test_normalize_collapses_repeated_whitespace() -> None:
    assert normalize_company_name("Acme    Corp") == "acme corp"


def test_normalize_strips_trivial_trailing_punctuation() -> None:
    assert normalize_company_name("Acme Corp.") == "acme corp"
    assert normalize_company_name("Acme Corp,") == "acme corp"


def test_normalize_does_not_fuzzy_match_legal_suffixes() -> None:
    """Deliberately not aggressive: distinct legal-entity phrasing stays distinct."""
    assert normalize_company_name("Acme Inc.") != normalize_company_name(
        "ACME Corporation"
    )


def test_constructing_a_company_auto_derives_normalized_name() -> None:
    company = Company(name="  ACME  Corp.  ")
    assert company.normalized_name == "acme corp"


# --- Job.company_id (STORY-011 addition) ---


def test_job_has_nullable_company_id_foreign_key() -> None:
    column = _job_column("company_id")
    assert column.nullable is True
    assert len(column.foreign_keys) == 1
    fk = next(iter(column.foreign_keys))
    assert fk.column.table.name == "companies"


def test_job_company_id_delete_behavior_is_set_null() -> None:
    column = _job_column("company_id")
    fk = next(iter(column.foreign_keys))
    assert fk.ondelete == "SET NULL"


def test_job_company_name_unchanged_by_story_011() -> None:
    """Regression: company_name must still exist exactly as STORY-010 left it."""
    column = _job_column("company_name")
    assert column.nullable is True
    assert column.type.length == 255
