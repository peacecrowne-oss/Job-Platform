"""Full-Text Search (STORY-030) -- the smallest reusable search
abstraction over the GIN expression index STORY-057 already built.
Faceted filtering (STORY-031) extends this with 7 optional, independently
composable filters. Sorting (STORY-032) extends it with a `sort` selector.

Ranking is in scope here, not STORY-032's: STORY-030's own literal
acceptance criterion is "results ranked above irrelevant ones," so
`ts_rank_cd()` is computed by this module. STORY-032 adds a user-facing
switch on top of this; it does not invent ranking.

`jobs_search_vector_english(job_title, company_name, description_full,
skills)` is called with the exact same arguments, in the exact same order,
the GIN index (`ix_jobs_search_vector`) stores -- required for PostgreSQL's
planner to recognize the match and use the index (verified live; see
progress.md). No field weighting is applied: the index expression itself
carries no `setweight()` labels, and changing that now would require
touching an already-verified index without justification.

`_has_search_terms()` treats punctuation-only input (e.g. "???") the same
as an empty query -- a deliberate, flagged extension of STORY-030's literal
"empty query returns unfiltered results" edge case, not literal text.

Filters (STORY-031) cover exactly the 5 dimensions STORY-031's own user
story names -- location (country/region/city), remote status (work_mode),
employment type, seniority, and company -- not an open-ended field list.
`work_mode`/`employment_type` are equality-matched against their canonical,
CHECK-constrained values (validated at the API layer against the existing
`WorkMode`/`EmploymentType` enums, so this layer trusts them as-is).
`seniority`/`company` are matched case-insensitively (`func.lower()` on
both sides) since neither has a supporting index either way, so
insensitivity costs nothing and is friendlier for free text. Location
filters are matched case-sensitively: `ix_jobs_location_country_region_city`
(STORY-057) is a plain B-tree over the raw column values, and wrapping the
column in `func.lower()` would defeat that index by turning it into an
expression the index doesn't store. Every filter uses `Column.in_(values)`
for OR-within-filter, AND-across-filters, with every value bound as a
SQLAlchemy parameter -- never string-interpolated. An absent/`None`/empty
filter applies no constraint; NULL columns never match a specific-value
filter (plain SQL `IN` semantics, no special-casing needed).

`SortMode` (STORY-032) covers exactly the 3 dimensions the Story's own
functional requirements name -- relevance, posting date, last-seen date --
not an open-ended field list, and no ascending/"oldest" direction (not
named or exemplified by the Story). `sort=None`/`SortMode.RELEVANCE`
reproduce the exact pre-STORY-032 default (`ts_rank_cd` when a query is
present, else newest-first) -- `sort=relevance` requested without a
meaningful query gracefully falls back to the same newest-first ordering
rather than erroring, matching this codebase's consistent "predictable,
non-error edge case" philosophy (STORY-030/031's own precedents).
`posting_date DESC` uses an explicit `NULLS LAST` -- a deliberate decision
required by the Story's own edge case ("defines and documents NULL
ordering"): an undated job should not appear to be the newest. This is a
real change from Postgres's previous implicit default (`NULLS FIRST` for
plain DESC), which was never a deliberate choice, only ever an accident of
never being specified (see progress.md for the full reasoning and the
real EXPLAIN finding on `ix_jobs_posting_date`'s usability under this
ordering). `last_seen_at` needs no NULL handling -- the column is
`nullable=False`. Sorting only changes `ORDER BY`; the existing `@@`
match predicate (when a query is present) is built independently of
`sort` and is never skipped just because a non-relevance sort was
requested -- sorting changes ordering, not matching. The `id ASC` final
tie-break from STORY-030 is preserved in every sort mode, unchanged --
this is what makes pagination (STORY-033) deterministic under all of
them, not just the original two branches.
"""

from __future__ import annotations

import enum
import re
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

import app.models.company  # noqa: F401 -- resolves Job.company relationship
from app.models.job import Job

_WORD_CHARACTER = re.compile(r"\w")


def _has_search_terms(value: str) -> bool:
    return _WORD_CHARACTER.search(value) is not None


class SortMode(str, enum.Enum):
    RELEVANCE = "relevance"
    POSTING_DATE = "posting_date"
    LAST_SEEN = "last_seen"


def search_jobs(
    session: Session,
    query: str | None,
    *,
    limit: int = 20,
    offset: int = 0,
    sort: SortMode | None = None,
    work_mode: Sequence[str] | None = None,
    employment_type: Sequence[str] | None = None,
    seniority: Sequence[str] | None = None,
    company: Sequence[str] | None = None,
    location_country: Sequence[str] | None = None,
    location_region: Sequence[str] | None = None,
    location_city: Sequence[str] | None = None,
    include_closed: bool = False,
) -> list[Job]:
    """Returns up to `limit` Jobs, `offset` results in. `query`, when it has
    usable search terms, filters to jobs whose search vector matches it,
    regardless of `sort` -- sorting changes ordering, not matching. `sort`
    selects the ORDER BY: `POSTING_DATE`/`LAST_SEEN` always use their own
    field; omitted/`RELEVANCE` uses `ts_rank_cd` when a query is present,
    else falls back to posting-date-newest-first (STORY-030's original
    default, unchanged). Every mode ends in a deterministic `id ASC`
    tie-break. Each faceted filter (STORY-031), when non-empty, ANDs in
    one additional constraint independent of `sort`; absent filters add
    nothing. `include_closed` (STORY-028): jobs auto-closed via absence
    (`Job.closed_at` set) are excluded by default -- "excluded from
    default search results but remains queryable historically" -- passing
    `include_closed=True` surfaces them too."""
    normalized = (query or "").strip()
    stmt = select(Job)
    if not include_closed:
        stmt = stmt.where(Job.closed_at.is_(None))
    has_query = _has_search_terms(normalized)
    search_vector = tsquery = None

    if has_query:
        search_vector = func.jobs_search_vector_english(
            Job.job_title, Job.company_name, Job.description_full, Job.skills
        )
        tsquery = func.websearch_to_tsquery("english", normalized)
        stmt = stmt.where(search_vector.op("@@")(tsquery))

    if sort is SortMode.POSTING_DATE:
        order_clause = (Job.posting_date.desc().nulls_last(), Job.id.asc())
    elif sort is SortMode.LAST_SEEN:
        order_clause = (Job.last_seen_at.desc(), Job.id.asc())
    elif has_query:  # sort is None or SortMode.RELEVANCE, and a query exists
        order_clause = (
            func.ts_rank_cd(search_vector, tsquery).desc(),
            Job.posting_date.desc().nulls_last(),
            Job.id.asc(),
        )
    else:  # sort is None or SortMode.RELEVANCE, no meaningful query -> fallback
        order_clause = (Job.posting_date.desc().nulls_last(), Job.id.asc())

    stmt = stmt.order_by(*order_clause)

    if work_mode:
        stmt = stmt.where(Job.work_mode.in_(work_mode))
    if employment_type:
        stmt = stmt.where(Job.employment_type.in_(employment_type))
    if seniority:
        stmt = stmt.where(func.lower(Job.seniority).in_([s.lower() for s in seniority]))
    if company:
        stmt = stmt.where(func.lower(Job.company_name).in_([c.lower() for c in company]))
    if location_country:
        stmt = stmt.where(Job.location_country.in_(location_country))
    if location_region:
        stmt = stmt.where(Job.location_region.in_(location_region))
    if location_city:
        stmt = stmt.where(Job.location_city.in_(location_city))

    stmt = stmt.limit(limit).offset(offset)
    return list(session.execute(stmt).scalars().all())
