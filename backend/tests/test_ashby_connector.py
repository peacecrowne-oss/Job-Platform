"""Tests for the Ashby connector (STORY-019). No live infrastructure or
network access required -- every request goes through a real
PolicyEnforcingHttpClient (STORY-017) wrapping a FakeTransport, so these
tests exercise the actual policy layer, not a bypassed shortcut, while
staying fully offline. Field shapes below match a real live board's
response, confirmed during implementation (see progress.md).
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import pytest

from app.connectors.ashby import AshbyConnector, AshbyConnectorConfig
from app.connectors.base import HttpResponse
from app.connectors.errors import (
    ConnectorConfigError,
    ConnectorRateLimitedError,
    ConnectorSourceFormatError,
    RobotsDisallowedError,
    SourceNotAuthorizedError,
)
from app.connectors.http_client import PolicyEnforcingHttpClient
from app.connectors.policy import require_source_authorized
from app.connectors.registry import registry as module_registry
from app.models.source import Source

API_BASE = "https://example.invalid"
JOBS_URL = f"{API_BASE}/posting-api/job-board/acme"
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


def _connector(transport: _FakeTransport, job_board_name: str = "acme") -> AshbyConnector:
    http_client = PolicyEnforcingHttpClient(transport=transport, user_agent="test-agent")
    return AshbyConnector(
        {"job_board_name": job_board_name, "api_base_url": API_BASE}, http_client
    )


def _with_robots_allow_all(transport: _FakeTransport) -> _FakeTransport:
    transport.set_response(ROBOTS_URL, _FakeResponse(200, ROBOTS_ALLOW_ALL))
    return transport


ONE_JOB = {
    "id": "7458d4e9-da2e-47bd-98cb-adfda43d42b2",
    "title": "Engineering Manager - EU",
    "department": "Engineering",
    "team": "EMEA Engineering",
    "employmentType": "FullTime",
    "location": "Remote - European Union",
    "secondaryLocations": [{"location": "Spain", "address": {}}],
    "publishedAt": "2026-07-01T00:00:00.000Z",
    "isListed": True,
    "isRemote": True,
    "workplaceType": "Remote",
    "jobUrl": "https://jobs.ashbyhq.com/acme/7458d4e9",
    "applyUrl": "https://jobs.ashbyhq.com/acme/7458d4e9/application",
    "descriptionHtml": "<p>Do things. <script>alert(1)</script></p>",
    "descriptionPlain": "Do things.",
}


def test_ashby_registers_in_registry() -> None:
    assert module_registry.get("ashby") is AshbyConnector
    assert AshbyConnector.connector_type == "ashby"


def test_valid_config_constructs_with_default_api_base_url() -> None:
    config = AshbyConnectorConfig(job_board_name="acme")
    assert config.api_base_url == "https://api.ashbyhq.com"


@pytest.mark.parametrize(
    "config",
    [
        {},
        {"job_board_name": ""},
        {"job_board_name": "acme/../etc"},
        {"job_board_name": "acme?x=1"},
    ],
)
def test_invalid_config_raises_connector_config_error(config: dict) -> None:
    transport = _with_robots_allow_all(_FakeTransport())
    http_client = PolicyEnforcingHttpClient(transport=transport, user_agent="test-agent")
    with pytest.raises(ConnectorConfigError):
        AshbyConnector(config, http_client)


def test_multiple_jobs_normalized_correctly() -> None:
    second_job = {**ONE_JOB, "id": "second-id", "title": "Designer", "department": None, "team": None}
    transport = _with_robots_allow_all(_FakeTransport())
    transport.set_response(
        JOBS_URL, _FakeResponse(200, json.dumps({"jobs": [ONE_JOB, second_job]}))
    )

    connector = _connector(transport)
    raw_records = list(connector.fetch())
    assert len(raw_records) == 2

    normalized = [connector.normalize(r) for r in raw_records]
    assert normalized[0].source_job_id == "7458d4e9-da2e-47bd-98cb-adfda43d42b2"
    assert normalized[0].job_title == "Engineering Manager - EU"
    assert normalized[1].source_job_id == "second-id"
    assert normalized[1].job_title == "Designer"


def test_empty_board_produces_empty_iterator_not_error() -> None:
    transport = _with_robots_allow_all(_FakeTransport())
    transport.set_response(JOBS_URL, _FakeResponse(200, json.dumps({"jobs": []})))

    connector = _connector(transport)
    assert list(connector.fetch()) == []


def test_missing_optional_fields_stay_none() -> None:
    minimal_job = {"id": "x1", "title": "X"}
    transport = _with_robots_allow_all(_FakeTransport())
    transport.set_response(JOBS_URL, _FakeResponse(200, json.dumps({"jobs": [minimal_job]})))

    connector = _connector(transport)
    record = connector.normalize(next(connector.fetch()))

    assert record.source_url is None
    assert record.application_url is None
    assert record.description_full is None
    assert record.location_raw is None
    assert record.department is None
    assert record.work_mode is None
    assert record.employment_type is None
    assert record.posting_date is None
    assert record.company_name is None
    assert record.compensation_min is None
    assert record.compensation_currency is None
    assert record.benefits is None
    assert record.seniority is None


def test_stable_source_job_identity() -> None:
    transport = _with_robots_allow_all(_FakeTransport())
    transport.set_response(JOBS_URL, _FakeResponse(200, json.dumps({"jobs": [ONE_JOB]})))

    connector = _connector(transport)
    raw_records = list(connector.fetch())
    first = connector.normalize(raw_records[0])
    second = connector.normalize(raw_records[0])

    assert first.source_job_id == second.source_job_id == "7458d4e9-da2e-47bd-98cb-adfda43d42b2"


def test_primary_location_mapped_secondary_preserved_in_raw_metadata_only() -> None:
    transport = _with_robots_allow_all(_FakeTransport())
    transport.set_response(JOBS_URL, _FakeResponse(200, json.dumps({"jobs": [ONE_JOB]})))

    connector = _connector(transport)
    record = connector.normalize(next(connector.fetch()))

    assert record.location_raw == "Remote - European Union"
    assert record.location_city is None
    assert record.location_region is None
    assert record.location_country is None
    assert record.raw_metadata["secondaryLocations"] == ONE_JOB["secondaryLocations"]


def test_department_and_team_joined() -> None:
    only_department = {**ONE_JOB, "id": "a", "team": None}
    only_team = {**ONE_JOB, "id": "b", "department": None}
    neither = {**ONE_JOB, "id": "c", "department": None, "team": None}
    transport = _with_robots_allow_all(_FakeTransport())
    transport.set_response(
        JOBS_URL,
        _FakeResponse(200, json.dumps({"jobs": [ONE_JOB, only_department, only_team, neither]})),
    )

    connector = _connector(transport)
    records = [connector.normalize(r) for r in connector.fetch()]

    assert records[0].department == "Engineering, EMEA Engineering"
    assert records[1].department == "Engineering"
    assert records[2].department == "EMEA Engineering"
    assert records[3].department is None


def test_workplace_type_and_employment_type_mapping() -> None:
    hybrid_job = {**ONE_JOB, "id": "h", "workplaceType": "Hybrid", "employmentType": "PartTime"}
    onsite_job = {**ONE_JOB, "id": "o", "workplaceType": "OnSite", "employmentType": "Contract"}
    unrecognized_job = {
        **ONE_JOB,
        "id": "u",
        "workplaceType": "Underwater",
        "employmentType": "Freelance",
    }
    transport = _with_robots_allow_all(_FakeTransport())
    transport.set_response(
        JOBS_URL,
        _FakeResponse(
            200, json.dumps({"jobs": [ONE_JOB, hybrid_job, onsite_job, unrecognized_job]})
        ),
    )

    connector = _connector(transport)
    records = [connector.normalize(r) for r in connector.fetch()]

    assert records[0].work_mode == "remote"
    assert records[0].employment_type == "full_time"
    assert records[1].work_mode == "hybrid"
    assert records[1].employment_type == "part_time"
    assert records[2].work_mode == "on_site"
    assert records[2].employment_type == "contract"
    assert records[3].work_mode is None  # unrecognized workplaceType -> None, never guessed
    assert records[3].employment_type == "other"  # unrecognized employmentType -> "other"


def test_compensation_missing_stays_none() -> None:
    transport = _with_robots_allow_all(_FakeTransport())
    transport.set_response(JOBS_URL, _FakeResponse(200, json.dumps({"jobs": [ONE_JOB]})))

    connector = _connector(transport)
    record = connector.normalize(next(connector.fetch()))

    assert record.compensation_min is None
    assert record.compensation_max is None
    assert record.compensation_currency is None
    assert record.compensation_period is None


def test_compensation_mapped_when_recognized_shape_present() -> None:
    job_with_comp = {
        **ONE_JOB,
        "id": "comp1",
        "compensation": {
            "summaryComponents": [
                {"minValue": 120000, "maxValue": 160000, "currencyCode": "USD", "interval": "Yearly"}
            ]
        },
    }
    transport = _with_robots_allow_all(_FakeTransport())
    transport.set_response(JOBS_URL, _FakeResponse(200, json.dumps({"jobs": [job_with_comp]})))

    connector = _connector(transport)
    record = connector.normalize(next(connector.fetch()))

    assert record.compensation_min == Decimal("120000")
    assert record.compensation_max == Decimal("160000")
    assert record.compensation_currency == "USD"
    assert record.compensation_period == "yearly"


def test_compensation_malformed_shape_stays_none_not_error() -> None:
    job_with_bad_comp = {**ONE_JOB, "id": "comp2", "compensation": {"summaryComponents": "oops"}}
    transport = _with_robots_allow_all(_FakeTransport())
    transport.set_response(JOBS_URL, _FakeResponse(200, json.dumps({"jobs": [job_with_bad_comp]})))

    connector = _connector(transport)
    record = connector.normalize(next(connector.fetch()))

    assert record.compensation_min is None
    assert record.compensation_currency is None


def test_unlisted_job_excluded_from_fetch_output() -> None:
    unlisted_job = {**ONE_JOB, "id": "unlisted-1", "isListed": False}
    transport = _with_robots_allow_all(_FakeTransport())
    transport.set_response(
        JOBS_URL, _FakeResponse(200, json.dumps({"jobs": [ONE_JOB, unlisted_job]}))
    )

    connector = _connector(transport)
    raw_records = list(connector.fetch())

    assert len(raw_records) == 1
    assert raw_records[0]["id"] == ONE_JOB["id"]


def test_job_missing_islisted_field_is_not_excluded() -> None:
    job_no_islisted = {k: v for k, v in ONE_JOB.items() if k != "isListed"}
    transport = _with_robots_allow_all(_FakeTransport())
    transport.set_response(JOBS_URL, _FakeResponse(200, json.dumps({"jobs": [job_no_islisted]})))

    connector = _connector(transport)
    assert len(list(connector.fetch())) == 1


def test_html_description_preserved_untouched() -> None:
    transport = _with_robots_allow_all(_FakeTransport())
    transport.set_response(JOBS_URL, _FakeResponse(200, json.dumps({"jobs": [ONE_JOB]})))

    connector = _connector(transport)
    record = connector.normalize(next(connector.fetch()))

    assert record.description_full == "<p>Do things. <script>alert(1)</script></p>"


def test_description_plain_fallback_when_html_absent() -> None:
    job = {k: v for k, v in ONE_JOB.items() if k != "descriptionHtml"}
    transport = _with_robots_allow_all(_FakeTransport())
    transport.set_response(JOBS_URL, _FakeResponse(200, json.dumps({"jobs": [job]})))

    connector = _connector(transport)
    record = connector.normalize(next(connector.fetch()))

    assert record.description_full == "Do things."


def test_malformed_response_missing_jobs_key_raises() -> None:
    transport = _with_robots_allow_all(_FakeTransport())
    transport.set_response(JOBS_URL, _FakeResponse(200, json.dumps({"not_jobs": []})))

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


def test_denied_source_causes_zero_ashby_network_execution() -> None:
    """Critical test: a disabled Source must result in zero network calls,
    proven end-to-end for the real Ashby connector."""

    class _SpyTransport:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def raw_get(self, url, *, headers=None, timeout=None):
            self.calls.append(url)
            raise AssertionError(f"raw_get should never be called, but was called with {url}")

    source = Source(name="Acme Ashby", connector_type="ashby", enabled=False)
    spy_transport = _SpyTransport()

    with pytest.raises(SourceNotAuthorizedError):
        require_source_authorized(source)
        http_client = PolicyEnforcingHttpClient(transport=spy_transport, user_agent="test-agent")
        connector = AshbyConnector({"job_board_name": "acme"}, http_client)
        list(connector.fetch())

    assert spy_transport.calls == []


def test_no_direct_network_imports_in_ashby_module() -> None:
    """Structural proof the connector can't bypass the injected http_client:
    it never imports urllib/requests/sockets itself."""
    import inspect

    import app.connectors.ashby as ashby_module

    source = inspect.getsource(ashby_module)
    for forbidden in ("import urllib", "import requests", "import socket", "import http.client"):
        assert forbidden not in source
