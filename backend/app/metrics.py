"""Application metrics (STORY-051).

Centralizes every metric definition in one module so the naming
convention stays consistent as future Stories add more (this Story's own
technical note) -- follows Prometheus's own official best-practice naming
guide: `<subsystem>_<name>_<unit>`, `_total` suffix for counters, base
units (seconds, not milliseconds) for durations.

Two separate OS processes record these: the backend API (imports this
module, serves `GET /metrics` via app/api/metrics.py) and the `scheduler`
process (STORY-021, imports this module, serves its own metrics via
`start_http_server()` on a separate port -- see app/ingestion/scheduler.py).
`prometheus_client`'s default registry is per-process and in-memory, so
each process's `/metrics` reflects only what that process itself recorded
since it started -- the standard, expected multi-process Prometheus
pattern (a scraper polls multiple independent targets), not a gap.

"queue depth" (the FR's own literal wording) has no literal counterpart in
this architecture -- STORY-021 deliberately rejected a broker-backed queue
in favor of a simple polling scheduler. `scheduler_due_sources` maps it by
analogy: how many sources were due but not yet processed at the start of
one scheduler cycle. Flagged in the approved plan, not silently invented.
"""

from __future__ import annotations

import time

from prometheus_client import Counter, Gauge, Histogram
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

http_requests_total = Counter(
    "http_requests_total",
    "Total HTTP requests handled by the backend API.",
    ["method", "path", "status_code"],
)

http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds.",
    ["method", "path"],
)

ingestion_runs_total = Counter(
    "ingestion_runs_total",
    "Total ingestion runs completed, by source and final status.",
    ["source", "status"],
)

scheduler_due_sources = Gauge(
    "scheduler_due_sources",
    "Number of sources due for refresh at the start of the current scheduler cycle.",
)


class MetricsMiddleware(BaseHTTPMiddleware):
    """Records http_requests_total/http_request_duration_seconds per
    request. Deliberately separate from STORY-050's CorrelationIdMiddleware
    -- distinct concerns, single responsibility each -- even though both
    independently time the request; the extra time.monotonic() call is
    negligible. A scrape of /metrics itself is not excluded from these
    counts -- a known, accepted, flagged characteristic, not hidden."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        start = time.monotonic()
        response = await call_next(request)
        duration = time.monotonic() - start

        path = request.url.path
        http_requests_total.labels(
            method=request.method, path=path, status_code=response.status_code
        ).inc()
        http_request_duration_seconds.labels(method=request.method, path=path).observe(duration)

        return response
