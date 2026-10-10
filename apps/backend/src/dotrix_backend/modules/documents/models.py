from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from dotrix_backend.db.base import Base, UUIDPrimaryKeyMixin, WorkspaceScopedMixin, str_enum


class DocumentStatus(enum.StrEnum):
    CONVERTING = "converting"  # the original is stored; its markdown is being made (a job)
    READY = "ready"  # the markdown is in the project's knowledge
    FAILED = "failed"  # couldn't be converted (see `error`); the original is kept


class Document(UUIDPrimaryKeyMixin, WorkspaceScopedMixin, Base):
    """An uploaded original (PDF, DOCX, ...). The bytes live in object storage; the
    markdown agents read lives in the project's knowledge at `knowledge_path`."""

    __tablename__ = "documents"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(255))
    size: Mapped[int]
    sha256: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(String(600), unique=True)
    knowledge_path: Mapped[str] = mapped_column(String(300))
    knowledge_version: Mapped[int]  # the knowledge file version this upload produced (0 until ready)
    status: Mapped[DocumentStatus] = mapped_column(
        str_enum(DocumentStatus, 16), default=DocumentStatus.READY, server_default=DocumentStatus.READY.value
    )
    error: Mapped[str | None] = mapped_column(Text)
    uploaded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
