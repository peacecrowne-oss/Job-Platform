"""Application-foundation tests for STORY-012.

Verifies the app can be imported, instantiated via the factory, and that
routing/bootstrap does not fail — without requiring any external
infrastructure (no live Postgres, Redis, network, or ATS services).
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import app, create_app


def test_create_app_returns_fastapi_instance() -> None:
    application = create_app()

    assert isinstance(application, FastAPI)


def test_create_app_uses_configured_metadata() -> None:
    application = create_app()

    assert application.title == "Job Platform API"
    assert application.version == "0.1.0"


def test_module_level_app_is_importable_and_usable() -> None:
    assert isinstance(app, FastAPI)


def test_test_client_initializes_successfully() -> None:
    client = TestClient(app)

    assert client is not None


def test_factory_produces_independent_app_instances() -> None:
    first = create_app()
    second = create_app()

    assert first is not second
