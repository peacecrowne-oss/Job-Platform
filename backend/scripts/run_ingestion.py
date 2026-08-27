"""Manual ingestion runner (STORY-021).

Exposes the same orchestration the scheduler uses, independent of its
sleep loop -- for local debugging, one-off runs, and any future external
scheduler (host cron, k8s CronJob) that would rather invoke a command than
run a long-lived process. Deliberately CLI-only, not an HTTP endpoint --
"run ingestion now" is not exposed unauthenticated over the network.

Usage (from backend/, with Postgres reachable):
    python scripts/run_ingestion.py                    # run every due, enabled source
    python scripts/run_ingestion.py --source-id <uuid>  # run one source now, ignoring due-check
"""

from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings  # noqa: E402
from app.db import get_session_factory  # noqa: E402
from app.ingestion.orchestrator import run_all_due_sources, run_source  # noqa: E402
from app.logging_config import configure_logging  # noqa: E402
from app.models.source import Source  # noqa: E402


def main() -> None:
    configure_logging(get_settings().log_level)  # STORY-050: JSON output, same as the API/scheduler
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-id",
        type=str,
        default=None,
        help="Run this one source now, ignoring its due-check (still respects enabled/lock).",
    )
    args = parser.parse_args()

    session = get_session_factory()()
    try:
        if args.source_id:
            source = session.get(Source, uuid.UUID(args.source_id))
            if source is None:
                print(f"No source with id {args.source_id}", file=sys.stderr)
                sys.exit(1)
            run = run_source(session, source)
            print(f"Run {run.id}: status={run.status} jobs_seen={run.jobs_seen}")
        else:
            runs = run_all_due_sources(session)
            print(f"Completed {len(runs)} run(s).")
            for run in runs:
                print(f"  {run.id}: source_id={run.source_id} status={run.status}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
