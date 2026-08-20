# Requirements — Job Opportunity Aggregation & Job-Seeking Platform

This document is the **source of truth** for product and technical requirements. All
implementation work must trace back to a Story ID in this file. Nothing here has been
implemented yet — see `progress.md` for the current state of the repository.

## 0. Product Purpose

A platform that aggregates job listings from lawful, permitted, and legitimately public
sources (company career pages, ATS APIs/feeds, job boards, and other approved sources),
normalizes and deduplicates them, and helps job seekers search, filter, save, and assess
their fit against listings — without ever fabricating a user's credentials or experience.

## 1. Conventions

### 1.1 Story format

Each Story has a stable ID (`STORY-NNN`, zero-padded, never reused or renumbered once
assigned) and, where relevant:

- **Title**
- **User story / outcome** — who benefits and why
- **Functional requirements**
- **Technical / data / API notes**
- **Acceptance criteria**
- **Edge cases / error handling**
- **Dependencies** — other Story IDs
- **Priority** — P0 (blocking foundation) / P1 (core value) / P2 (important, not blocking) / P3 (later)

### 1.2 Source legality (binding constraint on every ingestion Story)

The platform must, at all times:

- ingest jobs **only** from lawful, permitted, authorized, or legitimately public company
  career pages, ATS APIs/feeds, job boards, and other approved sources;
- **never** bypass `robots.txt` restrictions where applicable, authentication, anti-bot
  protections, CAPTCHAs, paywalls, rate limits, Terms of Service, or access controls;
- treat this as a hard constraint, not a configurable option — any connector or feature
  that would require circumventing the above is out of scope, regardless of technical
  feasibility.

### 1.3 Truthfulness constraint (binding on all resume/fit features)

Resume-fit and resume-guidance features must never fabricate credentials, employers,
work history, education, certifications, achievements, technologies, metrics, or
qualifications. All suggestions must be traceable to user-provided, truthful input.

## 2. Canonical Job Listing Schema (referenced by multiple Stories)

At minimum, a normalized job record must support:

| Field | Notes |
|---|---|
| `source_url` | canonical URL of the listing at the source |
| `source` | connector/source identifier (e.g. `greenhouse`, `ashby`) |
| `source_job_id` | source's own identifier for the job |
| `company_name` | |
| `job_title` | |
| `description_full` | full raw/normalized job description |
| `responsibilities` | parsed section, if present |
| `requirements` | parsed section, if present |
| `preferred_requirements` | parsed section, if present |
| `qualifications` | parsed section, if present |
| `skills` | extracted/normalized list |
| `location` | free text + normalized components |
| `work_mode` | remote / hybrid / on-site |
| `employment_type` | full-time / part-time / contract / internship / etc. |
| `seniority` | e.g. entry / mid / senior / staff / lead |
| `department` | department/function |
| `compensation` | when available (range, currency, period) |
| `benefits` | when available |
| `posting_date` | |
| `closing_date` | |
| `application_url` | |
| `first_seen_at` | ingestion timestamp, first observed |
| `last_seen_at` | ingestion timestamp, most recently observed |
| `source_updated_at` | source's own last-modified signal, if available |

## 3. Stories

### Repository & Local Development Foundation

#### STORY-001 — Repository Structure & Monorepo Layout
- **User story**: As a contributor, I need a predictable top-level layout so I know where
  frontend, backend, docs, scripts, and CI config live.
- **Functional requirements**:
  - Top-level directories: `frontend/`, `backend/`, `backend/app/`, `backend/tests/`,
    `docs/`, `scripts/`, `.github/workflows/`.
  - No application code committed as part of this Story — structure only.
- **Technical notes**: Directories with no content yet may be represented with a
  `.gitkeep` placeholder or left to be created alongside their first real file.
- **Acceptance criteria**: All listed directories exist; nothing outside this Story's
  scope is added.
- **Edge cases**: N/A (structural Story).
- **Dependencies**: none.
- **Priority**: P0

#### STORY-002 — Git Conventions
- **User story**: As a contributor, I need agreed conventions for branching, commits,
  and PRs so history stays readable and bisectable.
- **Functional requirements**:
  - Trunk-based development on `main`; short-lived feature branches
    (`feat/`, `fix/`, `chore/`, `docs/` prefixes).
  - Conventional Commits style messages (`type(scope): summary`).
  - PRs required for `main`; no direct pushes to `main` once collaborators exist.
  - `.gitignore` maintained to cover Python, Node, environment files, build
    outputs, test artifacts, IDE files, logs, OS metadata, and local databases.
- **Technical notes**: Documented in `README.md` and/or `docs/CONTRIBUTING.md`.
- **Acceptance criteria**: Convention documented; referenced from `README.md`.
- **Edge cases**: Solo-maintainer period may relax PR requirement; document this
  explicitly rather than leaving it ambiguous.
- **Dependencies**: STORY-001.
- **Priority**: P0

#### STORY-003 — README
- **User story**: As a new contributor or reviewer, I need one document that explains
  what this project is and how to run it.
- **Functional requirements**: README must explain product purpose, planned
  architecture, local setup, Docker workflow, migrations, tests, connector principles,
  and lawful-source restrictions (see §1.2).
- **Technical notes**: Kept in sync as architecture decisions land; treated as living
  documentation, not a one-time artifact.
- **Acceptance criteria**: All required sections present and accurate as of the current
  repository state; no aspirational claims about unimplemented features stated as done.
- **Edge cases**: When a section describes a not-yet-built component, it must be
  labeled as planned, not implemented.
- **Dependencies**: STORY-001.
- **Priority**: P0

#### STORY-004 — Backend & Frontend Docker Images
- **User story**: As a developer or operator, I need reproducible container images for
  both services.
- **Functional requirements**: `Dockerfile` for `backend/` (Python/FastAPI) and
  `Dockerfile` for `frontend/` (Node/Next.js); multi-stage builds; non-root runtime user.
