from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from .models import ApprovalStatus, RunKind, RunStatus

# `auto` (the Project Manager) or any agent handle the project has (built-in or custom).
AgentChoice = Annotated[str, Field(pattern=r"^(auto|[a-z][a-z0-9-]{1,30})$")]


class RunCreate(BaseModel):
    message: str = Field(min_length=1, max_length=20_000)
    thread_id: uuid.UUID | None = Field(
        default=None,
        description="Continue a conversation. Omit to start a new thread.",
    )
    agent: AgentChoice = Field(
        default="auto",
        description="Who answers: `auto` (the Project Manager involves the specialists it needs) or an "
        "agent's handle (`GET .../agents`: built-in or custom), who leads and may ask the agents it can call. "
        "422 `unknown_agent` if the project has no such agent",
    )
    model: str | None = Field(
        default=None,
        max_length=100,
        description="For a new conversation only: the model it runs on (one of `GET /v1/workspaces/{id}/models`; "
        "needs agents:choose_model unless it's the project's). Fixed for the whole conversation; omit to use "
        "the project's model.",
    )


class ModelOption(BaseModel):
    id: str = Field(description="provider:model, e.g. google_genai:gemini-3.8-flash")
    provider: str
    name: str = Field(description="The model's name without the provider")


class ArchitectureDraftRequest(BaseModel):
    repo_summary: str | None = Field(
        default=None,
        max_length=60_000,
        description="Optional summary of the repository (file tree, manifests, README) made on the "
        "owner's machine. Never the source code itself.",
    )


class ApprovalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    run_id: uuid.UUID
    position: int
    tool: str = Field(description="e.g. write_file, edit_file")
    target: str | None = Field(description="What the action changes, e.g. /pmagent/vision.md")
    args: dict[str, Any]
    diff: str | None = Field(description="For file writes: unified diff of what would change")
    status: ApprovalStatus
    reason: str | None
    decided_by_id: uuid.UUID | None
    decided_at: datetime | None
    created_at: datetime


class WorkspaceApprovalRead(ApprovalRead):
    """A pending action with where it's from, for the workspace's approvals queue."""

    project_id: uuid.UUID
    project_key: str
    project_name: str
    run_message: str = Field(description="The instruction the run was given")
    requested_by_id: uuid.UUID | None = Field(description="Who instructed the run")


class AgentUsage(BaseModel):
    agent: str = Field(description="project-manager, or the specialist's role (product, research, ...)")
    input_tokens: int
    output_tokens: int
    model_calls: int


class ToolUsage(BaseModel):
    tool: str
    calls: int
    result_tokens: int = Field(
        description="About how many tokens the tool's results added (re-sent with every later model call)"
    )


class RunFileRead(BaseModel):
    path: str
    times: int


class RunBreakdown(BaseModel):
    """Where a run's tokens went."""

    by_agent: list[AgentUsage] = Field(description="Largest first")
    tools: list[ToolUsage] = Field(description="Largest results first")
    files_read: list[RunFileRead] = Field(description="Most read first")
    token_budget: int | None = Field(description="The run's token budget (null: no limit)")


class AgentRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    thread_id: uuid.UUID
    kind: RunKind
    status: RunStatus
    message: str
    title: str | None = Field(
        default=None, description="The conversation's title; set on the first run of a thread"
    )
    reply: str | None
    error: str | None
    requested_by_id: uuid.UUID | None
    agent: Annotated[str, BeforeValidator(lambda v: v or "auto")] = Field(
        default="auto", description="Who answered: `auto` (the Project Manager) or the leading agent's handle"
    )
    conversation_model: str | None = Field(
        default=None,
        description="The model the conversation runs on (fixed when it started); null on older conversations, "
        "which use the project's model",
    )
    # Usage is for owners and admins (the usage:view permission); null for everyone else.
    model: str | None = Field(
        default=None,
        description="The project's model when the run last worked, e.g. `google_genai:gemini-3.8-flash`. "
        "Owners and admins only (null otherwise)",
    )
    input_tokens: int | None = Field(
        default=None,
        description="Input (prompt) tokens over every model call of the run, subagents included. "
        "Owners and admins only (null otherwise)",
    )
    output_tokens: int | None = Field(
        default=None,
        description="Output tokens over every model call of the run, subagents included. "
        "Owners and admins only (null otherwise)",
    )
    cached_input_tokens: int | None = Field(
        default=None,
        description="Of the input tokens, how many the provider served from its prompt cache (cheaper). "
        "Owners and admins only (null otherwise)",
    )
    model_calls: int | None = Field(
        default=None,
        description="Model calls the run made (each re-sends the prompt). Owners and admins only (null otherwise)",
    )
    breakdown: RunBreakdown | None = Field(
        default=None,
        description="Where the tokens went: by agent, by tool, and the files read. Owners and admins only "
        "(null otherwise)",
    )
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None
    approvals: list[ApprovalRead] = []


class Decision(BaseModel):
    approval_id: uuid.UUID
    decision: Literal["approve", "reject"]
    reason: str | None = Field(
        default=None, max_length=500, description="Sent back to the agent when rejecting"
    )


class DecisionsRequest(BaseModel):
    decisions: list[Decision] = Field(
        min_length=1, description="One decision for every pending approval of the run"
    )


class ThreadRename(BaseModel):
    title: str = Field(min_length=1, max_length=120)


class ThreadRead(BaseModel):
    thread_id: uuid.UUID
    title: str
