"""Tests for the STORY-030 full-text search service, extended by STORY-031
(faceted filtering) and STORY-032 (sorting). No live database required --
these check the SQLAlchemy statement `search_jobs()` builds by compiling
it (with bound parameters, never literal-inlined) and inspecting the
resulting SQL/params. Real matching/ranking/index-usage/filter-narrowing/
sort-ordering behavior was validated manually against a real Postgres
during implementation (see progress.md), matching this repo's established
convention (STORY-010/011/014/015/025/057/030/033/031) rather than
requiring live infrastructure in the committed suite -- and matching
README's own stated boundary that live-DB integration-test infrastructure
belongs to STORY-054, not this Story.
"""

from __future__ import annotations

from app.models.job import Job
from app.search.service import SortMode, _has_search_terms, search_jobs


class _FakeScalars:
    def __init__(self, rows: list[Job]) -> None:
        self._rows = rows

    def all(self) -> list[Job]:
        return self._rows


class _FakeResult:
    def __init__(self, rows: list[Job]) -> None:
        self._rows = rows

    def scalars(self) -> _FakeScalars:
        return _FakeScalars(self._rows)


class _CapturingSession:
    """Captures the compiled statement passed to execute() without ever
    touching a real database."""

    def __init__(self, rows: list[Job] | None = None) -> None:
        self.captured_stmt = None
        self._rows = rows or []

    def execute(self, stmt):
        self.captured_stmt = stmt
        return _FakeResult(self._rows)


def _compiled_sql(stmt) -> str:
    return str(stmt.compile(compile_kwargs={"literal_binds": False}))


class TestHasSearchTerms:
    def test_empty_string_has_no_terms(self) -> None:
        assert _has_search_terms("") is False

    def test_whitespace_only_has_no_terms(self) -> None:
        assert _has_search_terms("   \t\n  ") is False

    def test_punctuation_only_has_no_terms(self) -> None:
        assert _has_search_terms("???") is False
        assert _has_search_terms("!!! ---") is False

    def test_normal_keyword_has_terms(self) -> None:
        assert _has_search_terms("engineer") is True

    def test_alphanumeric_mixed_with_punctuation_has_terms(self) -> None:
        assert _has_search_terms("C++") is True


