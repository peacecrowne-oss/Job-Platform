"""Tests for app.rate_limit that don't require a live Redis (STORY-045),
matching the established offline-mocking pattern from test_redis.py."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException, Request
from redis.exceptions import RedisError

from app import rate_limit as rate_limit_module
from app.rate_limit import rate_limit


def _fake_request(ip: str = "1.2.3.4") -> Request:
    request = MagicMock(spec=Request)
    request.client = MagicMock()
    request.client.host = ip
    return request


def _fake_redis(counts: list[int]) -> MagicMock:
    """Returns a fake Redis client whose pipeline().execute() yields
    successive counts from `counts` on each call (INCR result first)."""
    client = MagicMock()
    pipe = MagicMock()
    client.pipeline.return_value = pipe
    pipe.execute.side_effect = [[c, True] for c in counts]
    return client


class TestRateLimitWithinBounds:
    def test_requests_within_limit_pass(self, monkeypatch) -> None:
        fake_client = _fake_redis([1, 2, 3])
        monkeypatch.setattr(rate_limit_module, "get_redis_client", lambda: fake_client)

        dependency = rate_limit(limit=3, window_seconds=60, scope="test")
        request = _fake_request()
        for _ in range(3):
            dependency(request)  # should not raise

    def test_exceeding_limit_raises_429(self, monkeypatch) -> None:
        fake_client = _fake_redis([4])
        monkeypatch.setattr(rate_limit_module, "get_redis_client", lambda: fake_client)

        dependency = rate_limit(limit=3, window_seconds=60, scope="test")
        with pytest.raises(HTTPException) as exc_info:
            dependency(_fake_request())

        assert exc_info.value.status_code == 429

    def test_429_includes_retry_after_header(self, monkeypatch) -> None:
        fake_client = _fake_redis([4])
        monkeypatch.setattr(rate_limit_module, "get_redis_client", lambda: fake_client)

        dependency = rate_limit(limit=3, window_seconds=60, scope="test")
        with pytest.raises(HTTPException) as exc_info:
            dependency(_fake_request())

        assert "Retry-After" in exc_info.value.headers
        retry_after = int(exc_info.value.headers["Retry-After"])
        assert 1 <= retry_after <= 60

    def test_retry_after_is_never_zero_at_the_end_of_a_window(self, monkeypatch) -> None:
        """A request landing 0.0001s before the window boundary would
        compute a sub-1-second retry_after -- must be clamped to >= 1,
        never 0 (a client can't usefully retry-after 0 seconds)."""
        fake_client = _fake_redis([4])
        monkeypatch.setattr(rate_limit_module, "get_redis_client", lambda: fake_client)
        # window_start for window_seconds=60 at now=1000060 is 1000020;
        # place `now` 0.0001s before the window's end (1000020 + 60).
        monkeypatch.setattr(rate_limit_module.time, "time", lambda: 1000079.9999)

        dependency = rate_limit(limit=3, window_seconds=60, scope="test")
        with pytest.raises(HTTPException) as exc_info:
            dependency(_fake_request())

        assert int(exc_info.value.headers["Retry-After"]) == 1


class TestRateLimitKeying:
    def test_different_scopes_use_independent_keys(self, monkeypatch) -> None:
        fake_client = MagicMock()
        pipe = MagicMock()
        fake_client.pipeline.return_value = pipe
        pipe.execute.return_value = [1, True]
        monkeypatch.setattr(rate_limit_module, "get_redis_client", lambda: fake_client)

        rate_limit(limit=5, window_seconds=60, scope="search")(_fake_request())
        rate_limit(limit=5, window_seconds=60, scope="other")(_fake_request())

        keys_used = [call.args[0] for call in pipe.incr.call_args_list]
        assert keys_used[0] != keys_used[1]
        assert "ratelimit:search:" in keys_used[0]
        assert "ratelimit:other:" in keys_used[1]

    def test_different_ips_use_independent_keys(self, monkeypatch) -> None:
        fake_client = MagicMock()
        pipe = MagicMock()
        fake_client.pipeline.return_value = pipe
        pipe.execute.return_value = [1, True]
        monkeypatch.setattr(rate_limit_module, "get_redis_client", lambda: fake_client)

        dependency = rate_limit(limit=5, window_seconds=60, scope="search")
        dependency(_fake_request("1.1.1.1"))
        dependency(_fake_request("2.2.2.2"))

        keys_used = [call.args[0] for call in pipe.incr.call_args_list]
        assert keys_used[0] != keys_used[1]
        assert "1.1.1.1" in keys_used[0]
        assert "2.2.2.2" in keys_used[1]

    def test_custom_key_func_is_used(self, monkeypatch) -> None:
        fake_client = MagicMock()
        pipe = MagicMock()
        fake_client.pipeline.return_value = pipe
        pipe.execute.return_value = [1, True]
        monkeypatch.setattr(rate_limit_module, "get_redis_client", lambda: fake_client)

        dependency = rate_limit(
            limit=5, window_seconds=60, scope="search", key_func=lambda r: "account-42"
        )
        dependency(_fake_request())

        key_used = pipe.incr.call_args_list[0].args[0]
        assert "account-42" in key_used


class TestRateLimitFailsOpen:
    def test_redis_error_allows_the_request(self, monkeypatch) -> None:
        fake_client = MagicMock()
        pipe = MagicMock()
        fake_client.pipeline.return_value = pipe
        pipe.execute.side_effect = RedisError("boom")
        monkeypatch.setattr(rate_limit_module, "get_redis_client", lambda: fake_client)

        dependency = rate_limit(limit=1, window_seconds=60, scope="test")
        dependency(_fake_request())  # must not raise


class TestRateLimitDefaults:
    def test_uses_configured_defaults_when_not_overridden(self, monkeypatch) -> None:
        fake_client = _fake_redis([1])
        monkeypatch.setattr(rate_limit_module, "get_redis_client", lambda: fake_client)

        dependency = rate_limit(scope="test")  # no explicit limit/window
        dependency(_fake_request())  # should not raise -- within default limit
