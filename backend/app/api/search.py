"""Job search endpoint (STORY-030; pagination metadata added by STORY-033).

Response fields are a deliberately minimal, search-result-shaped subset of
`Job` -- id, title, company, location, work_mode/employment_type,
seniority, department, posting_date, and the two provenance URLs. No full
`description_full` body, `raw_metadata`, `content_hash`, or internal
timestamps: none are needed for a result list, and no Story defines a
response contract requiring them (a flagged, revisitable judgment call --
see progress.md).

Schemas are kept inline here rather than in a new `app/schemas/` package --
this repo's established "smallest useful design" precedent (STORY-022's
self-contained retry.py, etc.) for a single-endpoint Story.

Pagination (STORY-033) is offset-based, continuing the `limit`/`offset`
contract STORY-030 already shipped -- a deliberate choice over cursor/
keyset pagination (see progress.md for the full reasoning: `ts_rank_cd()`
is a runtime-computed float with no supporting index, so keyset's usual
justification -- an index-accelerated seek -- doesn't apply to the ranked
branch). No `total` count field: a separate `COUNT(*)` would re-evaluate
the same search predicate a second time, and no literal requirement asks
for one. Instead, `search_jobs()` is over-fetched by one row so `has_next`
can be answered from the same single query. `search_jobs()` itself is
unchanged -- pagination metadata is computed entirely here.

Edge case (requirement.md's own literal text, accepted for the offset
choice): underlying data changing between page requests -- a job inserted,
deleted, or re-ranked between two page fetches -- can shift results across
page boundaries (e.g. a duplicate or skipped row). This is an accepted
limitation of offset pagination, not a defect; STORY-033's own acceptance
criterion only requires exactly-once paging over a *stable* result set,
which this implementation guarantees (see `app/search/service.py`'s
deterministic `id ASC` final tie-break, unchanged by this Story).

Faceted filtering (STORY-031) adds 7 optional, repeatable query params --
`work_mode`, `employment_type`, `seniority`, `company`,
`location_country`, `location_region`, `location_city` -- covering exactly
the 5 dimensions STORY-031's own user story names, not an open field list.
`work_mode`/`employment_type` reuse the existing `WorkMode`/
`EmploymentType` enums from `app.models.job` (no new allow-list invented);
FastAPI rejects any value outside them with a 422. All filter logic lives
in `search_jobs()`, not here -- this layer only parses/validates params and
forwards them. No `filters` field is echoed back in the response: not
required by any acceptance criterion, kept out to keep this change minimal.

Sorting (STORY-032) adds one optional `sort` query param, validated
against `app.search.service.SortMode` (`relevance`/`posting_date`/
`last_seen`) -- an allow-listed enum, never a raw client string reaching
`ORDER BY`. Passed straight through to `search_jobs()` (which already
accepts the enum) with no `.value` conversion needed, unlike the
string-valued filters above. Omitted -- the pre-STORY-032 default
(relevance-if-query-present-else-newest) is unchanged. Not echoed back in
the response, for the same minimal-change reasoning as the filters above.
"""

from __future__ import annotations

import datetime
import uuid

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.job import EmploymentType, Job, WorkMode
from app.search.service import SortMode, search_jobs

router = APIRouter(tags=["search"])


class JobSearchResult(BaseModel):
    id: uuid.UUID
    source: str
    job_title: str | None
    company_name: str | None
    location_city: str | None
    location_region: str | None
    location_country: str | None
    work_mode: str | None
    employment_type: str | None
    seniority: str | None
    department: str | None
    posting_date: datetime.date | None
    source_url: str | None
    application_url: str | None

    model_config = {"from_attributes": True}


class JobSearchResponse(BaseModel):
    query: str | None
    limit: int
    offset: int
    has_next: bool
    has_previous: bool
    results: list[JobSearchResult]


def _to_result(job: Job) -> JobSearchResult:
    return JobSearchResult.model_validate(job)


@router.get("/jobs/search", response_model=JobSearchResponse)
def get_job_search(
    q: str | None = Query(default=None, max_length=500),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    sort: SortMode | None = Query(default=None),
    work_mode: list[WorkMode] | None = Query(default=None),
    employment_type: list[EmploymentType] | None = Query(default=None),
    seniority: list[str] | None = Query(default=None),
    company: list[str] | None = Query(default=None),
    location_country: list[str] | None = Query(default=None),
    location_region: list[str] | None = Query(default=None),
    location_city: list[str] | None = Query(default=None),
    session: Session = Depends(get_db),
) -> JobSearchResponse:
    # Over-fetch by one to answer has_next from this single query, instead
    # of a second COUNT(*) that would re-evaluate the same search predicate.
    jobs = search_jobs(
        session,
        q,
        limit=limit + 1,
        offset=offset,
        sort=sort,
        work_mode=[m.value for m in work_mode] if work_mode else None,
        employment_type=[t.value for t in employment_type] if employment_type else None,
        seniority=seniority,
        company=company,
        location_country=location_country,
        location_region=location_region,
        location_city=location_city,
    )
    has_next = len(jobs) > limit
    page = jobs[:limit]
    return JobSearchResponse(
        query=q,
        limit=limit,
        offset=offset,
        has_next=has_next,
        has_previous=offset > 0,
        results=[_to_result(job) for job in page],
    )
