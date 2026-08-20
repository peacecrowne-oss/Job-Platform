"""The policy-enforcing HTTP client (STORY-017) -- fills the `HttpClient`
Protocol seam STORY-016 deliberately left unimplemented.

`PolicyEnforcingHttpClient` is the only concrete `HttpClient` implementation
anywhere in this repository. A connector has no other way to reach the
network, which is what makes this enforcement structural rather than a
"please remember to call this" convention (same reasoning STORY-016 used
for its own interface).

`UrllibTransport` uses only the Python standard library (`urllib`) -- no new
runtime dependency. It performs plain outbound requests with no IP-range/
allowlist awareness at all; that's deliberate. STORY-046 (SSRF Protection)
is expected to extend this exact transport, per its own technical note
("Enforced in the shared HTTP client from STORY-017"), not build a separate
one. See the module-level Security Boundary note in this Story's plan.

Policy enforced here, in order: robots.txt (fail-closed if undeterminable),
a documented crawl-delay if declared, an identifying User-Agent on every
request, and response-code refusal (401/403/429/known challenge markers) --
never a retry, never a workaround.
"""

from __future__ import annotations

import logging
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlencode, urlsplit
from urllib.robotparser import RobotFileParser

from app.connectors.base import HttpResponse
from app.connectors.errors import (
    AntiBotChallengeDetectedError,
    ConnectorAuthError,
    ConnectorRateLimitedError,
    ConnectorTransportError,
    RobotsDisallowedError,
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
    with policy checks; tests inject a fake instead of `UrllibTransport`."""

    def raw_get(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> HttpResponse:  # pragma: no cover - Protocol-style stub
        raise NotImplementedError


class UrllibTransport(Transport):
    """Real, stdlib-only network transport."""

    def raw_get(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> HttpResponse:
        request = urllib.request.Request(url, headers=headers or {}, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read()
                return _BufferedResponse(response.status, dict(response.headers), body)
        except urllib.error.HTTPError as exc:
            body = exc.read()
            return _BufferedResponse(exc.code, dict(exc.headers or {}), body)
        except urllib.error.URLError as exc:
            raise ConnectorTransportError(f"Transport error fetching {url}: {exc}") from exc


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
                context={"status_code": response.status_code},
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
        transport=UrllibTransport(),
        user_agent=user_agent or get_settings().ingestion_user_agent,
    )
