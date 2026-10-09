from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class ModelKeySave(BaseModel):
    api_key: str = Field(min_length=20, max_length=400, description="The provider's API key; stored encrypted, never shown again")

    @field_validator("api_key")
    @classmethod
    def _one_line(cls, value: str) -> str:
        value = value.strip()
        if any(c.isspace() for c in value):
            raise ValueError("An API key has no spaces or line breaks")
        return value


class ModelKeyRead(BaseModel):
    provider: str = Field(description="anthropic, openai, or google_genai")
    label: str = Field(description="The provider's name, e.g. Anthropic")
    connected: bool = Field(description="This workspace has its own key for the provider")
    last4: str | None = Field(description="The key's last four characters, when connected")
    added_by_id: uuid.UUID | None
    updated_at: datetime | None
    server_key: bool = Field(description="Without a key of its own, the workspace may use the server's for this provider")
    limit_reached_at: datetime | None = Field(
        description="When the provider last refused a run for a rate limit or quota (cleared by the next run that works)"
    )
    limit_message: str | None = Field(description="What the provider said, in a line")
    models: list[str] = Field(description="The models of this provider agents can be given")
