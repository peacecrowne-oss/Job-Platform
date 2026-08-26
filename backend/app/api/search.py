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

Input validation bounds (STORY-043): the 5 free-text filters
(`seniority`/`company`/`location_*`) previously had no length or
repeated-value-count bound, unlike `q`'s own `max_length=500` -- a real
gap in "input validation at API boundaries." Each now uses
`Annotated[str, StringConstraints(max_length=...)]` as its list's element
type (per-item string length) plus `Query(max_length=...)` on the list
itself (repeated-value count) -- verified empirically that these are two
genuinely distinct FastAPI/Pydantic mechanisms, not redundant, before
relying on both. Per-item lengths match the real `Job` column widths
they're compared against (`String(100)` for `seniority`, `String(255)`
for the other four) -- not arbitrary numbers. The repeated-value count
cap (20) is a reasoned, flagged judgment call for free-text filters with
no natural cardinality; `work_mode`/`employment_type` are capped at their
own real enum cardinality (3 and 7) instead, since enum validation alone
doesn't stop the same valid value being repeated an unbounded number of
times.

Per-IP rate limiting (STORY-045) via `app.rate_limit.rate_limit()` --
fixed-window Redis counter, fails open on Redis unavailability (see
`app/rate_limit.py`'s own docstring for the full reasoning). `GET
/health` is deliberately never rate-limited (Docker's own healthcheck
polls it continuously).
"""

from __future__ import annotations

import datetime
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, StringConstraints
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.job import EmploymentType, Job, WorkMode
from app.rate_limit import rate_limit
from app.search.service import SortMode, search_jobs

router = APIRouter(tags=["search"])

_Seniority = Annotated[str, StringConstraints(max_length=100)]
_Company = Annotated[str, StringConstraints(max_length=255)]
_LocationPart = Annotated[str, StringConstraints(max_length=255)]


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


# A named, module-level instance (not inlined into the decorator) so tests
# can target it directly via `app.dependency_overrides[search_rate_limit]`
# -- the same established pattern this file already uses for `get_db`.
search_rate_limit = rate_limit(scope="search")


@router.get(
    "/jobs/search",
    response_model=JobSearchResponse,
    dependencies=[Depends(search_rate_limit)],
)
def get_job_search(
    q: str | None = Query(default=None, max_length=500),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    sort: SortMode | None = Query(default=None),
    work_mode: list[WorkMode] | None = Query(default=None, max_length=3),
    employment_type: list[EmploymentType] | None = Query(default=None, max_length=7),
    seniority: list[_Seniority] | None = Query(default=None, max_length=20),
    company: list[_Company] | None = Query(default=None, max_length=20),
    location_country: list[_LocationPart] | None = Query(default=None, max_length=20),
    location_region: list[_LocationPart] | None = Query(default=None, max_length=20),
    location_city: list[_LocationPart] | None = Query(default=None, max_length=20),
    include_closed: bool = Query(default=False),
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
        include_closed=include_closed,
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
