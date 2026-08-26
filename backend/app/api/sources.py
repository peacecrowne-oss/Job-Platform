"""Source Health Monitoring API (STORY-024).

An internal, operator-facing view -- but unauthenticated like every other
route in this API today (STORY-036 hasn't been built), so it's rate-
limited the same way `/jobs/search` is rather than exempted like
`/health` (whose exemption is specifically because Docker's own
healthcheck polls it continuously -- a reason that doesn't apply here).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.ingestion.health import SourceHealth, list_all_source_health
from app.rate_limit import rate_limit

router = APIRouter(tags=["sources"])

# A named, module-level instance (not inlined into the decorator) so tests
# can target it directly via `app.dependency_overrides[sources_health_rate_limit]`
# -- the same established pattern app/api/search.py already uses.
sources_health_rate_limit = rate_limit(scope="sources_health")


class SourceHealthResponse(BaseModel):
    sources: list[SourceHealth]


@router.get(
    "/sources/health",
    response_model=SourceHealthResponse,
    dependencies=[Depends(sources_health_rate_limit)],
)
def get_sources_health(session: Session = Depends(get_db)) -> SourceHealthResponse:
    return SourceHealthResponse(sources=list_all_source_health(session))
