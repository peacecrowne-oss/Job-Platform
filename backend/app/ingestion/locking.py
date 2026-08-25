"""PostgreSQL session-scoped advisory locking (STORY-021).

Prevents two scheduler processes (or two overlapping loop iterations)
from running the same `Source` concurrently. Chosen over a Redis lock
because Postgres is already a hard dependency for everything in this app
(no fail-open story exists for it anywhere) -- this adds zero new
infrastructure and needs no TTL: a *session*-scoped advisory lock's
lifetime is tied to the underlying connection, not a timer, so it can
never expire mid-run (too early) or outlive a crashed process (too late).
If the process holding it dies, its connection drops and Postgres itself
releases every session-level advisory lock that connection held -- no
stale-lock cleanup code needed anywhere.

Two-int lock identity (`pg_try_advisory_lock(key1, key2)`): `key1` is a
fixed namespace constant so this Story's locks can never collide with any
future, unrelated use of advisory locks elsewhere in this codebase;
`key2` is `hashtext(source_id::text)`, Postgres's own built-in 32-bit
hash -- no custom UUID-to-bigint conversion needed in Python.

Deliberately holds a *separate*, raw `engine.connect()` for the lock only,
not the ORM session used for the actual data writes -- this decouples the
lock's lifetime (the whole per-source run) from the data session's own
commit boundaries (several small commits within that same run, per the
approved plan's Transaction Boundaries section).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

_LOCK_NAMESPACE = 21  # STORY-021 -- fixed, so future advisory-lock use can't collide


@contextmanager
def source_refresh_lock(engine: Engine, source_id: uuid.UUID) -> Iterator[bool]:
    """Context manager yielding True if the lock was acquired, False if
    another connection already holds it (caller should skip this source
    for this cycle, not wait or retry). Always releases on exit if it was
    acquired -- explicit `pg_advisory_unlock`, with Postgres's own
    connection-drop release as the crash-safety net if that never runs."""
    connection = engine.connect()
    try:
        acquired = connection.execute(
            text("SELECT pg_try_advisory_lock(:namespace, hashtext(:source_id))"),
            {"namespace": _LOCK_NAMESPACE, "source_id": str(source_id)},
        ).scalar()
        try:
            yield bool(acquired)
        finally:
            if acquired:
                connection.execute(
                    text("SELECT pg_advisory_unlock(:namespace, hashtext(:source_id))"),
                    {"namespace": _LOCK_NAMESPACE, "source_id": str(source_id)},
                )
    finally:
        connection.close()
