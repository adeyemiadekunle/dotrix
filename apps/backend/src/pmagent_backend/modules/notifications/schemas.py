from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from .models import NotificationKind


class NotificationRead(BaseModel):
    """Something that waits for you or happened to you. `kind` says which: changes waiting for
    a decision (`approval`), a plan waiting at a checkpoint (`checkpoint`), an issue assigned to you
    (`assigned`), or findings from a run you asked for (`finding`)."""

    id: uuid.UUID
    kind: NotificationKind
    created_at: datetime
    read: bool
    resolved: bool = Field(
        description="Approvals and checkpoints: decided since (nothing left to do). Always false for the others"
    )
    project_id: uuid.UUID
    project_key: str
    project_name: str
    actor_user_id: uuid.UUID | None = Field(description="The person who did it, if a person did")
    actor_agent: str | None = Field(description="The agent who did it, if an agent did")
    title: str = Field(description="What was asked (runs) or the issue's title, when it happened")
    count: int = Field(description="Changes waiting, or findings to look at; 1 for the others")
    run_id: uuid.UUID | None = None
    thread_id: uuid.UUID | None = Field(default=None, description="The conversation the run belongs to")
    issue_key: str | None = None


class NotificationCounts(BaseModel):
    """What still needs you, in total and by kind (for badges): approvals and checkpoints until
    they're decided, the others until you've read them."""

    unread: int
    by_kind: dict[NotificationKind, int]


class MarkRead(BaseModel):
    """Mark some of your notifications read (`ids`), or all of them (of one `kind`, if given)."""

    ids: list[uuid.UUID] = Field(default_factory=list, max_length=200)
    all: bool = False
    kind: NotificationKind | None = None

    @model_validator(mode="after")
    def _one_way(self) -> MarkRead:
        if not self.ids and not self.all:
            raise ValueError("Send `ids`, or `all: true`")
        return self
