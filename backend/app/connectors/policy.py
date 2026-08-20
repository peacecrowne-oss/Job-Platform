"""Pre-flight source-authorization gate (STORY-017).

`require_source_authorized` is a standalone, zero-I/O check. No
orchestrator exists yet to call it automatically -- the same situation
STORY-016 left its own connector interface in (nothing calls `fetch()`
end-to-end yet either). It's the intended first step of the flow: check
authorization, then -- only if authorized -- construct a connector with a
`PolicyEnforcingHttpClient`.

`Source.enabled` (STORY-014) is reused as the sole authorization gate; no
new `authorization_status`/reviewer/policy-reference columns were added --
see this Story's approved plan for why (no new database state was
justified by requirement.md's literal STORY-017 text).
"""

from __future__ import annotations

from app.connectors.errors import SourceNotAuthorizedError
from app.models.source import Source


def require_source_authorized(source: Source) -> None:
    """Raise `SourceNotAuthorizedError` if `source` is not eligible for
    connector execution. Currently: disabled sources are rejected; nothing
    else is checked here (robots.txt/response-code policy lives in
    `PolicyEnforcingHttpClient`, enforced per-request instead)."""
    if not source.enabled:
        raise SourceNotAuthorizedError(
            f"Source {source.name!r} is not authorized for connector execution (disabled)",
            context={"source_name": source.name},
        )
