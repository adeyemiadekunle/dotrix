from __future__ import annotations

import enum
import uuid

from sqlalchemy import ARRAY, Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pmagent_backend.db.base import (
    Base,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    WorkspaceScopedMixin,
    str_enum,
)


class WorkspaceKind(enum.StrEnum):
    PERSONAL = "personal"  # one per person, just its owner; never invites
    ORGANIZATION = "organization"  # a team: invites, roles, many projects


class Role(enum.StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    GUEST = "guest"


class Workspace(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "workspaces"

    name: Mapped[str] = mapped_column(String(100))
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    kind: Mapped[WorkspaceKind] = mapped_column(str_enum(WorkspaceKind, 20))
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    # Permissions this workspace grants its members beyond the defaults (permissions.py
    # MEMBER_GRANTABLE: edit documents, approve agent changes, instruct the coding agent).
    member_permissions: Mapped[list[str]] = mapped_column(
        ARRAY(String(32)), default=list, server_default="{}"
    )
    # Every agent asks before changing anything while set: the standing rules that let agents act
    # without approval are paused (owners and admins pause; owners resume).
    unattended_paused: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


class Membership(UUIDPrimaryKeyMixin, TimestampMixin, WorkspaceScopedMixin, Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("workspace_id", "user_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[Role] = mapped_column(str_enum(Role, 20))

    workspace: Mapped[Workspace] = relationship(lazy="raise")
