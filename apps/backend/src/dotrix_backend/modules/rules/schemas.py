from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

MAX_RULE_CHARS = 20_000


class WorkspaceRuleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    handle: str = Field(description='"base" (every agent) or an agent\'s handle')
    content: str
    version: int
    updated_by_id: uuid.UUID | None
    updated_at: datetime


class WorkspaceRuleSave(BaseModel):
    content: str = Field(max_length=MAX_RULE_CHARS, description="Markdown; empty removes the rule")
    base_version: int = Field(ge=0, description="The version you edited (0 for a new one); 409 if it changed since")


class WorkspaceSkillRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    description: str = Field(description='Its "Description:" line, as agents see it in their list')
    content: str
    version: int
    updated_by_id: uuid.UUID | None
    updated_at: datetime


class SkillCategoryRead(BaseModel):
    id: str
    label: str


class SkillRegistryItemRead(BaseModel):
    id: str
    name: str
    description: str
    category: str
    tags: list[str]
    agents: list[str]
    required_tools: list[str]
    trust: str
    origin: str
    enabled: bool
    version: int
    registry_version: str
    sha256: str
    source_repo: str | None = None
    source_revision: str | None = None
    license: str | None = None
    content: str
    updated_at: datetime | None = None


class SkillRegistryRead(BaseModel):
    categories: list[SkillCategoryRead]
    items: list[SkillRegistryItemRead]
