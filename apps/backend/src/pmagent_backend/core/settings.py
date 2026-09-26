from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo-root .env, so settings load the same from any working directory
# (uvicorn at the root, alembic in apps/backend). Real env vars take precedence.
REPO_ROOT_ENV = Path(__file__).resolve().parents[5] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PMAGENT_", env_file=(REPO_ROOT_ENV, ".env"), extra="ignore"
    )

    env: str = "development"
    log_level: str = "INFO"
    log_json: bool = True
    # Required, no default: credentials only ever come from the environment / .env.
    database_url: str
    database_echo: bool = False
    redis_url: str = "redis://localhost:6379/0"
    cors_origins: list[str] = ["http://localhost:3000"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
