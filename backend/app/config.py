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

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
