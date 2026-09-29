from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, Uuid, true
from sqlalchemy.orm import Mapped, mapped_column

from pmagent_backend.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, str_enum


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    # Stored lowercased (schemas normalise), so the unique index is case-insensitive.
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(100))
    # Null for accounts that only sign in via OAuth or magic link.
    password_hash: Mapped[str | None] = mapped_column(String(255))
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(default=True, server_default=true())

    @property
    def email_verified(self) -> bool:
        return self.email_verified_at is not None


class RefreshToken(UUIDPrimaryKeyMixin, Base):
    """One row per issued refresh token. Rotation: each use revokes the token and
    issues a new one in the same family. Presenting a revoked token means it was
    stolen or replayed, so the whole family is revoked."""

    __tablename__ = "refresh_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    family_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ActionTokenPurpose(enum.StrEnum):
    VERIFY_EMAIL = "verify_email"
    RESET_PASSWORD = "reset_password"
    MAGIC_LINK = "magic_link"  # sign in without a password


class ActionToken(UUIDPrimaryKeyMixin, Base):
    """Single-use emailed token (email verification, password reset, magic-link sign-in)."""

    __tablename__ = "action_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    purpose: Mapped[ActionTokenPurpose] = mapped_column(str_enum(ActionTokenPurpose))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EmailSignup(UUIDPrimaryKeyMixin, Base):
    """A sign-up by email link, before the account exists: someone asked for a sign-in link
    for an address with no account. Following the link (and giving a name) creates it."""

    __tablename__ = "email_signups"

    email: Mapped[str] = mapped_column(String(320), index=True)  # lowercased, like users.email
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OAuthAccount(UUIDPrimaryKeyMixin, Base):
    """A sign-in identity at another provider (GitHub), linked to one account. Found by the
    provider's own id, so a changed username or email there still signs in the same person.
    No provider tokens are stored: signing in needs none."""

    __tablename__ = "oauth_accounts"
    __table_args__ = (UniqueConstraint("provider", "provider_user_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str] = mapped_column(String(32))
    provider_user_id: Mapped[str] = mapped_column(String(64))
    login: Mapped[str | None] = mapped_column(String(100))  # their username there, for display
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
