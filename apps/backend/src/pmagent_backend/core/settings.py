from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PMAGENT_", env_file=".env", extra="ignore")

    env: str = "development"
    log_level: str = "INFO"
    log_json: bool = True
    database_url: str = "postgresql+asyncpg://pmagent:pmagent@localhost:5432/pmagent"
    database_echo: bool = False
    redis_url: str = "redis://localhost:6379/0"
    cors_origins: list[str] = ["http://localhost:3000"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
