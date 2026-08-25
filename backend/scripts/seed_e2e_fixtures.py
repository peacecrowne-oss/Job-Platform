"""Seeds/cleans up deterministic fixture jobs for the frontend Playwright
E2E suite (STORY-054).

Unlike the pytest-level integration tests (which use the isolated
`job_platform_test` database), E2E deliberately exercises the *real* local
Docker Compose stack end-to-end -- backend, frontend, and the real
`job_platform` database -- per the approved plan's own instruction to test
"using the real local stack".

Safety: every fixture row is tagged `source="e2e_fixture"`, a value no real
connector (`greenhouse`/`ashby`) ever produces. Cleanup deletes only
`WHERE source = 'e2e_fixture'` -- structurally incapable of touching real
ingested data, regardless of how much other data exists in the database.

Usage (from backend/, with the Docker stack's Postgres reachable):
    python scripts/seed_e2e_fixtures.py            # seed (idempotent)
    python scripts/seed_e2e_fixtures.py --cleanup   # remove fixture rows only
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import get_session_factory  # noqa: E402
import app.models.company  # noqa: E402,F401 -- resolves Job.company relationship
from app.models.job import Job  # noqa: E402

FIXTURE_SOURCE = "e2e_fixture"
FIXTURE_COUNT = 25

# The one row the E2E keyword-search step searches for -- a title distinct
# enough not to collide with real ingested data or any other fixture row.
DISTINCTIVE_TITLE = "Principal Distributed Systems Engineer"
DISTINCTIVE_SOURCE_URL = "https://example.com/jobs/e2e-fixture-distinctive"

_WORK_MODES = ["remote", "hybrid", "on_site"]


def _fixture_jobs() -> list[Job]:
    today = date.today()
    jobs = [
        Job(
            source=FIXTURE_SOURCE,
            source_job_id="e2e-fixture-0",
            job_title=DISTINCTIVE_TITLE,
            company_name="Fixture Systems Inc",
            location_country="United States",
            location_region="California",
            location_city="San Francisco",
            work_mode="remote",
            employment_type="full_time",
            seniority="Principal",
            posting_date=today - timedelta(days=1),
            source_url=DISTINCTIVE_SOURCE_URL,
            application_url="https://example.com/apply/e2e-fixture-distinctive",
        )
    ]
    for i in range(1, FIXTURE_COUNT):
        jobs.append(
            Job(
                source=FIXTURE_SOURCE,
                source_job_id=f"e2e-fixture-{i}",
                job_title=f"Fixture Role {i}",
                company_name="Fixture Systems Inc",
                location_country="United States",
                work_mode=_WORK_MODES[i % len(_WORK_MODES)],
                employment_type="full_time",
                posting_date=today - timedelta(days=i),
                source_url=f"https://example.com/jobs/e2e-fixture-{i}",
                application_url=f"https://example.com/apply/e2e-fixture-{i}",
            )
        )
    return jobs


def seed() -> None:
    session = get_session_factory()()
    try:
        session.query(Job).filter(Job.source == FIXTURE_SOURCE).delete()
        session.add_all(_fixture_jobs())
        session.commit()
        print(f"Seeded {FIXTURE_COUNT} fixture jobs (source={FIXTURE_SOURCE!r}).")
    finally:
        session.close()


def cleanup() -> None:
    session = get_session_factory()()
    try:
        deleted = session.query(Job).filter(Job.source == FIXTURE_SOURCE).delete()
        session.commit()
        print(f"Removed {deleted} fixture job(s) (source={FIXTURE_SOURCE!r}).")
    finally:
        session.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cleanup", action="store_true", help="Remove fixture rows instead of seeding")
    args = parser.parse_args()

    cleanup() if args.cleanup else seed()
