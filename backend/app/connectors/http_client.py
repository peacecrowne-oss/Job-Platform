"""The policy-enforcing HTTP client (STORY-017) -- fills the `HttpClient`
Protocol seam STORY-016 deliberately left unimplemented.

`PolicyEnforcingHttpClient` is the only concrete `HttpClient` implementation
anywhere in this repository. A connector has no other way to reach the
network, which is what makes this enforcement structural rather than a
"please remember to call this" convention (same reasoning STORY-016 used
for its own interface).

`SsrfSafeTransport` (STORY-046; formerly `UrllibTransport` -- renamed because
its implementation fundamentally changed, see below) uses only the Python
standard library -- no new runtime dependency. It is the *only* place
anywhere in this backend that opens a socket (confirmed by grep across
`backend/app/` during STORY-046's planning), which is exactly what makes
SSRF protection here structural rather than a per-connector convention:
`PolicyEnforcingHttpClient`/`BaseConnector` give a connector no other way
to reach the network, so protecting this one transport protects every
connector automatically.

Every destination -- the real target URL, a robots.txt fetch, and every
redirect hop -- goes through the same pipeline: scheme check (http/https
only) -> DNS resolution (or literal-IP parse) -> reject if ANY resolved
address is loopback/private/link-local/multicast/reserved/unspecified
(this also covers cloud metadata addresses, e.g. 169.254.169.254, since
that's within the link-local range -- no separate metadata rule needed)
-> connect a raw socket *directly to the validated IP*, never re-resolving
the hostname. That last step is what actually closes the DNS-rebinding
window named in this Story's edge case: since there is only ever one DNS
lookup and the connection uses that exact result, there is no second
resolution for an attacker's DNS server to answer differently. This
required moving off `urllib.request.urlopen()` (which always re-resolves
internally, uncontrollably, and auto-follows redirects with no
revalidation) to `http.client.HTTPConnection`/`HTTPSConnection` subclasses
with an overridden `.connect()` -- still pure stdlib.

Policy enforced in `PolicyEnforcingHttpClient` (STORY-017, unmodified by
STORY-046), in order: robots.txt (fail-closed if undeterminable), a
documented crawl-delay if declared, an identifying User-Agent on every
request, and response-code refusal (401/403/429/known challenge markers) --
never a retry, never a workaround.
"""

from __future__ import annotations

import http.client
import ipaddress
import logging
import socket
import ssl
import time
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import urlencode, urljoin, urlsplit
from urllib.robotparser import RobotFileParser

from app.connectors.base import HttpResponse
from app.connectors.errors import (
    AntiBotChallengeDetectedError,
    ConnectorAuthError,
    ConnectorRateLimitedError,
    ConnectorTransportError,
    RobotsDisallowedError,
    SsrfRejectedError,
)

logger = logging.getLogger(__name__)

# Best-effort, documented anti-bot challenge signatures only -- not
# exhaustive of every anti-bot system. Matched as header-name substrings.
_CHALLENGE_HEADER_MARKERS = ("cf-mitigated", "cf-chl-bypass")


class _BufferedResponse:
    """A `Transport`/`HttpClient` response already read into memory."""

    def __init__(self, status_code: int, headers: Mapping[str, str], body: bytes) -> None:
        self.status_code = status_code
        self.headers = headers
        self._body = body

    def json(self) -> Any:
        import json

        return json.loads(self._body.decode("utf-8"))

    @property
    def text(self) -> str:
        return self._body.decode("utf-8", errors="replace")


