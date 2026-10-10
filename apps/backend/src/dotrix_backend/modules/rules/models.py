"""Workspace rules (agents v2 step 2, layers): text every project's agents follow, written once
for the workspace. Layers run from the workspace to the project to the agent, the more
specific last (so it wins where they differ); the invariants in code can't be overridden by
any of them. One row per agent handle ("base" for every agent); each save is a new version,
and the audit log keeps what it replaced."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from dotrix_backend.db.base import Base, UUIDPrimaryKeyMixin, WorkspaceScopedMixin


class WorkspaceRule(UUIDPrimaryKeyMixin, WorkspaceScopedMixin, Base):
    __tablename__ = "workspace_rules"
    __table_args__ = (UniqueConstraint("workspace_id", "handle"),)

    handle: Mapped[str] = mapped_column(String(31))  # "base", or an agent's handle
    content: Mapped[str] = mapped_column(Text)
    version: Mapped[int]
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class WorkspaceSkill(UUIDPrimaryKeyMixin, WorkspaceScopedMixin, Base):
    """A skill every project's agents can use (agents v2 step 2): a procedure, "Description:"
    line first. A project's own skill of the same name (agent-rules/skills/) wins."""

    __tablename__ = "workspace_skills"
    __table_args__ = (UniqueConstraint("workspace_id", "name"),)

    name: Mapped[str] = mapped_column(String(40))
    content: Mapped[str] = mapped_column(Text)
    version: Mapped[int]
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