class TestSearchJobsQueryConstruction:
    def test_empty_query_omits_search_filter(self) -> None:
        session = _CapturingSession()
        search_jobs(session, "", limit=20, offset=0)
        sql = _compiled_sql(session.captured_stmt)
        assert "websearch_to_tsquery" not in sql
        assert "@@" not in sql

    def test_whitespace_query_omits_search_filter(self) -> None:
        session = _CapturingSession()
        search_jobs(session, "   ", limit=20, offset=0)
        sql = _compiled_sql(session.captured_stmt)
        assert "websearch_to_tsquery" not in sql

    def test_punctuation_only_query_omits_search_filter(self) -> None:
        session = _CapturingSession()
        search_jobs(session, "???", limit=20, offset=0)
        sql = _compiled_sql(session.captured_stmt)
        assert "websearch_to_tsquery" not in sql

    def test_none_query_omits_search_filter(self) -> None:
        session = _CapturingSession()
        search_jobs(session, None, limit=20, offset=0)
        sql = _compiled_sql(session.captured_stmt)
        assert "websearch_to_tsquery" not in sql

    def test_unfiltered_orders_by_posting_date_desc_then_id(self) -> None:
        session = _CapturingSession()
        search_jobs(session, "", limit=20, offset=0)
        sql = _compiled_sql(session.captured_stmt)
        assert "ORDER BY jobs.posting_date DESC" in sql
        assert "jobs.id ASC" in sql
        assert "ts_rank_cd" not in sql

    def test_real_query_applies_search_filter(self) -> None:
        session = _CapturingSession()
        search_jobs(session, "engineer", limit=20, offset=0)
        sql = _compiled_sql(session.captured_stmt)
        assert "websearch_to_tsquery" in sql
        assert "@@" in sql
        assert "jobs_search_vector_english" in sql

    def test_real_query_orders_by_rank_then_posting_date_then_id(self) -> None:
        session = _CapturingSession()
        search_jobs(session, "engineer", limit=20, offset=0)
        sql = _compiled_sql(session.captured_stmt)
        assert "ts_rank_cd" in sql
        assert sql.index("ts_rank_cd") < sql.index("jobs.posting_date DESC")
        assert sql.index("jobs.posting_date DESC") < sql.index("jobs.id ASC")

    def test_search_vector_expression_uses_exact_index_argument_order(self) -> None:
        """Must match ix_jobs_search_vector's stored expression argument-
        for-argument for PostgreSQL's planner to use the index."""
        session = _CapturingSession()
        search_jobs(session, "engineer", limit=20, offset=0)
        sql = _compiled_sql(session.captured_stmt)
        call = sql[sql.index("jobs_search_vector_english(") :]
        call = call[: call.index(")") + 1]
        assert "jobs.job_title" in call
        assert call.index("jobs.job_title") < call.index("jobs.company_name")
        assert call.index("jobs.company_name") < call.index("jobs.description_full")
        assert call.index("jobs.description_full") < call.index("jobs.skills")

    def test_limit_and_offset_applied(self) -> None:
        session = _CapturingSession()
        search_jobs(session, "engineer", limit=5, offset=10)
        sql = _compiled_sql(session.captured_stmt)
        assert "LIMIT" in sql
        assert "OFFSET" in sql

    def test_raw_search_text_never_appears_literally_in_compiled_sql(self) -> None:
        """Query safety: the search string must be bound, never
        interpolated -- proven with a deliberately adversarial input."""
        session = _CapturingSession()
        malicious = "'; DROP TABLE jobs; --"
        search_jobs(session, malicious, limit=20, offset=0)
        sql = _compiled_sql(session.captured_stmt)
        assert malicious not in sql
        assert "DROP TABLE" not in sql

    def test_search_text_is_bound_as_a_parameter(self) -> None:
        session = _CapturingSession()
        search_jobs(session, "engineer", limit=20, offset=0)
        compiled = session.captured_stmt.compile(compile_kwargs={"literal_binds": False})
        assert "engineer" in compiled.params.values()

    def test_returns_rows_from_session_execute(self) -> None:
        job = Job(source="synthetic", source_job_id="1", job_title="Engineer")
        session = _CapturingSession(rows=[job])
        result = search_jobs(session, "engineer", limit=20, offset=0)
        assert result == [job]


