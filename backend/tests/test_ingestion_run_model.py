"""Structural tests for the IngestionRun model (STORY-015). No live database
required — table/column/constraint inspection only, mirroring the rest of
this repo's test convention.
"""

from sqlalchemy import CheckConstraint

from app.models.ingestion_run import IngestionRun


def _column(name: str):
    return IngestionRun.__table__.columns[name]


def test_ingestion_run_table_name() -> None:
    assert IngestionRun.__tablename__ == "ingestion_runs"


def test_required_columns_are_not_nullable() -> None:
    for name in (
        "id",
        "started_at",
        "status",
        "jobs_seen",
        "jobs_created",
        "jobs_updated",
        "jobs_failed",
        "updated_at",
    ):
        assert _column(name).nullable is False, f"{name} should be NOT NULL"


def test_optional_columns_are_nullable() -> None:
    for name in ("source_id", "finished_at", "error_summary"):
        assert _column(name).nullable is True, f"{name} should be nullable"


def test_status_defaults_to_running() -> None:
    assert _column("status").server_default is not None
    assert "running" in str(_column("status").server_default.arg).lower()


def test_counters_default_to_zero() -> None:
    for name in ("jobs_seen", "jobs_created", "jobs_updated", "jobs_failed"):
        default = _column(name).server_default
        assert default is not None
        assert str(default.arg) == "0"


def test_status_check_constraint_exists_with_exact_values() -> None:
    check_names = {
        c.name for c in IngestionRun.__table__.constraints if isinstance(c, CheckConstraint)
    }
    assert "ck_ingestion_runs_status" in check_names
    status_check = next(
        c
        for c in IngestionRun.__table__.constraints
        if isinstance(c, CheckConstraint) and c.name == "ck_ingestion_runs_status"
    )
    condition = str(status_check.sqltext)
    for value in ("running", "success", "failed"):
        assert value in condition


def test_counter_non_negative_check_constraints_exist() -> None:
    check_names = {
        c.name for c in IngestionRun.__table__.constraints if isinstance(c, CheckConstraint)
    }
    for name in (
        "ck_ingestion_runs_jobs_seen_non_negative",
        "ck_ingestion_runs_jobs_created_non_negative",
        "ck_ingestion_runs_jobs_updated_non_negative",
        "ck_ingestion_runs_jobs_failed_non_negative",
    ):
        assert name in check_names


def test_source_id_is_nullable_foreign_key_with_set_null() -> None:
    column = _column("source_id")
    assert column.nullable is True
    assert len(column.foreign_keys) == 1
    fk = next(iter(column.foreign_keys))
    assert fk.column.table.name == "sources"
    assert fk.ondelete == "SET NULL"


def test_no_speculative_columns_invented() -> None:
    """jobs_discovered/jobs_unchanged/jobs_closed/worker_id deliberately
    don't exist — none of those names appear in requirement.md's STORY-015
    functional requirements (the literal counter name is jobs_seen, and a
    worker identifier belongs to scheduler infrastructure, not this Story).
    """
    for invented in ("jobs_discovered", "jobs_unchanged", "jobs_closed", "worker_id", "created_at"):
        assert invented not in IngestionRun.__table__.columns
