"""Source-authorization gate tests (STORY-017). No live infrastructure or
network access required.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from pydantic import BaseModel

from app.connectors.base import BaseConnector, NormalizedJobRecord
from app.connectors.errors import SourceNotAuthorizedError
from app.connectors.http_client import PolicyEnforcingHttpClient
from app.connectors.policy import require_source_authorized
from app.models.source import Source


class _SpyTransport:
    """Fails the test if .raw_get is ever called -- proves zero network
    execution when a source is denied."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def raw_get(self, url, *, headers=None, timeout=None):
        self.calls.append(url)
        raise AssertionError(f"Transport.raw_get should never be called, but was called with {url}")


class _EmptyConfig(BaseModel):
    pass


class _SpiedConnector(BaseConnector):
    connector_type = "spied"
    config_model = _EmptyConfig

    def fetch(self) -> Iterator[dict[str, Any]]:
        self.http_client.get("https://example.invalid/jobs")
        return iter(())

    def normalize(self, raw_record: dict[str, Any]) -> NormalizedJobRecord:
        return NormalizedJobRecord(source_job_id=str(raw_record["id"]))


def _make_source(*, enabled: bool) -> Source:
    return Source(name="Acme Greenhouse", connector_type="greenhouse", enabled=enabled)


def test_enabled_source_is_authorized() -> None:
    require_source_authorized(_make_source(enabled=True))  # does not raise


def test_disabled_source_raises_source_not_authorized_error() -> None:
    with pytest.raises(SourceNotAuthorizedError):
        require_source_authorized(_make_source(enabled=False))


def test_denied_source_causes_zero_connector_network_execution() -> None:
    """Critical test: proves the intended flow -- check authorization, then
    (only if authorized) construct a connector and fetch -- results in
    ZERO transport calls when the source is denied."""
    source = _make_source(enabled=False)
    spy_transport = _SpyTransport()

    with pytest.raises(SourceNotAuthorizedError):
        require_source_authorized(source)
        # Unreachable if the gate works -- nothing below should ever run.
        http_client = PolicyEnforcingHttpClient(transport=spy_transport, user_agent="test-agent")
        connector = _SpiedConnector({}, http_client)
        list(connector.fetch())

    assert spy_transport.calls == []
