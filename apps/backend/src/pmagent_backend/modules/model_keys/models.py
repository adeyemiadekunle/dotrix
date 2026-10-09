"""An organisation's own model provider keys (Anthropic, OpenAI, Google), encrypted at rest."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from pmagent_backend.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, WorkspaceScopedMixin


class WorkspaceModelKey(UUIDPrimaryKeyMixin, TimestampMixin, WorkspaceScopedMixin, Base):
    __tablename__ = "workspace_model_keys"
    __table_args__ = (UniqueConstraint("workspace_id", "provider"),)  # one key per provider

    provider: Mapped[str] = mapped_column(String(32))  # llm.PROVIDERS: anthropic, openai, google_genai
    encrypted: Mapped[str] = mapped_column(Text)  # Fernet token (core/crypto.py); never returned
    last4: Mapped[str] = mapped_column(String(4))  # shown so people can tell keys apart
    added_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    # The provider last refused a run for a rate limit or quota; cleared by the next run that works.
    limit_reached_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    limit_message: Mapped[str | None] = mapped_column(String(500))


class UserModelKey(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A person's own key for a provider (Account → Models), used for the runs they start where
    the workspace allows personal keys (always in their personal workspace)."""

    __tablename__ = "user_model_keys"
    __table_args__ = (UniqueConstraint("user_id", "provider"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(32))
    encrypted: Mapped[str] = mapped_column(Text)
    last4: Mapped[str] = mapped_column(String(4))
    limit_reached_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    limit_message: Mapped[str | None] = mapped_column(String(500))
