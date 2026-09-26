from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pmagent_backend.db.base import Base, UUIDPrimaryKeyMixin, WorkspaceScopedMixin, str_enum
from pmagent_backend.modules.workspaces.models import Role, Workspace


class InviteKind(enum.StrEnum):
    EMAIL = "email"  # for one address, single use
    LINK = "link"  # shareable, optional use limit


class Invite(UUIDPrimaryKeyMixin, WorkspaceScopedMixin, Base):
    __tablename__ = "invites"
    __table_args__ = (
        CheckConstraint("(kind = 'email') = (email IS NOT NULL)", name="email_iff_email_kind"),
        CheckConstraint("role <> 'owner'", name="not_owner"),
    )

    kind: Mapped[InviteKind] = mapped_column(str_enum(InviteKind, 20))
    email: Mapped[str | None] = mapped_column(String(320), index=True)
    role: Mapped[Role] = mapped_column(str_enum(Role, 20))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    invited_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Email invites: set when accepted. Links: counted per use.
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    max_uses: Mapped[int | None]
    use_count: Mapped[int] = mapped_column(default=0, server_default="0")

    workspace: Mapped[Workspace] = relationship(lazy="raise")

    def is_usable(self, now: datetime) -> bool:
        if self.revoked_at is not None or self.expires_at <= now:
            return False
        if self.kind is InviteKind.EMAIL:
            return self.accepted_at is None
        return self.max_uses is None or self.use_count < self.max_uses
