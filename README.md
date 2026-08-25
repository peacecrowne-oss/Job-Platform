# Job Opportunity Aggregation & Job-Seeking Platform

> **Status: early repository scaffolding, now with a working job search UI.**
> Repository structure, environment
> configuration, documentation, a backend API foundation (a health
> check and a full-text/filtered/sorted/paginated job search endpoint), a
> working frontend job search page (STORY-035 — search, filters, sorting,
> pagination, all URL-state-backed), a full
> local Docker Compose stack (backend, frontend, Postgres, Redis, all with
> healthchecks), backend connection plumbing to Postgres/Redis, the Alembic
> migration framework, the canonical `jobs`/`companies`/`sources`/
> `ingestion_runs` table schemas, a pluggable connector framework, a
> lawful-access policy-enforcing HTTP client (robots.txt, rate-limit
> honoring, response-code refusal, SSRF protection against private/
> loopback/link-local/metadata destinations with DNS-rebinding-safe
> pinned connections), two real connectors (Greenhouse, Ashby), a
> data-quality validation layer for connector output, exact deduplication
> (a real, working upsert into the `jobs` table, keyed on `(source,
> source_job_id)`, with durable provenance preservation across updates), a
> bounded retry primitive with exponential backoff/jitter for transient
> connector failures, a connector authoring guide, and a database indexing
> strategy (partial indexes on `work_mode`/`employment_type`, a composite
> location index, a `posting_date` index, and a GIN full-text expression
> index over title/company/description/skills, all verified via real
> `EXPLAIN` query plans), and a working `GET /jobs/search` endpoint
> (PostgreSQL full-text search via `websearch_to_tsquery`/`ts_rank_cd`,
> ranked results, the GIN index confirmed in use, offset-based pagination
> with `has_next`/`has_previous` metadata verified duplicate- and gap-free
> across pages, faceted filtering — location, remote status,
> employment type, seniority, and company, independently composable with
> keyword search and pagination alike, index usage confirmed for the
> filters STORY-057 built indexes for — plus sorting by relevance, posting
> date, or last-seen date (`sort=relevance|posting_date|last_seen`),
> preserving keyword matching regardless of which sort is chosen, with an
> explicit, documented `NULLS LAST` decision for undated postings), plus
> a real frontend job search page at `/` (STORY-035 — search box, 7
> filter controls, a sort select, Previous/Next pagination, all reflected
> in the URL for shareable/bookmarkable searches; CORS added to the
> backend so the browser can reach it cross-origin), and a security
> hardening pass (STORY-043 — input-validation length/count bounds on
> every search filter matching the real schema they're compared against,
> parameterized queries verified clean, a real `pip-audit` dependency
> scan that found and fixed 9 known vulnerabilities via a FastAPI
> upgrade, `npm audit` clean), and per-IP rate limiting (STORY-045 — a
> Redis-backed fixed-window limiter on `GET /jobs/search`, `429` with a
> real `Retry-After` hint once exceeded, fails open if Redis is
> unavailable, `GET /health` deliberately exempt so Docker's own
> healthcheck is never blocked), and liveness/readiness health checks
> (STORY-052 — `GET /health/live` for "is the process alive," `GET
> /health/ready` checking Postgres and Redis concurrently and returning
> `503` if either is unreachable, each check wall-clock-bounded to
> `health_check_timeout_seconds` end-to-end including DNS resolution
> (not just the TCP-connect phase), Docker Compose's backend healthcheck
> retargeted to `/health/ready`), and an automated testing strategy
> (STORY-054 — pytest `integration`/`postgres`/`redis` markers, an
> isolated `job_platform_test` database and Redis DB index for real
> Postgres/Redis integration tests with safety guards against ever
> targeting development data, and a first Playwright E2E test covering
> the search flow against the real local stack), and a CI pipeline
> (STORY-053 — three parallel GitHub Actions jobs on every PR and push to
> `main`: backend tests against real Postgres/Redis service containers plus
> `alembic check` and `pip-audit`, frontend tests/build/`npm audit`, and a
> `docker compose config` syntax check; lint/backend-type-check are a
> documented, deliberate gap since neither is configured anywhere in this
> repository), and scheduled refresh (STORY-021 — a dedicated `scheduler`
> Docker Compose service, reusing the backend image, that automatically
> runs every enabled, due `Source`'s connector on a configurable interval
> — no Celery/APScheduler/cron dependency added; a Postgres session-scoped
> advisory lock prevents overlapping runs across processes with no TTL to
> reason about; a manual CLI (`scripts/run_ingestion.py`) exposes the same
> orchestration independent of the scheduler loop) exist so far. The `jobs`
> table itself is empty again after each Story's own validation inserts
> (since removed) — nothing has been left running against real external
> sources by default. See
> [`progress.md`](progress.md) for the exact current state and
> [`requirement.md`](requirement.md) for the full requirements and Story
> backlog.

## Purpose

This platform aggregates job listings from lawful, permitted, and legitimately
public sources — company career pages, ATS APIs/feeds, job boards, and other
approved sources — normalizes and deduplicates them, and helps job seekers search,
filter, save, and assess their fit against listings, without ever fabricating a
user's credentials or experience.

