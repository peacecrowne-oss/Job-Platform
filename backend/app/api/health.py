"""Health endpoint (STORY-012).

This is a basic liveness-style check only: it reports that the process is up
without depending on any downstream service being reachable, per STORY-012's
edge case note. Readiness (dependency connectivity) is explicitly out of
scope here and belongs to STORY-052.
"""

from fastapi import APIRouter, Depends

from app.config import Settings, get_settings

router = APIRouter(tags=["health"])


@router.get("/health")
def get_health(settings: Settings = Depends(get_settings)) -> dict[str, str]:
    return {
        "status": "ok",
        "service": settings.app_name,
        "environment": settings.app_env,
    }
