"""Real-Postgres migration coverage (STORY-054).

Complements test_alembic.py's revision-graph-only checks (which never open
a database connection) by actually running `alembic upgrade head` (via the
`db_session`/`_postgres_test_db` fixtures in conftest.py) against a real,
isolated database and confirming the tables it's supposed to create exist.
"""

from __future__ import annotations

import pytest
from sqlalchemy import inspect, text

pytestmark = [pytest.mark.integration, pytest.mark.postgres]

EXPECTED_TABLES = {"jobs", "companies", "sources", "ingestion_runs"}


def test_migrated_test_database_has_expected_tables(db_session) -> None:
    inspector = inspect(db_session.get_bind())
    tables = set(inspector.get_table_names())

    assert EXPECTED_TABLES.issubset(tables)


def test_migrated_test_database_has_the_search_vector_function(db_session) -> None:
    """STORY-057's GIN index depends on `jobs_search_vector_english()`
    existing -- proves the migration that creates it actually ran, not
    just that the migration file exists on disk."""
    result = db_session.execute(
        text("SELECT jobs_search_vector_english('Engineer', 'Acme', 'desc', ARRAY['python'])")
    )
    assert result.scalar() is not None
