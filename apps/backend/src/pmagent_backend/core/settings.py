from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, model_validator
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
    # 127.0.0.1, not localhost: on Windows "localhost" tries IPv6 first and stalls.
    redis_url: str = "redis://127.0.0.1:6379/0"
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

    # Object storage for document originals: any S3-compatible store (MinIO locally).
    # Leave the endpoint and keys unset to run without uploads (they answer 503).
    s3_endpoint_url: str | None = None
    s3_access_key: SecretStr | None = None
    s3_secret_key: SecretStr | None = None
    s3_bucket: str = "pmagent-documents"
    s3_region: str = "us-east-1"
    max_upload_mb: int = Field(default=25, ge=1, le=200)

    # Model provider keys. Read under their usual names (no PMAGENT_ prefix), so the
    # same .env works for the CLI. A project's model ("anthropic:...") needs its key.
    anthropic_api_key: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("ANTHROPIC_API_KEY", "PMAGENT_ANTHROPIC_API_KEY")
    )
    openai_api_key: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("OPENAI_API_KEY", "PMAGENT_OPENAI_API_KEY")
    )
    google_api_key: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("GOOGLE_API_KEY", "PMAGENT_GOOGLE_API_KEY")
    )
    # Model for new projects ("provider:model"); each project can change its own.
    default_model: str = "anthropic:claude-sonnet-5"
    # Where agent runs execute:
    # - "local": background tasks in the API process (simplest; an API restart cuts runs off)
    # - "worker": queued in Redis and executed by `python -m pmagent_backend.worker`; runs
    #   survive API restarts, and a worker that dies has its run retried
    # - "inline": inside the request (tests, debugging)
    agent_runs: Literal["local", "worker", "inline"] = "local"
    # End-to-end tests only: allow the deterministic "e2e:rules" model (no API key, no cost).
    e2e_models: bool = False

    @model_validator(mode="after")
    def _safe_for_production(self) -> Settings:
        if self.env == "production" and self.email_backend == "console":
            raise ValueError("email_backend=console logs tokens; not allowed in production")
        if self.env == "production" and self.e2e_models:
            raise ValueError("e2e_models is for end-to-end tests; not allowed in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # values come from the environment


@lru_cache
def get_database_settings() -> DatabaseSettings:
    return DatabaseSettings()  # type: ignore[call-arg]
