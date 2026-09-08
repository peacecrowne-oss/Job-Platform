"""Job detail endpoint (STORY-034).

`GET /jobs/{job_id}` -- a separate router from `search.py` (STORY-030):
that endpoint's response is deliberately search-result-shaped (a minimal
subset of `Job`); this one returns every canonical field §2 of
requirement.md names, per this Story's own literal acceptance criterion
("all non-null canonical fields ... visible"). Excludes `raw_metadata`,
`content_hash`, and the generic `created_at`/`updated_at` row-audit
columns -- none are §2 canonical fields, matching `search.py`'s own
precedent of excluding internal/persistence-layer columns.

`closed_at` (STORY-028) is included even though it isn't itself a §2
canonical field -- it's the actual "is this job closed" signal this
Story's own edge case requires ("closed/inactive jobs are visibly labeled
as such"). `closing_date` (a §2 field, the *source's own* stated date, not
itself a reliable closed/open signal) is included separately as ordinary
content.

A closed job is still returned by a direct by-ID lookup -- this is not a
filtered search (unlike `include_closed` on `/jobs/search`), so there is
nothing to opt into; the frontend renders the "Closed" label from
`closed_at` instead.

Security boundary (STORY-047): `sanitize_html()` is called *again* here,
immediately before serialization, on every free-text section field --
satisfying that Story's own "sanitize on ingest, treat the stored value
as still-untrusted at render time" requirement. This is the render
boundary; the actual HTML rendering happens in the frontend, which must
only ever call `dangerouslySetInnerHTML` on a field that passed through
this function (ingest-time AND here).
"""

from __future__ import annotations

import datetime
import decimal
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.job import Job
from app.rate_limit import rate_limit
from app.sanitization import sanitize_html

router = APIRouter(tags=["jobs"])


class JobDetailResponse(BaseModel):
    id: uuid.UUID

    # --- Provenance ---
    source: str
    source_url: str | None
    source_job_id: str

    # --- Identity ---
    company_name: str | None
    job_title: str | None

    # --- Description sections (sanitized again below, before serialization) ---
    description_full: str | None
    responsibilities: str | None
    requirements: str | None
    preferred_requirements: str | None
    qualifications: str | None

    skills: list[str] | None

    location_city: str | None
    location_region: str | None
    location_country: str | None

    work_mode: str | None
    employment_type: str | None
    seniority: str | None
    department: str | None

    compensation_min: decimal.Decimal | None
    compensation_max: decimal.Decimal | None
    compensation_currency: str | None
    compensation_period: str | None

    benefits: list[str] | None

    posting_date: datetime.date | None
    closing_date: datetime.date | None
    application_url: str | None

    first_seen_at: datetime.datetime
    last_seen_at: datetime.datetime
    source_updated_at: datetime.datetime | None

    # Not a §2 canonical field -- included for this Story's own
    # closed/inactive-labeling edge case (see module docstring).
    closed_at: datetime.datetime | None

    model_config = {"from_attributes": True}


def _to_detail(job: Job) -> JobDetailResponse:
    detail = JobDetailResponse.model_validate(job)
    detail.description_full = sanitize_html(detail.description_full)
    detail.responsibilities = sanitize_html(detail.responsibilities)
    detail.requirements = sanitize_html(detail.requirements)
    detail.preferred_requirements = sanitize_html(detail.preferred_requirements)
    detail.qualifications = sanitize_html(detail.qualifications)
    return detail


job_detail_rate_limit = rate_limit(scope="job_detail")


@router.get(
    "/jobs/{job_id}",
    response_model=JobDetailResponse,
    dependencies=[Depends(job_detail_rate_limit)],
)
def get_job(job_id: uuid.UUID, session: Session = Depends(get_db)) -> JobDetailResponse:
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return _to_detail(job)