- **Technical notes**: Pin base image versions; separate build and runtime stages to
  keep images small.
- **Acceptance criteria**: Both images build successfully in isolation.
- **Edge cases**: Missing build args should fail fast with a clear error, not silently
  produce a broken image.
- **Dependencies**: STORY-001, STORY-012, STORY-013.
- **Priority**: P0

#### STORY-005 — Docker Compose Local Development Stack
- **User story**: As a developer, I need one command to bring up the full local stack.
- **Functional requirements**: `docker-compose.yml` defining `backend`, `frontend`,
  `postgres`, `redis`, and (once workers exist) a `worker` service; named volumes for
  Postgres data; healthchecks per service.
- **Technical notes**: Reads configuration from `.env` (see STORY-006); no secrets
  committed.
- **Acceptance criteria**: `docker compose up` brings up all services with passing
  healthchecks once dependent Stories exist.
- **Edge cases**: Service start-order dependencies (backend waiting on Postgres/Redis)
  must be handled via healthchecks, not fixed sleeps.
- **Dependencies**: STORY-004.
- **Priority**: P0

#### STORY-006 — Environment Variable Management
- **User story**: As a developer, I need to know every configuration variable the
  system uses without needing real credentials.
- **Functional requirements**: `.env.example` at repo root listing every variable name
  used by backend and frontend, with safe placeholder or default values only; no real
  secrets, keys, or credentials ever committed.
- **Technical notes**: Backend reads config via a typed settings object (e.g. Pydantic
  `BaseSettings`); frontend reads via Next.js environment variable conventions
  (`NEXT_PUBLIC_*` for browser-exposed values only).
- **Acceptance criteria**: `.env.example` covers every variable referenced in
  `docker-compose.yml` and application config; `.env` is git-ignored.
- **Edge cases**: Values that must differ between local/staging/prod are documented as
  such, not hardcoded.
- **Dependencies**: STORY-001.
- **Priority**: P0

### Data Layer Foundation

#### STORY-007 — PostgreSQL Provisioning & Configuration
- **User story**: As the system, I need a durable relational store for jobs, companies,
  users, and ingestion metadata.
- **Functional requirements**: Postgres service in Docker Compose; version pinned;
  connection managed via SQLAlchemy engine/session in backend.
- **Technical notes**: UTC timestamps throughout; `pgcrypto`/`uuid-ossp` extension for
  UUID primary keys if used.
- **Acceptance criteria**: Backend can connect and run a trivial query against Postgres
  in the local stack.
- **Edge cases**: Connection retry/backoff on backend startup before Postgres is ready.
- **Dependencies**: STORY-005.
- **Priority**: P0

#### STORY-008 — Redis Provisioning & Configuration
- **User story**: As the system, I need a fast store for caching, rate-limit counters,
  and task queue brokering.
- **Functional requirements**: Redis service in Docker Compose; used as Celery (or
  equivalent) broker/result backend and as an application cache.
- **Technical notes**: Separate logical DB indices or key prefixes for cache vs. queue
  usage to avoid collisions.
- **Acceptance criteria**: Backend can connect to Redis in the local stack.
- **Edge cases**: Redis unavailability must degrade caching gracefully rather than
  hard-fail unrelated requests, where feasible.
- **Dependencies**: STORY-005.
- **Priority**: P0

#### STORY-009 — Database Migration Framework (Alembic)
- **User story**: As a developer, I need versioned, reproducible schema changes.
- **Functional requirements**: Alembic configured against SQLAlchemy models; migration
  history committed to `backend/`.
- **Technical notes**: One migration per meaningful schema change; no editing of
  already-applied migrations.
- **Acceptance criteria**: `alembic upgrade head` succeeds from empty database.
- **Edge cases**: Downgrade paths documented or explicitly marked unsupported per
  migration.
- **Dependencies**: STORY-007, STORY-012.
- **Priority**: P0

#### STORY-010 — Canonical Job Listing Schema
- **User story**: As the system, I need one normalized shape for job data regardless of
  source.
- **Functional requirements**: SQLAlchemy model + migration implementing the fields in
  §2; source provenance fields (`source`, `source_url`, `source_job_id`) unique together.
- **Technical notes**: Long text fields for description sections; structured fields
  (skills, location) normalized where feasible, raw value retained alongside.
- **Acceptance criteria**: Schema matches §2; unique constraint prevents duplicate
  `(source, source_job_id)` rows.
- **Edge cases**: Sources that omit optional fields (compensation, benefits, closing
  date) must store `NULL`, not fabricated values.
- **Dependencies**: STORY-009.
- **Priority**: P0

#### STORY-011 — Canonical Company Schema
- **User story**: As the system, I need companies modeled once and referenced by many
  job listings.
- **Functional requirements**: `Company` model (name, normalized name/slug, domain,
  optional metadata); `Job.company_id` foreign key.
- **Technical notes**: Company resolution/matching logic lives with the connector
  framework (STORY-016), not hardcoded per connector.
- **Acceptance criteria**: Jobs from the same company via different sources resolve to
  one `Company` row where identifiable.
- **Edge cases**: Ambiguous or unresolvable company identity falls back to a
  source-scoped company record rather than blocking ingestion.
- **Dependencies**: STORY-010.
- **Priority**: P0

### Backend & Frontend Scaffolding

#### STORY-012 — Backend API Application Foundation
- **User story**: As an operator, I need a runnable backend service with health and
  configuration endpoints before any feature logic exists.
- **Functional requirements**: FastAPI app skeleton in `backend/app/`; typed settings;
  `/health` endpoint; structured error responses.
- **Technical notes**: Application factory pattern to support testing with different
  configs.
- **Acceptance criteria**: `GET /health` returns 200 with service status locally and in
  Docker.
- **Edge cases**: `/health` must not depend on downstream services being fully warm to
  report basic liveness (separate liveness vs. readiness later, see STORY-052).
