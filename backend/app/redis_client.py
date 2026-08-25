"""Redis client management (STORY-008).

No cache/broker usage exists yet — this only provides connection plumbing: a
client factory and a connectivity check that degrades gracefully rather than
raising, per the Story's edge case ("Redis unavailability must degrade
gracefully rather than hard-fail unrelated requests").

socket_connect_timeout/socket_timeout (STORY-052) bound every call this
client makes -- previously unset, a genuinely (network-level, not just
"actively refused") unreachable Redis could hang for an OS-default
duration far longer than any caller wants to wait, including
check_redis_connection() below (the STORY-052 readiness check) and
app.rate_limit's fail-open path (STORY-045 -- its own live validation
only ever exercised an immediately-raised RedisError, never genuine
network-level unreachability; this closes that gap too, for free).

check_redis_connection() (STORY-008, reused unmodified as the STORY-052
Redis readiness check) is already a single ping() attempt -- no retry
loop -- already the right shape for a fast readiness probe.
"""

import logging

import redis
from redis.exceptions import RedisError

from app.config import get_settings

logger = logging.getLogger(__name__)

_client: redis.Redis | None = None


def get_redis_client() -> redis.Redis:
    global _client
    if _client is None:
        timeout = get_settings().health_check_timeout_seconds
        _client = redis.from_url(
            get_settings().redis_url,
            socket_connect_timeout=timeout,
            socket_timeout=timeout,
        )
    return _client


def check_redis_connection() -> bool:
    """Ping Redis. Never raises — a failure returns False."""
    try:
        return bool(get_redis_client().ping())
    except RedisError as exc:
        logger.warning("Redis connection check failed: %s", exc)
        return False
