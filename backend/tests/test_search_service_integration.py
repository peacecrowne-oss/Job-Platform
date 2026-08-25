"""Real-Postgres integration coverage for search_jobs() (STORY-054).

STORY-030/031/032/033's own unit tests (test_search_service.py) build and
inspect SQLAlchemy Select statements without ever executing them -- they
prove the query is constructed correctly, not that real Postgres actually
returns the intended rows via the real GIN full-text index and real
filter/sort semantics (`ts_rank_cd`, `NULLS LAST`, etc.). This closes that
gap against the isolated test database (never the real `job_platform`
database -- see conftest.py's `db_session` fixture and its safety guard).
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest

import app.models.company  # noqa: F401 -- resolves Job.company relationship
from app.models.job import Job
from app.search.service import SortMode, search_jobs

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def _make_job(session, **overrides) -> Job:
    defaults: dict[str, object] = {
        "source": "itest",
        "source_job_id": str(uuid.uuid4()),
    }
    defaults.update(overrides)
    job = Job(**defaults)
    session.add(job)
    return job


def test_full_text_search_finds_matching_job_via_real_gin_index(db_session) -> None:
    match = _make_job(db_session, job_title="Senior Backend Engineer", company_name="Acme Corp")
    _make_job(db_session, job_title="Marketing Coordinator", company_name="Acme Corp")
    db_session.flush()

    results = search_jobs(db_session, "backend engineer")
    result_ids = {job.id for job in results}

    assert match.id in result_ids
    assert all(job.job_title != "Marketing Coordinator" for job in results)


def test_faceted_filter_narrows_results_against_real_postgres(db_session) -> None:
    remote = _make_job(db_session, job_title="Remote Role", work_mode="remote")
    onsite = _make_job(db_session, job_title="Onsite Role", work_mode="on_site")
    db_session.flush()

    results = search_jobs(db_session, None, work_mode=["remote"], limit=100)
    result_ids = {job.id for job in results}

    assert remote.id in result_ids
    assert onsite.id not in result_ids


def test_sort_by_posting_date_orders_newest_first_with_nulls_last(db_session) -> None:
    older = _make_job(db_session, job_title="Older Role", posting_date=date(2020, 1, 1))
    newer = _make_job(db_session, job_title="Newer Role", posting_date=date(2024, 1, 1))
    undated = _make_job(db_session, job_title="Undated Role", posting_date=None)
    db_session.flush()

    results = search_jobs(db_session, None, sort=SortMode.POSTING_DATE, limit=100)
    tracked_ids = {older.id, newer.id, undated.id}
    ordered_ids = [job.id for job in results if job.id in tracked_ids]

    assert ordered_ids == [newer.id, older.id, undated.id]


def test_pagination_across_real_postgres_is_gap_and_duplicate_free(db_session) -> None:
    jobs = [
        _make_job(db_session, job_title=f"Paginated Role {i}", posting_date=None)
        for i in range(5)
    ]
    db_session.flush()
    tracked_ids = {job.id for job in jobs}

    seen: list[uuid.UUID] = []
    for offset in (0, 2, 4):
        page = search_jobs(db_session, None, sort=SortMode.POSTING_DATE, limit=2, offset=offset)
        seen.extend(job.id for job in page if job.id in tracked_ids)

    assert set(seen) == tracked_ids
    assert len(seen) == len(set(seen))