- **Dependencies**: STORY-001, STORY-006.
- **Priority**: P0

#### STORY-013 — Frontend Application Foundation
- **User story**: As a user, I need a running web app shell before any real pages exist.
- **Functional requirements**: Next.js + TypeScript app skeleton in `frontend/`; base
  layout; environment-driven API base URL.
- **Technical notes**: App Router; strict TypeScript config.
- **Acceptance criteria**: Frontend builds and serves a placeholder home page locally
  and in Docker.
- **Edge cases**: Missing/misconfigured API base URL fails visibly in dev, not silently.
- **Dependencies**: STORY-001, STORY-006.
- **Priority**: P0

### Ingestion Framework

#### STORY-014 — Source Registry
- **User story**: As an operator, I need a single place that lists every ingestion
  source, its connector, and its status.
- **Functional requirements**: `Source` model (name, connector type, config, enabled
  flag, last-run summary); admin-visible listing.
- **Technical notes**: Config stored as structured JSON/JSONB, validated per connector.
- **Acceptance criteria**: Sources can be registered, enabled, and disabled without code
  changes to the connector itself.
- **Edge cases**: Disabling a source must stop future scheduled runs without deleting
  historical data.
- **Dependencies**: STORY-010, STORY-011.
- **Priority**: P1

#### STORY-015 — Ingestion Run Tracking
- **User story**: As an operator, I need a record of every ingestion attempt, its
  outcome, and counts.
- **Functional requirements**: `IngestionRun` model (source, started_at, finished_at,
  status, jobs_seen, jobs_created, jobs_updated, jobs_failed, error_summary).
- **Technical notes**: One run row per connector execution; linked to affected job rows
  where feasible for auditability.
- **Acceptance criteria**: Every connector execution produces exactly one run record,
  including failed runs.
- **Edge cases**: Crash mid-run still results in a run record marked failed/incomplete,
  not a silently missing run.
- **Dependencies**: STORY-014.
- **Priority**: P1

#### STORY-016 — Connector Framework (Pluggable Adapters)
- **User story**: As a developer, I need a stable interface so new sources can be added
  without touching core ingestion logic.
- **Functional requirements**: Abstract base connector defining `fetch()` / `normalize()`
  / `validate()` steps; connector registry keyed by source type; per-connector
  configuration schema.
- **Technical notes**: Connectors return an intermediate normalized-but-unpersisted
  representation; persistence and dedup happen in shared pipeline code, not per
  connector.
- **Acceptance criteria**: A new connector can be added by implementing the interface
  only, with no changes to scheduling, persistence, or dedup code.
- **Edge cases**: A connector raising an unexpected exception must not crash other
  connectors' runs (see STORY-023).
- **Dependencies**: STORY-014, STORY-015.
- **Priority**: P1

#### STORY-017 — Lawful Source Access Policy Enforcement
- **User story**: As the platform operator, I need technical guardrails, not just
  documentation, ensuring connectors only access permitted sources.
- **Functional requirements**: Shared HTTP client used by all connectors enforces
  `robots.txt` checks where applicable, honors documented rate limits, sends an
  identifying User-Agent, and refuses to run against sources flagged as
  requiring bypassed auth/CAPTCHA/anti-bot measures.
- **Technical notes**: Central place to add/adjust this policy so it cannot be
  bypassed per-connector.
- **Acceptance criteria**: A connector cannot make outbound requests without going
  through the policy-enforcing client.
- **Edge cases**: A source that changes its `robots.txt` to disallow previously-allowed
  paths must cause that path to stop being fetched on the next run.
- **Dependencies**: STORY-016.
- **Priority**: P0

#### STORY-018 — Greenhouse Connector
- **User story**: As a job seeker, I want listings from companies using Greenhouse's
  public job board API.
- **Functional requirements**: Connector implementing STORY-016's interface against
  Greenhouse's public job board API/feed; maps Greenhouse fields to the canonical
  schema (§2).
- **Technical notes**: Uses only Greenhouse's publicly documented, unauthenticated job
  board endpoints — no scraping of authenticated admin views.
- **Acceptance criteria**: Given a configured Greenhouse board token, connector
  produces normalized job records passing validation (STORY-027).
- **Edge cases**: Boards with zero open postings produce a successful empty run, not an
  error.
- **Dependencies**: STORY-016, STORY-017.
- **Priority**: P1

#### STORY-019 — Ashby Connector
- **User story**: As a job seeker, I want listings from companies using Ashby's public
  job posting API.
- **Functional requirements**: Connector implementing STORY-016's interface against
  Ashby's public job posting API; maps Ashby fields to the canonical schema (§2).
- **Technical notes**: Uses only Ashby's publicly documented, unauthenticated endpoints.
- **Acceptance criteria**: Given a configured Ashby organization identifier, connector
  produces normalized job records passing validation (STORY-027).
- **Edge cases**: Fields Ashby does not provide (e.g. compensation) are stored `NULL`,
  never inferred.
- **Dependencies**: STORY-016, STORY-017.
- **Priority**: P1

#### STORY-020 — Future Connector Extensibility Guidelines
- **User story**: As a future contributor, I need documented criteria for what makes a
  source addable.
- **Functional requirements**: `docs/` guide covering: how to evaluate whether a source
  is lawful/permitted to ingest, how to implement the connector interface, how to add
  field mappings, how to add connector-specific tests.
- **Technical notes**: References STORY-017's enforcement points so new connectors
  cannot accidentally bypass them.
- **Acceptance criteria**: Guide is sufficient for a new connector to be added by
  following it without additional core-team clarification, in principle.
- **Edge cases**: N/A (documentation Story).
- **Dependencies**: STORY-016, STORY-017, STORY-018.
- **Priority**: P2

#### STORY-021 — Scheduled Refresh
- **User story**: As an operator, I need sources refreshed automatically on a schedule.
- **Functional requirements**: Scheduled task (Celery beat or equivalent) triggers each
  enabled source's connector on a configurable interval.
