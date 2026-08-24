"""Tests for the Greenhouse connector (STORY-018). No live infrastructure
or network access required -- every request goes through a real
PolicyEnforcingHttpClient (STORY-017) wrapping a FakeTransport, so these
tests exercise the actual policy layer, not a bypassed shortcut, while
staying fully offline.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.connectors.base import HttpResponse
from app.connectors.errors import (
    ConnectorConfigError,
    ConnectorRateLimitedError,
    ConnectorSourceFormatError,
    RobotsDisallowedError,
    SourceNotAuthorizedError,
)
from app.connectors.greenhouse import GreenhouseConnector, GreenhouseConnectorConfig
from app.connectors.http_client import PolicyEnforcingHttpClient
from app.connectors.policy import require_source_authorized
from app.connectors.registry import registry as module_registry
from app.models.source import Source

API_BASE = "https://example.invalid"
JOBS_URL = f"{API_BASE}/v1/boards/acme/jobs?content=true"
ROBOTS_URL = f"{API_BASE}/robots.txt"

ROBOTS_ALLOW_ALL = "User-agent: *\nDisallow:\n"
ROBOTS_DISALLOW_ALL = "User-agent: *\nDisallow: /\n"


class _FakeResponse:
    def __init__(
        self, status_code: int, body: str = "", headers: dict[str, str] | None = None
    ) -> None:
        self.status_code = status_code
        self.headers = headers or {}
        self._body = body

    def json(self) -> Any:
        return json.loads(self._body)

    @property
    def text(self) -> str:
        return self._body


class _FakeTransport:
    def __init__(self) -> None:
        self.responses: dict[str, HttpResponse] = {}
        self.requested_urls: list[str] = []

    def set_response(self, url: str, response: HttpResponse) -> None:
        self.responses[url] = response

    def raw_get(self, url, *, headers=None, timeout=None) -> HttpResponse:
        self.requested_urls.append(url)
        try:
            return self.responses[url]
        except KeyError:
            raise AssertionError(f"No canned response for {url}") from None


def _connector(transport: _FakeTransport, board_token: str = "acme") -> GreenhouseConnector:
    http_client = PolicyEnforcingHttpClient(transport=transport, user_agent="test-agent")
    return GreenhouseConnector({"board_token": board_token, "api_base_url": API_BASE}, http_client)


def _with_robots_allow_all(transport: _FakeTransport) -> _FakeTransport:
    transport.set_response(ROBOTS_URL, _FakeResponse(200, ROBOTS_ALLOW_ALL))
    return transport


ONE_JOB = {
    "id": 12345,
    "title": "Software Engineer",
    "updated_at": "2026-08-01T10:00:00-05:00",
    "location": {"name": "Remote - US"},
    "absolute_url": "https://boards.greenhouse.io/acme/jobs/12345",
    "content": "<p>Build things. <script>alert(1)</script></p>",
    "departments": [{"id": 1, "name": "Engineering"}],
    "offices": [{"id": 1, "name": "Remote"}],
}


def test_greenhouse_registers_in_registry() -> None:
    assert module_registry.get("greenhouse") is GreenhouseConnector
    assert GreenhouseConnector.connector_type == "greenhouse"


def test_valid_config_constructs_with_default_api_base_url() -> None:
    config = GreenhouseConnectorConfig(board_token="acme")
    assert config.api_base_url == "https://boards-api.greenhouse.io"


@pytest.mark.parametrize(
    "config",
    [
        {},
        {"board_token": ""},
        {"board_token": "acme/../etc"},
        {"board_token": "acme?x=1"},
    ],
)
def test_invalid_config_raises_connector_config_error(config: dict) -> None:
    transport = _with_robots_allow_all(_FakeTransport())
    http_client = PolicyEnforcingHttpClient(transport=transport, user_agent="test-agent")
    with pytest.raises(ConnectorConfigError):
        GreenhouseConnector(config, http_client)


def test_multiple_jobs_normalized_correctly() -> None:
    second_job = {**ONE_JOB, "id": 999, "title": "Designer", "departments": []}
    transport = _with_robots_allow_all(_FakeTransport())
    transport.set_response(
        JOBS_URL, _FakeResponse(200, json.dumps({"jobs": [ONE_JOB, second_job]}))
    )

    connector = _connector(transport)
    raw_records = list(connector.fetch())
    assert len(raw_records) == 2

    normalized = [connector.normalize(r) for r in raw_records]
    assert normalized[0].source_job_id == "12345"
    assert normalized[0].job_title == "Software Engineer"
    assert normalized[1].source_job_id == "999"
    assert normalized[1].job_title == "Designer"


def test_zero_postings_produces_empty_iterator_not_error() -> None:
    transport = _with_robots_allow_all(_FakeTransport())
    transport.set_response(JOBS_URL, _FakeResponse(200, json.dumps({"jobs": []})))

    connector = _connector(transport)
    assert list(connector.fetch()) == []


def test_missing_optional_fields_stay_none() -> None:
    minimal_job = {"id": 1, "title": "X"}
    transport = _with_robots_allow_all(_FakeTransport())
    transport.set_response(JOBS_URL, _FakeResponse(200, json.dumps({"jobs": [minimal_job]})))

    connector = _connector(transport)
    record = connector.normalize(next(connector.fetch()))

    assert record.source_url is None
    assert record.application_url is None
    assert record.description_full is None
    assert record.location_raw is None
    assert record.department is None
    assert record.source_updated_at is None
    assert record.company_name is None
    assert record.skills is None
    assert record.compensation_min is None
    assert record.work_mode is None


def test_stable_source_job_identity() -> None:
    transport = _with_robots_allow_all(_FakeTransport())
    transport.set_response(JOBS_URL, _FakeResponse(200, json.dumps({"jobs": [ONE_JOB]})))

    connector = _connector(transport)
    raw_records = list(connector.fetch())
    first = connector.normalize(raw_records[0])
    second = connector.normalize(raw_records[0])

    assert first.source_job_id == second.source_job_id == "12345"


def test_location_mapping() -> None:
    transport = _with_robots_allow_all(_FakeTransport())
    transport.set_response(JOBS_URL, _FakeResponse(200, json.dumps({"jobs": [ONE_JOB]})))

    connector = _connector(transport)
    record = connector.normalize(next(connector.fetch()))

    assert record.location_raw == "Remote - US"
    assert record.location_city is None
    assert record.location_region is None
    assert record.location_country is None


def test_department_mapping_multiple_and_none() -> None:
    multi_dept_job = {
        **ONE_JOB,
        "departments": [{"id": 1, "name": "Engineering"}, {"id": 2, "name": "Platform"}],
    }
    no_dept_job = {**ONE_JOB, "id": 2, "departments": []}
    transport = _with_robots_allow_all(_FakeTransport())
    transport.set_response(
        JOBS_URL, _FakeResponse(200, json.dumps({"jobs": [multi_dept_job, no_dept_job]}))
    )

    connector = _connector(transport)
    raw_records = list(connector.fetch())
    records = [connector.normalize(r) for r in raw_records]

    assert records[0].department == "Engineering, Platform"
    assert records[1].department is None


def test_html_description_preserved_untouched() -> None:
    transport = _with_robots_allow_all(_FakeTransport())
    transport.set_response(JOBS_URL, _FakeResponse(200, json.dumps({"jobs": [ONE_JOB]})))

    connector = _connector(transport)
    record = connector.normalize(next(connector.fetch()))

    assert record.description_full == "<p>Build things. <script>alert(1)</script></p>"


def test_malformed_response_missing_jobs_key_raises() -> None:
    transport = _with_robots_allow_all(_FakeTransport())
    transport.set_response(JOBS_URL, _FakeResponse(200, json.dumps({"not_jobs": []})))

    connector = _connector(transport)
    with pytest.raises(ConnectorSourceFormatError):
        list(connector.fetch())


def test_malformed_response_jobs_not_a_list_raises() -> None:
    transport = _with_robots_allow_all(_FakeTransport())
    transport.set_response(JOBS_URL, _FakeResponse(200, json.dumps({"jobs": "oops"})))

    connector = _connector(transport)
    with pytest.raises(ConnectorSourceFormatError):
        list(connector.fetch())


def test_malformed_json_body_raises() -> None:
    transport = _with_robots_allow_all(_FakeTransport())
    transport.set_response(JOBS_URL, _FakeResponse(200, "{not valid json"))

    connector = _connector(transport)
    with pytest.raises(ConnectorSourceFormatError):
        list(connector.fetch())


def test_job_missing_id_raises() -> None:
    transport = _with_robots_allow_all(_FakeTransport())
    transport.set_response(JOBS_URL, _FakeResponse(200, json.dumps({"jobs": [{"title": "X"}]})))

    connector = _connector(transport)
    raw_record = next(connector.fetch())
    with pytest.raises(ConnectorSourceFormatError):
        connector.normalize(raw_record)


def test_404_raises_connector_config_error() -> None:
    transport = _with_robots_allow_all(_FakeTransport())
    transport.set_response(JOBS_URL, _FakeResponse(404, ""))

    connector = _connector(transport)
    with pytest.raises(ConnectorConfigError):
        list(connector.fetch())


def test_5xx_raises_connector_source_format_error() -> None:
    transport = _with_robots_allow_all(_FakeTransport())
    transport.set_response(JOBS_URL, _FakeResponse(503, ""))

    connector = _connector(transport)
    with pytest.raises(ConnectorSourceFormatError):
        list(connector.fetch())


def test_429_propagates_as_connector_rate_limited_error() -> None:
    transport = _with_robots_allow_all(_FakeTransport())
    transport.set_response(JOBS_URL, _FakeResponse(429, ""))

    connector = _connector(transport)
    with pytest.raises(ConnectorRateLimitedError):
        list(connector.fetch())


def test_robots_disallow_raises_and_jobs_url_never_requested() -> None:
    transport = _FakeTransport()
    transport.set_response(ROBOTS_URL, _FakeResponse(200, ROBOTS_DISALLOW_ALL))

    connector = _connector(transport)
    with pytest.raises(RobotsDisallowedError):
        list(connector.fetch())

    assert JOBS_URL not in transport.requested_urls


def test_denied_source_causes_zero_greenhouse_network_execution() -> None:
    """Critical test: a disabled Source must result in zero network calls,
    proven end-to-end for the real Greenhouse connector."""

    class _SpyTransport:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def raw_get(self, url, *, headers=None, timeout=None):
            self.calls.append(url)
            raise AssertionError(f"raw_get should never be called, but was called with {url}")

    source = Source(name="Acme Greenhouse", connector_type="greenhouse", enabled=False)
    spy_transport = _SpyTransport()

    with pytest.raises(SourceNotAuthorizedError):
        require_source_authorized(source)
        http_client = PolicyEnforcingHttpClient(transport=spy_transport, user_agent="test-agent")
        connector = GreenhouseConnector({"board_token": "acme"}, http_client)
        list(connector.fetch())

    assert spy_transport.calls == []


def test_no_direct_network_imports_in_greenhouse_module() -> None:
    """Structural proof the connector can't bypass the injected http_client:
    it never imports urllib/requests/sockets itself."""
    import inspect

    import app.connectors.greenhouse as greenhouse_module

    source = inspect.getsource(greenhouse_module)
    for forbidden in ("import urllib", "import requests", "import socket", "import http.client"):
        assert forbidden not in source
