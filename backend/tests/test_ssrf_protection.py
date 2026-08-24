"""Tests for SSRF protection (STORY-046). No live infrastructure or real
DNS/network access required -- DNS resolution is injected via a fake
resolver (constructor parameter), and the "perform request over the wire"
step is overridden in a test subclass, while all real validation/redirect
logic in `SsrfSafeTransport` is genuinely exercised.
"""

from __future__ import annotations

import ipaddress
import socket

import pytest

from app.connectors.errors import ConnectorTransportError, SsrfRejectedError
from app.connectors.http_client import (
    SsrfSafeTransport,
    _BufferedResponse,
    _is_blocked_ip,
    resolve_and_validate_host,
)


# -- _is_blocked_ip -----------------------------------------------------


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",  # loopback
        "127.255.255.255",  # loopback range
        "10.0.0.1",  # RFC1918
        "172.16.0.1",  # RFC1918
        "172.31.255.255",  # RFC1918
        "192.168.1.1",  # RFC1918
        "169.254.0.1",  # link-local
        "169.254.169.254",  # cloud metadata -- covered by link-local, no special rule
        "224.0.0.1",  # multicast
        "0.0.0.0",  # unspecified
        "::1",  # IPv6 loopback
        "fc00::1",  # IPv6 unique-local
        "fe80::1",  # IPv6 link-local
        "ff02::1",  # IPv6 multicast
        "::",  # IPv6 unspecified
    ],
)
def test_blocked_ips_are_blocked(ip: str) -> None:
    assert _is_blocked_ip(ipaddress.ip_address(ip)) is True


@pytest.mark.parametrize("ip", ["8.8.8.8", "1.1.1.1", "93.184.216.34", "2606:4700:4700::1111"])
def test_public_ips_are_not_blocked(ip: str) -> None:
    assert _is_blocked_ip(ipaddress.ip_address(ip)) is False


# -- resolve_and_validate_host: literal IPs (no resolver call) -----------


def _fail_if_called(hostname: str, port: int) -> list[str]:
    raise AssertionError(f"resolver should never be called for a literal IP, got {hostname!r}")


def test_literal_public_ip_allowed_without_dns_call() -> None:
    result = resolve_and_validate_host("93.184.216.34", 443, resolver=_fail_if_called)
    assert result == "93.184.216.34"


def test_literal_private_ip_rejected_without_dns_call() -> None:
    with pytest.raises(SsrfRejectedError):
        resolve_and_validate_host("127.0.0.1", 443, resolver=_fail_if_called)


def test_literal_metadata_ip_rejected_without_dns_call() -> None:
    with pytest.raises(SsrfRejectedError):
        resolve_and_validate_host("169.254.169.254", 443, resolver=_fail_if_called)


# -- resolve_and_validate_host: hostname resolution (fake resolver) ------


def test_hostname_resolving_only_public_is_allowed() -> None:
    result = resolve_and_validate_host("public.invalid", 443, resolver=lambda h, p: ["93.184.216.34"])
    assert result == "93.184.216.34"


def test_hostname_resolving_only_private_is_rejected() -> None:
    with pytest.raises(SsrfRejectedError):
        resolve_and_validate_host("internal.invalid", 443, resolver=lambda h, p: ["10.0.0.5"])


def test_hostname_resolving_to_mixed_public_and_private_is_rejected() -> None:
    """A host advertising both a public and a private address is treated
    as untrustworthy, not partially trusted."""
    with pytest.raises(SsrfRejectedError):
        resolve_and_validate_host(
            "mixed.invalid", 443, resolver=lambda h, p: ["93.184.216.34", "10.0.0.5"]
        )


def test_dns_failure_raises_connector_transport_error_not_ssrf_error() -> None:
    def _failing_resolver(hostname: str, port: int) -> list[str]:
        raise ConnectorTransportError(f"DNS resolution failed for {hostname}: boom")

    with pytest.raises(ConnectorTransportError):
        resolve_and_validate_host("nonexistent.invalid", 443, resolver=_failing_resolver)


# -- Scheme validation ----------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.invalid/",
        "gopher://example.invalid/",
        "data:text/plain,hello",
        "javascript:alert(1)",
    ],
)
def test_disallowed_scheme_rejected_before_any_resolution(url: str) -> None:
    transport = SsrfSafeTransport(resolver=_fail_if_called)
    with pytest.raises(SsrfRejectedError):
        transport.raw_get(url)


# -- Redirect revalidation, via a test subclass overriding only the wire step --


