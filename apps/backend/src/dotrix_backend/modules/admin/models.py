"""Admin accounts: a separate identity for the Admin app (apps/admin), never an app user.

An admin account is created by proving ownership of a workspace once (the owner's own
email and password at sign-up) and stays bound to that workspace; afterwards the admin signs
in with its own credentials only. Phase 1: personal workspaces."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from dotrix_backend.db.base import Base, UUIDPrimaryKeyMixin


class AdminUser(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "admin_users"

    # Optional: set when an admin was created against a specific workspace (earlier phase-1
    # accounts). The platform console reads the whole deployment, not one workspace.
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("workspaces.id", ondelete="SET NULL"), index=True)
    # The person who created the account (informational only).
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AdminSession(UUIDPrimaryKeyMixin, Base):
    """One signed-in admin browser: a single active refresh token at a time. Each refresh
    rotates it — the old token dies with the row's new hash, so a replayed one gets a 401."""

    __tablename__ = "admin_sessions"

    admin_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("admin_users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
