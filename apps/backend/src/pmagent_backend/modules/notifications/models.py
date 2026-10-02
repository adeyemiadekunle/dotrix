"""A person's notifications: what waits for them and what happened to them in a workspace."""
from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from pmagent_backend.db.base import Base, UUIDPrimaryKeyMixin, WorkspaceScopedMixin, str_enum


class NotificationKind(enum.StrEnum):
    APPROVAL = "approval"  # an agent's changes wait for a decision you may make
    CHECKPOINT = "checkpoint"  # an agent you asked wants you to confirm or change its plan
    ASSIGNED = "assigned"  # someone (or an agent) assigned an issue to you
    FINDING = "finding"  # a run you asked for finished with findings to look at
    MENTION = "mention"  # someone @mentioned you in an issue comment or a chat message


# What people may turn off. Approvals and checkpoints always come through: agents wait on them.
OPTIONAL_KINDS = (NotificationKind.MENTION, NotificationKind.ASSIGNED, NotificationKind.FINDING)


class Notification(UUIDPrimaryKeyMixin, WorkspaceScopedMixin, Base):
    """One per recipient. Rows hold ids and a short snapshot (a title); what is shown is checked
    against what the reader can see when it's read."""

    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_recipient", "user_id", "workspace_id", "created_at"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    kind: Mapped[NotificationKind] = mapped_column(str_enum(NotificationKind, 16))
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True)
    issue_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("issues.id", ondelete="CASCADE"), index=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    actor_agent: Mapped[str | None] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(300))
    excerpt: Mapped[str | None] = mapped_column(String(300))  # mentions: what was said
    count: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