- **Technical notes**: Per-source interval override; default global interval.
- **Acceptance criteria**: Enabled sources run automatically without manual triggering
  once workers are deployed.
- **Edge cases**: Overlapping runs for the same source are prevented (see STORY-024's
  locking).
- **Dependencies**: STORY-016, STORY-054 (workers/scheduler infra).
- **Priority**: P1

#### STORY-022 — Retry Handling for Transient Ingestion Failures
- **User story**: As an operator, I don't want a flaky network blip to mark a source
  unhealthy.
- **Functional requirements**: Retryable failures (timeouts, 5xx, connection errors)
  retried with exponential backoff up to a configured max; non-retryable failures
  (4xx auth/permission errors, parse errors) fail immediately.
- **Technical notes**: Retry policy configurable per connector/source.
- **Acceptance criteria**: A simulated transient failure succeeds on retry within the
  same run or the next scheduled run.
- **Edge cases**: Exhausted retries still produce a completed (failed) `IngestionRun`
  record, not a hung one.
- **Dependencies**: STORY-015, STORY-016.
- **Priority**: P1

#### STORY-023 — Per-Source Failure Isolation
- **User story**: As an operator, one broken source must never take down ingestion for
  every other source.
- **Functional requirements**: Each source's connector execution is isolated (separate
  task/process boundary); an unhandled exception in one is caught, logged, and recorded
  against that source's run only.
- **Technical notes**: Enforced at the scheduler/worker task boundary, not left to each
  connector to implement.
- **Acceptance criteria**: A connector that always raises does not prevent other
  sources' scheduled runs from executing.
- **Edge cases**: Repeated failures beyond a threshold flag the source unhealthy
  (STORY-024) rather than retrying indefinitely.
- **Dependencies**: STORY-016, STORY-021.
- **Priority**: P1

#### STORY-024 — Source Health Monitoring
- **User story**: As an operator, I need to see at a glance which sources are healthy.
- **Functional requirements**: Health status derived from recent `IngestionRun` history
  per source (success rate, last success time, consecutive failure count); exposed via
  an internal endpoint/view.
- **Technical notes**: Locking to prevent overlapping runs for the same source lives
  here or in STORY-021.
- **Acceptance criteria**: A source with N consecutive failures is visibly flagged
  unhealthy.
- **Edge cases**: A newly-added source with no runs yet shows as "unknown," not
  "unhealthy."
- **Dependencies**: STORY-015, STORY-023.
- **Priority**: P2

### Deduplication & Data Quality

#### STORY-025 — Exact Deduplication
- **User story**: As a job seeker, I don't want to see the same listing twice from the
  same source.
- **Functional requirements**: Enforce uniqueness on `(source, source_job_id)`;
  re-ingesting an existing job updates `last_seen_at` and changed fields rather than
  inserting a duplicate row.
- **Technical notes**: Upsert logic in the shared ingestion pipeline (STORY-016), not
  per connector.
- **Acceptance criteria**: Re-running a connector against unchanged source data
  produces zero new job rows, updated `last_seen_at`.
- **Edge cases**: A source reusing job IDs for genuinely different postings is treated
  as a data-quality issue to flag (STORY-027), not silently merged.
- **Dependencies**: STORY-010, STORY-016.
- **Priority**: P1

#### STORY-026 — Advanced / Cross-Source Deduplication
- **User story**: As a job seeker, I don't want to see the same underlying job posted
  by two different sources treated as unrelated listings.
- **Functional requirements**: Heuristic matching (company + normalized title +
  location + posting-date proximity, and/or description similarity) to link probable
  duplicates across sources without merging their provenance.
