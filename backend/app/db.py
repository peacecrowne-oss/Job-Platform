"""SQLAlchemy engine/session management (STORY-007).

No ORM models exist yet (that's STORY-010) — this only provides connection
plumbing: an engine, a session factory, a declarative base for Alembic
(STORY-009) to target, and a retrying connectivity check. Startup ordering
against a healthy Postgres is normally guaranteed by Docker Compose
healthchecks (STORY-005); the retry/backoff here covers the edge case of
running the backend where that guarantee doesn't hold.
"""

import logging
import time

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import DeclarativeBase, sessionmaker

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
        _engine = create_engine(get_settings().database_url, pool_pre_ping=True)
    return _engine


def get_session_factory() -> sessionmaker:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(bind=get_engine(), autoflush=False, autocommit=False)
    return _session_factory


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
