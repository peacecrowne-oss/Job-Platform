"""Structural tests for the Job model that don't require a live database
(STORY-010) — inspects SQLAlchemy metadata only, mirroring the rest of this
repo's infra-free test convention.
"""

from sqlalchemy import CheckConstraint, UniqueConstraint

from app.models.job import EmploymentType, Job, WorkMode


def _column(name: str):
    return Job.__table__.columns[name]


def test_job_table_name() -> None:
    assert Job.__tablename__ == "jobs"


def test_required_columns_are_not_nullable() -> None:
    for name in (
        "id",
        "source",
        "source_job_id",
        "first_seen_at",
        "last_seen_at",
        "created_at",
        "updated_at",
    ):
        assert _column(name).nullable is False, f"{name} should be NOT NULL"


def test_optional_columns_are_nullable() -> None:
    for name in (
        "source_url",
        "company_name",
        "job_title",
        "description_full",
        "compensation_min",
        "benefits",
        "closing_date",
        "work_mode",
        "employment_type",
        "seniority",
        "closed_at",
    ):
        assert _column(name).nullable is True, f"{name} should be nullable"


def test_unique_constraint_on_source_and_source_job_id() -> None:
    unique_constraints = [
        c for c in Job.__table__.constraints if isinstance(c, UniqueConstraint)
    ]
    assert len(unique_constraints) == 1
    column_names = {col.name for col in unique_constraints[0].columns}
    assert column_names == {"source", "source_job_id"}


def test_check_constraints_exist_for_work_mode_and_employment_type() -> None:
    check_names = {
        c.name for c in Job.__table__.constraints if isinstance(c, CheckConstraint)
    }
    assert "ck_jobs_work_mode" in check_names
    assert "ck_jobs_employment_type" in check_names


def test_work_mode_enum_has_no_unknown_member() -> None:
    values = {member.value for member in WorkMode}
    assert values == {"remote", "hybrid", "on_site"}
    assert "unknown" not in values


def test_employment_type_enum_has_no_unknown_member() -> None:
    values = {member.value for member in EmploymentType}
    assert values == {
        "full_time",
        "part_time",
        "contract",
        "temporary",
        "internship",
        "apprenticeship",
        "other",
    }
    assert "unknown" not in values


def test_company_id_is_nullable_and_additive() -> None:
    """STORY-011 added company_id (see test_company_model.py for full FK
    coverage) — this only re-confirms it didn't turn company_name NOT NULL
    or otherwise disturb STORY-010's own fields."""
    assert _column("company_id").nullable is True
    assert _column("company_name").nullable is True
