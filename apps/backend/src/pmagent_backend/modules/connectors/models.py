"""Code hosts connected to a workspace (the pmagent GitHub App) and the repo each project uses."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from pmagent_backend.db.base import Base, UUIDPrimaryKeyMixin, WorkspaceScopedMixin


class GitHubInstallation(UUIDPrimaryKeyMixin, WorkspaceScopedMixin, Base):
    """The GitHub App installed on a GitHub account (a person or an organisation), added to this
    workspace by someone GitHub says can manage that installation. Its repos can be connected
    to this workspace's projects."""

    __tablename__ = "github_installations"
    __table_args__ = (UniqueConstraint("workspace_id", "installation_id"),)

    installation_id: Mapped[int] = mapped_column(BigInteger, index=True)  # GitHub's
    account_login: Mapped[str] = mapped_column(String(100))
    account_type: Mapped[str] = mapped_column(String(20))  # "User" or "Organization"
    installed_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ConnectedRepo(UUIDPrimaryKeyMixin, WorkspaceScopedMixin, Base):
    """A project's repository, reached through one of the workspace's installations. One per
    project, and a repo serves one project per workspace."""

    __tablename__ = "connected_repos"
    __table_args__ = (UniqueConstraint("project_id"), UniqueConstraint("workspace_id", "github_repo_id"))

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    installation_ref: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("github_installations.id", ondelete="CASCADE"), index=True
    )
    github_repo_id: Mapped[int] = mapped_column(BigInteger, index=True)  # stable across renames
    full_name: Mapped[str] = mapped_column(String(200))  # "owner/name", kept current by pushes
    default_branch: Mapped[str] = mapped_column(String(200))
    private: Mapped[bool] = mapped_column(Boolean)
    html_url: Mapped[str] = mapped_column(String(300))
    connected_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_push_sha: Mapped[str | None] = mapped_column(String(40))  # the default branch's latest commit
    last_push_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # The checkout agents read (modules/code): the commit, when, and why the last sync failed.
    checkout_sha: Mapped[str | None] = mapped_column(String(40))
    checked_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    checkout_error: Mapped[str | None] = mapped_column(String(500))
