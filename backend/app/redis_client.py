"""Redis client management (STORY-008).

No cache/broker usage exists yet — this only provides connection plumbing: a
client factory and a connectivity check that degrades gracefully rather than
raising, per the Story's edge case ("Redis unavailability must degrade
gracefully rather than hard-fail unrelated requests").
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
        _client = redis.from_url(get_settings().redis_url)
    return _client


def check_redis_connection() -> bool:
    """Ping Redis. Never raises — a failure returns False."""
    try:
        return bool(get_redis_client().ping())
    except RedisError as exc:
        logger.warning("Redis connection check failed: %s", exc)
        return False
