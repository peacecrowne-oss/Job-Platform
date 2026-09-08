"""Tests for GET /jobs/{job_id} (STORY-034). No live database required --
`get_db` is overridden with a fake session via FastAPI's
`dependency_overrides`, matching `test_search_api.py`'s established
pattern. Real end-to-end behavior against a live database was validated
manually during implementation (see progress.md).
"""

from __future__ import annotations

import datetime
import uuid

import pytest
from fastapi.testclient import TestClient

from app.api.jobs import job_detail_rate_limit
from app.db import get_db
from app.main import app
from app.models.job import Job


class _FakeSession:
    def __init__(self, job: Job | None) -> None:
        self._job = job

    def get(self, model, job_id):  # noqa: ANN001, ARG002 -- matches Session.get()'s shape
        return self._job


def _override_get_db(job: Job | None):
    def _dep():
        yield _FakeSession(job)

    return _dep


def _sample_job(**overrides) -> Job:
    defaults = dict(
        id=uuid.uuid4(),
        source="greenhouse",
        source_job_id="123",
        job_title="Software Engineer",
        company_name="Acme Corp",
        description_full="<p>Build things.</p>",
        responsibilities="<ul><li>Ship code</li></ul>",
        requirements=None,
        preferred_requirements=None,
        qualifications=None,
        skills=["Python", "SQL"],
        location_city="Berlin",
        location_region="Berlin",
        location_country="Germany",
        work_mode="remote",
        employment_type="full_time",
        seniority="senior",
        department="Engineering",
        compensation_min=None,
        compensation_max=None,
        compensation_currency=None,
        compensation_period=None,
        benefits=None,
        posting_date=datetime.date(2026, 1, 1),
        closing_date=None,
        source_url="https://example.com/job/123",
        application_url="https://example.com/apply/123",
        first_seen_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc),
        last_seen_at=datetime.datetime(2026, 1, 2, tzinfo=datetime.timezone.utc),
        source_updated_at=None,
        closed_at=None,
    )
    defaults.update(overrides)
    return Job(**defaults)


client = TestClient(app)


def teardown_function(function) -> None:
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(job_detail_rate_limit, None)


def test_get_job_success_returns_full_shape() -> None:
    job = _sample_job()
    app.dependency_overrides[get_db] = _override_get_db(job)
    app.dependency_overrides[job_detail_rate_limit] = lambda: None

    response = client.get(f"/jobs/{job.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(job.id)
    assert body["job_title"] == "Software Engineer"
    assert body["company_name"] == "Acme Corp"
    assert body["description_full"] == "<p>Build things.</p>"
    assert body["responsibilities"] == "<ul><li>Ship code</li></ul>"
    assert body["skills"] == ["Python", "SQL"]
    assert body["source_url"] == "https://example.com/job/123"
    assert body["application_url"] == "https://example.com/apply/123"


def test_get_job_returns_404_for_nonexistent_id() -> None:
    app.dependency_overrides[get_db] = _override_get_db(None)
    app.dependency_overrides[job_detail_rate_limit] = lambda: None

    response = client.get(f"/jobs/{uuid.uuid4()}")

    assert response.status_code == 404


def test_get_job_returns_422_for_malformed_id() -> None:
    app.dependency_overrides[get_db] = _override_get_db(None)
    app.dependency_overrides[job_detail_rate_limit] = lambda: None

    response = client.get("/jobs/not-a-uuid")

    assert response.status_code == 422


def test_get_job_includes_closed_at_when_set() -> None:
    closed_at = datetime.datetime(2026, 2, 1, tzinfo=datetime.timezone.utc)
    job = _sample_job(closed_at=closed_at)
    app.dependency_overrides[get_db] = _override_get_db(job)
    app.dependency_overrides[job_detail_rate_limit] = lambda: None

    response = client.get(f"/jobs/{job.id}")

    assert response.json()["closed_at"] is not None


def test_get_job_omits_internal_fields() -> None:
    job = _sample_job()
    app.dependency_overrides[get_db] = _override_get_db(job)
    app.dependency_overrides[job_detail_rate_limit] = lambda: None

    response = client.get(f"/jobs/{job.id}")

    body = response.json()
    assert "raw_metadata" not in body
    assert "content_hash" not in body
    assert "created_at" not in body
    assert "updated_at" not in body


def test_get_job_null_optional_fields_serialize_as_null() -> None:
    job = _sample_job(
        company_name=None,
        skills=None,
        compensation_min=None,
        benefits=None,
        closing_date=None,
    )
    app.dependency_overrides[get_db] = _override_get_db(job)
    app.dependency_overrides[job_detail_rate_limit] = lambda: None

    response = client.get(f"/jobs/{job.id}")

    body = response.json()
    assert body["company_name"] is None
    assert body["skills"] is None
    assert body["compensation_min"] is None
    assert body["benefits"] is None
    assert body["closing_date"] is None


def test_get_job_sanitizes_description_at_the_render_boundary() -> None:
    # Simulates an old row persisted before STORY-047 (or any future gap in
    # the ingest-time pass) -- the endpoint's own sanitization must not
    # depend on the stored value already being clean.
    job = _sample_job(description_full="<p>Real</p><script>alert(1)</script>")
    app.dependency_overrides[get_db] = _override_get_db(job)
    app.dependency_overrides[job_detail_rate_limit] = lambda: None

    response = client.get(f"/jobs/{job.id}")

    description = response.json()["description_full"]
    assert "<script" not in description
    assert "Real" in description
