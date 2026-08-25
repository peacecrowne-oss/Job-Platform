"""Typed application settings, sourced from environment variables / `.env`.

Field names correspond to the variables listed in the repository-root
`.env.example` (STORY-006). No default here is a secret — `.env.example`
documents the same placeholder values.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Job Platform API"
    app_env: str = "development"
    log_level: str = "info"
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000
    database_url: str = "postgresql+psycopg2://job_platform:changeme@postgres:5432/job_platform"
    redis_url: str = "redis://redis:6379/0"
    # Platform-wide identifying User-Agent for all outbound connector
    # requests (STORY-017) -- not per-source, not a secret.
    ingestion_user_agent: str = "JobPlatformBot/1.0"
    # The frontend's origin (STORY-035) -- the only origin allowed to read
    # cross-origin responses from this API. Not a secret; scoped to exactly
    # one origin rather than a wildcard.
    cors_allowed_origin: str = "http://localhost:3000"
    # Per-IP rate limit for public endpoints (STORY-045) -- a fixed window
    # of this many requests per rate_limit_window_seconds. Not a secret.
    rate_limit_requests: int = 60
    rate_limit_window_seconds: int = 60
    # Bounded connection timeout, in seconds, for both the Postgres and
    # Redis clients (STORY-052) -- one shared value, no literal requirement
    # demands per-dependency configurability. Keeps readiness fast and
    # bounded, and also hardens both clients' real traffic against
    # indefinite hangs on genuine network unreachability (previously
    # unbounded). Not a secret.
    health_check_timeout_seconds: float = 2.0
    # STORY-054: an isolated database/Redis DB-index for the integration
    # test suite -- same containers as dev (no second Postgres/Redis
    # service), but a distinct database name / DB index so tests can never
    # collide with or destroy development data. Not a secret.
    test_database_url: str = "postgresql+psycopg2://job_platform:changeme@postgres:5432/job_platform_test"
    test_redis_url: str = "redis://redis:6379/1"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