class TestSearchJobsFiltering:
    def test_no_filters_adds_no_where_clause_beyond_search(self) -> None:
        """STORY-028: the default `closed_at IS NULL` filter is always
        present now -- this test's own name predates that and only ever
        meant "no *facet* filter adds anything beyond search"."""
        session = _CapturingSession()
        search_jobs(session, "engineer", limit=20, offset=0)
        sql = _compiled_sql(session.captured_stmt)
        assert sql.count("WHERE") == 1
        assert sql.count(" AND ") == 1  # search predicate AND closed_at IS NULL, nothing more
        assert "jobs.closed_at IS NULL" in sql

    def test_work_mode_filter_adds_in_clause(self) -> None:
        session = _CapturingSession()
        search_jobs(session, "", limit=20, offset=0, work_mode=["remote", "hybrid"])
        sql = _compiled_sql(session.captured_stmt)
        assert "jobs.work_mode IN" in sql

    def test_employment_type_filter_adds_in_clause(self) -> None:
        session = _CapturingSession()
        search_jobs(session, "", limit=20, offset=0, employment_type=["full_time"])
        sql = _compiled_sql(session.captured_stmt)
        assert "jobs.employment_type IN" in sql

    def test_work_mode_and_employment_type_are_case_sensitive_equality(self) -> None:
        session = _CapturingSession()
        search_jobs(session, "", limit=20, offset=0, work_mode=["remote"])
        sql = _compiled_sql(session.captured_stmt)
        assert "lower(jobs.work_mode" not in sql

    def test_seniority_filter_uses_case_insensitive_match(self) -> None:
        session = _CapturingSession()
        search_jobs(session, "", limit=20, offset=0, seniority=["Senior"])
        sql = _compiled_sql(session.captured_stmt)
        assert "lower(jobs.seniority)" in sql

    def test_seniority_filter_lowercases_python_side_values(self) -> None:
        session = _CapturingSession()
        search_jobs(session, "", limit=20, offset=0, seniority=["Senior", "STAFF"])
        compiled = session.captured_stmt.compile(compile_kwargs={"literal_binds": False})
        # .in_() binds the whole list as one array-valued parameter.
        bound_lists = [v for v in compiled.params.values() if isinstance(v, list)]
        assert any("senior" in lst and "staff" in lst for lst in bound_lists)
        assert not any("Senior" in lst or "STAFF" in lst for lst in bound_lists)

    def test_company_filter_uses_case_insensitive_match(self) -> None:
        session = _CapturingSession()
        search_jobs(session, "", limit=20, offset=0, company=["Acme Corp"])
        sql = _compiled_sql(session.captured_stmt)
        assert "lower(jobs.company_name)" in sql

    def test_location_country_filter_is_case_sensitive(self) -> None:
        """Deliberately NOT wrapped in lower() -- preserves
        ix_jobs_location_country_region_city's usability (STORY-057)."""
        session = _CapturingSession()
        search_jobs(session, "", limit=20, offset=0, location_country=["Germany"])
        sql = _compiled_sql(session.captured_stmt)
        assert "jobs.location_country IN" in sql
        assert "lower(jobs.location_country)" not in sql

    def test_location_region_filter_adds_in_clause(self) -> None:
        session = _CapturingSession()
        search_jobs(session, "", limit=20, offset=0, location_region=["Berlin"])
        sql = _compiled_sql(session.captured_stmt)
        assert "jobs.location_region IN" in sql

    def test_location_city_filter_adds_in_clause(self) -> None:
        session = _CapturingSession()
        search_jobs(session, "", limit=20, offset=0, location_city=["Munich"])
        sql = _compiled_sql(session.captured_stmt)
        assert "jobs.location_city IN" in sql

    def test_empty_list_filter_adds_no_constraint(self) -> None:
        session = _CapturingSession()
        search_jobs(session, "", limit=20, offset=0, work_mode=[], seniority=[])
        sql = _compiled_sql(session.captured_stmt)
        # work_mode/seniority still appear in the SELECT column list itself
        # -- what matters is that no additional IN constraint was added for
        # them. The default closed_at IS NULL filter (STORY-028) is always
        # present, but it's not an "IN" constraint, so this assertion still
        # correctly proves the empty-list filters added nothing.
        assert "IN" not in sql
        assert "jobs.closed_at IS NULL" in sql
        assert sql.count(" AND ") == 0  # only the standalone closed_at condition

    def test_none_filters_add_no_constraints(self) -> None:
        """STORY-028: `WHERE` is always present now (the default
        closed_at filter) -- this test's own name always meant "no facet
        filter adds a constraint," not "no WHERE clause at all"."""
        session = _CapturingSession()
        search_jobs(session, "", limit=20, offset=0)
        sql = _compiled_sql(session.captured_stmt)
        assert sql.count("WHERE") == 1
        assert "jobs.closed_at IS NULL" in sql
        assert sql.count(" AND ") == 0

    def test_multiple_filters_combine_with_and(self) -> None:
        session = _CapturingSession()
        search_jobs(
            session, "", limit=20, offset=0,
            work_mode=["remote"], employment_type=["full_time"], location_country=["Germany"],
        )
        sql = _compiled_sql(session.captured_stmt)
        # 3 facet conditions + the default closed_at IS NULL -> 3 ANDs.
        assert sql.count(" AND ") == 3
        assert "jobs.work_mode IN" in sql
        assert "jobs.employment_type IN" in sql
        assert "jobs.location_country IN" in sql
        assert "jobs.closed_at IS NULL" in sql

    def test_include_closed_omits_the_default_closed_at_filter(self) -> None:
        session = _CapturingSession()
        search_jobs(session, "", limit=20, offset=0, include_closed=True)
        sql = _compiled_sql(session.captured_stmt)
        # closed_at still appears in the SELECT column list itself -- what
        # matters is that no WHERE/IS NULL constraint was added for it.
        assert "closed_at IS NULL" not in sql
        assert "WHERE" not in sql

    def test_filters_compose_with_real_search_query(self) -> None:
        session = _CapturingSession()
        search_jobs(session, "engineer", limit=20, offset=0, work_mode=["remote"])
        sql = _compiled_sql(session.captured_stmt)
        assert "@@" in sql
        assert "jobs.work_mode IN" in sql
        assert " AND " in sql

    def test_filters_compose_with_punctuation_only_query(self) -> None:
        session = _CapturingSession()
        search_jobs(session, "???", limit=20, offset=0, work_mode=["remote"])
        sql = _compiled_sql(session.captured_stmt)
        assert "@@" not in sql
        assert "jobs.work_mode IN" in sql

    def test_filters_do_not_alter_ordering(self) -> None:
        session = _CapturingSession()
        search_jobs(session, "engineer", limit=20, offset=0, work_mode=["remote"])
        sql = _compiled_sql(session.captured_stmt)
        assert sql.index("ts_rank_cd") < sql.index("jobs.posting_date DESC")
        assert sql.index("jobs.posting_date DESC") < sql.index("jobs.id ASC")

    def test_filter_value_never_appears_literally_in_compiled_sql(self) -> None:
        session = _CapturingSession()
        malicious = "'; DROP TABLE jobs; --"
        search_jobs(session, "", limit=20, offset=0, company=[malicious])
        sql = _compiled_sql(session.captured_stmt)
        assert malicious not in sql
        assert "DROP TABLE" not in sql

    def test_filter_values_are_bound_as_parameters(self) -> None:
        session = _CapturingSession()
        search_jobs(session, "", limit=20, offset=0, location_country=["Germany"])
        compiled = session.captured_stmt.compile(compile_kwargs={"literal_binds": False})
        # .in_() binds the whole list as one array-valued parameter.
        bound_lists = [v for v in compiled.params.values() if isinstance(v, list)]
        assert any("Germany" in lst for lst in bound_lists)


