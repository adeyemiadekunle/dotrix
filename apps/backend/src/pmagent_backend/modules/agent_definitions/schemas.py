from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from pmagent_engine.contracts import Autonomy
from pmagent_engine.permissions import Access

AgentSource = Literal["built_in", "customised", "custom"]
AgentScope = Literal["default", "workspace", "project"]


class AgentFields(BaseModel):
    """An agent's contract without its handle (the handle is in the path). Validated against
    `pmagent_engine.contracts.AgentSpec` on save (422 with the reason)."""

    name: str = Field(min_length=1, max_length=60)
    description: str = Field(default="", max_length=200)
    instructions: str = Field(min_length=1, max_length=20_000, description="Its role prompt (Markdown)")
    model: str | None = Field(default=None, max_length=100, description="provider:model; null uses the run's model")
    budget_tokens: int | None = Field(default=None, description="Tokens one run it leads may use; null: the project's")
    tools: list[str] = Field(description="Tool ids from `GET .../agents/catalog`")
    access: dict[str, Access] = Field(
        default_factory=dict, description="Folder pattern relative to .pmagent/ (e.g. research/*) -> access"
    )
    issue_types: list[str] = Field(default_factory=list, description="Issue types it may open (needs issues.create)")
    can_call: list[str] = Field(default_factory=list, description="Handles it may hand work to; ['*'] for all")
    autonomy: dict[str, Autonomy] = Field(
        default_factory=dict,
        description="Action -> allow, ask, or block (unlisted: ask). Only owners set allow, and only for low-risk actions",
    )
    output: str | None = None
    pipeline: str | None = None
    triggers: list[dict[str, Any]] = Field(default_factory=list, description="Stored for automations; not run yet")


class AgentSave(BaseModel):
    agent: AgentFields
    note: str = Field(default="", max_length=500, description="Why it changed, shown in its history")
    base_version: int | None = Field(
        default=None,
        description="The version you edited (from `version`); 409 `agent_changed` if someone saved since. "
        "Omit when creating",
    )


class AgentRead(AgentFields):
    handle: str
    base: str | None = Field(description="The built-in it's based on, or null for a custom agent")
    source: AgentSource = Field(description="built_in (the default), customised (a changed built-in), or custom")
    scope: AgentScope = Field(
        description="Where it's defined: default (built in), workspace, or project (an override for one project)"
    )
    version: int | None = Field(description="Its definition's current version; null for an unchanged built-in")
    updated_at: datetime | None


class AgentVersionRead(BaseModel):
    version: int
    agent: AgentFields
    note: str
    author_user_id: str | None
    created_at: datetime


class ToolOption(BaseModel):
    id: str
    label: str
    description: str
    actions: list[str]


class AgentCatalog(BaseModel):
    tools: list[ToolOption]
    actions: list[str] = Field(description="Every action an autonomy rule can name")
    low_risk_actions: list[str] = Field(description="The actions that may be set to allow (owners only)")
    access_levels: list[Access]
    issue_types: list[str]
    reserved_handles: list[str] = Field(description="Handles a new agent can't take")
    outputs: list[str] = Field(description="Result schemas an agent can declare (its `output`)")
    pipelines: dict[str, list[str]] = Field(description="Pipelines an agent can follow, with their stages")
