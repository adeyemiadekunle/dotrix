from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from .models import CodingAgent, CodingRunStatus


class CodingAvailability(BaseModel):
    available: bool
    agent: CodingAgent | None = Field(description="Who would code: Claude Code with an Anthropic key, else Codex")
    sandbox: str | None = Field(description="`openshell`, or `local` (development, no isolation)")
    reason: str | None = Field(description="Why not, when it isn't available")


class CodingRunCreate(BaseModel):
    note: str | None = Field(default=None, max_length=5_000, description="Anything to add to the issue for the agent")


class CodingDecision(BaseModel):
    decision: Literal["approve", "reject"]
    reason: str | None = Field(default=None, max_length=1_000)


class CodingEvent(BaseModel):
    at: datetime
    kind: str = Field(description="`step`, `text` (the agent's words), `tool` (what it did), `error`")
    text: str


class CodingRunRead(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    issue_key: str
    agent: CodingAgent
    model: str | None
    status: CodingRunStatus
    brief: str = Field(description="Exactly what the agent is told")
    note: str | None
    repo_full_name: str
    base_branch: str
    base_sha: str | None
    branch: str | None
    commit_sha: str | None
    pr_number: int | None
    pr_url: str | None
    files_changed: list[dict[str, Any]]
    events: list[CodingEvent]
    summary: str | None = Field(description="The agent's last message")
    error: str | None
    input_tokens: int | None = Field(description="Owners and admins (usage:view) only")
    output_tokens: int | None
    cost_usd: float | None
    requested_by_id: uuid.UUID | None
    decided_by_id: uuid.UUID | None
    decision_reason: str | None
    review_run_id: uuid.UUID | None = Field(description="The Reviewer's run on the PR")
    review_thread_id: uuid.UUID | None = Field(description="Its conversation, to open in Chat")
    created_at: datetime
    decided_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    can_decide: bool = Field(description="Whether you may approve or reject it now")
    can_stop: bool = Field(description="Whether you may stop it now")
