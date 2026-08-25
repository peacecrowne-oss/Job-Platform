"""Per-IP rate limiting (STORY-045).

A fixed-window Redis counter -- chosen over a token bucket, both
explicitly permitted by requirement.md's own "counters/token buckets"
technical note; a fixed window is simpler to make atomically correct and
nothing here demands smoother rate-shaping. The key embeds
`window_start = floor(now / window_seconds) * window_seconds`, so every
window gets a fresh key automatically -- `INCR` and `EXPIRE` can be sent
together in one `MULTI`/`EXEC` transaction with no race: re-applying the
same TTL on every request within a window is idempotent, never harmful.
Known, accepted fixed-window characteristic: a burst is possible right at
a window boundary. Not addressed -- no literal requirement asks for
smoother shaping.

Fails open, not closed, on any Redis failure -- required by
`app/redis_client.py`'s own established precedent ("Redis unavailability
must degrade gracefully rather than hard-fail unrelated requests"). A
rate limiter that hard-fails when its own backing store is down would
itself become an availability bug, defeating this Story's own purpose.

`key_func` defaults to the direct TCP peer IP (`request.client.host`) --
correct for the current deployment topology (Docker Compose maps the host
port straight to the container; no reverse proxy exists anywhere in this
project). Deliberately does NOT trust `X-Forwarded-For`: without a real,
controlled proxy in front, honoring that header would let any client
simply spoof a different rate-limit identity. `key_func` is pluggable
specifically so STORY-036 can later pass an account-ID-based key for its
own stricter login-endpoint limiting using this same mechanism -- not
unused speculative scaffolding, a direct parameterization of what's
already built for today's real use case (`/jobs/search`).

`/health` is deliberately never rate-limited anywhere in this codebase:
Docker's own healthcheck polls it every 5 seconds, continuously, for the
container's entire lifetime (docker-compose.yml) -- a real, legitimate,
internal traffic pattern. A blanket limit would make the backend
container report itself unhealthy from its own infrastructure's normal
operation. This is the same principle STORY-045's own edge case names for
ingestion workers, applied by direct analogy -- flagged as an
interpretive extension, not literal text.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from fastapi import HTTPException, Request
from redis.exceptions import RedisError

from app.config import get_settings
from app.redis_client import get_redis_client

logger = logging.getLogger(__name__)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def rate_limit(
    *,
    limit: int | None = None,
    window_seconds: int | None = None,
    scope: str,
    key_func: Callable[[Request], str] = _client_ip,
):
    """Returns a FastAPI dependency enforcing `limit` requests per
    `window_seconds` per `key_func(request)`, independently per `scope`.
    `limit`/`window_seconds` default to the configured
    `rate_limit_requests`/`rate_limit_window_seconds` settings."""

    def dependency(request: Request) -> None:
        settings = get_settings()
        effective_limit = limit if limit is not None else settings.rate_limit_requests
        effective_window = (
            window_seconds if window_seconds is not None else settings.rate_limit_window_seconds
        )

        now = time.time()
        window_start = int(now // effective_window) * effective_window
        key = f"ratelimit:{scope}:{key_func(request)}:{window_start}"

        try:
            client = get_redis_client()
            pipe = client.pipeline()
            pipe.incr(key)
            pipe.expire(key, effective_window)
            count, _ = pipe.execute()
        except RedisError as exc:
            logger.warning("Rate limit check failed, allowing request: %s", exc)
            return

        if count > effective_limit:
            retry_after = effective_window - (now - window_start)
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded. Try again later.",
                headers={"Retry-After": str(max(1, int(retry_after)))},
            )

    return dependency
