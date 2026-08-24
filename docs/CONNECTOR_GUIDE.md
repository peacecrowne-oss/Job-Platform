# Connector Authoring Guide

This document implements **STORY-020 — Future Connector Extensibility
Guidelines** from [`requirement.md`](../requirement.md). It is referenced
from the top-level [`README.md`](../README.md).

It documents the *actual* connector architecture as implemented by
STORY-016 (framework), STORY-017 (lawful-access policy), STORY-046 (SSRF
protection), STORY-022 (retry handling), STORY-025 (exact deduplication),
STORY-027 (data-quality validation), and the two real connectors,
STORY-018 (Greenhouse) and STORY-019 (Ashby) — not a hypothetical design.
Every class, module, and function name below refers to real code in this
repository; where useful, the guide points at `greenhouse.py`/`ashby.py`
as literal worked examples rather than repeating their content.

Building a new connector without reading this guide first is not
recommended — every step below exists because an earlier Story already
solved it, and skipping it means re-solving (or worse, silently
under-solving) the same problem.

## 1. Source Onboarding Checklist

Fill this out **before writing any code**. If a source fails any check
below, it must not be onboarded — no workaround, no exception.

- [ ] **Documented, public, authorized access method** — does the source
  publish an official API/feed intended for this kind of consumption
  (like Greenhouse's Job Board API or Ashby's Job Board API), not an
  internal/admin endpoint you'd have to reverse-engineer?
- [ ] **Authorization basis** — is this genuinely public and
  unauthenticated? This platform's current HTTP client
  (`PolicyEnforcingHttpClient`) has **no credential-handling path at
  all** — a source requiring auth is out of scope until a future Story
  extends the client. Do not build around this by embedding credentials
  in connector code.
- [ ] **Terms of Service / access restrictions** — does fetching this
  data via this method violate the source's stated terms? If yes, stop.
- [ ] **robots.txt applicability** — `PolicyEnforcingHttpClient` already
  enforces this automatically for every request (see §5) — confirm the
  source's robots.txt doesn't disallow the paths you intend to fetch.
- [ ] **Authentication requirements** — none supported today (see above).
- [ ] **Rate limits** — does the source publish a `Crawl-delay` in
  robots.txt, or documented request limits? `PolicyEnforcingHttpClient`
  already honors `Crawl-delay` automatically; document anything beyond
  that in your connector's own docstring.
- [ ] **Pagination** — does the list endpoint page, or return every
  result in one response (like both Greenhouse's and Ashby's do today)?
  If it paginates, your `fetch()` handles that internally — STORY-016
  deliberately left pagination out of the shared interface since styles
  vary too much to standardize.
- [ ] **Stable job identifier** — does the source guarantee an ID stays
  the same across refreshes of the same posting? This becomes
  `source_job_id`, the literal identity key STORY-025's `upsert_job()`
  relies on (`(source, source_job_id)` uniqueness).
