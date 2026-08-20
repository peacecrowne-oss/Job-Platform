"""Connector registry (STORY-016): maps `connector_type -> connector class`.

Pure in-memory Python — no database migration is ever needed to add a new
connector type, since `Source.connector_type` is already a permissive
string with no CHECK/enum (STORY-014 decision). Testable without network
access: the registry only stores classes.
"""

from __future__ import annotations

from app.connectors.base import BaseConnector
from app.connectors.errors import DuplicateConnectorTypeError, UnknownConnectorTypeError


class ConnectorRegistry:
    def __init__(self) -> None:
        self._connectors: dict[str, type[BaseConnector]] = {}

    def register(self, connector_type: str, connector_cls: type[BaseConnector]) -> None:
        if connector_type in self._connectors:
            raise DuplicateConnectorTypeError(connector_type)
        self._connectors[connector_type] = connector_cls

    def get(self, connector_type: str) -> type[BaseConnector]:
        try:
            return self._connectors[connector_type]
        except KeyError:
            raise UnknownConnectorTypeError(connector_type) from None

    def is_registered(self, connector_type: str) -> bool:
        return connector_type in self._connectors


registry = ConnectorRegistry()


def register_connector(connector_type: str):
    """Class decorator: sets `connector_type` on the class and registers it
    into the module-level `registry` singleton."""

    def decorator(cls: type[BaseConnector]) -> type[BaseConnector]:
        cls.connector_type = connector_type
        registry.register(connector_type, cls)
        return cls

    return decorator
