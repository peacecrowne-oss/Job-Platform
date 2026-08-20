# Job Opportunity Aggregation & Job-Seeking Platform

> **Status: early repository scaffolding.** Repository structure, environment
> configuration, documentation, a minimal backend API foundation (health check
> only), a minimal frontend foundation (placeholder home page only), a full
> local Docker Compose stack (backend, frontend, Postgres, Redis, all with
> healthchecks), backend connection plumbing to Postgres/Redis, the Alembic
> migration framework, the canonical `jobs`/`companies`/`sources`/
> `ingestion_runs` table schemas, a pluggable connector framework (interface
> + registry, no real connector yet), and a lawful-access policy-enforcing
> HTTP client (robots.txt, rate-limit honoring, response-code refusal) exist
> so far. No real connectors or CI have been implemented yet — none of the
> tables have rows written by any real pipeline, just the schema itself (and
> a handful of manual rows used to validate constraints during
> implementation, since removed). See
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
Frontend rows have minimal foundations only: the backend is app bootstrap,
configuration, `/health`, error handling, and now a SQLAlchemy engine/session and
a Redis client with verified real connectivity (no models, no auth, no product
endpoints); the frontend is a single placeholder page (no search, job listings, or
auth UI). Containerization is implemented end-to-end: individual `Dockerfile`s for
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
is ever constructed. Still no real connector (Greenhouse/Ashby) and no SSRF
protection (STORY-046) — `PolicyEnforcingHttpClient`'s transport has no
IP-range awareness yet; the only implementations anywhere are fake
connectors/transports used in tests. Every other row is not yet
implemented.

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
frontend/app/           App Router: root layout + placeholder home page (STORY-013)
frontend/lib/           Environment-driven config (API base URL)
frontend/tests/         Frontend test suite (vitest; STORY-013 tests only so far)
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
                                      (STORY-016; +3 classes STORY-017)
backend/app/connectors/http_client.py  PolicyEnforcingHttpClient, UrllibTransport,
                                        robots.txt/crawl-delay/response-code policy (STORY-017)
backend/app/connectors/policy.py     require_source_authorized() pre-flight gate (STORY-017)
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

This serves the current backend foundation, which only exposes `GET /health`. There
is no database connection, authentication, or product API yet — those belong to
later Stories.

Frontend (STORY-013 — foundation only; a single placeholder page, no product UI):

```bash
cd frontend
npm ci
npm run dev
```

Serves the placeholder home page at `http://localhost:3000`, reading
`NEXT_PUBLIC_API_BASE_URL` from the repository-root `.env` (copied above). If that
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

This builds and starts all 4 services — `backend`, `frontend`, `postgres`,
`redis` — wired together on one Docker network, reading configuration from the
same root `.env` used for local (non-Docker) development. `backend` waits for
`postgres` and `redis` to report healthy (via their own healthchecks, not a fixed
sleep) before starting; each service has its own healthcheck. Verify everything
came up:

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
all via a fake transport (STORY-017)). They require no external
infrastructure or network access — everything is tested via mocks,
on-disk config parsing, or SQLAlchemy metadata introspection, never a live
connection:

```bash
cd backend
pip install -r requirements-dev.txt
pytest
```

**Frontend foundation tests are implemented and runnable** (STORY-013 scope only —
the environment-driven API base URL logic, including its "fails visibly when
missing/invalid" behavior). They require no external infrastructure:

```bash
cd frontend
npm ci
npm test
```

A full backend/frontend testing strategy — integration tests against an isolated
test database, broader frontend unit/component coverage, and Playwright end-to-end
coverage — is **not yet implemented**; that is tracked separately as STORY-054.

Connectors will be tested against recorded/mocked responses only; CI will never make
live calls to external job sources.

## Connector principles

Job data is ingested through a **pluggable connector framework** (STORY-016): each
source (e.g. Greenhouse, Ashby) implements a common `fetch()` / `normalize()` /
`validate()` interface, so new sources can be added without touching shared
scheduling, persistence, or deduplication logic. Every connector:

- normalizes listings into the canonical job schema (`requirement.md` §2);
- preserves source provenance (`source`, `source_url`, `source_job_id`) on every
  record, with a link back to the original posting;
- runs through a shared, policy-enforcing HTTP client (STORY-017) rather than making
  ad-hoc requests, so lawful-source restrictions (below) apply uniformly;
- has its failures isolated per source, so one broken source cannot take down
  ingestion for any other (STORY-023).

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