Full product and technical requirements live in [`requirement.md`](requirement.md),
organized as numbered Stories (`STORY-NNN`). Implementation progress is tracked in
[`progress.md`](progress.md).

## Planned architecture

This describes the target architecture per `requirement.md` §4. The Backend API and
Frontend rows now have real feature content: the backend is app bootstrap,
configuration, `/health`, error handling, a SQLAlchemy engine/session and
a Redis client with verified real connectivity, and a full-text/filtered/
sorted/paginated job search endpoint (no auth, no other product endpoints
yet); the frontend is a working job search page at `/` (STORY-035 — search,
filters, sorting, pagination; no job listings/detail page, saved jobs, or
auth UI yet). Containerization is implemented end-to-end: individual `Dockerfile`s for
both services (STORY-004) plus a `docker-compose.yml` (STORY-005) orchestrating
backend, frontend, Postgres, and Redis together with healthchecks — verified via a
real `docker compose up`. Cache/task-broker row is "provisioned and reachable"
(STORY-008), not yet "used by the product." The Database/ORM/Migrations rows
now have real content: a `jobs` table (STORY-010, matching `requirement.md`
§2) and a `companies` table (STORY-011) with a nullable `jobs.company_id` FK
(`ON DELETE SET NULL`) linking them — `jobs.company_name` is untouched and
still holds the raw source-provided text. A `sources` table (STORY-014) now
registers ingestion sources (name, connector type, JSONB config, an
`enabled` flag, an optional nullable link to `companies`) — sources can be
enabled/disabled with a plain `UPDATE`, no connector code involved. An
`ingestion_runs` table (STORY-015) now records one row per connector
execution attempt (source, start/finish timestamps, status, per-run job
counters, an error summary), with a nullable `source_id` FK
(`ON DELETE SET NULL`) so run history survives source deletion. All four
tables are schema only; no ingestion pipeline writes to them yet, and
nothing resolves a job's `company_name` to a `companies` row automatically.
A pluggable connector framework (STORY-016 — `app/connectors/`) now exists:
an abstract `BaseConnector` (`fetch()`/`normalize()`/`validate()`), a
`NormalizedJobRecord` intermediate DTO, a structured connector-error
hierarchy, and an in-memory `ConnectorRegistry`. A real `PolicyEnforcingHttpClient`
(STORY-017) now fills the `HttpClient` seam STORY-016 left open — it's the
only concrete implementation in the repository, so a connector has no other
way to reach the network. It enforces robots.txt (fetched/parsed per host,
fails closed if undeterminable), a documented `Crawl-delay` if declared, an
identifying User-Agent on every request, and refuses (never bypasses) 401/
403/429/identifiable-anti-bot-challenge responses; a disabled `Source`
(reusing the existing `enabled` flag — no new schema) is rejected by a
separate pre-flight `require_source_authorized()` check before a connector
is ever constructed. `PolicyEnforcingHttpClient`'s transport (`SsrfSafeTransport`,
STORY-046) validates every destination — the target URL, the robots.txt
fetch, and every redirect hop — against loopback/RFC1918/link-local
(which also covers cloud metadata addresses like `169.254.169.254`)/
multicast/reserved ranges before ever opening a socket, then connects
directly to the validated IP rather than re-resolving the hostname,
closing the DNS-rebinding window by construction; live-verified against a
real public API, a real loopback address, a real cloud-metadata address,
and — as a bonus confirmation — a real internal Docker hostname, all
correctly allowed/rejected. Two real connectors now implement
`BaseConnector`: `GreenhouseConnector` (STORY-018
— `app/connectors/greenhouse.py`) against Greenhouse's public,
unauthenticated Job Board API, and `AshbyConnector` (STORY-019 —
`app/connectors/ashby.py`) against Ashby's public, unauthenticated Job
Board API. Both need no pagination (each source's list endpoint returns
the complete job set in one response), no secrets, and map fields
conservatively — nothing fabricated; whatever a source doesn't reliably
provide (company name, structured responsibilities/skills, etc.) is left
`None`. Ashby additionally maps `workplaceType`/`employmentType` to
`work_mode`/`employment_type` (fields Greenhouse's API has no equivalent
for) and defensively excludes any job explicitly marked `isListed: false`
(defense in depth — the public endpoint is believed to already exclude
unlisted jobs). Both connectors preserve raw HTML descriptions untouched
as untrusted data pending STORY-047, and the complete raw job payload in
`raw_metadata`. Both were verified against their real live public boards
during implementation (Greenhouse: 14 real records; Ashby: 62 real
records, confirming the field-shape assumptions the mapping was built on)
as well as full mocked/offline test suites. A data-quality validation
layer (STORY-027 — `app/validation/data_quality.py`) now sits between
connector output and any future persistence step: `validate_record()`
checks the three fields `requirement.md` names as required (title,
company, source_url — "company" satisfiable by either the record's own
`company_name` or a caller-supplied `source_company_name`, since neither
connector currently populates `company_name` itself), flags sanity-check
issues as non-blocking warnings (empty description, malformed
`application_url`, a naive `source_updated_at`, an unrecognized controlled
value), and never raises an issue at all for merely-absent optional data
(compensation, benefits, department, etc.) — matching `requirement.md`'s
own edge case. `validate_batch()` guarantees one malformed record can
never prevent the rest of a batch from being validated. Exact
deduplication (STORY-025 — `app/ingestion/dedup.py`) now implements the
logic behind `jobs.content_hash`/`first_seen_at`/`last_seen_at` — three
columns that existed since STORY-010 as declared-but-unused schema hooks.
`upsert_job()`/`upsert_batch()` key strictly on `(source, source_job_id)`
— the same composite unique constraint STORY-010 already created, no new
migration needed — creating a row on first sight, bumping only
`last_seen_at` on an unchanged re-ingestion, and updating content fields
(plus `content_hash`) when a source job's substance actually changes. The
content hash deliberately excludes `source_updated_at`/`raw_metadata` (too
volatile for meaningful change detection) and is computed via
`sha256(json.dumps(fields, sort_keys=True))` for field-order-independent
stability. No fuzzy or cross-source matching exists anywhere — verified
live against real Postgres: two records with identical title/company/
location but different `source` values persist as two independent rows,
never merged. Provenance is now durably preserved across updates
(STORY-029): `source_url`/`application_url`/`raw_metadata`/
`source_updated_at` are never regressed to `None` by a later observation
that happens to lack them — the Story's own literal edge case (a source's
raw payload becoming unavailable later must not destroy what's already
stored) — while ordinary content fields still fully update, including to
`None`, per STORY-025's original design; required no migration, since
every field STORY-029 names already existed on `Job` since STORY-010. A
bounded retry primitive (STORY-022 —
`app/ingestion/retry.py`) now exists: `with_retry()` wraps any zero-
argument callable (a connector fetch, a future persistence call) and
retries a transient failure — `ConnectorTransportError`, a 5xx-shaped
`ConnectorSourceFormatError`, or `ConnectorRateLimitedError` (honoring
`Retry-After` when present, bounded to the policy's own `max_delay`) —
with exponential backoff and full jitter, up to a configured
`max_attempts`. Every policy/security rejection (config errors, auth
failures, `SourceNotAuthorizedError`, `RobotsDisallowedError`,
`SsrfRejectedError`, `AntiBotChallengeDetectedError`) fails on the very
first attempt, never retried — retrying those would functionally be
evasion, which this platform refuses to do. Still no connector-to-
persistence orchestration — nothing currently wires a live connector run
into the upsert or the retry wrapper automatically. Every other row is
not yet implemented.

| Layer | Planned choice |
|---|---|
| Frontend | Next.js + TypeScript |
| Backend API | FastAPI + Python |
| Database | PostgreSQL |
| Cache / task broker | Redis |
| Background workers | Celery or equivalent |
| Scheduling | Scheduled ingestion via the worker system (e.g. Celery beat) |
| ORM | SQLAlchemy |
| Migrations | Alembic |
| Search | PostgreSQL full-text search initially; OpenSearch only if later justified |
| Containerization | Docker, Docker Compose |
| CI | GitHub Actions |
| Testing | pytest (backend), vitest (frontend unit), Playwright (end-to-end, not yet added) |

## Repository structure

```
frontend/               Next.js + TypeScript app
frontend/app/           App Router: root layout + job search page (STORY-013, STORY-035)
frontend/components/    JobCard (STORY-035)
frontend/lib/           Environment-driven config, search API client, URL-state helpers
frontend/tests/         Frontend test suite (vitest + Testing Library; 56 tests)
frontend/package.json   Pinned dependencies; package-lock.json for reproducible installs
frontend/Dockerfile     Multi-stage build image (STORY-004)
frontend/.dockerignore
backend/                FastAPI service
backend/app/            Application source — app factory, config, routing,
                         error handling, /health endpoint (STORY-012);
                         db.py (Postgres) and redis_client.py (Redis)
                         connection plumbing (STORY-007/STORY-008)
backend/app/models/job.py            Canonical Job model — requirement.md §2 (STORY-010)
backend/app/models/company.py        Canonical Company model + name normalization (STORY-011)
backend/app/models/source.py         Source Registry model (STORY-014)
backend/app/models/ingestion_run.py  Ingestion Run Tracking model (STORY-015)
backend/app/connectors/base.py       BaseConnector interface, NormalizedJobRecord DTO,
                                      HttpClient/HttpResponse Protocols (STORY-016)
backend/app/connectors/registry.py   ConnectorRegistry, register_connector decorator (STORY-016)
backend/app/connectors/errors.py     Structured connector/registry error hierarchy
                                      (STORY-016; +3 classes STORY-017; +1 class STORY-046)
backend/app/connectors/http_client.py  PolicyEnforcingHttpClient (STORY-017: robots.txt/
                                        crawl-delay/response-code policy) + SsrfSafeTransport
                                        (STORY-046: scheme/DNS/IP-range validation, pinned-IP
                                        connect, redirect revalidation)
backend/app/connectors/policy.py     require_source_authorized() pre-flight gate (STORY-017)
backend/app/connectors/greenhouse.py  GreenhouseConnector -- real connector against
                                       Greenhouse's public Job Board API (STORY-018)
backend/app/connectors/ashby.py       AshbyConnector -- real connector against
                                       Ashby's public Job Board API (STORY-019)
backend/app/validation/data_quality.py  validate_record()/validate_batch() --
                                         required-field/sanity-check validation
                                         for NormalizedJobRecord (STORY-027)
backend/app/ingestion/dedup.py  upsert_job()/upsert_batch() -- exact deduplication
                                 keyed on (source, source_job_id) (STORY-025)
backend/app/ingestion/retry.py  with_retry() -- bounded exponential backoff +
                                 jitter for transient connector failures (STORY-022)
backend/app/ingestion/orchestrator.py  run_source()/run_all_due_sources() -- the
                                 shared ingestion pipeline wiring STORY-017/022/
                                 025/027/015 together (STORY-021)
backend/app/ingestion/locking.py  Postgres session-scoped advisory lock preventing
                                   overlapping refreshes of the same Source (STORY-021)
backend/app/ingestion/scheduler.py  Scheduler process entry point -- thin polling
                                     loop around the orchestrator (STORY-021)
backend/scripts/run_ingestion.py  Manual/one-off ingestion CLI, independent of the
                                   scheduler loop (STORY-021)
backend/tests/          Backend test suite (pytest; no live infra required)
backend/requirements.txt      Pinned runtime dependencies (incl. SQLAlchemy,
                               psycopg2-binary, redis)
backend/requirements-dev.txt  Runtime + test dependencies (pytest, httpx)
backend/pytest.ini      pytest configuration (adds backend/ to the import path)
backend/Dockerfile      Multi-stage build image (STORY-004; also copies
                         alembic.ini/alembic/ into the runtime image)
backend/.dockerignore
backend/alembic.ini     Alembic config — no credentials committed (STORY-009)
backend/alembic/env.py  Migration environment, wired to Settings/Base
backend/alembic/versions/  Baseline (no-op) + create-jobs-table +
                            create-companies-table + create-sources-table +
                            create-ingestion_runs-table migrations
docker-compose.yml       Full local stack: backend, frontend, Postgres, Redis,
                          with healthchecks (STORY-005)
docs/                   Project documentation
scripts/                Developer/operational scripts (none yet)
.github/workflows/      CI workflows (not yet implemented — see STORY-053)
requirement.md          Source of truth for requirements (Stories)
progress.md             Implementation ledger
.env.example            Environment variable reference (see below)
.gitignore              Ignore rules for Python, Node, env files, build/test
                         artifacts, IDE files, logs, OS metadata, local databases
```

## Local setup

**Currently available:**

```bash
cp .env.example .env
```

This creates your local environment file from the tracked example. Edit values in
`.env` as needed; `.env` itself is git-ignored and must never be committed.

Backend (STORY-012 — foundation only; no database/Redis-backed features yet):

```bash
cd backend
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements-dev.txt

uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

This serves the current backend, which exposes `GET /health`
(liveness alias), `GET /health/live`, `GET /health/ready` (checks
Postgres + Redis, `503` if either is unreachable), and
`GET /jobs/search`. There is no authentication or other product API yet —
those belong to later Stories. Note: `python -m uvicorn` run this way
doesn't have `CORS_ALLOWED_ORIGIN` set unless you export it or use the
Docker workflow below — the frontend's search requests will be blocked by
the browser without it.

Frontend (STORY-013 foundation + STORY-035 job search UI):

```bash
cd frontend
npm ci
npm run dev
```

Serves the job search page at `http://localhost:3000`, reading
`NEXT_PUBLIC_API_BASE_URL` from the repository-root `.env` (copied above) — the
backend must also be running and reachable, with CORS configured for this
origin (see above). If that
variable is missing or not a valid URL, `npm run dev` / `npm run build` fail with an
explicit error rather than silently rendering a broken page — this is a deliberate
requirement of STORY-013, not a bug.

This section covers the individual `cp .env.example .env` / native venv / `npm`
workflow above. See "Docker workflow" below for running everything in containers
instead, including Postgres and Redis.

## Docker workflow

**Full stack orchestration is implemented** (STORY-005 — `docker-compose.yml` at
the repo root, building on STORY-004's images).

```bash
cp .env.example .env   # if you haven't already
docker compose up -d --build
```

This builds and starts all 5 services — `backend`, `frontend`, `postgres`,
`redis`, `scheduler` — wired together on one Docker network, reading configuration
from the same root `.env` used for local (non-Docker) development. `backend`/
`scheduler` wait for `postgres` and `redis` to report healthy (via their own
healthchecks, not a fixed sleep) before starting; each request/response service
has its own healthcheck. `scheduler` (STORY-021) reuses the `backend` image with
a different command — a background polling loop, not an HTTP server — so it has
no healthcheck of its own and no published port; `restart: unless-stopped` keeps
it running across a crash. Verify everything came up:

```bash
docker compose ps
curl http://localhost:8000/health
curl http://localhost:3000/
```

Postgres and Redis are **not** published to host ports — only `backend`
(`:8000`) and `frontend` (`:3000`) are, since only those need direct host
access today. Add a `ports:` mapping in `docker-compose.yml` if you need a local
`psql`/Redis client against the containers directly.

Tear down:

```bash
docker compose down       # stop and remove containers, keep Postgres data
docker compose down -v    # also delete the named volume (fresh Postgres next time)
```

Individual image builds (no orchestration, no Postgres/Redis) are still
available if you only need one service:

```bash
docker build -t job-platform-backend:local ./backend
docker run --rm -p 8000:8000 job-platform-backend:local

docker build --build-arg NEXT_PUBLIC_API_BASE_URL=http://localhost:8000 \
  -t job-platform-frontend:local ./frontend
docker run --rm -p 3000:3000 job-platform-frontend:local
```

Both images are multi-stage (separate build/runtime stages, pinned base image
versions) and run as a non-root user.

**Postgres and Redis connectivity is implemented** (STORY-007/STORY-008): the
backend can open a SQLAlchemy connection to Postgres and ping Redis, both with
graceful handling of the other side being down (retry-with-backoff for
Postgres, a non-raising failure for Redis) — but nothing in the product uses
either yet (no models, no caching, no auth). Not exposed via any endpoint;
verified with `docker compose exec backend python -c "..."` during
implementation, not something you'd normally run day-to-day yet.

## Database migrations

**The Alembic framework is implemented** (STORY-009), and the canonical
`jobs` (STORY-010 — see `app/models/job.py`), `companies` (STORY-011 — see
`app/models/company.py`), `sources` (STORY-014 — see `app/models/source.py`),
and `ingestion_runs` (STORY-015 — see `app/models/ingestion_run.py`) tables
now exist. `jobs.company_id` and `sources.company_id` are both nullable FKs
to `companies.id`; `ingestion_runs.source_id` is a nullable FK to
`sources.id` — all three use `ON DELETE SET NULL` so deleting a parent row
never deletes dependent history. No connector or other tables exist yet
(later Stories).

Postgres isn't published to a host port (see "Docker workflow" above), so run
migrations through the container:

```bash
docker compose up -d
docker compose exec backend alembic current    # current revision
docker compose exec backend alembic history     # migration history
docker compose exec backend alembic upgrade head
docker compose exec backend alembic downgrade -1   # one step back
docker compose exec backend alembic downgrade base # all the way back
```

To generate a new migration:

```bash
docker compose exec backend alembic revision --autogenerate -m "description"
```

**Important**: the container has no bind-mount to the host — a migration
generated with `docker compose exec` only exists *inside* the container until
you copy it out, or it's lost when the container is removed:

```bash
docker compose cp backend:/app/alembic/versions/<generated_file>.py backend/alembic/versions/
```

No database URL or credentials are hardcoded in `alembic.ini` — it's read at
runtime from the same `Settings.database_url` (`.env`) used everywhere else in
the backend. Every schema change ships as its own migration; already-applied
migrations are never edited after the fact. Every migration must implement a
real, reversible `downgrade()`, or explicitly `raise NotImplementedError` with
a stated reason if downgrading genuinely isn't safe.

## Tests

**Backend foundation tests are implemented and runnable** (app factory, routing
bootstrap, `/health`, structured error responses (STORY-012), Postgres
connection retry/backoff and Redis graceful-failure logic (STORY-007/STORY-008),
Alembic config/revision-graph checks (STORY-009), `Job` model structure —
nullability, constraints, enum membership (STORY-010), `Company` model
structure and `normalize_company_name()` behavior (STORY-011), `Source`
model structure — constraints, defaults, nullable company FK (STORY-014),
`IngestionRun` model structure — status/counter constraints, defaults,
nullable source FK (STORY-015), the connector framework — contract
round-trip, config validation, registry registration/lookup/duplicate/
unknown-type handling, all via a fake in-test connector and a fake
in-memory HTTP client (STORY-016), plus the lawful-access policy layer —
robots.txt allow/disallow/404/5xx/unreachable handling, crawl-delay
honoring, 401/403/429/anti-bot-challenge refusal, identifying User-Agent,
no-secrets-in-errors, the source-authorization pre-flight gate, and the
critical "a denied source causes zero connector/network execution" test,
all via a fake transport (STORY-017), plus the Greenhouse connector — field
mapping, missing-optional-field handling, stable source-job identity,
malformed/404/429/5xx response handling, robots.txt disallow, the same
critical zero-network-execution proof, and a structural check that the
connector never imports `urllib`/`requests`/sockets directly, all through a
real `PolicyEnforcingHttpClient` wrapping a fake transport (STORY-018),
plus the Ashby connector — the same shape of coverage adapted to Ashby's
payload: `workplaceType`/`employmentType` mapping (including unrecognized
values), department/team joining, compensation mapping (recognized shape,
missing, and malformed-shape cases), and the `isListed: false` exclusion
proof (STORY-019), plus data-quality validation — required-field
rejection (title/company/source_url), sanity-check warnings that don't
block validity (empty description, malformed `application_url`, naive
timestamps, unrecognized controlled values), structural-impossibility
errors (compensation min > max, negative compensation, closing date
before posting date), zero-issue handling of merely-absent optional
fields, realistic Greenhouse- and Ashby-shaped fixtures proving the
company-attribution design works for both, no-mutation-of-input, and
batch validation where one broken record never blocks the rest
(STORY-027), plus exact deduplication's pure-logic layer — content-hash
stability (identical records hash identically, changed content hashes
differently, `source_updated_at`/`raw_metadata` deliberately excluded so
they never trigger spurious changes, field-order independence),
create/update/unchanged classification, full field mapping, Greenhouse/
Ashby fixture compatibility, and the critical proof that identical title/
company/location under different `source` values are never compared or
merged by anything in the module (STORY-025 — `upsert_job()`/
`upsert_batch()`'s original database behavior against real Postgres was
validated manually during implementation, matching the same convention
STORY-010/011/014/015 established, rather than requiring live
infrastructure in the committed suite), plus provenance preservation
across updates — `source_url`/`application_url`/`raw_metadata`/
`source_updated_at` each individually proven to survive a later
observation that omits them (the Story's own literal edge case), the same
four fields proven to still update normally when a real new value is
present, an ordinary content field proven free to become `None` on update
(confirming the protection is scoped only to provenance, not universal),
`first_seen_at` proven stable across repeated updates, and realistic
Greenhouse/Ashby-shaped fixtures proving the protection against real
connector shapes — all via a minimal fake `Session` exercising the real
`upsert_job()` UPDATE-path logic with zero real database access
(STORY-029), plus SSRF protection — every
blocked IP range (loopback, RFC1918, link-local incl. cloud metadata,
multicast, reserved/unspecified, IPv6 equivalents) individually proven
blocked and a normal public IP proven allowed, literal-IP URLs rejected
without any DNS call, hostname resolution via an injected fake resolver
(a hostname resolving only to a private IP, only to public, to a mix of
both, or triggering a DNS failure — each handled correctly and
distinctly), disallowed schemes rejected before any resolution, and
redirect revalidation via a test subclass that overrides only the
"perform request over the wire" step while exercising all real
validation/redirect logic — a safe public redirect allowed, a redirect to
a hostname resolving to a private IP or to `localhost` blocked with the
final hop's request-performing step *never invoked* (the critical
zero-network test), a redirect loop bounded rather than infinite, and a
scheme-changing redirect blocked (STORY-046 — `SsrfSafeTransport`'s
actual socket/DNS-rebinding behavior was validated manually against a
real public API and real loopback/metadata/internal-Docker-hostname
destinations, matching the same established convention), plus retry
handling — exact exponential-backoff/jitter math, `max_delay` capping,
success-on-first-attempt (no sleep), transient-failure-then-success,
exhausted-attempts raising the original exception, valid/malformed/
missing `Retry-After` handling (including bounding to `max_delay`), the
5xx-vs-malformed-payload classification ambiguity resolved via
`context["status_code"]` (both share `ConnectorSourceFormatError`), and
the critical test that every policy/security rejection (config, auth,
`SourceNotAuthorizedError`, `RobotsDisallowedError`, `SsrfRejectedError`,
`AntiBotChallengeDetectedError`) results in exactly one attempt with zero
sleep calls, entirely via an injected `sleep`/`random_func` — no real
sleeping or randomness anywhere (STORY-022)), plus the database indexing
strategy — each new index's column order/partial predicate/GIN expression
checked against the `Job` model's real `Index` declarations, that the
exact-dedup and `company_id` indexes aren't duplicated, and a guard test
that no index touches a column outside STORY-057's own literal scope
(STORY-057 — planner-level proof that PostgreSQL actually prefers these
indexes over a sequential scan was validated manually against real
Postgres with ~5,000 rows of temporary synthetic data, never committed,
matching the same established convention), plus full-text job search —
the `search_jobs()` query-construction shape (filtered vs. unfiltered
branch, ranking clause, bound-not-interpolated search text, proven via a
deliberately adversarial `'; DROP TABLE jobs; --`-style input) and the
`GET /jobs/search` endpoint's request validation/response shape (STORY-030
— actual keyword matching, English stemming, ranking, and GIN-index usage
were validated manually against real Postgres with deterministic fixture
rows plus a ~5,000-row synthetic scale check, matching the same
established convention), plus pagination — `has_next`/`has_previous`
correctness for a full page, a partial last page, and an empty result set,
via the same over-fetch-by-one query `search_jobs()` itself is never
modified for (STORY-033 — no-duplicate/no-gap correctness across every
page of a stable dataset, for both the ranked and unfiltered branches, was
proven manually against real Postgres by walking every page of two
deterministic fixture sets and comparing the union against a single
unpaginated baseline query, matching the same established convention),
plus faceted filtering — each of the 5 filters' `.where()`-clause
construction, case sensitivity, AND-across-types/OR-within-a-filter
composition, and parameter binding (STORY-031 — the literal acceptance
criterion, "combining two or more filters narrows results correctly
relative to either filter alone," was verified directly against real
Postgres with a 48-row deterministic fixture set: the true intersection
of two filters was computed independently and matched exactly; `EXPLAIN`
confirmed `work_mode`/`employment_type`/`location_country` filters each
use their STORY-057 index, and `location_region` filtered alone correctly
falls back to a sequential scan, a documented composite-index limitation
rather than a defect), plus sorting — each of the 3 sort modes'
`ORDER BY` construction, the `id`-tie-break's determinism, and that
sorting never disables the keyword-match predicate (STORY-032 — verified
directly against real Postgres with fixture rows sharing identical
`posting_date`/`last_seen_at` values: ties resolved reproducibly by `id`,
full page-walks under all 3 sort modes produced zero duplicates and zero
missing rows, and the deliberate `posting_date DESC NULLS LAST` decision
was confirmed correct — with the honest tradeoff, verified via `EXPLAIN`
at both small and ~5,000-row scale, that `ix_jobs_posting_date` cannot
serve that exact ordering and a `Seq Scan` + `Sort` is used instead, a
small cost at any realistic scale that doesn't affect correctness). They
require no external
infrastructure or network access — everything is tested via mocks,
on-disk config parsing, or SQLAlchemy metadata introspection, never a
live connection:

```bash
cd backend
pip install -r requirements-dev.txt
pytest
```

Also covered: STORY-043's input-validation bounds (each free-text search
filter at/over its real schema-derived length limit and its repeated-value
count limit), a live SQL-injection-shaped-value regression across every
text-accepting search param confirming the table stays intact, and that an
unhandled exception never returns its message/stack trace to the client
(only a fixed generic one, the real exception logged server-side only),
plus rate limiting — the fixed-window counter's limit/reject/Retry-After
behavior, independent keying per scope and per IP, a pluggable `key_func`,
and failing open (never closed) on a Redis error, all against a mocked
Redis client (STORY-045 — live-validated against real Redis and Docker's
own healthcheck traffic pattern during implementation; see progress.md
for the full validation record, including a real regression this Story's
own implementation caused and fixed in the test suite itself).

**Dependency vulnerability scanning** (STORY-043 — run manually today;
CI wiring is STORY-053's own future scope, not built here):

```bash
cd backend
pip install -r requirements-dev.txt
pip-audit -r requirements.txt

cd ../frontend
npm audit
```

Both are clean as of the last STORY-043 run (`pip-audit`: 0 known
vulnerabilities, after upgrading `fastapi` 0.115.6 → 0.135.0 to resolve 9
that were found in a transitive `starlette` dependency; `npm audit`: 0
known vulnerabilities). See `progress.md` for the full finding and fix.

**Frontend tests are implemented and runnable** — STORY-013's environment-driven
API base URL logic (including its "fails visibly when missing/invalid" behavior),
plus a full suite for STORY-035's job search page: the URL-state helpers
(`lib/searchParams.ts`, pure functions, round-trip tested), the search API
client (`lib/searchApi.ts` — query-parameter encoding including repeated
values and special characters, non-2xx/network-failure handling, abort-signal
passthrough, all against a mocked `fetch`), `JobCard` rendering (present vs.
absent optional fields, safe vs. unsafe link schemes), and the page itself
(initial render, default/keyword/Enter-key/clear search, every filter
control individually and combined, sort selection, Previous/Next with
offset reset on every other change, loading/both empty-state variants/
error/retry, missing-optional-field rendering, external-link safety,
URL-state initialization from a pre-set URL, and basic keyboard/tab-order
interaction) — via Vitest + `@testing-library/react` + `@testing-library/user-event`
against a `jsdom` environment, mocking `next/navigation` and the search API
module rather than touching a live backend. They require no external
infrastructure:

```bash
cd frontend
npm ci
npm test
```

**Automated testing strategy is implemented** (STORY-054): pytest markers
(`integration`, `postgres`, `redis`, registered in `backend/pytest.ini`)
split the backend suite into a fast, dependency-free subset and a
Postgres/Redis-backed integration subset, plus a first Playwright E2E test
for the search flow (job detail/auth E2E is deferred until STORY-034/036
are built — the AC's own "once built" qualifier).

```bash
# Backend -- fast/local (no Docker required)
cd backend && pytest -m "not integration"

# Backend -- integration (requires Docker Compose's postgres/redis running;
# run from inside the network, e.g. `docker compose exec backend ...`, or
# via a throwaway container attached to the compose network, since
# Postgres/Redis aren't published to the host)
pytest -m integration

# Backend -- full suite
pytest

# Frontend
cd frontend && npm test          # unit/component
npm run build                     # production build + real TS type-check

# Whole repo, fast checks only (backend fast + frontend unit + frontend build)
scripts/run-tests.sh              # requires the backend venv already activated
```

**Isolated test database**: integration tests run against `job_platform_test`
(new `TEST_DATABASE_URL` setting, defaulting to the same Postgres container/
credentials, a different database name), created and migrated to head
automatically by a session-scoped fixture (`backend/tests/conftest.py`),
never the real `job_platform` database — a safety guard refuses to run if the
test URL isn't clearly distinct. Each test runs inside its own transaction,
rolled back afterward, so nothing persists and tests never see each other's
rows.

**Isolated Redis**: integration tests use Redis DB index `1` (new
`TEST_REDIS_URL` setting) — never DB `0` (development/rate-limiting). Cleanup
deletes only the specific keys a test created, never `FLUSHDB`/`FLUSHALL`.

**E2E (Playwright)**: runs against the real local Docker Compose stack, not a
Playwright-managed server:

```bash
docker compose up -d
python backend/scripts/seed_e2e_fixtures.py     # seeds 25 deterministic
                                                  # fixture jobs, source="e2e_fixture"
cd frontend && npm run e2e
python ../backend/scripts/seed_e2e_fixtures.py --cleanup   # removes only
                                                              # source="e2e_fixture" rows
```

Real, live-validated numbers (see `progress.md` for the full record): backend
421/421 passing (413 pre-existing + 8 new integration tests), frontend 56/56
plus 1 passing E2E test, `pytest -m "not integration"` confirmed to need no
Docker at all, a deliberately-introduced failing test confirmed `pytest`
returns a real non-zero exit code, and the real `job_platform`
database/Redis DB 0 confirmed untouched (row/key counts checked before and
after) by every integration/E2E run including their own cleanup steps.

No coverage percentage gate is enforced (`pytest-cov` is wired in
diagnostically only, since STORY-054's own literal AC specifies none).

Connectors are tested against recorded/mocked responses only; nothing here
makes a live call to an external job source.

## Continuous Integration

**Implemented** (STORY-053): `.github/workflows/ci.yml` runs on every pull
request targeting `main`, every push to `main`, and manually via
`workflow_dispatch`. Three independent jobs run in parallel — a failing job
is separately diagnosable from the others, and none swallow a failure
(`|| true`/`continue-on-error` are never used):

- **`backend`** — Python 3.11.9 (matching `backend/Dockerfile`), the full
  `pytest` suite (fast + integration together) against real Postgres 16.4 /
  Redis 7.4 GitHub Actions service containers (the same versions
  `docker-compose.yml` pins), `alembic check` for migration/model drift, and
  `pip-audit`.
- **`frontend`** — Node 22.11.0 (matching `frontend/Dockerfile`), `npm ci`
  (lockfile-exact, never `npm install`), `npm test`, `npm run build` (real
  TypeScript type-checking via Next.js's own build step), and `npm audit`.
- **`docker-validate`** — `docker compose config` against a placeholder
  `.env` (copied from `.env.example`, never a real one) — syntax/variable-
  reference validation only, no image build, no container startup.

All service credentials in the workflow are fake, CI-only values, never
reused anywhere real. No GitHub Secrets are required for a normal PR.

**Known, deliberate gap**: this repository has no lint tooling configured
for either language (no ruff/mypy/flake8, no ESLint config) — CI therefore
does not run a lint step for either backend or frontend, and backend has no
static type-checking. Frontend *type-checking* is still covered (via
`next build`); frontend *lint* and all backend static analysis are not.
Recorded as a Decision in `progress.md` rather than invented ad hoc — adding
either is a small, separate, future change.

**Required-check names**, for anyone configuring GitHub branch protection
manually (not performed by this Story — no tooling here can make that
remote change): `backend`, `frontend`, `docker-validate`.

Local commands above (this section) reproduce every job's checks exactly —
running them before pushing gives the same signal CI will.

## Connector principles

Job data is ingested through a **pluggable connector framework** (STORY-016): each
source implements a common `fetch()` / `normalize()` / `validate()` interface, so
new sources can be added without touching shared scheduling, persistence, or
deduplication logic. **Greenhouse (STORY-018) and Ashby (STORY-019) are both
implemented**, each against its public, unauthenticated Job Board API — both
verified offline (mocked test suites) and once, manually, against each source's
own live public board (Greenhouse: 14 real records; Ashby: 62 real records).
Every connector:

- normalizes listings into the canonical job schema (`requirement.md` §2);
- preserves source provenance (`source`, `source_url`, `source_job_id`) on every
  record, with a link back to the original posting;
- runs through a shared, policy-enforcing HTTP client (STORY-017) rather than making
  ad-hoc requests, so lawful-source restrictions (below) apply uniformly;
- has its failures isolated per source, so one broken source cannot take down
  ingestion for any other (STORY-023).

**Adding a new connector?** See the
[Connector Authoring Guide](docs/CONNECTOR_GUIDE.md) (STORY-020) for the
real, step-by-step sequence — configuration, registration, the
`BaseConnector` contract, normalization rules, the full error/retry
taxonomy, and the required test suite — using Greenhouse and Ashby as
worked examples.

## Lawful-source restrictions

This is a hard constraint on the entire system, not a configurable option
(`requirement.md` §1.2). The platform ingests jobs **only** from lawful, permitted,
authorized, or legitimately public company career pages, ATS APIs/feeds, job boards,
and other approved sources. It will **never**:

- bypass `robots.txt` restrictions where applicable;
- bypass authentication, anti-bot protections, or CAPTCHAs;
- bypass paywalls, rate limits, or other access controls;
- violate a source's Terms of Service.

Any connector or feature that would require circumventing the above is out of scope,
regardless of technical feasibility.

## Contributing

See [`docs/CONTRIBUTING.md`](docs/CONTRIBUTING.md) for branching, commit message, and
pull request conventions (STORY-002).

Before starting implementation work, read `requirement.md` and `progress.md` in
full, inspect the actual repository state, and pick the highest-priority unblocked
Story from the Implementation Sequence in `requirement.md` §5.
