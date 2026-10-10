"""Automations: agents that run on their own, on a schedule or when something happens in a
project (agents v2 step 4). Each runs as the person who set it up ("instructed by"), within its
daily limit; its changes wait for approval like anyone's."""
from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, SmallInteger, String, Text, Uuid
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from dotrix_backend.db.base import (
    Base,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    WorkspaceScopedMixin,
    str_enum,
)


class AutomationEvent(enum.StrEnum):
    """What can set an automation off. Only what people (and pushes) do: an agent's own changes
    never trigger automations, so they can't set each other off in a loop."""

    ISSUE_CREATED = "issue.created"  # someone created an issue
    ISSUE_DONE = "issue.done"  # someone moved an issue to done
    DOCUMENT_CHANGED = "document.changed"  # someone edited a document (not agent-rules/)
    CHANGES_APPROVED = "changes.approved"  # an agent's changes were approved and made (not an automation's)
    CODE_PUSHED = "code.pushed"  # a push to the connected repo's default branch


class Automation(UUIDPrimaryKeyMixin, TimestampMixin, WorkspaceScopedMixin, Base):
    __tablename__ = "automations"

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    agent: Mapped[str | None] = mapped_column(String(32))  # a handle; null: Auto (the Project Manager)
    instructions: Mapped[str] = mapped_column(Text)
    # When: on events, and/or on a schedule (every day, or one weekday, at an hour in UTC).
    events: Mapped[list[str]] = mapped_column(ARRAY(String(32)), default=list, server_default="{}")
    schedule_hour: Mapped[int | None] = mapped_column(SmallInteger)  # 0-23 UTC; null: no schedule
    schedule_weekday: Mapped[int | None] = mapped_column(SmallInteger)  # 0 Monday … 6 Sunday; null: daily
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    # Its own daily cap, if an owner set one; null: none (runs use the organisation's own keys).
    max_runs_per_day: Mapped[int | None] = mapped_column(Integer)
    # Its runs may use the agents' standing rules to change things without approval (beyond the
    # low-risk ones). Off by default; owners turn it on.
    unattended: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # Who set it up: its runs are instructed by them, see what they see, and stop if they can't.
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    thread_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)  # its conversation, from the first run
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    last_error: Mapped[str | None] = mapped_column(String(500))


class AutomationEventRow(UUIDPrimaryKeyMixin, WorkspaceScopedMixin, Base):
    """Something that happened, waiting for the automations it sets off (an outbox: written in
    the same transaction as what happened, handled within a minute, then deleted)."""

    __tablename__ = "automation_events"

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    event: Mapped[AutomationEvent] = mapped_column(str_enum(AutomationEvent, 32))
    summary: Mapped[str] = mapped_column(String(300))  # what happened, in a line (data for the agent)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
