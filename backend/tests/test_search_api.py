"""Tests for GET /jobs/search (STORY-030; pagination metadata added by
STORY-033). No live database required -- `get_db` is overridden with a
fake session via FastAPI's `dependency_overrides`, matching the app's own
dependency-injection shape rather than patching internals. Real end-to-end
matching/pagination behavior against a live database was validated
manually during implementation (see progress.md), matching this repo's
established convention.
"""

from __future__ import annotations

import datetime
import uuid

from fastapi.testclient import TestClient

from app.db import get_db
from app.main import app
from app.models.job import Job


class _FakeSession:
    pass


def _override_get_db():
    yield _FakeSession()


def _sample_job(**overrides) -> Job:
    defaults = dict(
        id=uuid.uuid4(),
        source="greenhouse",
        source_job_id="123",
        job_title="Software Engineer",
        company_name="Acme Corp",
        location_city="Berlin",
        location_region="Berlin",
        location_country="Germany",
        work_mode="remote",
        employment_type="full_time",
        seniority="senior",
        department="Engineering",
        posting_date=datetime.date(2026, 1, 1),
        source_url="https://example.com/job/123",
        application_url="https://example.com/apply/123",
    )
    defaults.update(overrides)
    return Job(**defaults)


client = TestClient(app)


def setup_module(module) -> None:
    app.dependency_overrides[get_db] = _override_get_db


def teardown_module(module) -> None:
    app.dependency_overrides.pop(get_db, None)


def test_search_endpoint_reachable(monkeypatch) -> None:
    import app.api.search as search_module

    monkeypatch.setattr(search_module, "search_jobs", lambda session, q, *, limit, offset, **kwargs: [])
    response = client.get("/jobs/search")
    assert response.status_code == 200


def test_search_endpoint_returns_expected_shape(monkeypatch) -> None:
    import app.api.search as search_module

    job = _sample_job()
    monkeypatch.setattr(
        search_module, "search_jobs", lambda session, q, *, limit, offset, **kwargs: [job]
    )
    response = client.get("/jobs/search", params={"q": "engineer"})
    assert response.status_code == 200
    body = response.json()
    assert body["query"] == "engineer"
    assert body["limit"] == 20
    assert body["offset"] == 0
    assert len(body["results"]) == 1
    result = body["results"][0]
    assert result["job_title"] == "Software Engineer"
    assert result["company_name"] == "Acme Corp"
    assert result["id"] == str(job.id)


def test_search_endpoint_omits_internal_fields(monkeypatch) -> None:
    import app.api.search as search_module

    job = _sample_job(description_full="internal long text", raw_metadata={"secret": "x"})
    monkeypatch.setattr(
        search_module, "search_jobs", lambda session, q, *, limit, offset, **kwargs: [job]
    )
    response = client.get("/jobs/search", params={"q": "engineer"})
    body = response.json()
    result = body["results"][0]
    assert "description_full" not in result
    assert "raw_metadata" not in result
    assert "content_hash" not in result


def test_search_endpoint_passes_query_param_through(monkeypatch) -> None:
    import app.api.search as search_module

    captured = {}

    def fake_search_jobs(session, q, *, limit, offset, **kwargs):
        captured["q"] = q
        captured["limit"] = limit
        captured["offset"] = offset
        return []

    monkeypatch.setattr(search_module, "search_jobs", fake_search_jobs)
    client.get("/jobs/search", params={"q": "backend developer", "limit": 5, "offset": 10})
    # search_jobs() is over-fetched by 1 (STORY-033) to answer has_next
    # from a single query; the response's own `limit`/`offset` still
    # reflect exactly what the client requested (see test below).
    assert captured == {"q": "backend developer", "limit": 6, "offset": 10}


