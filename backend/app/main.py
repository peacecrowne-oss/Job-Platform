"""Backend API application foundation (STORY-012).

Provides an application-factory so tests can construct isolated app
instances against different settings, per STORY-012's technical notes.
Only foundation concerns live here: app creation, metadata, routing
bootstrap, and structured error handling. Feature routers (jobs, search,
auth, etc.) belong to their own later Stories and are not added here.
"""

from fastapi import FastAPI

from app.api import health
from app.config import get_settings
from app.errors import register_exception_handlers


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
    )

    register_exception_handlers(app)

    app.include_router(health.router)

    return app


app = create_app()
