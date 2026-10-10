"""Lessons (agents v2 step 2): what people's decisions teach the agents. A rejected change or a
dismissed finding, with its reason, becomes a proposed lesson for the agent that made it; an
owner or admin accepts it (into the project's `agent-rules/lessons/<agent>.md`, versioned and
reversible like any rule) or declines it. Accepted lessons are part of that agent's rules."""
from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from dotrix_backend.db.base import Base, UUIDPrimaryKeyMixin, WorkspaceScopedMixin, str_enum


class LessonStatus(enum.StrEnum):
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    DECLINED = "declined"


class LessonSource(enum.StrEnum):
    REJECTION = "rejection"  # a change the agent proposed was rejected, with a reason
    DISMISSAL = "dismissal"  # an item the agent reported (a finding, a spec, …) was dismissed, with why


class AgentLesson(UUIDPrimaryKeyMixin, WorkspaceScopedMixin, Base):
    __tablename__ = "agent_lessons"

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    agent: Mapped[str] = mapped_column(String(32))  # the agent's handle ("project-manager" for Auto)
    text: Mapped[str] = mapped_column(String(600))  # the lesson as the agent will read it
    source: Mapped[LessonSource] = mapped_column(str_enum(LessonSource, 16))
    reason: Mapped[str] = mapped_column(String(500))  # what the person said
    run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)  # where it came from
    status: Mapped[LessonStatus] = mapped_column(str_enum(LessonStatus, 16), default=LessonStatus.PROPOSED)
    proposed_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    decided_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