- [ ] **Freshness / removal semantics** — does the source explicitly
  signal a closed posting, or only stop returning it? (Informational only
  today — STORY-028, freshness tracking, isn't built yet.)
- [ ] **Application URL vs. source URL** — does the source expose a
  distinct "apply here" URL (like Ashby's `applyUrl`), or only one URL
  that serves both purposes (like Greenhouse's `absolute_url`)? Don't
  assume one pattern generalizes to a new source.
- [ ] **Available structured fields** — which canonical fields
  (`work_mode`, `employment_type`, `seniority`, `department`,
  compensation, etc.) does this source *actually* provide? Greenhouse
  provides almost none of these; Ashby provides `workplaceType`/
  `employmentType`/compensation. Check the real payload, don't assume.
- [ ] **Compensation support** — structured, free-text, or absent
  entirely? Most sources won't have it — that's normal, not a bug (see §7).
- [ ] **Public vs. unlisted semantics** — does the public endpoint already
  filter out unlisted/draft postings, or does your connector need its own
  defensive filter (like Ashby's `isListed` check)? When in doubt, filter
  defensively even if you believe the endpoint already does.
- [ ] **Testability** — can a complete test suite be built using only a
  fake, in-memory HTTP transport, with zero real network access? If a
  source's API can't be meaningfully faked, that's a red flag.
- [ ] **Monitoring considerations** — forward-looking only; STORY-023
  (failure isolation) and STORY-024 (source health) aren't built yet, so
  there's nothing to wire up today. Note anything source-specific that a
  future monitoring Story should know about.

## 2. The Real Sequence

1. **Create the connector module** — `backend/app/connectors/<name>.py`.
   Follow `greenhouse.py`'s or `ashby.py`'s file layout exactly: a config
   model, helper functions for field mapping, then the connector class.

2. **Define connector configuration** — a `pydantic.BaseModel` subclass.
   Minimum shape, following `GreenhouseConnectorConfig`'s pattern:

   ```python
   class ExampleConnectorConfig(BaseModel):
       board_identifier: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_-]+$")
       api_base_url: str = "https://api.example-ats.com"  # real default; override is testability-only
   ```

   Restrict any public-identifier field to a safe character class (it
   ends up embedded in a URL path) — never accept an arbitrary string.
   Never add a field that holds a literal secret; if a future source
   genuinely needs one, that's a new capability for `BaseConnector`
   itself, not something to improvise per-connector.

3. **Register a connector type** — one decorator, nothing else:

   ```python
   from app.connectors.registry import register_connector

   @register_connector("example_ats")
   class ExampleConnector(BaseConnector):
       ...
   ```

   `register_connector()` sets `connector_type` on the class and adds it
   to the module-level `registry` singleton (`app.connectors.registry`).
   No other file needs to change — this is the literal mechanism behind
   STORY-016's own acceptance criterion.

4. **Implement the `BaseConnector` contract** — see §3 for the full
   reference; `config_model`, `fetch()`, and `normalize()` are the three
   things every connector must provide.

5. **Use the centralized HTTP client** — every network call is
   `self.http_client.get(url, params=..., headers=..., timeout=...)`.
   This is the *only* way to reach the network from a connector. Never
   import `urllib`, `requests`, `socket`, or `http.client` directly in a
   connector file — see §4 for why this is a hard rule, not a style
   preference.

6. **Passing lawful-source enforcement (automatic)** — every
   `self.http_client.get()` call already goes through
   `PolicyEnforcingHttpClient` (STORY-017): robots.txt is checked and
   cached per host, a documented `Crawl-delay` is honored, an identifying
   User-Agent is attached, and 401/403/429/recognized-challenge responses
   are refused automatically. **Nothing in your connector code needs to
   implement any of this.**

7. **Inheriting SSRF protection (automatic)** — `PolicyEnforcingHttpClient`'s
   transport, `SsrfSafeTransport` (STORY-046), validates every destination
   — the target URL, the robots.txt fetch, and every redirect hop —
   against loopback/private/link-local/multicast/reserved ranges before
   ever opening a socket, and connects to a pinned, pre-validated IP so
   there's no DNS-rebinding window. A connector cannot opt out of this,
   and must never try to (see §4).

8. **Returning normalized job records** — `normalize()` must return a
   `NormalizedJobRecord` (`app.connectors.base`). Only `source_job_id` is
   required; every other field defaults to `None`.

9. **Preserving unsupported/missing fields as `None`** — see §5 for the
   full normalization rules. The short version: never guess, always
   preserve the complete raw record in `raw_metadata`.

10. **Handling source errors** — raise the existing classes from
    `app.connectors.errors`; see §6 for the full taxonomy and
    retryability table. In practice, a connector's own code usually only
    ever raises `ConnectorConfigError` (e.g. "board not found") and
    `ConnectorSourceFormatError` (malformed/unexpected response) directly
    — everything else (auth, rate-limit, robots, SSRF, challenge
    detection) is already raised automatically before your `fetch()` body
    runs.

11. **Integrating retry behavior** — a connector does **not** implement
    retry loops itself. A caller wraps the operation:

    ```python
    from app.ingestion.retry import RetryPolicy, with_retry

    records = with_retry(
        lambda: list(connector.fetch()),
        policy=RetryPolicy(max_attempts=3, base_delay=1.0, max_delay=30.0),
    )
    ```

    Retryability is entirely determined by which exception type (and, for
    `ConnectorSourceFormatError`, `context["status_code"]`) your connector
    raises — get the error classification right and retry behavior falls
    out for free.

12. **Writing deterministic fixture/fake-transport tests** — see §7 for
    the full required suite. The short version: copy
    `test_greenhouse_connector.py`'s or `test_ashby_connector.py`'s
    pattern — a local `_FakeTransport`/`_FakeResponse`, wrapped in a
    **real** `PolicyEnforcingHttpClient` (never a bypassed shortcut), so
    policy/robots/SSRF logic is genuinely exercised with zero real network
    access.

13. **Optional lawful live validation** — a single, manual, read-only
    request against the source's real public endpoint, run once during
    implementation, never committed as a `pytest` test, never a CI
    dependency, and only after separate explicit approval — the exact
    pattern STORY-018/019 both used.

14. **Updating documentation/progress** — add the new connector to
    `README.md`'s architecture summary, repository-structure listing, and
    Tests section, and to `progress.md`, matching every prior connector
    Story's own closing steps.

## 3. Connector Contract Reference

Full source of truth: `backend/app/connectors/base.py`. Summarized here,
not duplicated:

- **`connector_type: ClassVar[str]`** — set automatically by
  `@register_connector(...)`.
- **`config_model: ClassVar[type[BaseModel]]`** — your pydantic config
  class; validated automatically in `__init__`.
- **`__init__(self, config: dict[str, Any], http_client: HttpClient)`** —
  inherited, not overridden. Invalid config raises `ConnectorConfigError`
  before `http_client` is even touched.
- **`fetch(self) -> Iterator[dict[str, Any]]`** *(abstract, must
  implement)* — yields raw records from the source, one dict per
  posting. Handles pagination internally if the source paginates.
- **`normalize(self, raw_record: dict[str, Any]) -> NormalizedJobRecord`**
  *(abstract, must implement)* — converts one raw record into the
  canonical shape.
- **`validate(self, record: NormalizedJobRecord) -> bool`** *(has a
  working default: `bool(record.source_job_id)`)* — override only for
  connector-specific structural checks; this is **not** the same thing as
  STORY-027's `validate_record()` (§8), which is a separate, later,
  cross-connector data-quality gate.

**`NormalizedJobRecord`** (pydantic model, `app.connectors.base`) — only
`source_job_id` is required:

```
source_job_id (required), job_title, company_name, source_url,
description_full, responsibilities, requirements, preferred_requirements,
qualifications, skills, skills_raw, location_raw, location_city,
location_region, location_country, work_mode, employment_type, seniority,
department, compensation_min, compensation_max, compensation_currency,
compensation_period, benefits, posting_date, closing_date, application_url,
source_updated_at, raw_metadata
```

**`HttpClient`/`HttpResponse`** (Protocols, `app.connectors.base`) — your
connector only ever calls `self.http_client.get(url, *, params=None,
headers=None, timeout=None) -> HttpResponse`, where `HttpResponse` has
`status_code`, `headers`, `.json()`, and `.text`.

## 4. Network and Security Rules

Every connector **must** reach the network exclusively through
`self.http_client`. This is a hard rule, not a preference — it's the
entire reason lawful-access enforcement and SSRF protection are automatic
in the first place (there is no other network path in this backend for a
connector to accidentally use).

**Explicitly prohibited, no exceptions:**

- Importing `urllib`, `requests`, `socket`, or `http.client` directly in a
  connector file.
- CAPTCHA solving or bypass.
- Anti-bot evasion of any kind.
- Authentication bypass.
- Scraping around access controls.
- Proxy rotation intended to evade restrictions.
- Disabling, working around, or "just this once" skipping SSRF checks.
- Silently ignoring a robots.txt disallow.

Every real connector proves compliance with a structural test — see
`test_no_direct_network_imports_in_greenhouse_module`/
`test_no_direct_network_imports_in_ashby_module` in their respective test
files. **Add the identical test for your own connector.**

## 5. Normalization Rules

- **`source_job_id`** must be a stable string across refreshes of the same
  posting — this is the literal deduplication identity key.
- **`source_url`/`application_url`** — map as the source actually provides
  them. Only use the same value for both if the source genuinely has no
  distinct apply URL (documented, source-specific — don't default to this).
- **Title, company, location, description** — mapped directly from the
  source, never inferred or reconstructed.
- **Structured fields** (`work_mode`, `employment_type`, `seniority`,
  `compensation_*`) — mapped only when the source gives an unambiguous,
  recognized value. An unrecognized value maps to `None` — except
  `employment_type`, where `"other"` is the intentional CHECK-constraint
  escape hatch for "the source gave something that doesn't fit our set"
  (see `Job.employment_type`'s own docstring) — never guessed or coerced.
- **`None` = absent.** `unknown` is **not** used anywhere in this schema
  (STORY-010's own established precedent) — do not introduce it.
- **Never extract structured fields from free-form description text**
  (responsibilities, requirements, skills, etc.) unless a separately
  approved Story explicitly owns that extraction.
- **`raw_metadata`** always preserves the complete raw record — even
  fields you don't map to a canonical column. This is the only place
  unmapped data survives for STORY-029's future use.

## 6. Error Taxonomy

Source of truth: `backend/app/connectors/errors.py` (classification) and
`backend/app/ingestion/retry.py`'s `is_retryable()` (retry behavior).

| Class | When to raise | Retryable (STORY-022)? |
|---|---|---|
| `ConnectorConfigError` | Invalid/missing config, or a source-reported "not found" (e.g. 404 on a board lookup) | No |
| `ConnectorTransportError` | Timeouts, connection errors, DNS resolution failure | Yes |
| `ConnectorSourceFormatError` | Malformed/unparseable response, unexpected schema, or a non-2xx/non-404 status code (include `status_code` in `context` when applicable) | Yes only if `context["status_code"] >= 500`; No otherwise |
| `ConnectorAuthError` | 401/403 — raised automatically by `PolicyEnforcingHttpClient`, never by connector code | No |
| `ConnectorRateLimitedError` | 429 — same, automatic | Yes, `Retry-After`-aware |
| `SourceNotAuthorizedError` | A disabled `Source` — raised by `require_source_authorized()`, not connector code | No |
| `RobotsDisallowedError` | robots.txt disallow — automatic | No |
| `AntiBotChallengeDetectedError` | A recognized challenge signature — automatic | No |
| `SsrfRejectedError` | A disallowed destination — automatic | No |

In practice, your connector's own code will usually only ever raise
`ConnectorConfigError` and `ConnectorSourceFormatError` directly — always
include `context={"status_code": ...}` on `ConnectorSourceFormatError`
when a status code is available, since that's what distinguishes a
retryable 5xx from a non-retryable parse error.

## 7. Testing Guidelines

Every connector's committed test suite must be fully deterministic and
require **zero** live network access. Copy
`test_greenhouse_connector.py`/`test_ashby_connector.py` as your literal
template. Minimum required coverage:

- Registration in `app.connectors.registry`.
- Valid config construction; invalid config raises `ConnectorConfigError`.
- Successful multi-record normalization.
- Missing optional fields all stay `None` (one comprehensive test).
- Empty result set — a successful empty run, not an error.
- Stable source-job identity across two `normalize()` calls on the same
  raw record.
- Malformed payload / missing required raw fields raise
  `ConnectorSourceFormatError`.
- Timeout/transport errors propagate as `ConnectorTransportError`.
- 4xx/5xx handling per §6's table.
- 429 propagates as `ConnectorRateLimitedError` — proving it isn't
  silently swallowed.
- Lawful-policy denial (robots.txt disallow) — target URL never requested.
- SSRF rejection where relevant to your connector's own config (e.g. a
  malicious `api_base_url` override).
- The critical zero-network-execution test: a disabled `Source` results in
  zero transport calls, end-to-end.
- The no-direct-network-imports structural check (§4).

Route every test through a **real** `PolicyEnforcingHttpClient` wrapping a
local `_FakeTransport` — never bypass the policy layer just to make a test
simpler; that would mean the test isn't actually proving compliance.

**Optional live validation** (separate from the committed suite):
- Requires separate, explicit approval before being performed.
- Must target a genuinely public, lawfully accessible source.
- Minimal — a single, read-only request.
- Never becomes a CI dependency; never added to the committed `pytest`
  suite.

## 8. Where Your Output Goes Next

Your connector's `normalize()` output is not persisted directly. The
existing downstream pieces (not something a new connector needs to call
itself, but useful context):

- **`app.validation.data_quality.validate_record()`** (STORY-027) — checks
  required fields (title, company, source_url) and sanity issues before
  anything is treated as usable.
- **`app.ingestion.dedup.upsert_job()`** (STORY-025) — persists a validated
  record, keyed on `(source, source_job_id)`.
- **`app.ingestion.retry.with_retry()`** (STORY-022) — wraps whichever of
  the above a future orchestrator calls.

No orchestrator wires these together yet — that's a future Story, not
something a new connector needs to build.
