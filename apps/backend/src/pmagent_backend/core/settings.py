from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo-root .env, so settings load the same from any working directory
# (uvicorn at the root, alembic in apps/backend). Real env vars take precedence.
REPO_ROOT_ENV = Path(__file__).resolve().parents[5] / ".env"

_CONFIG = SettingsConfigDict(
    env_prefix="PMAGENT_", env_file=(REPO_ROOT_ENV, ".env"), extra="ignore"
)


class DatabaseSettings(BaseSettings):
    """Just what migrations and test setup need, so they don't require app secrets."""

    model_config = _CONFIG

    # Required, no default: credentials only ever come from the environment / .env.
    database_url: str
    database_echo: bool = False


class Settings(DatabaseSettings):
    model_config = _CONFIG

    env: str = "development"
    log_level: str = "INFO"
    log_json: bool = True
    redis_url: str = "redis://localhost:6379/0"
    cors_origins: list[str] = ["http://localhost:3000"]
    # Swagger UI (/docs), ReDoc (/redoc), and /openapi.json. Turn off to hide the API surface.
    docs_enabled: bool = True

    # Auth. The secret is required and never has a default.
    jwt_secret: SecretStr = Field(min_length=32)
    jwt_issuer: str = "pmagent"
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 30
    email_verification_ttl_hours: int = 48
    password_reset_ttl_minutes: int = 60

    # Base URL of the web app, used to build links in emails.
    app_url: str = "http://localhost:3000"
    # "console" logs emails (development only); real providers come later.
    email_backend: str = "console"

    @model_validator(mode="after")
    def _safe_for_production(self) -> Settings:
        if self.env == "production" and self.email_backend == "console":
            raise ValueError("email_backend=console logs tokens; not allowed in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # values come from the environment


@lru_cache
def get_database_settings() -> DatabaseSettings:
    return DatabaseSettings()  # type: ignore[call-arg]
