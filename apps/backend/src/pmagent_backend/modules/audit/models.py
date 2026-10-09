"""Append-only audit log (FR-5): every write to project knowledge, every approval
decision, and every agent run, with who instructed and who approved it.

Rows are only ever inserted; there is no update or delete path in the app.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from pmagent_backend.db.base import Base, UUIDPrimaryKeyMixin, WorkspaceScopedMixin, str_enum
from pmagent_backend.modules.knowledge.models import AuthorType


class AuditEvent(UUIDPrimaryKeyMixin, WorkspaceScopedMixin, Base):
    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_events_workspace_id_created_at", "workspace_id", "created_at"),)

    # SET NULL: deleting a project keeps its history here (append-only); `target` names what it was.
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), index=True
    )
    # e.g. "knowledge.write", "knowledge.delete", "approval.approved", "agent_run.started"
    action: Mapped[str] = mapped_column(String(64))
    target: Mapped[str | None] = mapped_column(String(400))  # e.g. a file path
    actor_type: Mapped[AuthorType] = mapped_column(str_enum(AuthorType, 16))
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    agent: Mapped[str | None] = mapped_column(String(32))
    instructed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
