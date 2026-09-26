from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PMAGENT_", env_file=".env", extra="ignore")

    env: str = "development"
    database_url: str = "postgresql://pmagent:pmagent@localhost:5432/pmagent"
    redis_url: str = "redis://localhost:6379/0"
    cors_origins: list[str] = ["http://localhost:3000"]


settings = Settings()
