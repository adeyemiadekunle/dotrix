"""A project's `.pmagent/` source of truth, stored on the platform (FR-18).

`knowledge_files` holds the current content of each path; `knowledge_versions`
is the append-only history: every change records the content, who wrote it
(person, agent, or system), who instructed it, and who approved it. Deletes
are versions too, so nothing is lost and any version can be restored.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from pmagent_backend.db.base import Base, UUIDPrimaryKeyMixin, WorkspaceScopedMixin, str_enum


class AuthorType(enum.StrEnum):
    USER = "user"
    AGENT = "agent"
    SYSTEM = "system"  # scaffolding, imports


class KnowledgeFile(UUIDPrimaryKeyMixin, WorkspaceScopedMixin, Base):
    __tablename__ = "knowledge_files"
    __table_args__ = (
        UniqueConstraint("project_id", "path"),
        # Sync: "what changed in this project since revision N?"
        Index("ix_knowledge_files_project_id_revision", "project_id", "revision"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    path: Mapped[str] = mapped_column(String(300))
    version: Mapped[int]
    revision: Mapped[int]  # project knowledge_revision of the latest change
    content: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    size: Mapped[int]
    deleted: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # What the document is about (pmagent_engine.knowledge_index), for the knowledge index in
    # every agent run's context pack. `described_version` is the version it describes: older
    # rows are filled in when the index next needs them.
    title: Mapped[str | None] = mapped_column(String(200))
    summary: Mapped[str | None] = mapped_column(String(300))
    outline: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    described_version: Mapped[int | None]


class KnowledgeVersion(UUIDPrimaryKeyMixin, WorkspaceScopedMixin, Base):
    __tablename__ = "knowledge_versions"
    __table_args__ = (UniqueConstraint("file_id", "version"),)

    file_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("knowledge_files.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int]
    revision: Mapped[int]
    content: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    deleted: Mapped[bool] = mapped_column(default=False)
    author_type: Mapped[AuthorType] = mapped_column(str_enum(AuthorType, 16))
    # The person who wrote it (author_type=user), or null.
    author_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    # The agent that wrote it (author_type=agent), e.g. "product".
    agent: Mapped[str | None] = mapped_column(String(32))
    instructed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    message: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
