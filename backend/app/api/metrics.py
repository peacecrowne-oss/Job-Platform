"""Metrics endpoint (STORY-051).

Not rate-limited -- exempted the same way `/health` is (STORY-045): a
Prometheus scraper polls continuously, and a blanket limit would make the
backend report itself unhealthy from its own expected, legitimate scrape
traffic. This is different from `/sources/health` (STORY-024), which
stayed rate-limited as an occasional human-consulted view, not a
continuous scrape target.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

router = APIRouter(tags=["metrics"])


@router.get("/metrics")
def get_metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
