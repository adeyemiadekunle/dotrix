"""Organisations own several workspaces (e.g. one per division or client) and manage their
people, without seeing inside them.

Isolation is unchanged: everything in a workspace (projects, knowledge, issues, agent
runs) still requires membership of that workspace. An org admin manages workspaces and
people across the organisation, but sees a workspace's content only if they are a member
of it. Every member of an organisation's workspace is also a member of the organisation.
"""
from __future__ import annotations

import enum
import uuid

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from pmagent_backend.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, str_enum


class OrgRole(enum.StrEnum):
    OWNER = "owner"  # billing, deleting the organisation, owners
    ADMIN = "admin"  # workspaces and people across the organisation
    MEMBER = "member"  # belongs; placed into workspaces by admins


class Organization(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(100))
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class OrgMembership(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "org_memberships"
    __table_args__ = (UniqueConstraint("organization_id", "user_id"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[OrgRole] = mapped_column(str_enum(OrgRole, 20))
