from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ActivityKind(enum.StrEnum):
    ISSUE_CREATED = "issue.created"
    ISSUE_UPDATED = "issue.updated"
    ISSUE_COMMENTED = "issue.commented"
    ISSUE_CLAIMED = "issue.claimed"
    DOCUMENT_CHANGED = "document.changed"
    DOCUMENT_DELETED = "document.deleted"
    RUN_STARTED = "run.started"
    APPROVAL_DECIDED = "approval.decided"


class ActivityItem(BaseModel):
    """One thing that happened in a project, by a person or an agent. Only the fields for its
    `kind` are set: issue events carry the issue; document changes the path and version; runs the
    request; decisions what was decided."""

    kind: ActivityKind
    at: datetime
    project_id: uuid.UUID
    project_key: str
    project_name: str
    actor_user_id: uuid.UUID | None = Field(description="The person who did it, if a person did")
    actor_agent: str | None = Field(description="The agent who did it, if an agent did")
    issue_key: str | None = None
    issue_title: str | None = None
    changes: dict[str, Any] = Field(default_factory=dict, description="Issue fields changed: old → new")
    body: str | None = Field(default=None, description="A comment, a change note, or what was asked")
    path: str | None = None
    version: int | None = None
    instructed_by_id: uuid.UUID | None = None
    approved_by_id: uuid.UUID | None = None
    run_id: uuid.UUID | None = None
    run_kind: str | None = None
    run_status: str | None = None
    tool: str | None = None
    target: str | None = None
    decision: str | None = Field(default=None, description="`approved` or `rejected`")
    reason: str | None = None
