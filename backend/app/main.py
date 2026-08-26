"""Backend API application foundation (STORY-012).

Provides an application-factory so tests can construct isolated app
instances against different settings, per STORY-012's technical notes.
Only foundation concerns live here: app creation, metadata, routing
bootstrap, and structured error handling. Feature routers (jobs, auth,
etc.) belong to their own later Stories and are not added here. The
search router (STORY-030) is the first feature router, now wired in.

CORS (STORY-035): the frontend (a different origin -- localhost:3000 vs
this API's localhost:8000) fetches directly from the browser, which the
browser blocks without an explicit Access-Control-Allow-Origin response
header, regardless of how correct the frontend code is. Scoped to exactly
`settings.cors_allowed_origin` and GET only -- the only method this API
exposes -- not a wildcard.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import health, search, sources
from app.config import get_settings
from app.errors import register_exception_handlers


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.cors_allowed_origin],
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)

    app.include_router(health.router)
    app.include_router(search.router)
    app.include_router(sources.router)

    return app


app = create_app()
