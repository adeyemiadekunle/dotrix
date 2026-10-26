"""Ops accounts: a separate identity for the Ops app (apps/ops), never an app user.

An ops account is created by proving ownership of a workspace once (the owner's own
email and password at sign-up) and stays bound to that workspace; afterwards the ops signs
in with its own credentials only. Phase 1: personal workspaces."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from dotrix_backend.db.base import Base, UUIDPrimaryKeyMixin


class OpsUser(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "ops_users"

    # The workspace this ops observes and manages (never crosses it).
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    # The owner who proved the workspace at sign-up: the ops reads as them (their runs,
    # their usage), under the same workspace scope.
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OpsSession(UUIDPrimaryKeyMixin, Base):
    """One signed-in ops browser: a single active refresh token at a time. Each refresh
    rotates it — the old token dies with the row's new hash, so a replayed one gets a 401."""

    __tablename__ = "ops_sessions"

    ops_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ops_users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
