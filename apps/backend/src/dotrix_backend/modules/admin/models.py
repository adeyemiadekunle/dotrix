"""Admin accounts: a separate identity for the Admin app (apps/admin), never an app user.

An admin account is created with the deployment's setup token (the first account) or from the
server's command line (`python -m dotrix_backend.admin_cli`); it signs in with its own
credentials only."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from dotrix_backend.db.base import Base, UUIDPrimaryKeyMixin


class AdminUser(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "admin_users"

    email: Mapped[str] = mapped_column(String(320), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # "owner" manages admins; "viewer" only reads.
    role: Mapped[str] = mapped_column(String(16), server_default="owner")
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AdminInvite(UUIDPrimaryKeyMixin, Base):
    """A single-use, emailed invitation to become an admin. Only the token's hash is stored."""

    __tablename__ = "admin_invites"

    email: Mapped[str] = mapped_column(String(320))
    role: Mapped[str] = mapped_column(String(16))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    invited_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("admin_users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


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


class AdminEvent(UUIDPrimaryKeyMixin, Base):
    """The admin console's append-only trail: who signed in, failed to, or changed an admin account.
    No free text and no secrets; the emails are kept so a row still reads after its account is gone."""

    __tablename__ = "admin_events"

    action: Mapped[str] = mapped_column(String(64), index=True)
    admin_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("admin_users.id", ondelete="SET NULL"))
    actor_email: Mapped[str | None] = mapped_column(String(320))
    target_email: Mapped[str | None] = mapped_column(String(320))
    workspace: Mapped[str | None] = mapped_column(String(100))
    ip: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