- **Technical notes**: Explicitly out of scope for initial delivery; implemented after
  exact dedup and at least two connectors are stable (see Implementation Sequence #23).
- **Acceptance criteria**: Candidate duplicate pairs are surfaced for review rather than
  auto-merged, at least initially.
- **Edge cases**: False-positive matches must be reversible; nothing about a job's
  original provenance is destroyed by linking.
- **Dependencies**: STORY-025, STORY-018, STORY-019.
- **Priority**: P3

#### STORY-027 — Data Quality Validation
- **User story**: As a job seeker, I don't want to see garbled or clearly broken
  listings.
- **Functional requirements**: Validation step in the ingestion pipeline rejecting or
  flagging records missing required fields (title, company, source_url) or failing
  sanity checks (e.g. empty description); flagged records excluded from search results
  until resolved.
- **Technical notes**: Validation failures recorded on the `IngestionRun` (see
  STORY-015), not silently dropped.
- **Acceptance criteria**: A malformed source payload does not reach search results;
  the failure is visible in run history.
- **Edge cases**: Partial data (e.g. missing compensation) is valid; only structurally
  required fields cause rejection.
- **Dependencies**: STORY-010, STORY-016.
- **Priority**: P1

#### STORY-028 — Freshness Tracking & Auto-Closure
- **User story**: As a job seeker, I don't want to apply to a job that's no longer open.
- **Functional requirements**: `first_seen_at`/`last_seen_at` maintained per job; a job
  not seen in N consecutive runs of its source is marked closed/inactive rather than
  deleted.
- **Technical notes**: Threshold `N` configurable per source (posting cadence varies).
- **Acceptance criteria**: A job absent from a source for the configured threshold is
  excluded from default search results but remains queryable historically.
- **Edge cases**: A source-wide outage (all jobs "missing") must not mass-close every
  job — distinguish "source failed to run" from "source ran and job is gone"
  (dependent on STORY-023).
- **Dependencies**: STORY-025, STORY-023.
- **Priority**: P2

#### STORY-029 — Provenance Preservation
- **User story**: As a job seeker or operator, I need to know exactly where a listing
  came from and trust it wasn't altered beyond normalization.
- **Functional requirements**: Every job row retains `source`, `source_url`,
  `source_job_id`, and raw-payload reference/snapshot; UI surfaces "view original
  posting" linking to `source_url`.
- **Technical notes**: Raw payload retention format (e.g. JSONB column vs. object
  storage) decided during implementation; must not block launch.
- **Acceptance criteria**: Every displayed job links back to its original source URL.
- **Edge cases**: If a source's raw payload becomes unavailable later, provenance
  metadata already stored remains intact.
- **Dependencies**: STORY-010.
- **Priority**: P1

### Search & Discovery

#### STORY-030 — Full-Text Search (PostgreSQL)
- **User story**: As a job seeker, I want to search job listings by keyword.
- **Functional requirements**: Postgres `tsvector`/`tsquery`-based full-text search over
  title, company, description, and skills; ranked results.
- **Technical notes**: OpenSearch/Elasticsearch considered later only if Postgres FTS
  proves insufficient at scale — not part of initial delivery.
- **Acceptance criteria**: Keyword search returns relevant results ranked above
  irrelevant ones for representative queries.
- **Edge cases**: Empty query returns unfiltered (paginated) results rather than an
  error.
- **Dependencies**: STORY-010, STORY-057.
- **Priority**: P1

#### STORY-031 — Faceted Filtering
- **User story**: As a job seeker, I want to narrow results by location, remote status,
  employment type, seniority, and company.
- **Functional requirements**: API accepts filters across arbitrary combinations of
  canonical job fields; filters composable with full-text search.
- **Technical notes**: Filter parameters validated against an allow-list of filterable
  fields.
- **Acceptance criteria**: Combining two or more filters narrows results correctly
  relative to either filter alone.
- **Edge cases**: A filter combination with zero matches returns an empty result set,
  not an error.
- **Dependencies**: STORY-030.
- **Priority**: P1

#### STORY-032 — Sorting
- **User story**: As a job seeker, I want to sort results (e.g. newest first,
  relevance).
- **Functional requirements**: Sort by relevance (when a search query is present),
  posting date, and last-seen date at minimum.
- **Technical notes**: Default sort documented (relevance when query present, else
  newest-first).
- **Acceptance criteria**: Sort order changes are reflected correctly across paginated
  pages (no duplicate/skipped rows across pages).
- **Edge cases**: Sorting by a field with many `NULL`s (e.g. compensation) defines and
  documents `NULL` ordering.
- **Dependencies**: STORY-030.
- **Priority**: P2

#### STORY-033 — Pagination
- **User story**: As a job seeker, I want to page through results without duplicates or
  gaps.
- **Functional requirements**: Cursor- or offset-based pagination (decided during
  implementation) with a stable page size limit.
- **Technical notes**: Cursor-based preferred for consistency under concurrent writes,
  if feasible within timeline.
- **Acceptance criteria**: Paging through a stable result set yields every result
  exactly once.
- **Edge cases**: Underlying data changing between page requests documented as an
  accepted limitation if offset-based pagination is used.
- **Dependencies**: STORY-030.
- **Priority**: P1

#### STORY-034 — Job Detail Page (Frontend)
- **User story**: As a job seeker, I want a full view of one listing.
- **Functional requirements**: Route displaying all canonical fields available for a
  job, sanitized description HTML (STORY-047), link to original posting and to
  `application_url`.
- **Technical notes**: Server-rendered for SEO where feasible.
- **Acceptance criteria**: All non-null canonical fields for a job are visible on its
  detail page.
- **Edge cases**: Closed/inactive jobs are visibly labeled as such rather than
  presented as open.
- **Dependencies**: STORY-013, STORY-029, STORY-047.
- **Priority**: P1

#### STORY-035 — Job Search UI (Frontend)
- **User story**: As a job seeker, I want to search and filter jobs from the web app.
- **Functional requirements**: Search box, facet controls, sort control, paginated
  result list wired to the search API (STORY-030–033).
- **Technical notes**: URL state reflects search/filter/sort/page so results are
  shareable/bookmarkable.
- **Acceptance criteria**: A user can search, filter, sort, and page through results
  entirely through the UI.
- **Edge cases**: Slow/failed API responses show loading/error states, not a blank
  page.
- **Dependencies**: STORY-013, STORY-030, STORY-031, STORY-032, STORY-033.
- **Priority**: P1

### Users, Authentication & Personalization

#### STORY-036 — Authentication
- **User story**: As a user, I want to create an account and log in securely.
- **Functional requirements**: Email/password registration and login at minimum;
  hashed credentials (e.g. bcrypt/argon2); session or token-based auth
  (e.g. JWT/httpOnly cookie).
- **Technical notes**: Rate-limited login attempts (ties into STORY-045).
- **Acceptance criteria**: A user can register, log out, and log back in; passwords are
  never stored or logged in plaintext.
- **Edge cases**: Duplicate registration email is rejected with a clear, non-user-
  enumerating error where practical.
- **Dependencies**: STORY-007, STORY-012.
- **Priority**: P2

#### STORY-037 — User Profiles
- **User story**: As a user, I want basic profile information associated with my
  account.
- **Functional requirements**: Name, contact preferences, account settings.
- **Technical notes**: Kept separate from resume/experience data (STORY-040).
- **Acceptance criteria**: A logged-in user can view and edit their profile.
- **Edge cases**: Profile edits are validated server-side, not trusted from client
  input alone.
- **Dependencies**: STORY-036.
- **Priority**: P2

#### STORY-038 — Saved Jobs
- **User story**: As a job seeker, I want to bookmark listings to revisit later.
- **Functional requirements**: Save/unsave a job; list of a user's saved jobs.
- **Technical notes**: Saved-job rows reference job by ID; behavior on job closure
  documented (still visible, marked closed).
- **Acceptance criteria**: Saved jobs persist across sessions and are listed correctly.
- **Edge cases**: Saving an already-saved job is idempotent, not an error.
- **Dependencies**: STORY-036, STORY-010.
- **Priority**: P2

#### STORY-039 — Saved Searches
- **User story**: As a job seeker, I want to save a search/filter combination to reuse
  or (later) be notified about.
- **Functional requirements**: Persist a named search's query/filter/sort parameters
  per user; re-run it on demand.
- **Technical notes**: Notification-on-new-match is explicitly out of scope unless a
  future Story adds it.
- **Acceptance criteria**: A saved search reproduces the same result set when re-run
  against current data.
- **Edge cases**: A saved search referencing filter values that no longer exist
  degrades gracefully (ignores the stale filter) rather than erroring.
- **Dependencies**: STORY-036, STORY-031.
- **Priority**: P3

#### STORY-040 — Resume / Experience Profiles
- **User story**: As a job seeker, I want to enter my real work history, education, and
  skills once and reuse them.
- **Functional requirements**: Structured entry for employers, titles, dates,
  descriptions, education, certifications, skills — all user-provided and editable.
- **Technical notes**: No field is ever auto-populated with inferred or generated
  content the user didn't provide or explicitly approve.
- **Acceptance criteria**: A user can create, edit, and delete experience entries.
- **Edge cases**: Overlapping/inconsistent dates are allowed (not everyone's history is
  clean) but not silently "corrected."
- **Dependencies**: STORY-036.
- **Priority**: P2

#### STORY-041 — Resume-to-Job Fit Analysis
- **User story**: As a job seeker, I want to understand how my real experience aligns
  with a specific listing's requirements.
- **Functional requirements**:
  - analyze a selected job's requirements and qualifications;
  - identify important keywords and competencies from that listing;
  - compare them against the user's stored, truthful experience (STORY-040);
  - recommend which existing user experiences to emphasize for this job;
  - identify gaps between the listing and the user's stored experience.
- **Technical notes**: Every recommendation must cite which job requirement and which
  user-provided experience entry it's based on (explainable/traceable output, per §1.3).
- **Acceptance criteria**: Output never references any employer, title, skill, or
  achievement not present in the user's stored experience; every recommendation is
  traceable to a specific job requirement and a specific user experience entry.
- **Edge cases**: A user with little/no relevant experience for a listing receives an
  honest gap summary, not fabricated alignment.
- **Dependencies**: STORY-040, STORY-034.
- **Priority**: P3

#### STORY-042 — ATS-Friendly Resume Guidance
- **User story**: As a job seeker, I want guidance on structuring my resume for a
  specific job so it passes ATS screening.
- **Functional requirements**: Recommend an ATS-friendly resume structure and truthful
  wording suggestions based on STORY-041's analysis; formatting guidance (standard
  section headers, avoiding graphics/tables that break ATS parsing, keyword placement).
