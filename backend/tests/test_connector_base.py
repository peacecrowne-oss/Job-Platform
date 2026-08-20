"""Contract/DTO/error tests for the connector framework (STORY-016). No live
infrastructure or network access required -- `FakeConnector` and
`_FakeHttpClient` are defined entirely in this file, demonstrating that a
new connector can be added with zero changes to app/connectors/*.py.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from app.connectors.base import BaseConnector, HttpResponse, NormalizedJobRecord
from app.connectors.errors import (
    ConnectorAuthError,
    ConnectorConfigError,
    ConnectorError,
    ConnectorRateLimitedError,
    ConnectorSourceFormatError,
    ConnectorTransportError,
)


class _FakeConfig(BaseModel):
    board_token: str


class _FakeHttpResponse:
    def __init__(self, payload: Any, status_code: int = 200) -> None:
        self.status_code = status_code
        self.headers: dict[str, str] = {}
        self._payload = payload

    def json(self) -> Any:
        return self._payload

    @property
    def text(self) -> str:
        return str(self._payload)


class _FakeHttpClient:
    """No network access -- returns a canned response and records what was
    requested, so tests can prove the connector used this client and not a
    real one."""

    def __init__(self, response: HttpResponse) -> None:
        self._response = response
        self.requested_urls: list[str] = []

    def get(self, url, *, params=None, headers=None, timeout=None) -> HttpResponse:
        self.requested_urls.append(url)
        return self._response


class FakeConnector(BaseConnector):
    connector_type = "fake"
    config_model = _FakeConfig

    def fetch(self) -> Iterator[dict[str, Any]]:
        response = self.http_client.get(f"https://example.invalid/{self.config.board_token}")
        yield from response.json()

    def normalize(self, raw_record: dict[str, Any]) -> NormalizedJobRecord:
        return NormalizedJobRecord(
            source_job_id=raw_record["id"],
            job_title=raw_record.get("title"),
        )


def _make_connector(raw_records: list[dict[str, Any]]) -> FakeConnector:
    response = _FakeHttpResponse(raw_records)
    return FakeConnector({"board_token": "acme"}, _FakeHttpClient(response))


def test_fetch_normalize_validate_round_trip() -> None:
    connector = _make_connector(
        [{"id": "123", "title": "Engineer"}, {"id": "456", "title": "Designer"}]
    )

    raw_records = list(connector.fetch())
    assert len(raw_records) == 2

    normalized = [connector.normalize(r) for r in raw_records]
    assert normalized[0].source_job_id == "123"
    assert normalized[0].job_title == "Engineer"

    assert all(connector.validate(r) for r in normalized)


def test_fetch_uses_injected_http_client_not_network() -> None:
    connector = _make_connector([{"id": "1", "title": "X"}])
    list(connector.fetch())
    assert connector.http_client.requested_urls == ["https://example.invalid/acme"]


def test_invalid_config_raises_connector_config_error() -> None:
    with pytest.raises(ConnectorConfigError):
        FakeConnector({}, _FakeHttpClient(_FakeHttpResponse([])))


def test_normalized_record_defaults_to_none_for_unsupplied_fields() -> None:
    record = NormalizedJobRecord(source_job_id="abc")
    assert record.job_title is None
    assert record.company_name is None
    assert record.compensation_min is None
    assert record.raw_metadata is None


def test_normalized_record_requires_source_job_id() -> None:
    with pytest.raises(ValidationError):
        NormalizedJobRecord()  # type: ignore[call-arg]


def test_default_validate_rejects_empty_source_job_id() -> None:
    connector = _make_connector([])
    assert connector.validate(NormalizedJobRecord(source_job_id="")) is False
    assert connector.validate(NormalizedJobRecord(source_job_id="x")) is True


def test_no_unknown_value_used_anywhere_in_normalized_record() -> None:
    """Consistent with STORY-010's precedent: `unknown` is not a controlled
    value on any canonical job field; `None` is the only representation of
    absent/unclassified data."""
    record = NormalizedJobRecord(source_job_id="abc")
    for value in record.model_dump().values():
        assert value != "unknown"


@pytest.mark.parametrize(
    "error_cls",
    [
        ConnectorConfigError,
        ConnectorTransportError,
        ConnectorSourceFormatError,
        ConnectorAuthError,
        ConnectorRateLimitedError,
    ],
)
def test_connector_error_subtypes_are_connector_errors(error_cls) -> None:
    err = error_cls("boom", context={"detail": "x"})
    assert isinstance(err, ConnectorError)
    assert err.context == {"detail": "x"}
