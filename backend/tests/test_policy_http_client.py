"""Tests for PolicyEnforcingHttpClient (STORY-017). No live infrastructure
or network access required -- everything goes through a FakeTransport.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from typing import Any

import pytest
from pydantic import BaseModel

from app.connectors.base import BaseConnector, HttpResponse, NormalizedJobRecord
from app.connectors.errors import (
    AntiBotChallengeDetectedError,
    ConnectorAuthError,
    ConnectorRateLimitedError,
    ConnectorTransportError,
    RobotsDisallowedError,
)
from app.connectors.http_client import PolicyEnforcingHttpClient


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
    """Maps exact URLs to canned responses (or a raised exception). Records
    every URL requested for call-count/order assertions."""

    def __init__(self) -> None:
        self.responses: dict[str, HttpResponse] = {}
        self.exceptions: dict[str, Exception] = {}
        self.requested_urls: list[str] = []

    def set_response(self, url: str, response: HttpResponse) -> None:
        self.responses[url] = response

    def set_exception(self, url: str, exc: Exception) -> None:
        self.exceptions[url] = exc

    def raw_get(self, url, *, headers=None, timeout=None) -> HttpResponse:
        self.requested_urls.append(url)
        if url in self.exceptions:
            raise self.exceptions[url]
        try:
            return self.responses[url]
        except KeyError:
            raise AssertionError(f"No canned response for {url}") from None


ROBOTS_ALLOW_ALL = "User-agent: *\nDisallow:\n"
ROBOTS_DISALLOW_JOBS = "User-agent: *\nDisallow: /jobs\n"
ROBOTS_WITH_CRAWL_DELAY = "User-agent: *\nDisallow:\nCrawl-delay: 5\n"


def _client(transport: _FakeTransport, user_agent: str = "test-agent") -> PolicyEnforcingHttpClient:
    return PolicyEnforcingHttpClient(transport=transport, user_agent=user_agent)


def test_robots_allows_path_request_proceeds() -> None:
    transport = _FakeTransport()
    transport.set_response("https://example.invalid/robots.txt", _FakeResponse(200, ROBOTS_ALLOW_ALL))
    transport.set_response("https://example.invalid/jobs", _FakeResponse(200, "[]"))

    response = _client(transport).get("https://example.invalid/jobs")

    assert response.status_code == 200
    assert transport.requested_urls == [
        "https://example.invalid/robots.txt",
        "https://example.invalid/jobs",
    ]


def test_robots_disallows_path_raises_and_target_never_requested() -> None:
    transport = _FakeTransport()
    transport.set_response("https://example.invalid/robots.txt", _FakeResponse(200, ROBOTS_DISALLOW_JOBS))

    with pytest.raises(RobotsDisallowedError):
        _client(transport).get("https://example.invalid/jobs")

    assert transport.requested_urls == ["https://example.invalid/robots.txt"]


def test_robots_404_treated_as_allow_all() -> None:
    transport = _FakeTransport()
    transport.set_response("https://example.invalid/robots.txt", _FakeResponse(404, ""))
    transport.set_response("https://example.invalid/jobs", _FakeResponse(200, "[]"))

    response = _client(transport).get("https://example.invalid/jobs")
    assert response.status_code == 200


def test_robots_5xx_fails_closed() -> None:
    transport = _FakeTransport()
    transport.set_response("https://example.invalid/robots.txt", _FakeResponse(503, ""))

    with pytest.raises(RobotsDisallowedError):
        _client(transport).get("https://example.invalid/jobs")


def test_robots_transport_failure_fails_closed() -> None:
    transport = _FakeTransport()
    transport.set_exception("https://example.invalid/robots.txt", ConnectorTransportError("boom"))

    with pytest.raises(RobotsDisallowedError):
        _client(transport).get("https://example.invalid/jobs")


def test_crawl_delay_is_honored(monkeypatch) -> None:
    transport = _FakeTransport()
    transport.set_response(
        "https://example.invalid/robots.txt", _FakeResponse(200, ROBOTS_WITH_CRAWL_DELAY)
    )
    transport.set_response("https://example.invalid/jobs/1", _FakeResponse(200, "[]"))
    transport.set_response("https://example.invalid/jobs/2", _FakeResponse(200, "[]"))

    slept: list[float] = []
    monkeypatch.setattr(time, "sleep", lambda seconds: slept.append(seconds))

    client = _client(transport)
    client.get("https://example.invalid/jobs/1")
    client.get("https://example.invalid/jobs/2")

    assert slept, "expected a crawl-delay sleep for a same-host request"
    assert slept[0] > 0


def test_401_raises_connector_auth_error() -> None:
    transport = _FakeTransport()
    transport.set_response("https://example.invalid/robots.txt", _FakeResponse(404, ""))
    transport.set_response("https://example.invalid/jobs", _FakeResponse(401, "unauthorized"))

    with pytest.raises(ConnectorAuthError):
        _client(transport).get("https://example.invalid/jobs")


def test_403_raises_connector_auth_error() -> None:
    transport = _FakeTransport()
    transport.set_response("https://example.invalid/robots.txt", _FakeResponse(404, ""))
    transport.set_response("https://example.invalid/jobs", _FakeResponse(403, "forbidden"))

    with pytest.raises(ConnectorAuthError):
        _client(transport).get("https://example.invalid/jobs")


def test_429_raises_connector_rate_limited_error_with_no_retry() -> None:
    transport = _FakeTransport()
    transport.set_response("https://example.invalid/robots.txt", _FakeResponse(404, ""))
    transport.set_response("https://example.invalid/jobs", _FakeResponse(429, "slow down"))

    with pytest.raises(ConnectorRateLimitedError):
        _client(transport).get("https://example.invalid/jobs")

    assert transport.requested_urls.count("https://example.invalid/jobs") == 1


def test_challenge_marker_raises_anti_bot_challenge_error() -> None:
    transport = _FakeTransport()
    transport.set_response("https://example.invalid/robots.txt", _FakeResponse(404, ""))
    transport.set_response(
        "https://example.invalid/jobs",
        _FakeResponse(503, "please wait", headers={"cf-mitigated": "challenge"}),
    )

    with pytest.raises(AntiBotChallengeDetectedError):
        _client(transport).get("https://example.invalid/jobs")


def test_identifying_user_agent_sent_on_every_request() -> None:
    transport = _FakeTransport()
    transport.set_response("https://example.invalid/robots.txt", _FakeResponse(404, ""))
    transport.set_response("https://example.invalid/jobs", _FakeResponse(200, "[]"))

    sent_headers: list[dict] = []
    original_raw_get = transport.raw_get

    def _spying_raw_get(url, *, headers=None, timeout=None):
        sent_headers.append(headers or {})
        return original_raw_get(url, headers=headers, timeout=timeout)

    transport.raw_get = _spying_raw_get  # type: ignore[method-assign]

    _client(transport, user_agent="MyBot/9.9").get("https://example.invalid/jobs")

    assert sent_headers, "expected at least one request"
    assert all(h.get("User-Agent") == "MyBot/9.9" for h in sent_headers)


def test_no_secrets_or_headers_leak_into_raised_errors() -> None:
    transport = _FakeTransport()
    transport.set_response("https://example.invalid/robots.txt", _FakeResponse(404, ""))
    transport.set_response("https://example.invalid/jobs", _FakeResponse(401, "unauthorized"))

    with pytest.raises(ConnectorAuthError) as excinfo:
        _client(transport).get(
            "https://example.invalid/jobs", headers={"Authorization": "Bearer super-secret-token"}
        )

    assert "super-secret-token" not in str(excinfo.value)
    assert "super-secret-token" not in str(excinfo.value.context)


class _EmptyConfig(BaseModel):
    pass


class _PolicyFakeConnector(BaseConnector):
    connector_type = "policy-fake"
    config_model = _EmptyConfig

    def fetch(self) -> Iterator[dict[str, Any]]:
        response = self.http_client.get("https://example.invalid/jobs")
        yield from response.json()

    def normalize(self, raw_record: dict[str, Any]) -> NormalizedJobRecord:
        return NormalizedJobRecord(source_job_id=str(raw_record["id"]))


def test_fake_connector_works_unchanged_with_policy_enforcing_client() -> None:
    """Proves PolicyEnforcingHttpClient is a drop-in HttpClient -- STORY-016's
    connector contract needs no changes to use it."""
    transport = _FakeTransport()
    transport.set_response("https://example.invalid/robots.txt", _FakeResponse(404, ""))
    transport.set_response("https://example.invalid/jobs", _FakeResponse(200, '[{"id": "1"}]'))

    connector = _PolicyFakeConnector({}, _client(transport))
    records = [connector.normalize(r) for r in connector.fetch()]

    assert records[0].source_job_id == "1"