def test_search_endpoint_defaults_query_to_none(monkeypatch) -> None:
    import app.api.search as search_module

    captured = {}

    def fake_search_jobs(session, q, *, limit, offset, **kwargs):
        captured["q"] = q
        return []

    monkeypatch.setattr(search_module, "search_jobs", fake_search_jobs)
    client.get("/jobs/search")
    assert captured["q"] is None


def test_limit_below_minimum_returns_422() -> None:
    response = client.get("/jobs/search", params={"limit": 0})
    assert response.status_code == 422


def test_limit_above_maximum_returns_422() -> None:
    response = client.get("/jobs/search", params={"limit": 101})
    assert response.status_code == 422


def test_negative_offset_returns_422() -> None:
    response = client.get("/jobs/search", params={"offset": -1})
    assert response.status_code == 422


def test_default_limit_and_offset(monkeypatch) -> None:
    import app.api.search as search_module

    monkeypatch.setattr(search_module, "search_jobs", lambda session, q, *, limit, offset, **kwargs: [])
    response = client.get("/jobs/search")
    body = response.json()
    assert body["limit"] == 20
    assert body["offset"] == 0


def test_error_response_matches_existing_envelope_shape() -> None:
    response = client.get("/jobs/search", params={"limit": 0})
    body = response.json()
    assert "error" in body
    assert "details" in body["error"]


# --- STORY-033: pagination metadata ---


def test_search_jobs_is_called_with_limit_plus_one(monkeypatch) -> None:
    import app.api.search as search_module

    captured = {}

    def fake_search_jobs(session, q, *, limit, offset, **kwargs):
        captured["limit"] = limit
        return []

    monkeypatch.setattr(search_module, "search_jobs", fake_search_jobs)
    client.get("/jobs/search", params={"limit": 20})
    assert captured["limit"] == 21


def test_full_page_plus_extra_row_sets_has_next_true(monkeypatch) -> None:
    import app.api.search as search_module

    jobs = [_sample_job() for _ in range(4)]  # limit=3, so 4 rows means "more exist"
    monkeypatch.setattr(
        search_module, "search_jobs", lambda session, q, *, limit, offset, **kwargs: jobs
    )
    response = client.get("/jobs/search", params={"limit": 3})
    body = response.json()
    assert body["has_next"] is True
    assert len(body["results"]) == 3  # the extra over-fetched row is sliced off


def test_partial_page_sets_has_next_false(monkeypatch) -> None:
    import app.api.search as search_module

    jobs = [_sample_job() for _ in range(2)]  # fewer than limit+1
    monkeypatch.setattr(
        search_module, "search_jobs", lambda session, q, *, limit, offset, **kwargs: jobs
    )
    response = client.get("/jobs/search", params={"limit": 5})
    body = response.json()
    assert body["has_next"] is False
    assert len(body["results"]) == 2


def test_empty_result_set_sets_has_next_false(monkeypatch) -> None:
    import app.api.search as search_module

    monkeypatch.setattr(search_module, "search_jobs", lambda session, q, *, limit, offset, **kwargs: [])
    response = client.get("/jobs/search")
    body = response.json()
    assert body["has_next"] is False
    assert body["results"] == []


def test_offset_zero_sets_has_previous_false(monkeypatch) -> None:
    import app.api.search as search_module

    monkeypatch.setattr(search_module, "search_jobs", lambda session, q, *, limit, offset, **kwargs: [])
    response = client.get("/jobs/search", params={"offset": 0})
    assert response.json()["has_previous"] is False


def test_offset_above_zero_sets_has_previous_true(monkeypatch) -> None:
    import app.api.search as search_module

    monkeypatch.setattr(search_module, "search_jobs", lambda session, q, *, limit, offset, **kwargs: [])
    response = client.get("/jobs/search", params={"offset": 10})
    assert response.json()["has_previous"] is True


def test_response_limit_reflects_requested_limit_not_the_overfetch(monkeypatch) -> None:
    import app.api.search as search_module

    monkeypatch.setattr(search_module, "search_jobs", lambda session, q, *, limit, offset, **kwargs: [])
    response = client.get("/jobs/search", params={"limit": 7})
    assert response.json()["limit"] == 7


