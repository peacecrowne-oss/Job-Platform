"""Shared pytest fixtures for STORY-054's Postgres/Redis integration tests.

Integration tests reuse the same Docker Compose containers as local
development, but a *separate* database (`job_platform_test`, via the new
`test_database_url` setting) / Redis DB index (`1`, via `test_redis_url`)
-- never the real `job_platform` database or Redis DB `0`. Every fixture
that could perform a destructive operation asserts this isolation first
(`_assert_isolated_from_development`), so a misconfigured
TEST_DATABASE_URL/TEST_REDIS_URL can never point at development data and
have something happen to it.

Tests requesting these fixtures are skipped (not failed) if Postgres/
Redis aren't reachable -- `pytest -m "not integration"` never needs
Docker at all; `pytest -m integration` requires it running.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
import redis as redis_lib
from redis.exceptions import RedisError
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _assert_isolated_from_development(test_url: str, dev_url: str, must_contain: str) -> None:
    """Refuse to proceed unless the test URL is clearly distinct from the
    real, configured development URL -- the safety guard STORY-054's plan
    requires before any destructive test operation runs."""
    if test_url == dev_url:
        raise RuntimeError(
            "Refusing to run: the test URL is identical to the development URL. "
            "This guard exists specifically so a misconfigured "
            "TEST_DATABASE_URL/TEST_REDIS_URL can never cause a destructive test "
            "operation to hit real data."
        )
    if must_contain not in test_url:
        raise RuntimeError(
            f"Refusing to run: expected {must_contain!r} in the test URL, got "
            f"{test_url!r}. This guard exists to prevent destructive test "
            "operations from targeting an unexpected database."
        )


@pytest.fixture(scope="session")
def _postgres_test_db() -> str | None:
    """Creates (if needed) the isolated test database and migrates it to
    head via the real `alembic` CLI (a subprocess, not `command.upgrade()`
    in-process -- alembic/env.py always re-reads `Settings.database_url`
    itself, so the only reliable way to point it at a different URL is via
    the DATABASE_URL environment variable, not the Config object).
    Returns the test database URL, or None if Postgres is unreachable
    (callers should skip rather than fail)."""
    settings = get_settings()
    test_url = settings.test_database_url
    dev_url = settings.database_url

    _assert_isolated_from_development(test_url, dev_url, "job_platform_test")

    test_db_name = test_url.rsplit("/", 1)[-1]
    maintenance_url = test_url.rsplit("/", 1)[0] + "/postgres"

    try:
        maintenance_engine = create_engine(maintenance_url, connect_args={"connect_timeout": 2})
        with maintenance_engine.connect() as conn:
            conn = conn.execution_options(isolation_level="AUTOCOMMIT")
            try:
                conn.execute(text(f'CREATE DATABASE "{test_db_name}"'))
            except ProgrammingError as exc:
                if "already exists" not in str(exc).lower():
                    raise
        maintenance_engine.dispose()
    except OperationalError:
        return None

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_DIR,
        env={**os.environ, "DATABASE_URL": test_url},
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"alembic upgrade head against the test database failed:\n{result.stderr}"
        )

    return test_url


@pytest.fixture
def db_session(_postgres_test_db: str | None) -> Session:
    """A Session bound to a connection with its own open transaction
    against the isolated test database. Rolled back after the test --
    nothing persists, and tests never see each other's rows."""
    if _postgres_test_db is None:
        pytest.skip("Postgres is not reachable -- start Docker Compose to run integration tests")

    engine = create_engine(_postgres_test_db, connect_args={"connect_timeout": 2})
    connection = engine.connect()
    transaction = connection.begin()
    session = sessionmaker(bind=connection)()

    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
        engine.dispose()


# STORY-021: unlike `db_session` above, code under test here (the ingestion
# orchestrator) calls `session.commit()` itself, more than once, as part of
# its own approved transaction-boundary design -- a Session bound to a
# connection with an already-open outer transaction would need SQLAlchemy's
# SAVEPOINT-restarting "join an external transaction" machinery to make
# those inner commits safe to roll back, which `db_session` above doesn't
# have. Simpler and just as safe here: a plain, real Session against the
# same isolated `job_platform_test` database (same safety guard, same
# unreachable-Postgres skip), with an explicit TRUNCATE of the tables this
# fixture touches before *and* after each test -- safe specifically because
# this is always the already-guarded, disposable test database, never an
# arbitrary one.
_TRUNCATE_TABLES = ("ingestion_runs", "jobs", "sources")


@pytest.fixture
def db_session_committing(_postgres_test_db: str | None) -> Session:
    if _postgres_test_db is None:
        pytest.skip("Postgres is not reachable -- start Docker Compose to run integration tests")

    engine = create_engine(_postgres_test_db, connect_args={"connect_timeout": 2})
    session = sessionmaker(bind=engine)()

    def _truncate() -> None:
        session.execute(text(f"TRUNCATE {', '.join(_TRUNCATE_TABLES)} RESTART IDENTITY CASCADE"))
        session.commit()

    _truncate()
    try:
        yield session
    finally:
        session.rollback()
        _truncate()
        session.close()
        engine.dispose()


class RedisTestNamespace:
    """Wraps a real Redis client bound to the isolated test DB index.
    Cleanup deletes only keys explicitly tracked via `.key()`/`.track()`
    -- never FLUSHDB/FLUSHALL, so unrelated Redis data is never at risk."""

    def __init__(self, client: redis_lib.Redis, node_id: str) -> None:
        self.client = client
        self._node_id = node_id
        self._created: list[str] = []

    def key(self, name: str) -> str:
        """Generate and track a namespaced key unique to this test."""
        namespaced = f"pytest:{self._node_id}:{name}"
        self._created.append(namespaced)
        return namespaced

    def track(self, key: str) -> str:
        """Track an already-known key (e.g. one the code under test
        derived internally) for cleanup, without renaming it."""
        self._created.append(key)
        return key

    def cleanup(self) -> None:
        if self._created:
            self.client.delete(*self._created)


@pytest.fixture
def redis_test_client(request: pytest.FixtureRequest) -> RedisTestNamespace:
    """A RedisTestNamespace bound to the isolated test Redis DB index --
    never index 0 (development)."""
    settings = get_settings()
    test_url = settings.test_redis_url
    dev_url = settings.redis_url

    _assert_isolated_from_development(test_url, dev_url, "/1")

    client = redis_lib.from_url(test_url, socket_connect_timeout=2, socket_timeout=2)
    try:
        client.ping()
    except RedisError:
        pytest.skip("Redis is not reachable -- start Docker Compose to run integration tests")

    namespace = RedisTestNamespace(client, request.node.nodeid)
    try:
        yield namespace
    finally:
        namespace.cleanup()
        client.close()
