"""Tests for app.logging_config (STORY-050). No live database required.

`configure_logging()` attaches its handler to the `"app"` logger with
`propagate=False` (deliberately, so it never duplicates onto the root
logger) -- which means pytest's own `caplog` fixture (a handler on the
*root* logger) can't see these records. Tests that need to inspect actual
emitted records attach their own temporary handler directly to the `"app"`
logger instead, restoring it afterward.
"""

from __future__ import annotations

import json
import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.logging_config import (
    CORRELATION_ID_HEADER,
    CorrelationIdFilter,
    CorrelationIdMiddleware,
    JsonFormatter,
    configure_logging,
    correlation_id_var,
)


def _make_record(**overrides) -> logging.LogRecord:
    defaults = dict(
        name="app.example",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello",
        args=(),
        exc_info=None,
    )
    defaults.update(overrides)
    return logging.LogRecord(**defaults)


class _CapturingHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def captured_app_records():
    """Temporarily replaces the "app" logger's handler with a capturing one
    (bypassing JSON formatting) so tests can inspect raw record attributes,
    e.g. record.correlation_id after CorrelationIdFilter runs."""
    app_logger = logging.getLogger("app")
    original_handlers = app_logger.handlers
    original_propagate = app_logger.propagate

    handler = _CapturingHandler()
    handler.addFilter(CorrelationIdFilter())
    app_logger.handlers = [handler]
    app_logger.propagate = False
    app_logger.setLevel(logging.DEBUG)

    try:
        yield handler.records
    finally:
        app_logger.handlers = original_handlers
        app_logger.propagate = original_propagate


def test_json_formatter_produces_valid_parseable_json() -> None:
    formatter = JsonFormatter()
    output = formatter.format(_make_record(msg="hello %s", args=("world",)))
    payload = json.loads(output)
    assert payload["message"] == "hello world"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "app.example"


def test_json_formatter_includes_bound_correlation_id() -> None:
    token = correlation_id_var.set("test-correlation-123")
    try:
        record = _make_record()
        CorrelationIdFilter().filter(record)
        payload = json.loads(JsonFormatter().format(record))
        assert payload["correlation_id"] == "test-correlation-123"
    finally:
        correlation_id_var.reset(token)


def test_json_formatter_correlation_id_is_null_when_unbound() -> None:
    record = _make_record()
    CorrelationIdFilter().filter(record)
    payload = json.loads(JsonFormatter().format(record))
    assert payload["correlation_id"] is None


def test_json_formatter_includes_extra_fields() -> None:
    record = _make_record()
    record.http_method = "GET"
    record.status_code = 200
    payload = json.loads(JsonFormatter().format(record))
    assert payload["http_method"] == "GET"
    assert payload["status_code"] == 200


def test_json_formatter_never_raises_on_unserializable_extra() -> None:
    """STORY-050's own literal edge case: a logging failure must not crash
    the request/task being logged."""
    record = _make_record()
    record.broken = object()  # not JSON-serializable and no __str__ override needed -- default() handles it
    output = JsonFormatter().format(record)
    json.loads(output)  # must not raise


def test_json_formatter_includes_exception_info() -> None:
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        record = _make_record(exc_info=sys.exc_info())
    payload = json.loads(JsonFormatter().format(record))
    assert "ValueError" in payload["exception"]
    assert "boom" in payload["exception"]


def test_logs_within_one_request_share_the_same_correlation_id(captured_app_records) -> None:
    app = FastAPI()
    app.add_middleware(CorrelationIdMiddleware)

    @app.get("/ping")
    def ping():
        logging.getLogger("app.example").info("inside handler")
        return {"ok": True}

    client = TestClient(app)
    response = client.get("/ping")

    assert response.status_code == 200
    correlation_id = response.headers[CORRELATION_ID_HEADER]

    # Both this app-code log line and the middleware's own "request
    # completed" line must carry the identical correlation ID.
    ids = {getattr(r, "correlation_id", None) for r in captured_app_records}
    assert ids == {correlation_id}


def test_middleware_reuses_client_supplied_correlation_id() -> None:
    app = FastAPI()
    app.add_middleware(CorrelationIdMiddleware)

    @app.get("/ping")
    def ping():
        return {"ok": True}

    client = TestClient(app)
    response = client.get("/ping", headers={CORRELATION_ID_HEADER: "client-supplied-id"})

    assert response.headers[CORRELATION_ID_HEADER] == "client-supplied-id"


def test_middleware_generates_id_when_absent() -> None:
    app = FastAPI()
    app.add_middleware(CorrelationIdMiddleware)

    @app.get("/ping")
    def ping():
        return {"ok": True}

    client = TestClient(app)
    response = client.get("/ping")

    assert response.headers[CORRELATION_ID_HEADER]  # non-empty, generated


def test_different_requests_get_different_correlation_ids() -> None:
    app = FastAPI()
    app.add_middleware(CorrelationIdMiddleware)

    @app.get("/ping")
    def ping():
        return {"ok": True}

    client = TestClient(app)
    first = client.get("/ping").headers[CORRELATION_ID_HEADER]
    second = client.get("/ping").headers[CORRELATION_ID_HEADER]

    assert first != second


def test_scheduler_logger_name_is_hardcoded_not_dunder_name() -> None:
    """Regression test for a real bug caught during live Docker
    validation: when app/ingestion/scheduler.py is run as the entry point
    (`python -m app.ingestion.scheduler`), __name__ becomes "__main__", not
    "app.ingestion.scheduler" -- logging.getLogger(__name__) there would
    silently fall outside the "app" logger tree (no handler, INFO-level
    lines dropped entirely) regardless of how the module is invoked. The
    module must use a hardcoded logger name instead."""
    import app.ingestion.scheduler as scheduler_module

    assert scheduler_module.logger.name == "app.ingestion.scheduler"


def test_configure_logging_attaches_handler_without_propagating_to_root() -> None:
    app_logger = logging.getLogger("app")
    original_handlers = app_logger.handlers
    original_propagate = app_logger.propagate
    try:
        configure_logging("debug")
        assert len(app_logger.handlers) == 1
        assert isinstance(app_logger.handlers[0].formatter, JsonFormatter)
        assert app_logger.propagate is False
        assert app_logger.level == logging.DEBUG
    finally:
        app_logger.handlers = original_handlers
        app_logger.propagate = original_propagate
