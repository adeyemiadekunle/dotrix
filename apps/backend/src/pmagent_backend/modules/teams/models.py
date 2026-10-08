"""Teams: groups of people in a workspace (Design, Engineering, ...), and the projects each looks
after. One team each: a person is in at most one team of a workspace, a project under at most one.
"""
from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from pmagent_backend.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, WorkspaceScopedMixin


class Team(UUIDPrimaryKeyMixin, TimestampMixin, WorkspaceScopedMixin, Base):
    __tablename__ = "teams"
    __table_args__ = (UniqueConstraint("workspace_id", "name"),)

    name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    icon: Mapped[str] = mapped_column(String(40), default="users", server_default="users")
    color: Mapped[str] = mapped_column(String(7), default="#8A867E", server_default="#8A867E")  # "#RRGGBB"


class TeamMember(TimestampMixin, WorkspaceScopedMixin, Base):
    __tablename__ = "team_members"
    __table_args__ = (UniqueConstraint("workspace_id", "user_id"),)  # one team each

    team_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), primary_key=True, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)


class TeamProject(TimestampMixin, WorkspaceScopedMixin, Base):
    __tablename__ = "team_projects"

    team_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), index=True)
    # One team each: the project is the key.
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