- **Technical notes**: Wording suggestions rephrase the user's own stated experience;
  they do not introduce new claims (per §1.3).
- **Acceptance criteria**: Every suggested phrase is traceable to a user-provided
  experience entry; no suggested wording introduces unverified claims.
- **Edge cases**: If the user's experience doesn't support a requirement, guidance says
  so rather than suggesting wording that implies it does.
- **Dependencies**: STORY-041.
- **Priority**: P3

### Security & Privacy

#### STORY-043 — Security Hardening (General)
- **User story**: As an operator, I need standard web application security practices
  applied consistently.
- **Functional requirements**: Input validation at API boundaries, parameterized
  queries only (no raw SQL string interpolation), CSRF protection for cookie-based
  auth flows, secure cookie flags, dependency vulnerability scanning in CI.
- **Technical notes**: Threat surface includes ingestion (untrusted external HTML/JSON)
  as well as user-facing endpoints.
- **Acceptance criteria**: No known-high-severity dependency vulnerabilities at release
  time; automated scan wired into CI (STORY-053).
- **Edge cases**: N/A — cross-cutting Story revisited as new features land.
- **Dependencies**: STORY-012.
- **Priority**: P1

#### STORY-044 — Privacy Controls & Data Handling
- **User story**: As a user, I want control over my personal data and clarity on how
  it's used.
- **Functional requirements**: Account/data deletion; resume/experience data never
  used for anything beyond the user's own fit-analysis requests; no resale/sharing of
  personal data to third parties.
- **Technical notes**: Deletion must cascade to saved jobs, saved searches, and resume
  data.
- **Acceptance criteria**: Requesting account deletion removes personal data per the
  documented scope.
- **Edge cases**: Deletion requests during an in-flight fit-analysis request are
  handled without leaving orphaned data.
- **Dependencies**: STORY-036, STORY-037, STORY-040.
- **Priority**: P2

#### STORY-045 — Rate Limiting
- **User story**: As an operator, I need to protect the API from abusive or accidental
  overload.
- **Functional requirements**: Per-IP and per-account rate limits on public and
  authenticated endpoints; stricter limits on auth endpoints (STORY-036) and any
  externally-triggered ingestion endpoints.
- **Technical notes**: Backed by Redis (STORY-008) counters/token buckets.
- **Acceptance criteria**: Requests exceeding the configured limit receive a 429 with a
  retry-after hint.
- **Edge cases**: Rate limiting must not block legitimate scheduled internal jobs
  (ingestion workers exempted or separately budgeted).
- **Dependencies**: STORY-008, STORY-012.
- **Priority**: P1

#### STORY-046 — SSRF Protection
- **User story**: As an operator, I need to ensure outbound requests (ingestion,
  URL-based features) can't be abused to reach internal/private network resources.
- **Functional requirements**: All outbound HTTP calls (connectors, any user-supplied
  URL handling) validated against an allow-list of intended external hosts and/or
  block private/link-local/loopback IP ranges before connecting; no following of
  redirects into disallowed ranges.
- **Technical notes**: Enforced in the shared HTTP client from STORY-017 so no
  connector can bypass it.
