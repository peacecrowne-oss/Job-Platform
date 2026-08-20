"""Tests for app.db that don't require a live Postgres (STORY-007)."""

import time
from unittest.mock import MagicMock, patch

from sqlalchemy.exc import OperationalError

from app import db as db_module


def test_get_engine_returns_same_instance() -> None:
    assert db_module.get_engine() is db_module.get_engine()


def test_get_session_factory_returns_same_instance() -> None:
    assert db_module.get_session_factory() is db_module.get_session_factory()


def test_check_database_connection_retries_then_succeeds(monkeypatch) -> None:
    monkeypatch.setattr(time, "sleep", lambda _: None)
    attempts = {"n": 0}

    class FlakyConn:
        def __enter__(self):
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise OperationalError("stmt", {}, Exception("boom"))
            return self

        def __exit__(self, *args):
            return False

        def execute(self, *args, **kwargs):
            return None

    fake_engine = MagicMock()
    fake_engine.connect.return_value = FlakyConn()

    with patch.object(db_module, "get_engine", return_value=fake_engine):
        result = db_module.check_database_connection(max_attempts=5, initial_delay=0.01)

    assert result is True
    assert attempts["n"] == 3


def test_check_database_connection_returns_false_after_exhausting_retries(monkeypatch) -> None:
    monkeypatch.setattr(time, "sleep", lambda _: None)

    class AlwaysFailConn:
        def __enter__(self):
            raise OperationalError("stmt", {}, Exception("boom"))

        def __exit__(self, *args):
            return False

    fake_engine = MagicMock()
    fake_engine.connect.return_value = AlwaysFailConn()

    with patch.object(db_module, "get_engine", return_value=fake_engine):
        result = db_module.check_database_connection(max_attempts=3, initial_delay=0.01)

    assert result is False