class Transport:
    """Protocol for low-level, policy-free network access -- the only thing
    that actually opens a socket. `PolicyEnforcingHttpClient` wraps this
    with policy checks; tests inject a fake instead of `SsrfSafeTransport`."""

    def raw_get(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> HttpResponse:  # pragma: no cover - Protocol-style stub
        raise NotImplementedError


_ALLOWED_SCHEMES = ("http", "https")
_MAX_REDIRECTS = 5


def _is_blocked_ip(ip_obj: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        ip_obj.is_loopback
        or ip_obj.is_private
        or ip_obj.is_link_local
        or ip_obj.is_multicast
        or ip_obj.is_reserved
        or ip_obj.is_unspecified
    )


def _default_resolve(hostname: str, port: int) -> list[str]:
    """Real DNS resolution via the stdlib -- returns every A/AAAA result."""
    try:
        addr_info = socket.getaddrinfo(hostname, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise ConnectorTransportError(f"DNS resolution failed for {hostname}: {exc}") from exc
    return sorted({info[4][0] for info in addr_info})


def resolve_and_validate_host(
    hostname: str, port: int, *, resolver: Callable[[str, int], list[str]] = _default_resolve
) -> str:
    """Returns a single validated IP address string to connect to, or
    raises SsrfRejectedError/ConnectorTransportError. If ANY resolved
    address for the hostname is blocked, the whole hostname is rejected --
    a host advertising both a public and a private address is treated as
    untrustworthy, not partially trusted."""
    try:
        literal_ip = ipaddress.ip_address(hostname)
    except ValueError:
        literal_ip = None

    if literal_ip is not None:
        if _is_blocked_ip(literal_ip):
            raise SsrfRejectedError(
                f"Destination IP is not permitted: {hostname}",
                context={"reason": "blocked_ip", "host": hostname},
            )
        return str(literal_ip)

    resolved_ips = resolver(hostname, port)
    if not resolved_ips:
        raise ConnectorTransportError(f"DNS resolution returned no addresses for {hostname}")

    for ip_str in resolved_ips:
        ip_obj = ipaddress.ip_address(ip_str.split("%", 1)[0])  # strip IPv6 zone id if present
        if _is_blocked_ip(ip_obj):
            raise SsrfRejectedError(
                f"{hostname} resolves to a disallowed destination: {ip_str}",
                context={"reason": "blocked_ip", "host": hostname, "resolved_ip": ip_str},
            )

    return resolved_ips[0]


class _PinnedHTTPConnection(http.client.HTTPConnection):
    """An HTTPConnection that connects to a pre-validated literal IP
    instead of re-resolving `host` -- this is what closes the DNS-rebinding
    window: there is no second DNS lookup between validation and connect."""

    def __init__(self, host: str, port: int, pinned_ip: str, *, timeout: float | None) -> None:
        super().__init__(host, port, timeout=timeout)
        self._pinned_ip = pinned_ip

    def connect(self) -> None:
        self.sock = socket.create_connection((self._pinned_ip, self.port), self.timeout)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """As above, but wraps the socket in TLS using the *original* hostname
    for SNI/certificate validation -- connecting by IP without weakening
    certificate checking."""

    def __init__(
        self, host: str, port: int, pinned_ip: str, *, context: ssl.SSLContext, timeout: float | None
    ) -> None:
        super().__init__(host, port, context=context, timeout=timeout)
        self._pinned_ip = pinned_ip

    def connect(self) -> None:
        sock = socket.create_connection((self._pinned_ip, self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


class SsrfSafeTransport(Transport):
    """Real, stdlib-only network transport with SSRF protection built in
    (STORY-046). Every request -- including every redirect hop -- is fully
    revalidated from scratch; nothing is pre-approved.

    `resolver` is injectable so tests can supply deterministic DNS results
    without any real network access; production use (via
    `build_policy_enforcing_http_client()`) always uses the real resolver.
    """

    def __init__(self, *, resolver: Callable[[str, int], list[str]] = _default_resolve) -> None:
        self._resolver = resolver

    def raw_get(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> HttpResponse:
        return self._get_with_redirects(url, headers=headers, timeout=timeout, redirects_remaining=_MAX_REDIRECTS)

    def _get_with_redirects(
        self,
        url: str,
        *,
        headers: dict[str, str] | None,
        timeout: float | None,
        redirects_remaining: int,
    ) -> HttpResponse:
        parsed = urlsplit(url)
        if parsed.scheme not in _ALLOWED_SCHEMES:
            raise SsrfRejectedError(
                f"Scheme not permitted: {parsed.scheme!r}",
                context={"reason": "disallowed_scheme", "scheme": parsed.scheme},
            )

        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        validated_ip = resolve_and_validate_host(parsed.hostname, port, resolver=self._resolver)

        response = self._perform_request(parsed, validated_ip, port, headers, timeout)

        if response.status_code in (301, 302, 303, 307, 308):
            location = response.headers.get("Location") or response.headers.get("location")
            if not location:
                return response
            if redirects_remaining <= 0:
                raise SsrfRejectedError(
                    "Too many redirects", context={"reason": "too_many_redirects", "url": url}
                )
            next_url = urljoin(url, location)
            return self._get_with_redirects(
                next_url, headers=headers, timeout=timeout, redirects_remaining=redirects_remaining - 1
            )

        return response

    def _perform_request(
        self,
        parsed,
        validated_ip: str,
        port: int,
        headers: dict[str, str] | None,
        timeout: float | None,
    ) -> HttpResponse:
        """Connects to the pinned, already-validated IP and performs the
        HTTP request. Overridden in tests to avoid real sockets while
        keeping all validation/redirect logic above genuinely exercised."""
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"

        if parsed.scheme == "https":
            context = ssl.create_default_context()
            conn: http.client.HTTPConnection = _PinnedHTTPSConnection(
                parsed.hostname, port, validated_ip, context=context, timeout=timeout
            )
        else:
            conn = _PinnedHTTPConnection(parsed.hostname, port, validated_ip, timeout=timeout)

        try:
            conn.request("GET", path, headers=headers or {})
            response = conn.getresponse()
            body = response.read()
            return _BufferedResponse(response.status, dict(response.getheaders()), body)
        except OSError as exc:
            raise ConnectorTransportError(
                f"Transport error connecting to {parsed.hostname}: {exc}"
            ) from exc
        finally:
            conn.close()


class PolicyEnforcingHttpClient:
    """Implements STORY-016's `HttpClient` Protocol. One instance is meant
    to be injected per connector run, so its per-host robots.txt cache and
    crawl-delay bookkeeping naturally cover that connector's entire run
    (including pagination) without needing cross-run persistence -- a fresh
    instance per run also means a source's changed robots.txt takes effect
    "on the next run," per STORY-017's own edge case, with no cache
    invalidation logic needed.
    """

    def __init__(self, transport: Transport, user_agent: str) -> None:
        self._transport = transport
        self._user_agent = user_agent
        self._robots_cache: dict[str, RobotFileParser] = {}
        self._crawl_delay_cache: dict[str, float | None] = {}
        self._last_request_at: dict[str, float] = {}

    def get(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> HttpResponse:
        if params:
            separator = "&" if "?" in url else "?"
            url = f"{url}{separator}{urlencode(params)}"

        parsed = urlsplit(url)
        host = parsed.netloc

        self._enforce_robots(parsed.scheme, host, url)

        request_headers = {"User-Agent": self._user_agent, **(headers or {})}
        response = self._raw_get_throttled(url, host, headers=request_headers, timeout=timeout)

        self._enforce_response_policy(url, response)
        logger.info("policy: allowed request to %s (status=%s)", url, response.status_code)
        return response

    # -- robots.txt -----------------------------------------------------

    def _enforce_robots(self, scheme: str, host: str, url: str) -> None:
        parser = self._get_robots_parser(scheme, host)
        if not parser.can_fetch(self._user_agent, url):
            logger.warning("policy: robots.txt disallows %s", url)
            raise RobotsDisallowedError(f"robots.txt disallows fetching {url}")

    def _get_robots_parser(self, scheme: str, host: str) -> RobotFileParser:
        if host in self._robots_cache:
            return self._robots_cache[host]

        robots_url = f"{scheme}://{host}/robots.txt"
        parser = RobotFileParser()

        try:
            response = self._raw_get_throttled(
                robots_url, host, headers={"User-Agent": self._user_agent}, timeout=10
            )
        except ConnectorTransportError:
            # Can't determine robots.txt at all -- fail closed.
            parser.disallow_all = True
            self._robots_cache[host] = parser
            self._crawl_delay_cache[host] = None
            return parser

        if response.status_code == 404:
            parser.allow_all = True
        elif 200 <= response.status_code < 300:
            parser.parse(response.text.splitlines())
        elif 500 <= response.status_code < 600:
            # Source may be signaling "don't crawl me right now" -- fail closed.
            parser.disallow_all = True
        else:
            # Other 4xx on robots.txt itself (e.g. 401/403): no *readable*
            # robots.txt means no declared restriction exists to enforce.
            parser.allow_all = True

        self._robots_cache[host] = parser
        self._crawl_delay_cache[host] = parser.crawl_delay(self._user_agent)
        return parser

    # -- crawl-delay ("honors documented rate limits") -------------------

    def _raw_get_throttled(
        self, url: str, host: str, *, headers: dict[str, str], timeout: float | None
    ) -> HttpResponse:
        self._enforce_crawl_delay(host)
        response = self._transport.raw_get(url, headers=headers, timeout=timeout)
        self._last_request_at[host] = time.monotonic()
        return response

    def _enforce_crawl_delay(self, host: str) -> None:
        delay = self._crawl_delay_cache.get(host)
        if not delay:
            return
        last = self._last_request_at.get(host)
        if last is None:
            return
        remaining = delay - (time.monotonic() - last)
        if remaining > 0:
            time.sleep(remaining)

    # -- response-code refusal -------------------------------------------

    def _enforce_response_policy(self, url: str, response: HttpResponse) -> None:
        if response.status_code in (401, 403):
            logger.warning(
                "policy: auth required/forbidden for %s (status=%s)", url, response.status_code
            )
            raise ConnectorAuthError(
                f"Source rejected request as unauthenticated/unauthorized: {url}",
                context={"status_code": response.status_code},
            )
        if response.status_code == 429:
            logger.warning("policy: rate limited for %s", url)
            raise ConnectorRateLimitedError(
                f"Source rate-limited the request: {url}",
                context={
                    "status_code": response.status_code,
                    # STORY-022 reads this to honor Retry-After, bounded to
                    # its own policy's max_delay -- never an indefinite wait.
                    "retry_after": response.headers.get("Retry-After")
                    or response.headers.get("retry-after"),
                },
            )

        header_names = {name.lower() for name in response.headers}
        if any(marker in name for name in header_names for marker in _CHALLENGE_HEADER_MARKERS):
            logger.warning("policy: anti-bot challenge detected for %s", url)
            raise AntiBotChallengeDetectedError(
                f"Anti-bot challenge detected: {url}",
                context={"status_code": response.status_code},
            )


def build_policy_enforcing_http_client(user_agent: str | None = None) -> PolicyEnforcingHttpClient:
    """Factory for real (non-test) use: a `PolicyEnforcingHttpClient` backed
    by the real stdlib transport, defaulting to the app-wide configured
    User-Agent."""
    from app.config import get_settings

    return PolicyEnforcingHttpClient(
        transport=SsrfSafeTransport(),
        user_agent=user_agent or get_settings().ingestion_user_agent,
    )
