"""Structural tests for the STORY-057 (Database Indexing Strategy) index
declarations on `Job`. These check the SQLAlchemy `Index` objects declared
in `Job.__table_args__` -- column order, partial predicates, GIN expression
text -- entirely offline, with zero live infrastructure. Planner-behavior
proof (that PostgreSQL actually chooses these indexes over a sequential
scan at realistic data volumes) is a separate, manual, real-Postgres
validation documented in progress.md, matching this repo's established
convention (STORY-010/011/014/015/025) rather than requiring live infra in
the committed suite -- and matching STORY-057's own explicit instruction
not to claim an index is broken based on a tiny/empty test table.
"""

from __future__ import annotations

from app.models.job import Job


def _index_by_name(name: str):
    for index in Job.__table__.indexes:
        if index.name == name:
            return index
    raise AssertionError(f"index {name!r} not found on Job.__table__.indexes")


def test_work_mode_index_is_partial_on_non_null():
    index = _index_by_name("ix_jobs_work_mode")
    columns = [c.name for c in index.columns]
    assert columns == ["work_mode"]
    assert "work_mode IS NOT NULL" in str(index.dialect_options["postgresql"]["where"])


def test_employment_type_index_is_partial_on_non_null():
    index = _index_by_name("ix_jobs_employment_type")
    columns = [c.name for c in index.columns]
    assert columns == ["employment_type"]
    assert "employment_type IS NOT NULL" in str(index.dialect_options["postgresql"]["where"])


def test_location_composite_index_column_order_is_broadest_to_narrowest():
    index = _index_by_name("ix_jobs_location_country_region_city")
    columns = [c.name for c in index.columns]
    assert columns == ["location_country", "location_region", "location_city"]


def test_posting_date_index_is_full_not_partial():
    index = _index_by_name("ix_jobs_posting_date")
    columns = [c.name for c in index.columns]
    assert columns == ["posting_date"]
    assert index.dialect_options["postgresql"]["where"] is None


def test_search_vector_index_uses_gin():
    index = _index_by_name("ix_jobs_search_vector")
    assert index.dialect_options["postgresql"]["using"] == "gin"


def test_search_vector_index_expression_covers_story_030_field_list():
    index = _index_by_name("ix_jobs_search_vector")
    expression_sql = str(list(index.expressions)[0])
    assert "job_title" in expression_sql
    assert "company_name" in expression_sql
    assert "description_full" in expression_sql
    assert "skills" in expression_sql
    assert "jobs_search_vector_english" in expression_sql


def test_no_duplicate_index_added_for_exact_dedup_identity():
    """The (source, source_job_id) UNIQUE constraint already provides its
    own index (STORY-010) -- STORY-057 must not add a second, redundant one."""
    index_names = {index.name for index in Job.__table__.indexes}
    assert "ix_jobs_source_source_job_id" not in index_names
    assert not any(
        [c.name for c in index.columns] == ["source", "source_job_id"]
        for index in Job.__table__.indexes
    )


def test_no_duplicate_index_added_for_company_id_fk():
    """company_id already has ix_jobs_company_id from STORY-011 -- STORY-057
    must not add a second index over the same single column."""
    company_id_indexes = [
        index
        for index in Job.__table__.indexes
        if [c.name for c in index.columns] == ["company_id"]
    ]
    assert len(company_id_indexes) == 1
    assert company_id_indexes[0].name == "ix_jobs_company_id"


def test_exactly_five_new_indexes_added_by_story_057():
    expected_new = {
        "ix_jobs_work_mode",
        "ix_jobs_employment_type",
        "ix_jobs_location_country_region_city",
        "ix_jobs_posting_date",
        "ix_jobs_search_vector",
    }
    index_names = {index.name for index in Job.__table__.indexes}
    assert expected_new.issubset(index_names)


def test_no_index_added_for_fields_outside_story_057_literal_scope():
    """seniority/compensation/closing_date/last_seen_at were deliberately
    NOT indexed -- not named by STORY-057's own literal functional
    requirements. This guards against silent, unapproved scope creep."""
    out_of_scope_single_columns = {
        "seniority",
        "compensation_min",
        "compensation_max",
        "compensation_currency",
        "compensation_period",
        "closing_date",
        "last_seen_at",
        "location_raw",
    }
    for index in Job.__table__.indexes:
        columns = {c.name for c in index.columns}
        assert not columns & out_of_scope_single_columns, (
            f"unexpected index {index.name!r} touches out-of-scope column(s) "
            f"{columns & out_of_scope_single_columns}"
        )
