"""Structural tests for the Source model (STORY-014). No live database
required — table/column/constraint inspection only, mirroring the rest of
this repo's test convention.
"""

from sqlalchemy import CheckConstraint

from app.models.source import Source


def _column(name: str):
    return Source.__table__.columns[name]


def test_source_table_name() -> None:
    assert Source.__tablename__ == "sources"


def test_required_columns_are_not_nullable() -> None:
    for name in ("id", "name", "connector_type", "config", "enabled", "created_at", "updated_at"):
        assert _column(name).nullable is False, f"{name} should be NOT NULL"


def test_optional_columns_are_nullable() -> None:
    for name in ("company_id", "last_run_summary"):
        assert _column(name).nullable is True, f"{name} should be nullable"


def test_enabled_defaults_to_true() -> None:
    assert _column("enabled").server_default is not None
    assert "true" in str(_column("enabled").server_default.arg).lower()


def test_config_defaults_to_empty_object() -> None:
    assert _column("config").server_default is not None


def test_name_and_connector_type_check_constraints_exist() -> None:
    check_names = {
        c.name for c in Source.__table__.constraints if isinstance(c, CheckConstraint)
    }
    assert "ck_sources_name_not_empty" in check_names
    assert "ck_sources_connector_type_not_empty" in check_names


def test_company_id_is_nullable_foreign_key_with_set_null() -> None:
    column = _column("company_id")
    assert column.nullable is True
    assert len(column.foreign_keys) == 1
    fk = next(iter(column.foreign_keys))
    assert fk.column.table.name == "companies"
    assert fk.ondelete == "SET NULL"


def test_no_speculative_scheduling_columns_invented() -> None:
    """base_url and refresh_interval_minutes deliberately don't exist yet —
    base_url belongs inside config (JSONB); refresh_interval_minutes is
    STORY-021's own field to add later."""
    for invented in ("base_url", "refresh_interval_minutes"):
        assert invented not in Source.__table__.columns
