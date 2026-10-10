"""Agent contracts stored per workspace, with per-project overrides (docs/agents-v2.md §4.2).

A definition exists only once someone edits a built-in or creates an agent; everything else
comes from the engine's built-ins. Every save is a new version (append-only, like knowledge
versions), so what an agent was at any time can be shown and restored.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from dotrix_backend.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, WorkspaceScopedMixin


class AgentDefinition(UUIDPrimaryKeyMixin, TimestampMixin, WorkspaceScopedMixin, Base):
    __tablename__ = "agent_definitions"
    __table_args__ = (
        # One definition per handle in the workspace, and per handle in each project.
        Index(
            "uq_agent_definitions_workspace_handle", "workspace_id", "handle",
            unique=True, postgresql_where=text("project_id IS NULL"),
        ),
        Index(
            "uq_agent_definitions_project_handle", "project_id", "handle",
            unique=True, postgresql_where=text("project_id IS NOT NULL"),
        ),
    )

    # Null: the workspace's definition; set: a project's override.
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    handle: Mapped[str] = mapped_column(String(31))
    # The built-in it changes (its handle), or null for a custom agent.
    base: Mapped[str | None] = mapped_column(String(31))
    current_version: Mapped[int]
    # Set when a custom agent is removed or a built-in is reset; saving again revives it.
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class AgentDefinitionVersion(UUIDPrimaryKeyMixin, WorkspaceScopedMixin, Base):
    __tablename__ = "agent_definition_versions"
    __table_args__ = (UniqueConstraint("definition_id", "version"),)

    definition_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_definitions.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int]
    spec: Mapped[dict[str, Any]] = mapped_column(JSONB)  # an AgentSpec, as JSON
    note: Mapped[str] = mapped_column(String(500), default="", server_default="")
    author_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AgentPreference(UUIDPrimaryKeyMixin, TimestampMixin, WorkspaceScopedMixin, Base):
    """One person's own touches to an agent in a workspace (Settings → Your agents): extra
    instructions and a model, for the runs they start. Never tools, folder access, issue types,
    or what it may do without asking: those stay the workspace's (the contract)."""

    __tablename__ = "agent_preferences"
    __table_args__ = (UniqueConstraint("workspace_id", "user_id", "handle"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    handle: Mapped[str] = mapped_column(String(32))
    instructions: Mapped[str] = mapped_column(String(2000), default="", server_default="")
    model: Mapped[str | None] = mapped_column(String(100))
