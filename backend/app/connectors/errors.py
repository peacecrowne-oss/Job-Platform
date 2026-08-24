"""Structured connector errors (STORY-016; extended by STORY-017/STORY-046).

Five `ConnectorError` subtypes from STORY-016 match exactly the distinctions
requirement.md/STORY-022 name (config/transport/format/auth/rate-limit) —
deliberately not exhaustive of every possible HTTP failure mode. STORY-017
adds 3 more (`SourceNotAuthorizedError`/`RobotsDisallowedError`/
`AntiBotChallengeDetectedError`) — its 401/403/429 cases reuse
`ConnectorAuthError`/`ConnectorRateLimitedError` rather than duplicating
them. STORY-046 adds exactly 1 more (`SsrfRejectedError`) — DNS resolution
failure deliberately stays a `ConnectorTransportError`, not this, since
it's an ordinary connectivity problem, not a security-policy rejection.
No retry logic lives here (STORY-022's job); these exist so a future
retry/orchestration layer can pattern-match on failure type (e.g. retry
`ConnectorTransportError`/`ConnectorRateLimitedError`, don't retry
`ConnectorAuthError`/`ConnectorConfigError`/`SourceNotAuthorizedError`/
`RobotsDisallowedError`/`SsrfRejectedError`).

`context` is a plain dict for structured logging. Do not put raw config
values or credentials into it — no secret manager or redaction exists in
this repository to protect it.
"""

from __future__ import annotations

from typing import Any


class ConnectorError(Exception):
    """Base class for all connector execution errors."""

    def __init__(self, message: str, *, context: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.context = context or {}


class ConnectorConfigError(ConnectorError):
    """A connector's configuration is missing or invalid."""


class ConnectorTransportError(ConnectorError):
    """A network-level failure occurred while talking to the source."""


class ConnectorSourceFormatError(ConnectorError):
    """The source returned data the connector could not parse/normalize."""


class ConnectorAuthError(ConnectorError):
    """The source rejected the request as unauthenticated/unauthorized."""


class ConnectorRateLimitedError(ConnectorError):
    """The source responded with a rate-limit signal."""


class SourceNotAuthorizedError(ConnectorError):
    """A `Source` is not eligible for connector execution (STORY-017) —
    currently means `Source.enabled` is `False`. Raised before any
    connector is constructed or any network access occurs."""


class RobotsDisallowedError(ConnectorError):
    """robots.txt disallows the requested path for our user agent
    (STORY-017), or robots.txt itself could not be determined and policy
    fails closed. The target path is never requested in either case."""


class AntiBotChallengeDetectedError(ConnectorError):
    """A response matched a known, documented anti-bot/CAPTCHA challenge
    signature (STORY-017). Best-effort only — not exhaustive of every
    anti-bot system."""


class SsrfRejectedError(ConnectorError):
    """A destination was rejected by SSRF protection (STORY-046) —
    disallowed scheme, a private/loopback/link-local/reserved/multicast
    IP address (direct or via DNS resolution), or a redirect target
    failing the same checks. Deliberately distinct from
    `ConnectorTransportError`: this is a security-policy decision, not an
    ordinary connectivity failure (e.g. DNS resolution failure alone stays
    a `ConnectorTransportError`, not this). Never raised after a
    connection has been attempted -- the destination is always fully
    validated first."""


class ConnectorRegistryError(Exception):
    """Base class for connector-registry misuse errors."""


class UnknownConnectorTypeError(ConnectorRegistryError):
    """`ConnectorRegistry.get()` was called with an unregistered type."""

    def __init__(self, connector_type: str) -> None:
        super().__init__(f"Unknown connector type: {connector_type!r}")
        self.connector_type = connector_type


class DuplicateConnectorTypeError(ConnectorRegistryError):
    """`ConnectorRegistry.register()` was called with an already-used type."""

    def __init__(self, connector_type: str) -> None:
        super().__init__(f"Connector type already registered: {connector_type!r}")
        self.connector_type = connector_type
