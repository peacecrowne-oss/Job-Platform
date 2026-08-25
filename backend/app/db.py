"""SQLAlchemy engine/session management (STORY-007).

No ORM models exist yet (that's STORY-010) — this only provides connection
plumbing: an engine, a session factory, a declarative base for Alembic
(STORY-009) to target, and a retrying connectivity check. Startup ordering
against a healthy Postgres is normally guaranteed by Docker Compose
healthchecks (STORY-005); the retry/backoff here covers the edge case of
running the backend where that guarantee doesn't hold.

check_database_connection(max_attempts=1) (STORY-052) reuses this exact
function, unmodified, as the Postgres readiness check -- a single bounded
attempt, no retry loop; retries remain this function's own default
behavior for the startup use case, a separate concern.
"""

import logging
import time
from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """Shared declarative base for future ORM models (STORY-010+).

    Empty today — Alembic's env.py targets this class's metadata so future
    models registered against it are picked up for autogeneration without
    any further Alembic configuration changes.
    """


_engine: Engine | None = None
_session_factory: sessionmaker | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        # connect_args={"connect_timeout": ...} (STORY-052) only bounds
        # establishing a *new* connection -- never query execution time on
        # an already-pooled one -- so this is safe for normal traffic and
        # also directly benefits it: previously unbounded, a genuinely
        # unreachable Postgres could hang for an OS-default duration far
        # longer than any caller (including the STORY-052 readiness check,
        # which needs this to fail fast) would want to wait.
        _engine = create_engine(
            get_settings().database_url,
            pool_pre_ping=True,
            connect_args={"connect_timeout": int(get_settings().health_check_timeout_seconds)},
        )
    return _engine


def get_session_factory() -> sessionmaker:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(bind=get_engine(), autoflush=False, autocommit=False)
    return _session_factory


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a request-scoped Session (STORY-030 --
    the first Story to wire a route to the database). Closes the session
    after the request regardless of outcome; does not commit -- read-only
    routes have nothing to commit, and any future write route owns its own
    transaction boundary explicitly, per this repo's established
    convention (see app/ingestion/dedup.py's upsert_job())."""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def check_database_connection(max_attempts: int = 5, initial_delay: float = 0.5) -> bool:
    """Run a trivial query against Postgres, retrying with exponential backoff.

    Never raises — returns False if every attempt fails, so callers can
    decide how to react instead of crashing.
    """
    delay = initial_delay
    for attempt in range(1, max_attempts + 1):
        try:
            with get_engine().connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        except OperationalError as exc:
            logger.warning(
                "Database connection attempt %s/%s failed: %s", attempt, max_attempts, exc
            )
            if attempt == max_attempts:
                return False
            time.sleep(delay)
            delay *= 2
    return False
