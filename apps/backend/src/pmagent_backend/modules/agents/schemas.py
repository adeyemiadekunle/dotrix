from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .models import ApprovalStatus, RunKind, RunStatus


class RunCreate(BaseModel):
    message: str = Field(min_length=1, max_length=20_000)
    thread_id: uuid.UUID | None = Field(
        default=None,
        description="Continue a conversation. Omit to start a new thread.",
    )


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
