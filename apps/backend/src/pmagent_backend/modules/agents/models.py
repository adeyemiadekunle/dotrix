"""Agent runs and their approvals (FR-35, FR-36).

A run is one message to the Project Manager on a conversation thread. The
agent team runs in the background; its state is checkpointed per thread (LangGraph),
so a paused run resumes exactly where it stopped. When an agent wants to write,
the run pauses with one approval per pending action; a permitted person decides
them all, and the run resumes.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pmagent_backend.db.base import Base, UUIDPrimaryKeyMixin, WorkspaceScopedMixin, str_enum


class RunKind(enum.StrEnum):
    CHAT = "chat"
    BRIEFING = "briefing"  # read-only: any write is rejected automatically


class RunStatus(enum.StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"


ACTIVE_STATUSES = (RunStatus.QUEUED, RunStatus.RUNNING, RunStatus.AWAITING_APPROVAL)


class ApprovalStatus(enum.StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class AgentRun(UUIDPrimaryKeyMixin, WorkspaceScopedMixin, Base):
    __tablename__ = "agent_runs"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    thread_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    kind: Mapped[RunKind] = mapped_column(str_enum(RunKind, 16))
    status: Mapped[RunStatus] = mapped_column(str_enum(RunStatus, 24))
    message: Mapped[str] = mapped_column(Text)
    reply: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    # The person who instructed the run; recorded as "instructed by" on every write.
    requested_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    approvals: Mapped[list[AgentApproval]] = relationship(
        back_populates="run", order_by="AgentApproval.created_at, AgentApproval.position", lazy="raise"
    )


class AgentApproval(UUIDPrimaryKeyMixin, WorkspaceScopedMixin, Base):
    __tablename__ = "agent_approvals"

    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    # Order within one pause; decisions are sent back in this order.
    position: Mapped[int]
    interrupt_id: Mapped[str | None] = mapped_column(String(128))
    tool: Mapped[str] = mapped_column(String(64))
    args: Mapped[dict[str, Any]] = mapped_column(JSONB)
    target: Mapped[str | None] = mapped_column(String(400))  # e.g. the file path
    diff: Mapped[str | None] = mapped_column(Text)  # for file writes: what would change
    status: Mapped[ApprovalStatus] = mapped_column(str_enum(ApprovalStatus, 16))
    reason: Mapped[str | None] = mapped_column(String(500))
    decided_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    run: Mapped[AgentRun] = relationship(back_populates="approvals", lazy="raise")
