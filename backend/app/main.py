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

Structured logging (STORY-050): `configure_logging()` is called once here
so every `app.*` logger anywhere in the codebase gets JSON output and an
injected correlation ID, without touching any of those existing call
sites. `CorrelationIdMiddleware` is added *after* CORS deliberately --
Starlette applies middleware in reverse-registration order, so this makes
the correlation ID available for the entire remaining request lifecycle,
including CORS's own processing.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import health, search, sources
from app.config import get_settings
from app.errors import register_exception_handlers
from app.logging_config import CorrelationIdMiddleware, configure_logging


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

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
    app.add_middleware(CorrelationIdMiddleware)

    register_exception_handlers(app)

    app.include_router(health.router)
    app.include_router(search.router)
    app.include_router(sources.router)

    return app


app = create_app()
