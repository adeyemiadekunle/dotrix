from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from dotrix_backend.db.base import Base, UUIDPrimaryKeyMixin, str_enum


class FeedScope(enum.StrEnum):
    MINE = "mine"  # issues assigned to you or that you watch
    ALL = "all"  # every dated issue in the projects you can see


class CalendarFeed(UUIDPrimaryKeyMixin, Base):
    """A person's calendar feed (FR-32): a secret URL calendar apps subscribe to. At most
    one per person; turning it on again replaces the URL."""

    __tablename__ = "calendar_feeds"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    scope: Mapped[FeedScope] = mapped_column(str_enum(FeedScope, 16), default=FeedScope.MINE)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
