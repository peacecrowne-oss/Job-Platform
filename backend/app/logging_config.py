"""Structured (JSON) logging with request/task correlation IDs (STORY-050).

Every module in this codebase already uses `logging.getLogger(__name__)`
consistently (`app.db`, `app.ingestion.orchestrator`, etc.) -- all of them
live under the shared `"app"` logger namespace. `configure_logging()`
attaches one JSON-formatting handler to that single parent logger, so
every existing `logger.warning()`/`logger.exception()` call site anywhere
in the codebase gets structured output and an injected correlation ID for
free -- zero changes needed to any of those call sites.

The correlation ID itself is a `contextvars.ContextVar`, not a parameter
threaded through every function call: `app/main.py`'s
`CorrelationIdMiddleware` binds it for the duration of one HTTP request;
`app/ingestion/orchestrator.py`'s `run_source()` binds it to the
`IngestionRun.id` it already creates (no new ID generation) for the
duration of one source's run. Each STORY-023 worker thread calls
`run_source()` independently, so each thread naturally sets its own
value -- no cross-thread propagation is needed or attempted.

Edge case ("logging failures must not crash the request/task being
logged") is satisfied twice over: Python's own `logging.Handler.emit()`
already catches a formatting exception and routes it to `handleError()`
rather than propagating it into application code, and `JsonFormatter`
below additionally wraps its own `json.dumps()` call in a `try/except`
with a safe fallback, so a formatting bug can never surface as a crash
even if that stdlib guarantee were somehow bypassed.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

CORRELATION_ID_HEADER = "X-Correlation-ID"

correlation_id_var: ContextVar[str | None] = ContextVar("correlation_id", default=None)

_RESERVED_RECORD_ATTRS = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
    "message",
    "asctime",
}


class CorrelationIdFilter(logging.Filter):
    """Injects the current correlation ID (or None, outside any bound
    request/run) into every LogRecord it sees."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = correlation_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        try:
            payload: dict[str, object] = {
                "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
                "correlation_id": getattr(record, "correlation_id", None),
            }
            # Anything passed via logger.info(..., extra={...}) that isn't
            # one of LogRecord's own built-in attributes -- e.g. this
            # module's own `method`/`path`/`status_code`/`duration_ms`.
            for key, value in record.__dict__.items():
                if key not in _RESERVED_RECORD_ATTRS and key != "correlation_id":
                    payload[key] = value
            if record.exc_info:
                payload["exception"] = self.formatException(record.exc_info)
            return json.dumps(payload, default=str)
        except Exception:  # noqa: BLE001 -- a formatting bug must never crash the caller
            return json.dumps(
                {"level": "ERROR", "logger": "app.logging_config", "message": "log formatting failed"}
            )


def configure_logging(level: str = "info") -> None:
    handler = logging.StreamHandler()
    handler.addFilter(CorrelationIdFilter())
    handler.setFormatter(JsonFormatter())

    app_logger = logging.getLogger("app")
    app_logger.handlers = [handler]
    app_logger.setLevel(level.upper())
    # Prevents duplicate lines if the root logger (uvicorn's own default
    # setup, left untouched -- see this Story's approved scope boundary)
    # also ends up with a handler attached.
    app_logger.propagate = False


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Binds a correlation ID (client-supplied via `X-Correlation-ID`, or a
    freshly generated one) for the duration of one HTTP request, logs one
    structured "request completed" line, and echoes the ID back as a
    response header so a caller can correlate their own logs too."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        correlation_id = request.headers.get(CORRELATION_ID_HEADER) or str(uuid.uuid4())
        token = correlation_id_var.set(correlation_id)
        start = time.monotonic()
        try:
            response = await call_next(request)
            duration_ms = (time.monotonic() - start) * 1000
            response.headers[CORRELATION_ID_HEADER] = correlation_id
            logger.info(
                "request completed",
                extra={
                    "http_method": request.method,
                    "http_path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": round(duration_ms, 2),
                },
            )
            return response
        finally:
            correlation_id_var.reset(token)