class TestSearchJobsSorting:
    def test_default_sort_with_query_unchanged_from_pre_story_032(self) -> None:
        session = _CapturingSession()
        search_jobs(session, "engineer", limit=20, offset=0)
        sql = _compiled_sql(session.captured_stmt)
        assert "ts_rank_cd" in sql
        assert sql.index("ts_rank_cd") < sql.index("jobs.posting_date DESC")

    def test_default_sort_without_query_unchanged_from_pre_story_032(self) -> None:
        session = _CapturingSession()
        search_jobs(session, "", limit=20, offset=0)
        sql = _compiled_sql(session.captured_stmt)
        assert "ts_rank_cd" not in sql
        assert "ORDER BY jobs.posting_date DESC" in sql

    def test_sort_relevance_explicit_matches_default_with_query(self) -> None:
        session = _CapturingSession()
        search_jobs(session, "engineer", limit=20, offset=0, sort=SortMode.RELEVANCE)
        sql = _compiled_sql(session.captured_stmt)
        assert "ts_rank_cd" in sql

    def test_sort_relevance_with_empty_query_falls_back_to_posting_date(self) -> None:
        session = _CapturingSession()
        search_jobs(session, "", limit=20, offset=0, sort=SortMode.RELEVANCE)
        sql = _compiled_sql(session.captured_stmt)
        assert "ts_rank_cd" not in sql
        assert "jobs.posting_date DESC" in sql

    def test_sort_relevance_with_punctuation_only_query_falls_back(self) -> None:
        session = _CapturingSession()
        search_jobs(session, "???", limit=20, offset=0, sort=SortMode.RELEVANCE)
        sql = _compiled_sql(session.captured_stmt)
        assert "ts_rank_cd" not in sql

    def test_sort_posting_date_uses_nulls_last(self) -> None:
        session = _CapturingSession()
        search_jobs(session, "", limit=20, offset=0, sort=SortMode.POSTING_DATE)
        sql = _compiled_sql(session.captured_stmt)
        assert "jobs.posting_date DESC NULLS LAST" in sql
        assert "ts_rank_cd" not in sql

    def test_sort_posting_date_ends_in_id_tiebreak(self) -> None:
        session = _CapturingSession()
        search_jobs(session, "", limit=20, offset=0, sort=SortMode.POSTING_DATE)
        sql = _compiled_sql(session.captured_stmt)
        assert sql.index("jobs.posting_date DESC") < sql.index("jobs.id ASC")

    def test_sort_last_seen_orders_by_last_seen_at_desc(self) -> None:
        session = _CapturingSession()
        search_jobs(session, "", limit=20, offset=0, sort=SortMode.LAST_SEEN)
        sql = _compiled_sql(session.captured_stmt)
        assert "ORDER BY jobs.last_seen_at DESC" in sql
        assert "ts_rank_cd" not in sql
        assert "jobs.posting_date" not in sql.split("ORDER BY")[1]

    def test_sort_last_seen_has_no_nulls_clause(self) -> None:
        """last_seen_at is NOT NULL -- no NULLS ordering decision applies."""
        session = _CapturingSession()
        search_jobs(session, "", limit=20, offset=0, sort=SortMode.LAST_SEEN)
        sql = _compiled_sql(session.captured_stmt)
        assert "NULLS" not in sql

    def test_sort_last_seen_ends_in_id_tiebreak(self) -> None:
        session = _CapturingSession()
        search_jobs(session, "", limit=20, offset=0, sort=SortMode.LAST_SEEN)
        sql = _compiled_sql(session.captured_stmt)
        assert sql.index("jobs.last_seen_at DESC") < sql.index("jobs.id ASC")

    def test_sort_posting_date_with_real_query_still_filters(self) -> None:
        """Sorting changes ordering, not matching -- the @@ predicate must
        survive even when a non-relevance sort is explicitly requested."""
        session = _CapturingSession()
        search_jobs(session, "engineer", limit=20, offset=0, sort=SortMode.POSTING_DATE)
        sql = _compiled_sql(session.captured_stmt)
        assert "@@" in sql
        assert "websearch_to_tsquery" in sql
        assert "ts_rank_cd" not in sql
        assert "jobs.posting_date DESC NULLS LAST" in sql

    def test_sort_last_seen_with_real_query_still_filters(self) -> None:
        session = _CapturingSession()
        search_jobs(session, "engineer", limit=20, offset=0, sort=SortMode.LAST_SEEN)
        sql = _compiled_sql(session.captured_stmt)
        assert "@@" in sql
        assert "jobs.last_seen_at DESC" in sql

    def test_sort_posting_date_composes_with_filters(self) -> None:
        session = _CapturingSession()
        search_jobs(
            session, "", limit=20, offset=0, sort=SortMode.POSTING_DATE, work_mode=["remote"]
        )
        sql = _compiled_sql(session.captured_stmt)
        assert "jobs.work_mode IN" in sql
        assert "jobs.posting_date DESC NULLS LAST" in sql

    def test_sort_last_seen_composes_with_filters(self) -> None:
        session = _CapturingSession()
        search_jobs(
            session, "", limit=20, offset=0, sort=SortMode.LAST_SEEN, employment_type=["full_time"]
        )
        sql = _compiled_sql(session.captured_stmt)
        assert "jobs.employment_type IN" in sql
        assert "jobs.last_seen_at DESC" in sql

    def test_sort_does_not_alter_limit_offset(self) -> None:
        session = _CapturingSession()
        search_jobs(session, "", limit=5, offset=10, sort=SortMode.POSTING_DATE)
        sql = _compiled_sql(session.captured_stmt)
        assert "LIMIT" in sql
        assert "OFFSET" in sql

    def test_sort_none_is_identical_to_omitted(self) -> None:
        session_a = _CapturingSession()
        search_jobs(session_a, "engineer", limit=20, offset=0)
        session_b = _CapturingSession()
        search_jobs(session_b, "engineer", limit=20, offset=0, sort=None)
        assert _compiled_sql(session_a.captured_stmt) == _compiled_sql(session_b.captured_stmt)