class _FakeSsrfSafeTransport(SsrfSafeTransport):
    """Overrides only the 'perform request over the wire' step -- all real
    scheme/DNS/redirect-revalidation logic from SsrfSafeTransport is
    genuinely exercised, only sockets are avoided."""

    def __init__(self, *, resolver, responses: dict[str, _BufferedResponse]) -> None:
        super().__init__(resolver=resolver)
        self._responses = responses
        self.performed_requests: list[str] = []

    def _perform_request(self, parsed, validated_ip, port, headers, timeout):
        url = parsed.geturl()
        self.performed_requests.append(url)
        try:
            return self._responses[url]
        except KeyError:
            raise AssertionError(f"No canned response for {url}") from None


def _resolver_for(mapping: dict[str, list[str]]):
    def _resolve(hostname: str, port: int) -> list[str]:
        try:
            return mapping[hostname]
        except KeyError:
            raise AssertionError(f"No resolver entry for {hostname!r}") from None

    return _resolve


def test_safe_public_redirect_allowed() -> None:
    resolver = _resolver_for({"a.invalid": ["93.184.216.1"], "b.invalid": ["93.184.216.2"]})
    responses = {
        "http://a.invalid/start": _BufferedResponse(302, {"Location": "http://b.invalid/final"}, b""),
        "http://b.invalid/final": _BufferedResponse(200, {}, b"ok"),
    }
    transport = _FakeSsrfSafeTransport(resolver=resolver, responses=responses)

    response = transport.raw_get("http://a.invalid/start")

    assert response.status_code == 200
    assert transport.performed_requests == ["http://a.invalid/start", "http://b.invalid/final"]


def test_redirect_to_hostname_resolving_to_private_ip_blocked() -> None:
    """Critical test: the final hop's request-performing step is NEVER
    invoked when the redirect target is unsafe -- zero network execution
    for the rejected destination."""
    resolver = _resolver_for({"public.invalid": ["93.184.216.1"], "internal.invalid": ["10.0.0.5"]})
    responses = {
        "http://public.invalid/start": _BufferedResponse(
            302, {"Location": "http://internal.invalid/secret"}, b""
        ),
    }
    transport = _FakeSsrfSafeTransport(resolver=resolver, responses=responses)

    with pytest.raises(SsrfRejectedError):
        transport.raw_get("http://public.invalid/start")

    assert transport.performed_requests == ["http://public.invalid/start"]
    assert "http://internal.invalid/secret" not in transport.performed_requests


def test_redirect_to_localhost_hostname_blocked() -> None:
    resolver = _resolver_for({"public.invalid": ["93.184.216.1"], "localhost": ["127.0.0.1"]})
    responses = {
        "http://public.invalid/start": _BufferedResponse(302, {"Location": "http://localhost/admin"}, b""),
    }
    transport = _FakeSsrfSafeTransport(resolver=resolver, responses=responses)

    with pytest.raises(SsrfRejectedError):
        transport.raw_get("http://public.invalid/start")

    assert "http://localhost/admin" not in transport.performed_requests


def test_redirect_loop_exhausts_budget_and_raises() -> None:
    resolver = _resolver_for({"a.invalid": ["93.184.216.1"], "b.invalid": ["93.184.216.2"]})
    responses = {
        "http://a.invalid/x": _BufferedResponse(302, {"Location": "http://b.invalid/x"}, b""),
        "http://b.invalid/x": _BufferedResponse(302, {"Location": "http://a.invalid/x"}, b""),
    }
    transport = _FakeSsrfSafeTransport(resolver=resolver, responses=responses)

    with pytest.raises(SsrfRejectedError):
        transport.raw_get("http://a.invalid/x")

    # Bounded -- did not loop forever.
    assert len(transport.performed_requests) <= 7


def test_redirect_scheme_change_to_disallowed_scheme_blocked() -> None:
    resolver = _resolver_for({"public.invalid": ["93.184.216.1"]})
    responses = {
        "http://public.invalid/start": _BufferedResponse(302, {"Location": "file:///etc/passwd"}, b""),
    }
    transport = _FakeSsrfSafeTransport(resolver=resolver, responses=responses)

    with pytest.raises(SsrfRejectedError):
        transport.raw_get("http://public.invalid/start")


# -- Regression: real socket.getaddrinfo used by the real default resolver --


def test_default_resolver_uses_real_getaddrinfo(monkeypatch) -> None:
    calls = []

    def _fake_getaddrinfo(host, port, *args, **kwargs):
        calls.append((host, port))
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.1", port))]

    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo)

    result = resolve_and_validate_host("public.invalid", 443)

    assert result == "93.184.216.1"
    assert calls == [("public.invalid", 443)]
