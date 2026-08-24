"""Tests for retry handling (STORY-022). No live infrastructure, network
access, or real sleeping required -- `sleep` and `random_func` are always
injected test doubles.
"""

from __future__ import annotations

import pytest

from app.connectors.errors import (
    AntiBotChallengeDetectedError,
    ConnectorAuthError,
    ConnectorConfigError,
    ConnectorRateLimitedError,
    ConnectorSourceFormatError,
    ConnectorTransportError,
    RobotsDisallowedError,
    SourceNotAuthorizedError,
    SsrfRejectedError,
)
from app.ingestion.retry import (
    RetryPolicy,
    compute_backoff_delay,
    is_retryable,
    with_retry,
)


class _RecordingSleep:
    def __init__(self) -> None:
        self.calls: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


def _no_jitter() -> float:
    """random_func returning 1.0 -- delay equals the full capped value,
    making assertions exact and deterministic."""
    return 1.0


# -- is_retryable classification ------------------------------------------


def test_transport_error_is_retryable() -> None:
    assert is_retryable(ConnectorTransportError("boom")) is True


def test_rate_limited_error_is_retryable() -> None:
    assert is_retryable(ConnectorRateLimitedError("boom")) is True


@pytest.mark.parametrize("status_code", [500, 502, 503])
def test_source_format_error_5xx_is_retryable(status_code: int) -> None:
    exc = ConnectorSourceFormatError("boom", context={"status_code": status_code})
    assert is_retryable(exc) is True


@pytest.mark.parametrize("status_code", [400, 405, None])
def test_source_format_error_non_5xx_is_not_retryable(status_code) -> None:
    context = {"status_code": status_code} if status_code is not None else {}
    exc = ConnectorSourceFormatError("boom", context=context)
    assert is_retryable(exc) is False


def test_source_format_error_malformed_json_no_status_code_not_retryable() -> None:
    """The exact ambiguity this Story resolves: Greenhouse/Ashby raise this
    same class for both a 5xx and a parse error -- only the status_code
    in context tells them apart."""
    exc = ConnectorSourceFormatError("Greenhouse response body was not valid JSON")
    assert is_retryable(exc) is False


@pytest.mark.parametrize(
    "exc",
    [
        ConnectorConfigError("boom"),
        ConnectorAuthError("boom"),
        SourceNotAuthorizedError("boom"),
        RobotsDisallowedError("boom"),
        AntiBotChallengeDetectedError("boom"),
        SsrfRejectedError("boom"),
    ],
)
def test_policy_and_security_errors_are_never_retryable(exc: Exception) -> None:
    assert is_retryable(exc) is False


def test_unrecognized_exception_is_not_retryable() -> None:
    assert is_retryable(ValueError("something else entirely")) is False


# -- compute_backoff_delay -------------------------------------------------


def test_backoff_delay_grows_exponentially_before_cap() -> None:
    d1 = compute_backoff_delay(1, base_delay=1.0, max_delay=100.0, random_func=_no_jitter)
    d2 = compute_backoff_delay(2, base_delay=1.0, max_delay=100.0, random_func=_no_jitter)
    d3 = compute_backoff_delay(3, base_delay=1.0, max_delay=100.0, random_func=_no_jitter)
    assert d1 == 1.0
    assert d2 == 2.0
    assert d3 == 4.0


def test_backoff_delay_capped_at_max_delay() -> None:
    delay = compute_backoff_delay(10, base_delay=1.0, max_delay=5.0, random_func=_no_jitter)
    assert delay == 5.0


@pytest.mark.parametrize("random_value", [0.0, 0.5, 0.999])
def test_jitter_stays_within_bounds(random_value: float) -> None:
    delay = compute_backoff_delay(3, base_delay=1.0, max_delay=100.0, random_func=lambda: random_value)
    assert 0.0 <= delay <= 4.0


# -- with_retry: success paths ---------------------------------------------


def test_success_on_first_attempt_no_sleep() -> None:
    sleep = _RecordingSleep()
    calls = []

    def operation():
        calls.append(1)
        return "ok"

    result = with_retry(operation, policy=RetryPolicy(), sleep=sleep)

    assert result == "ok"
    assert len(calls) == 1
    assert sleep.calls == []


def test_transient_failure_then_success() -> None:
    sleep = _RecordingSleep()
    attempts = {"count": 0}

    def operation():
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise ConnectorTransportError("transient")
        return "ok"

    result = with_retry(operation, policy=RetryPolicy(max_attempts=3), sleep=sleep, random_func=_no_jitter)

    assert result == "ok"
    assert attempts["count"] == 2
    assert len(sleep.calls) == 1


# -- with_retry: exhaustion --------------------------------------------------


