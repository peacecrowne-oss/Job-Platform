"""Real-Redis integration coverage for STORY-045's rate limiter (STORY-054).

test_rate_limit.py's own unit tests already prove the fixed-window logic
against a mocked Redis pipeline. Per progress.md's own STORY-045 entry, the
real 429-then-reset behavior was previously only validated *manually*
during that Story's implementation, never committed as a repeatable test --
this closes exactly that gap, against the isolated test Redis DB index
(never DB 0, the real development/rate-limiting index -- see conftest.py's
`redis_test_client` fixture and its safety guard).
"""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app import rate_limit as rate_limit_module

pytestmark = [pytest.mark.integration, pytest.mark.redis]


def _fake_request(ip: str) -> SimpleNamespace:
    return SimpleNamespace(client=SimpleNamespace(host=ip))


def test_rate_limit_blocks_after_real_redis_limit_exceeded(redis_test_client, monkeypatch) -> None:
    monkeypatch.setattr(rate_limit_module, "get_redis_client", lambda: redis_test_client.client)

    window_seconds = 5
    scope = "itest-block"
    ip = "203.0.113.5"
    dependency = rate_limit_module.rate_limit(limit=3, window_seconds=window_seconds, scope=scope)
    request = _fake_request(ip)

    window_start = int(time.time() // window_seconds) * window_seconds
    redis_test_client.track(f"ratelimit:{scope}:{ip}:{window_start}")

    for _ in range(3):
        dependency(request)  # must not raise

    with pytest.raises(HTTPException) as exc_info:
        dependency(request)

    assert exc_info.value.status_code == 429
    retry_after = int(exc_info.value.headers["Retry-After"])
    assert 1 <= retry_after <= window_seconds


def test_rate_limit_resets_after_real_redis_window_passes(redis_test_client, monkeypatch) -> None:
    monkeypatch.setattr(rate_limit_module, "get_redis_client", lambda: redis_test_client.client)

    window_seconds = 1
    scope = "itest-reset"
    ip = "203.0.113.6"
    dependency = rate_limit_module.rate_limit(limit=1, window_seconds=window_seconds, scope=scope)
    request = _fake_request(ip)

    first_window_start = int(time.time() // window_seconds) * window_seconds
    redis_test_client.track(f"ratelimit:{scope}:{ip}:{first_window_start}")

    dependency(request)  # consumes the only allowed request this window
    with pytest.raises(HTTPException):
        dependency(request)

    time.sleep(window_seconds + 0.2)

    second_window_start = int(time.time() // window_seconds) * window_seconds
    redis_test_client.track(f"ratelimit:{scope}:{ip}:{second_window_start}")

    dependency(request)  # new window -- must not raise