- **Acceptance criteria**: A crafted URL/redirect targeting a private IP range is
  rejected before any request is made to it.
- **Edge cases**: DNS rebinding (hostname resolving to a private IP after validation)
  is accounted for by re-validating the resolved IP at connect time.
- **Dependencies**: STORY-017.
- **Priority**: P0

#### STORY-047 — Sanitization of External Job HTML
- **User story**: As a job seeker, I want job descriptions rendered safely even though
  they originate from external, untrusted sources.
- **Functional requirements**: All externally-sourced HTML (job descriptions, etc.) is
  sanitized (allow-listed tags/attributes, scripts/styles/event-handlers stripped)
  before storage and again before rendering.
- **Technical notes**: Sanitize on ingest (defense in depth) and treat the stored value
  as still-untrusted at render time (escape/sanitize again on output).
- **Acceptance criteria**: A job description containing `<script>` or inline event
  handlers renders with that content neutralized, not executed.
- **Edge cases**: Legitimate formatting (lists, bold, links) is preserved; sanitization
  isn't so aggressive it destroys readability.
- **Dependencies**: STORY-010, STORY-016.
- **Priority**: P0

### Accessibility & UI Quality

#### STORY-048 — Accessibility (WCAG)
- **User story**: As a user relying on assistive technology, I need the app to be
  usable.
- **Functional requirements**: Semantic HTML, keyboard navigability, sufficient color
  contrast, ARIA labeling where semantic HTML is insufficient — targeting WCAG 2.1 AA
  for core flows (search, job detail, auth, saved jobs).
- **Technical notes**: Automated accessibility checks (e.g. axe) added to frontend
  tests where practical.
- **Acceptance criteria**: Core flows pass automated accessibility checks with no
  critical violations.
- **Edge cases**: Dynamically loaded content (search results) announces updates to
  screen readers appropriately.
- **Dependencies**: STORY-013, STORY-035, STORY-034.
- **Priority**: P2

#### STORY-049 — Responsive UI
- **User story**: As a user on any device, I want the app to be usable on my screen
  size.
- **Functional requirements**: Layouts adapt across mobile, tablet, and desktop
  breakpoints for all user-facing pages.
- **Technical notes**: Mobile-first CSS approach.
- **Acceptance criteria**: Core flows are fully usable at common mobile viewport widths
  without horizontal scrolling or clipped controls.
- **Edge cases**: N/A — cross-cutting Story revisited as new pages land.
- **Dependencies**: STORY-013.
- **Priority**: P2

### Observability & Operations

#### STORY-050 — Structured Logging
- **User story**: As an operator, I need consistent, machine-parseable logs across
  backend and workers.
- **Functional requirements**: JSON-structured log output; request/task correlation
  IDs; no secrets or full credentials logged.
- **Technical notes**: Consistent log schema across backend API and worker processes.
- **Acceptance criteria**: A single request/task can be traced end-to-end via its
  correlation ID across log lines.
- **Edge cases**: Logging failures must not crash the request/task being logged.
- **Dependencies**: STORY-012.
- **Priority**: P2

#### STORY-051 — Metrics & Observability
- **User story**: As an operator, I need visibility into system behavior over time.
- **Functional requirements**: Application metrics (request latency/rate/errors,
  ingestion run outcomes, queue depth) exposed in a scrapeable format (e.g.
  Prometheus-compatible endpoint).
- **Technical notes**: Naming convention documented so future metrics stay consistent.
- **Acceptance criteria**: Key metrics are visible and update under load in the local
  stack.
- **Edge cases**: N/A — cross-cutting Story revisited as new features land.
- **Dependencies**: STORY-012, STORY-050.
- **Priority**: P2

#### STORY-052 — Health Checks
- **User story**: As an operator/orchestrator, I need liveness and readiness signals
  distinct from basic uptime.
- **Functional requirements**: Liveness endpoint (process is running) separate from
  readiness endpoint (dependencies like Postgres/Redis are reachable).
- **Technical notes**: Used by Docker Compose healthchecks (STORY-005) and, later,
  deployment orchestration (STORY-056).
- **Acceptance criteria**: Readiness reports unhealthy when a required dependency is
  unreachable; liveness does not.
- **Edge cases**: Flapping dependency connectivity doesn't cause rapid restart loops
  (debounce/threshold on readiness).
- **Dependencies**: STORY-012, STORY-007, STORY-008.
- **Priority**: P1

#### STORY-053 — CI/CD Pipeline
- **User story**: As a contributor, I need automated checks on every change.
- **Functional requirements**: GitHub Actions workflows in `.github/workflows/`
  running backend tests/lint/type-check, frontend tests/lint/type-check, and
  dependency vulnerability scanning on every PR.
- **Technical notes**: Deployment automation is a separate, later Story (STORY-056);
  CI here covers verification only.
- **Acceptance criteria**: A PR with a failing test or lint error is blocked from
  merge-readiness by a red CI check.
- **Edge cases**: Flaky tests are quarantined/fixed, not ignored via blanket retries.
- **Dependencies**: STORY-001, STORY-054.
- **Priority**: P1

#### STORY-054 — Automated Testing Strategy
- **User story**: As a contributor, I need confidence that changes don't silently break
  existing behavior.
- **Functional requirements**: `pytest` for backend (unit + integration against a test
  database); frontend unit tests; Playwright end-to-end tests for core user flows
  (search, job detail, auth).
- **Technical notes**: Test database isolated from development data; connectors tested
  against recorded/mocked responses, never live external calls in CI.
- **Acceptance criteria**: Test suite runs locally and in CI; core flows have at least
  one passing end-to-end test each once built.
- **Edge cases**: Tests requiring network access are explicitly marked and excluded
  from default CI runs if they can't be mocked.
- **Dependencies**: STORY-012, STORY-013.
- **Priority**: P1

