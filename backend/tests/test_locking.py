"""Tests for app.ingestion.locking (STORY-021) -- real Postgres advisory
locks, since the whole point is verifying cross-connection mutual
exclusion, which no mock can meaningfully stand in for.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine

from app.ingestion.locking import source_refresh_lock

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def test_lock_is_acquired_when_free(db_session_committing) -> None:
    engine = db_session_committing.get_bind()
    source_id = uuid.uuid4()

    with source_refresh_lock(engine, source_id) as acquired:
        assert acquired is True


def test_second_connection_cannot_acquire_a_held_lock(_postgres_test_db) -> None:
    engine_a = create_engine(_postgres_test_db, connect_args={"connect_timeout": 2})
    engine_b = create_engine(_postgres_test_db, connect_args={"connect_timeout": 2})
    source_id = uuid.uuid4()

    try:
        with source_refresh_lock(engine_a, source_id) as acquired_a:
            assert acquired_a is True
            with source_refresh_lock(engine_b, source_id) as acquired_b:
                assert acquired_b is False  # already held by engine_a's connection
    finally:
        engine_a.dispose()
        engine_b.dispose()


def test_lock_is_released_after_the_context_exits(_postgres_test_db) -> None:
    engine = create_engine(_postgres_test_db, connect_args={"connect_timeout": 2})
    source_id = uuid.uuid4()

    try:
        with source_refresh_lock(engine, source_id):
            pass

        with source_refresh_lock(engine, source_id) as acquired_again:
            assert acquired_again is True  # released -- available again
    finally:
        engine.dispose()


def test_crashed_connection_releases_the_lock(_postgres_test_db) -> None:
    """Simulates a crash: the lock-holding connection is torn down (not
    just returned to its pool -- plain Connection.close() would leave the
    real backend connection alive and pooled for reuse, which is not what
    a crash looks like) without ever calling pg_advisory_unlock -- Postgres
    itself must release a session-level advisory lock when the connection
    actually disconnects."""
    engine_a = create_engine(_postgres_test_db, connect_args={"connect_timeout": 2})
    engine_b = create_engine(_postgres_test_db, connect_args={"connect_timeout": 2})
    source_id = uuid.uuid4()

    try:
        from sqlalchemy import text

        connection = engine_a.connect()
        connection.execute(
            text("SELECT pg_try_advisory_lock(21, hashtext(:source_id))"),
            {"source_id": str(source_id)},
        )
        connection.close()
        engine_a.dispose()  # actually tears down the pooled connection -- the real "crash"

        with source_refresh_lock(engine_b, source_id) as acquired:
            assert acquired is True  # Postgres released it on disconnect
    finally:
        engine_a.dispose()
        engine_b.dispose()


def test_different_sources_do_not_contend(_postgres_test_db) -> None:
    engine_a = create_engine(_postgres_test_db, connect_args={"connect_timeout": 2})
    engine_b = create_engine(_postgres_test_db, connect_args={"connect_timeout": 2})

    try:
        with source_refresh_lock(engine_a, uuid.uuid4()) as acquired_a:
            assert acquired_a is True
            with source_refresh_lock(engine_b, uuid.uuid4()) as acquired_b:
                assert acquired_b is True
    finally:
        engine_a.dispose()
        engine_b.dispose()
