"""Registry tests for the connector framework (STORY-016). No live
infrastructure or network access required.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from pydantic import BaseModel

from app.connectors.base import BaseConnector, NormalizedJobRecord
from app.connectors.errors import DuplicateConnectorTypeError, UnknownConnectorTypeError
from app.connectors.registry import ConnectorRegistry, register_connector
from app.connectors.registry import registry as module_registry


class _EmptyConfig(BaseModel):
    pass


class _MinimalConnector(BaseConnector):
    connector_type = "minimal"
    config_model = _EmptyConfig

    def fetch(self) -> Iterator[dict[str, Any]]:
        return iter(())

    def normalize(self, raw_record: dict[str, Any]) -> NormalizedJobRecord:
        return NormalizedJobRecord(source_job_id=str(raw_record["id"]))


def test_register_and_get_round_trip() -> None:
    reg = ConnectorRegistry()
    reg.register("minimal", _MinimalConnector)
    assert reg.get("minimal") is _MinimalConnector
    assert reg.is_registered("minimal") is True


def test_duplicate_registration_raises() -> None:
    reg = ConnectorRegistry()
    reg.register("minimal", _MinimalConnector)
    with pytest.raises(DuplicateConnectorTypeError):
        reg.register("minimal", _MinimalConnector)


def test_unknown_connector_type_raises() -> None:
    reg = ConnectorRegistry()
    with pytest.raises(UnknownConnectorTypeError):
        reg.get("does-not-exist")
    assert reg.is_registered("does-not-exist") is False


@register_connector("decorator-test-connector")
class _DecoratedConnector(BaseConnector):
    config_model = _EmptyConfig

    def fetch(self) -> Iterator[dict[str, Any]]:
        return iter(())

    def normalize(self, raw_record: dict[str, Any]) -> NormalizedJobRecord:
        return NormalizedJobRecord(source_job_id=str(raw_record["id"]))


def test_register_connector_decorator_wires_into_module_singleton() -> None:
    assert module_registry.get("decorator-test-connector") is _DecoratedConnector
    assert _DecoratedConnector.connector_type == "decorator-test-connector"


def test_no_network_access_required() -> None:
    """The registry only stores classes -- nothing here touches sockets."""
    reg = ConnectorRegistry()
    reg.register("minimal", _MinimalConnector)
    connector_cls = reg.get("minimal")
    instance = connector_cls({}, http_client=None)  # type: ignore[arg-type]
    assert list(instance.fetch()) == []
