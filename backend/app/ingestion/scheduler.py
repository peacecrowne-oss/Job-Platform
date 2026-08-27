"""Scheduler process entry point (STORY-021).

Deliberately a thin wrapper -- all real logic lives in
`app.ingestion.orchestrator`, which has no sleep loop and is directly unit
testable. This module's only job is "call that, then wait, forever."

Runs as its own Docker Compose service (`scheduler`), reusing the backend
image with a different command (`python -m app.ingestion.scheduler`) --
no duplicated application source, no new image.

Why not Celery beat/APScheduler (per the approved architecture decision):
at this project's current scale (two connector types, a handful of
Source rows), a broker-backed task queue and a beat scheduler buy nothing
this literal FR asks for, while adding real new infrastructure (a broker,
a worker pool, task serialization) this codebase has never needed before.
Nothing here forecloses adopting Celery later -- the orchestration logic
itself has no sleep loop baked into it, so swapping this thin wrapper for
a Celery beat schedule later would not require touching
app/ingestion/orchestrator.py at all.
"""

from __future__ import annotations

import logging
import time

from app.config import get_settings
from app.db import get_session_factory
from app.ingestion.orchestrator import run_all_due_sources
from app.logging_config import configure_logging

# STORY-050: NOT logging.getLogger(__name__) -- when this module is run as
# the entry point (`python -m app.ingestion.scheduler`), __name__ becomes
# "__main__", not "app.ingestion.scheduler", which would put this logger
# outside the "app" logger tree entirely (a real bug caught during live
# Docker validation: the "Scheduler started" line was silently dropped --
# "__main__" has no handler of its own and only WARNING+ reaches Python's
# last-resort handler). A hardcoded name keeps this logger under "app"
# regardless of how the module is invoked.
logger = logging.getLogger("app.ingestion.scheduler")


def run_forever() -> None:
    settings = get_settings()

    if not settings.scheduler_enabled:
        logger.info("Scheduler disabled (scheduler_enabled=False) -- exiting.")
        return

    logger.info(
        "Scheduler started -- polling every %s seconds.", settings.scheduler_poll_interval_seconds
    )
    while True:
        session = get_session_factory()()
        try:
            runs = run_all_due_sources(session)
            if runs:
                logger.info("Completed %d ingestion run(s) this cycle.", len(runs))
        except Exception:  # noqa: BLE001 -- the loop must survive an unexpected error and keep polling
            logger.exception("Unexpected error in scheduler cycle")
        finally:
            session.close()

        time.sleep(settings.scheduler_poll_interval_seconds)


if __name__ == "__main__":
    configure_logging(get_settings().log_level)  # STORY-050: JSON output, same as the API
    run_forever()
