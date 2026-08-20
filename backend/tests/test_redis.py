"""Tests for app.redis_client that don't require a live Redis (STORY-008)."""

from unittest.mock import MagicMock, patch

from redis.exceptions import RedisError

from app import redis_client as redis_module


def test_get_redis_client_returns_same_instance() -> None:
    assert redis_module.get_redis_client() is redis_module.get_redis_client()


def test_check_redis_connection_returns_true_on_successful_ping() -> None:
    fake_client = MagicMock()
    fake_client.ping.return_value = True

    with patch.object(redis_module, "get_redis_client", return_value=fake_client):
        assert redis_module.check_redis_connection() is True


def test_check_redis_connection_returns_false_without_raising_on_failure() -> None:
    fake_client = MagicMock()
    fake_client.ping.side_effect = RedisError("boom")

    with patch.object(redis_module, "get_redis_client", return_value=fake_client):
        assert redis_module.check_redis_connection() is False