def test_maximum_limit_overfetches_within_bounds(monkeypatch) -> None:
    import app.api.search as search_module

    captured = {}

    def fake_search_jobs(session, q, *, limit, offset, **kwargs):
        captured["limit"] = limit
        return []

    monkeypatch.setattr(search_module, "search_jobs", fake_search_jobs)
    client.get("/jobs/search", params={"limit": 100})
    assert captured["limit"] == 101


def test_query_and_offset_still_present_alongside_pagination_fields(monkeypatch) -> None:
    import app.api.search as search_module

    monkeypatch.setattr(search_module, "search_jobs", lambda session, q, *, limit, offset, **kwargs: [])
    response = client.get("/jobs/search", params={"q": "engineer", "offset": 15})
    body = response.json()
    assert body["query"] == "engineer"
    assert body["offset"] == 15
    assert "has_next" in body
    assert "has_previous" in body
    assert "results" in body


# --- STORY-031: faceted filtering ---


def test_work_mode_filter_is_passed_through_as_enum_values(monkeypatch) -> None:
    import app.api.search as search_module

    captured = {}

    def fake_search_jobs(session, q, *, limit, offset, **kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(search_module, "search_jobs", fake_search_jobs)
    client.get("/jobs/search", params={"work_mode": ["remote", "hybrid"]})
    assert captured["work_mode"] == ["remote", "hybrid"]


def test_employment_type_filter_is_passed_through_as_enum_values(monkeypatch) -> None:
    import app.api.search as search_module

    captured = {}

    def fake_search_jobs(session, q, *, limit, offset, **kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(search_module, "search_jobs", fake_search_jobs)
    client.get("/jobs/search", params={"employment_type": "full_time"})
    assert captured["employment_type"] == ["full_time"]


def test_invalid_work_mode_returns_422() -> None:
    response = client.get("/jobs/search", params={"work_mode": "bogus"})
    assert response.status_code == 422


def test_invalid_employment_type_returns_422() -> None:
    response = client.get("/jobs/search", params={"employment_type": "bogus"})
    assert response.status_code == 422


def test_seniority_filter_is_passed_through(monkeypatch) -> None:
    import app.api.search as search_module

    captured = {}

    def fake_search_jobs(session, q, *, limit, offset, **kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(search_module, "search_jobs", fake_search_jobs)
    client.get("/jobs/search", params={"seniority": ["Senior", "Staff"]})
    assert captured["seniority"] == ["Senior", "Staff"]


def test_company_filter_is_passed_through(monkeypatch) -> None:
    import app.api.search as search_module

    captured = {}

    def fake_search_jobs(session, q, *, limit, offset, **kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(search_module, "search_jobs", fake_search_jobs)
    client.get("/jobs/search", params={"company": "Acme Corp"})
    assert captured["company"] == ["Acme Corp"]


def test_location_filters_are_passed_through(monkeypatch) -> None:
    import app.api.search as search_module

    captured = {}

    def fake_search_jobs(session, q, *, limit, offset, **kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(search_module, "search_jobs", fake_search_jobs)
    client.get(
        "/jobs/search",
        params={
            "location_country": "Germany",
            "location_region": "Berlin",
            "location_city": "Berlin",
        },
    )
    assert captured["location_country"] == ["Germany"]
    assert captured["location_region"] == ["Berlin"]
    assert captured["location_city"] == ["Berlin"]


def test_absent_filters_pass_none(monkeypatch) -> None:
    import app.api.search as search_module

    captured = {}

    def fake_search_jobs(session, q, *, limit, offset, **kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(search_module, "search_jobs", fake_search_jobs)
    client.get("/jobs/search")
    assert captured["work_mode"] is None
    assert captured["employment_type"] is None
    assert captured["seniority"] is None
    assert captured["company"] is None
    assert captured["location_country"] is None
    assert captured["location_region"] is None
    assert captured["location_city"] is None


def test_filters_still_work_alongside_pagination(monkeypatch) -> None:
    import app.api.search as search_module

    jobs = [_sample_job() for _ in range(4)]
    captured = {}

    def fake_search_jobs(session, q, *, limit, offset, **kwargs):
        captured["limit"] = limit
        captured.update(kwargs)
        return jobs

    monkeypatch.setattr(search_module, "search_jobs", fake_search_jobs)
    response = client.get(
        "/jobs/search", params={"work_mode": "remote", "limit": 3}
    )
    body = response.json()
    assert captured["limit"] == 4  # limit + 1 over-fetch, unaffected by filters
    assert captured["work_mode"] == ["remote"]
    assert body["has_next"] is True
    assert len(body["results"]) == 3


# --- STORY-032: sorting ---


def test_sort_param_is_passed_through_as_enum(monkeypatch) -> None:
    import app.api.search as search_module
    from app.search.service import SortMode

    captured = {}

    def fake_search_jobs(session, q, *, limit, offset, **kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(search_module, "search_jobs", fake_search_jobs)
    client.get("/jobs/search", params={"sort": "posting_date"})
    assert captured["sort"] is SortMode.POSTING_DATE


def test_sort_last_seen_is_passed_through(monkeypatch) -> None:
    import app.api.search as search_module
    from app.search.service import SortMode

    captured = {}

    def fake_search_jobs(session, q, *, limit, offset, **kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(search_module, "search_jobs", fake_search_jobs)
    client.get("/jobs/search", params={"sort": "last_seen"})
    assert captured["sort"] is SortMode.LAST_SEEN


def test_sort_relevance_is_passed_through(monkeypatch) -> None:
    import app.api.search as search_module
    from app.search.service import SortMode

    captured = {}

    def fake_search_jobs(session, q, *, limit, offset, **kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(search_module, "search_jobs", fake_search_jobs)
    client.get("/jobs/search", params={"sort": "relevance"})
    assert captured["sort"] is SortMode.RELEVANCE


def test_absent_sort_passes_none(monkeypatch) -> None:
    import app.api.search as search_module

    captured = {}

    def fake_search_jobs(session, q, *, limit, offset, **kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(search_module, "search_jobs", fake_search_jobs)
    client.get("/jobs/search")
    assert captured["sort"] is None


def test_invalid_sort_value_returns_422() -> None:
    response = client.get("/jobs/search", params={"sort": "bogus"})
    assert response.status_code == 422


def test_sql_injection_style_sort_value_returns_422_not_sql() -> None:
    response = client.get(
        "/jobs/search", params={"sort": "posting_date; DROP TABLE jobs; --"}
    )
    assert response.status_code == 422


def test_sort_composes_with_filters_and_pagination(monkeypatch) -> None:
    import app.api.search as search_module
    from app.search.service import SortMode

    jobs = [_sample_job() for _ in range(4)]
    captured = {}

    def fake_search_jobs(session, q, *, limit, offset, **kwargs):
        captured["limit"] = limit
        captured.update(kwargs)
        return jobs

    monkeypatch.setattr(search_module, "search_jobs", fake_search_jobs)
    response = client.get(
        "/jobs/search",
        params={"sort": "last_seen", "work_mode": "remote", "limit": 3},
    )
    body = response.json()
    assert captured["sort"] is SortMode.LAST_SEEN
    assert captured["work_mode"] == ["remote"]
    assert captured["limit"] == 4
    assert body["has_next"] is True
    assert len(body["results"]) == 3


def test_sort_not_echoed_in_response(monkeypatch) -> None:
    import app.api.search as search_module

    monkeypatch.setattr(search_module, "search_jobs", lambda session, q, *, limit, offset, **kwargs: [])
    response = client.get("/jobs/search", params={"sort": "posting_date"})
    assert "sort" not in response.json()
