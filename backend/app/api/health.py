"""Health endpoints.

`GET /health` (STORY-012, unchanged) is kept exactly as-is forever, not
deprecated -- STORY-012's own original docstring already stated readiness
was "explicitly out of scope here and belongs to STORY-052," confirming
`/health` was always meant to stay liveness-only. Converting it to
readiness now would be a silent, breaking behavior change for anything
already calling it expecting an unconditional 200.

`GET /health/live` (STORY-052) is the same check under a precise name:
"is the process alive?" -- never touches Postgres/Redis, per the Story's
own literal acceptance criterion ("liveness does not" report unhealthy
for a dependency).

`GET /health/ready` (STORY-052) is the new capability: "can this instance
safely receive normal application traffic?" -- checks both Postgres and
Redis (the Story's own literal text names both), each a single bounded
attempt (`check_database_connection(max_attempts=1)`,
`check_redis_connection()`, both reused unmodified -- no new check-helper
code). Run concurrently (not sequentially) via a 2-worker
ThreadPoolExecutor so worst-case latency is max(pg, redis) rather than
their sum. Any unexpected exception (e.g. a malformed configuration
producing something other than the specific exception type each helper
already catches) is caught broadly here too, logged server-side only,
and reported as "unreachable" -- never a raw 500 or leaked exception
text, matching this repo's established errors.py discipline.

Real, live-discovered finding: `connect_args={"connect_timeout": ...}`
(app/db.py) and `socket_connect_timeout`/`socket_timeout`
(app/redis_client.py) only bound the TCP-connect phase *after* a
hostname has already resolved to an IP -- neither bounds DNS resolution
itself. Verified live: Docker's embedded DNS takes ~3s to fail resolving
a *stopped* service's hostname, which the driver-level timeouts above
have zero effect on -- a real dependency outage (the exact scenario this
endpoint exists for) could therefore take meaningfully longer than
`health_check_timeout_seconds` to report, eating into Docker's `timeout:
5s` healthcheck budget with too little margin. Fixed by *also* wrapping
each check in `future.result(timeout=health_check_timeout_seconds)`, an
explicit wall-clock bound covering every failure mode (DNS, TCP connect,
auth, query) regardless of which layer is actually slow -- not just
defense in depth, the layer that actually turned out to matter. The
executor is shut down with `wait=False`: a timed-out check's background
thread isn't forcibly killable (Python threads can't be), so it's simply
abandoned to finish on its own and be garbage collected, rather than
blocking this response waiting for it -- the whole point of the timeout.

Neither new route is behind app.rate_limit's rate_limit() dependency --
consistent with how /health has always been exempt (by simply never
having that dependency attached, not a special-case allowlist).

The Story's own edge case ("flapping dependency connectivity doesn't
cause rapid restart loops -- debounce/threshold on readiness") is
deliberately NOT solved with new in-process state here. Docker Compose's
own `retries: 5` / `interval: 5s` (docker-compose.yml, unchanged since
STORY-005) already is a debounce/threshold mechanism: a container isn't
marked unhealthy until 5 consecutive failures (up to 25s of sustained
unavailability), and a single success resets that counter. Readiness
stays a simple, honest, stateless point-in-time check; Docker's existing
configuration provides the smoothing -- verified live, not assumed (see
progress.md).
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError

from fastapi import APIRouter, Depends, Response, status

from app.config import Settings, get_settings
from app.db import check_database_connection
from app.redis_client import check_redis_connection

router = APIRouter(tags=["health"])


@router.get("/health")
@router.get("/health/live")
def get_liveness(settings: Settings = Depends(get_settings)) -> dict[str, str]:
    return {
        "status": "ok",
        "service": settings.app_name,
        "environment": settings.app_env,
    }


def _check_postgres() -> str:
    try:
        return "ok" if check_database_connection(max_attempts=1) else "unreachable"
    except Exception:  # noqa: BLE001 -- broad on purpose, see module docstring
        return "unreachable"


def _check_redis() -> str:
    try:
        return "ok" if check_redis_connection() else "unreachable"
    except Exception:  # noqa: BLE001 -- broad on purpose, see module docstring
        return "unreachable"


def _resolve(future, timeout: float) -> str:
    try:
        return future.result(timeout=timeout)
    except FutureTimeoutError:
        return "unreachable"


@router.get("/health/ready")
def get_readiness(response: Response, settings: Settings = Depends(get_settings)) -> dict[str, object]:
    timeout = settings.health_check_timeout_seconds
    pool = ThreadPoolExecutor(max_workers=2)
    postgres_future = pool.submit(_check_postgres)
    redis_future = pool.submit(_check_redis)
    checks = {
        "postgres": _resolve(postgres_future, timeout),
        "redis": _resolve(redis_future, timeout),
    }
    # wait=False: a timed-out check's thread can't be force-killed (Python
    # can't interrupt a blocking syscall) -- abandon it to finish and be
    # garbage-collected on its own rather than blocking this response on it.
    pool.shutdown(wait=False)

    ready = all(value == "ok" for value in checks.values())
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {"status": "ready" if ready else "not_ready", "checks": checks}
