"""Retry Handling for Transient Ingestion Failures (STORY-022).

A reusable, bounded retry wrapper for connector operations -- lives
alongside `app/ingestion/dedup.py` as another "shared ingestion pipeline"
primitive (STORY-016's own technical note), not duplicated per connector
and not mixed into the transport/policy layer
(`app/connectors/http_client.py`).

Classification is driven entirely by exception type (and, for
`ConnectorSourceFormatError`, the `status_code` already present in its
`context`) -- never connector-aware. `ConnectorSourceFormatError` is
raised by Greenhouse/Ashby for *both* a 5xx response and a malformed/
unexpected payload; only the former is transient, so `is_retryable()`
inspects `context["status_code"]` to tell them apart rather than requiring
any change to either connector.

No IngestionRun wiring here -- no orchestrator exists yet to drive a real
run. The edge case this Story owns ("exhausted retries still produce a
completed (failed) run, not a hung one") is satisfied structurally:
`with_retry()` always either returns a result or raises a real exception
once `max_attempts` is exhausted, never hangs or loops forever.

"Retry policy configurable per connector/source" (the technical note) is
satisfied by `RetryPolicy` being a plain, freely-constructible parameter --
no wiring into `Source.config` or connector classes is implemented, since
no orchestrator exists yet to consume it.
"""

from __future__ import annotations

import email.utils
import logging
import random
import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any, TypeVar

from pydantic import BaseModel

from app.connectors.errors import (
    AntiBotChallengeDetectedError,
    ConnectorAuthError,
    ConnectorConfigError,
    ConnectorRateLimitedError,
    ConnectorRegistryError,
    ConnectorSourceFormatError,
    ConnectorTransportError,
    RobotsDisallowedError,
    SourceNotAuthorizedError,
    SsrfRejectedError,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")

_RETRYABLE_STATUS_MIN = 500


class RetryPolicy(BaseModel):
    max_attempts: int = 3
    base_delay: float = 1.0
    max_delay: float = 30.0


def is_retryable(exc: Exception) -> bool:
    """Fail-safe default: anything not explicitly recognized as transient
    is never retried -- including access-control/security rejections
    (SourceNotAuthorizedError, RobotsDisallowedError, SsrfRejectedError,
    AntiBotChallengeDetectedError, ConnectorAuthError), which must never
    be retried as a way to evade those restrictions."""
    if isinstance(exc, ConnectorTransportError):
        return True
    if isinstance(exc, ConnectorRateLimitedError):
        return True
    if isinstance(exc, ConnectorSourceFormatError):
        status_code = exc.context.get("status_code")
        return isinstance(status_code, int) and status_code >= _RETRYABLE_STATUS_MIN

    # Explicitly non-retryable, listed for clarity even though the
    # fail-safe default below already covers them:
    if isinstance(
        exc,
        (
            ConnectorConfigError,
            ConnectorAuthError,
            SourceNotAuthorizedError,
            RobotsDisallowedError,
            AntiBotChallengeDetectedError,
            SsrfRejectedError,
            ConnectorRegistryError,
        ),
    ):
        return False

    return False


def compute_backoff_delay(
    attempt: int,
    *,
    base_delay: float,
    max_delay: float,
    random_func: Callable[[], float] = random.random,
) -> float:
    """Exponential backoff with full jitter. `attempt` is 1-indexed: the
    delay before retry #1 uses 2**0, before retry #2 uses 2**1, etc.,
    capped at max_delay *before* jitter is applied so jitter never pushes
    past the cap."""
    capped = min(base_delay * (2 ** (attempt - 1)), max_delay)
    return capped * random_func()


def _parse_retry_after(value: str | None, *, max_delay: float) -> float | None:
    """Returns a bounded delay in seconds, or None if absent/unparseable
    (caller falls back to normal exponential backoff in that case)."""
    if not value:
        return None

    try:
        seconds = float(value)
        return max(0.0, min(seconds, max_delay))
    except ValueError:
        pass

    try:
        target = email.utils.parsedate_to_datetime(value)
        if target.tzinfo is None:
            target = target.replace(tzinfo=timezone.utc)
        seconds = (target - datetime.now(timezone.utc)).total_seconds()
        return max(0.0, min(seconds, max_delay))
    except (TypeError, ValueError):
        return None


def with_retry(
    operation: Callable[[], T],
    *,
    policy: RetryPolicy,
    sleep: Callable[[float], None] = time.sleep,
    random_func: Callable[[], float] = random.random,
    context: dict[str, Any] | None = None,
) -> T:
    """Calls operation(), retrying on a retryable failure up to
    policy.max_attempts. Never retries anything is_retryable() rejects --
    those propagate immediately, unchanged, after exactly one attempt.

    `context` is optional caller-supplied logging context (e.g. source_id/
    connector_type) -- with_retry() itself has no notion of what it's
    retrying.
    """
    log_context = dict(context or {})
    attempt = 0

    while True:
        attempt += 1
        try:
            return operation()
        except Exception as exc:
            if not is_retryable(exc) or attempt >= policy.max_attempts:
                raise

            delay = None
            if isinstance(exc, ConnectorRateLimitedError):
                delay = _parse_retry_after(
                    exc.context.get("retry_after"), max_delay=policy.max_delay
                )
            if delay is None:
                delay = compute_backoff_delay(
                    attempt,
                    base_delay=policy.base_delay,
                    max_delay=policy.max_delay,
                    random_func=random_func,
                )

            logger.warning(
                "retrying after transient failure",
                extra={
                    **log_context,
                    "attempt": attempt,
                    "max_attempts": policy.max_attempts,
                    "error_type": type(exc).__name__,
                    "status_code": exc.context.get("status_code")
                    if hasattr(exc, "context")
                    else None,
                    "delay_seconds": delay,
                },
            )
            sleep(delay)