#### STORY-055 — Backups
- **User story**: As an operator, I need to recover from data loss.
- **Functional requirements**: Documented (and, where feasible, automated) Postgres
  backup procedure; restore procedure tested at least once.
- **Technical notes**: Backup target/retention decided at implementation time based on
  chosen hosting.
- **Acceptance criteria**: A documented restore procedure exists and has been exercised
  successfully at least once before relying on it.
- **Edge cases**: N/A.
- **Dependencies**: STORY-007.
- **Priority**: P2

#### STORY-056 — Deployment
- **User story**: As an operator, I need a repeatable way to deploy the system beyond
  local Docker Compose.
- **Functional requirements**: Documented deployment target and process (specifics
  decided during implementation); environment-specific configuration via environment
  variables only (no hardcoded environment branching in application code).
- **Technical notes**: Builds on the Docker images from STORY-004.
- **Acceptance criteria**: A documented, repeatable deployment procedure exists and has
  been exercised at least once.
- **Edge cases**: N/A.
- **Dependencies**: STORY-004, STORY-053.
- **Priority**: P3

### Performance

#### STORY-057 — Database Indexing Strategy
- **User story**: As a job seeker, I want search and filtering to stay fast as the
  dataset grows.
- **Functional requirements**: Indexes on filterable/sortable columns (company, work
  mode, employment type, posting date, location) and a GIN index supporting full-text
  search (STORY-030).
- **Technical notes**: Index choices revisited based on observed query plans, not
  guessed once and left static.
- **Acceptance criteria**: Representative filtered/search queries use an index (verified
  via `EXPLAIN`) rather than a sequential scan at expected data volumes.
- **Edge cases**: N/A — revisited as query patterns evolve.
- **Dependencies**: STORY-010.
- **Priority**: P1

#### STORY-058 — Caching Strategy
- **User story**: As a job seeker, I want frequently-requested pages/queries to load
  quickly.
- **Functional requirements**: Redis-backed caching for expensive/frequent read paths
  (e.g. popular search queries, job detail pages); explicit invalidation on relevant
  writes (job updated/closed).
- **Technical notes**: Cache keys versioned so a schema/logic change can't silently
  serve stale-shaped data.
- **Acceptance criteria**: Cached responses are invalidated correctly when underlying
  data changes; stale data is never served past its defined TTL/invalidation trigger.
- **Edge cases**: Cache unavailability falls back to direct reads rather than failing
  the request.
- **Dependencies**: STORY-008, STORY-030.
- **Priority**: P2

## 4. Recommended Architecture Baseline

- Frontend: Next.js + TypeScript
- Backend: FastAPI + Python
- Database: PostgreSQL
- Cache/broker: Redis
- Background workers: Celery or equivalent
- Scheduling: scheduled ingestion via the worker system (e.g. Celery beat)
- ORM: SQLAlchemy
- Migrations: Alembic
- Search: PostgreSQL full-text search initially; OpenSearch considered later only if
  justified by demonstrated scale/relevance limitations
- Containerization: Docker, Docker Compose
- CI: GitHub Actions
- Testing: pytest (backend), frontend unit test framework, Playwright (end-to-end)

This baseline may be revisited if a Story's implementation surfaces a concrete reason
to deviate; deviations should be recorded as Decisions in `progress.md`.

## 5. Implementation Sequence for Claude

Work through Stories in this priority order. Do not skip ahead to a later group until
the current group's Stories are complete and verified (per the Definition of Done,
§6). Within a group, Story order is not strict unless a Dependency requires it.

1. **Repository foundation** — STORY-001, STORY-002, STORY-003
2. **Docker / local development** — STORY-004, STORY-005, STORY-006
3. **Backend health / configuration** — STORY-012
4. **Database / migrations** — STORY-007, STORY-008, STORY-009
5. **Canonical job / company schema** — STORY-010, STORY-011
6. **Source registry** — STORY-014
7. **Ingestion run tracking** — STORY-015
8. **Connector framework** — STORY-016, STORY-017
9. **Exact deduplication** — STORY-025
10. **Greenhouse connector** — STORY-018
11. **Ashby connector** — STORY-019
12. **Freshness / closure handling** — STORY-028
13. **Retries** — STORY-022
14. **Workers / scheduler** — STORY-021, STORY-023
15. **Data-quality validation** — STORY-027, STORY-029
16. **Search API** — STORY-030, STORY-031, STORY-032, STORY-033, STORY-057
17. **Frontend search** — STORY-013, STORY-035
18. **Job detail UI** — STORY-034, STORY-047
19. **Security hardening** — STORY-043, STORY-045, STORY-046
20. **CI** — STORY-053, STORY-054
21. **Authentication and personalization** — STORY-036, STORY-037, STORY-038,
    STORY-039, STORY-044
22. **Resume-fit features** — STORY-040, STORY-041, STORY-042
23. **Advanced deduplication and scaling** — STORY-026, STORY-024, STORY-050,
    STORY-051, STORY-052, STORY-055, STORY-056, STORY-058, STORY-048, STORY-049,
    STORY-020

## 6. Definition of Done (per Story)

A Story is complete only when **all** of the following are true:

1. Functional requirements and acceptance criteria in this document are met.
2. Code is committed with tests where the Story involves logic (not pure
   scaffolding/docs).
3. Relevant tests pass locally (`pytest` for backend, frontend test runner for
   frontend, Playwright for affected end-to-end flows).
4. Lint and type checks pass for changed code.
5. Database migrations, if any, apply cleanly from a clean database.
6. No secrets, credentials, or real personal data were committed.
7. `progress.md` is updated: Story marked complete in the Completed Story Log with
   files changed, commands run, and results — not merely "code was generated."
8. Any deviation from this Story's stated requirements is recorded as a Decision in
   `progress.md`, not silently implemented differently.

A Story is **not** done if code exists but was not verified (tests not run, migration
not applied, build not confirmed). Generated-but-unverified code must remain marked
incomplete.
