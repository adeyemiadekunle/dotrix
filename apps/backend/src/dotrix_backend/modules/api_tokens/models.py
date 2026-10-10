from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import ARRAY, DateTime, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from dotrix_backend.db.base import Base, UUIDPrimaryKeyMixin, str_enum


class Scope(enum.StrEnum):
    READ = "read"  # GET / HEAD / OPTIONS only
    WRITE = "write"  # everything else the user's role allows


class ApiToken(UUIDPrimaryKeyMixin, Base):
    """Personal access token for the CLI, Claude Code, Codex, and scripts (FR-6).

    Acts as the user, within their workspace roles, narrowed by scopes.
    """

    __tablename__ = "api_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    # First characters of the token, so people can tell tokens apart in a list.
    display_prefix: Mapped[str] = mapped_column(String(16))
    scopes: Mapped[list[str]] = mapped_column(ARRAY(String(16)))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    def is_active(self, now: datetime) -> bool:
        return self.revoked_at is None and (self.expires_at is None or self.expires_at > now)


class DeviceStatus(enum.StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    CONSUMED = "consumed"  # the device has collected its token


class DeviceAuthorization(UUIDPrimaryKeyMixin, Base):
    """One CLI sign-in attempt (OAuth 2.0 device authorization grant, RFC 8628)."""

    __tablename__ = "device_authorizations"
    __table_args__ = (
        # User codes are short, so they only need to be unique while pending.
        Index(
            "uq_device_authorizations_pending_user_code",
            "user_code",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
    )

    device_code_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_code: Mapped[str] = mapped_column(String(8))  # stored without the dash
    client_name: Mapped[str] = mapped_column(String(100))
    scopes: Mapped[list[str]] = mapped_column(ARRAY(String(16)))
    status: Mapped[DeviceStatus] = mapped_column(
        str_enum(DeviceStatus, 20), default=DeviceStatus.PENDING
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