def test_repeated_transient_failures_exhaust_attempts_and_raise() -> None:
    sleep = _RecordingSleep()
    attempts = {"count": 0}

    def operation():
        attempts["count"] += 1
        raise ConnectorTransportError("always fails")

    with pytest.raises(ConnectorTransportError):
        with_retry(operation, policy=RetryPolicy(max_attempts=3), sleep=sleep, random_func=_no_jitter)

    assert attempts["count"] == 3
    assert len(sleep.calls) == 2  # slept between attempts 1->2 and 2->3, not after the last


# -- with_retry: non-retryable fails immediately (critical test) -----------


@pytest.mark.parametrize(
    "exc_factory",
    [
        lambda: ConnectorConfigError("bad config"),
        lambda: ConnectorAuthError("unauthorized"),
        lambda: SourceNotAuthorizedError("disabled"),
        lambda: RobotsDisallowedError("disallowed"),
        lambda: SsrfRejectedError("blocked ip"),
        lambda: AntiBotChallengeDetectedError("challenge"),
    ],
)
def test_non_retryable_policy_or_security_failure_results_in_exactly_one_attempt(exc_factory) -> None:
    """Critical test: a non-retryable policy/security failure results in
    exactly ONE attempt -- never retried as a way to evade the rejection."""
    sleep = _RecordingSleep()
    attempts = {"count": 0}

    def operation():
        attempts["count"] += 1
        raise exc_factory()

    with pytest.raises(Exception):
        with_retry(operation, policy=RetryPolicy(max_attempts=5), sleep=sleep)

    assert attempts["count"] == 1
    assert sleep.calls == []


# -- with_retry: 5xx / Retry-After ------------------------------------------


def test_5xx_source_format_error_is_retried() -> None:
    sleep = _RecordingSleep()
    attempts = {"count": 0}

    def operation():
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise ConnectorSourceFormatError("server error", context={"status_code": 503})
        return "ok"

    result = with_retry(operation, policy=RetryPolicy(), sleep=sleep, random_func=_no_jitter)
    assert result == "ok"
    assert attempts["count"] == 2


def test_valid_retry_after_seconds_used_for_delay() -> None:
    sleep = _RecordingSleep()
    attempts = {"count": 0}

    def operation():
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise ConnectorRateLimitedError("slow down", context={"retry_after": "7"})
        return "ok"

    with_retry(operation, policy=RetryPolicy(max_delay=30.0), sleep=sleep, random_func=_no_jitter)

    assert sleep.calls == [7.0]


def test_retry_after_bounded_to_max_delay() -> None:
    sleep = _RecordingSleep()
    attempts = {"count": 0}

    def operation():
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise ConnectorRateLimitedError("slow down", context={"retry_after": "99999"})
        return "ok"

    with_retry(operation, policy=RetryPolicy(max_delay=10.0), sleep=sleep, random_func=_no_jitter)

    assert sleep.calls == [10.0]


def test_malformed_retry_after_falls_back_to_backoff() -> None:
    sleep = _RecordingSleep()
    attempts = {"count": 0}

    def operation():
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise ConnectorRateLimitedError("slow down", context={"retry_after": "not-a-date-or-number"})
        return "ok"

    with_retry(
        operation,
        policy=RetryPolicy(base_delay=2.0, max_delay=30.0),
        sleep=sleep,
        random_func=_no_jitter,
    )

    # Falls back to exponential backoff: attempt=1 -> base_delay * 2**0 = 2.0
    assert sleep.calls == [2.0]


def test_missing_retry_after_falls_back_to_backoff() -> None:
    sleep = _RecordingSleep()
    attempts = {"count": 0}

    def operation():
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise ConnectorRateLimitedError("slow down", context={"status_code": 429})
        return "ok"

    with_retry(
        operation,
        policy=RetryPolicy(base_delay=3.0, max_delay=30.0),
        sleep=sleep,
        random_func=_no_jitter,
    )

    assert sleep.calls == [3.0]


# -- Connector compatibility -------------------------------------------------


def test_greenhouse_5xx_shaped_exception_is_retryable() -> None:
    exc = ConnectorSourceFormatError(
        "Greenhouse returned an unexpected status fetching jobs: 503",
        context={"status_code": 503},
    )
    assert is_retryable(exc) is True


def test_greenhouse_malformed_json_shaped_exception_is_not_retryable() -> None:
    exc = ConnectorSourceFormatError("Greenhouse response body was not valid JSON: boom")
    assert is_retryable(exc) is False


def test_ashby_404_shaped_exception_is_not_retryable() -> None:
    exc = ConnectorConfigError("Ashby job board not found for 'acme'", context={"status_code": 404})
    assert is_retryable(exc) is False
