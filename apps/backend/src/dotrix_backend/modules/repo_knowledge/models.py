"""A connected repository's inventory at a commit (the Repository Knowledge skill's first step).

Each snapshot lists every path git tracks at that commit, classified without a model
(dotrix_engine/inventory.py): what it is, which knowledge domains it's evidence for, and its
status. Nothing in the declared scope is skipped silently: excluded, unsupported, and
inaccessible paths stay listed with why. A project keeps its latest few snapshots.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from dotrix_backend.db.base import Base, UUIDPrimaryKeyMixin, WorkspaceScopedMixin, str_enum


class PathStatus(enum.StrEnum):
    PENDING = "pending"  # to be read
    ANALYZED = "analyzed"  # read by the skill for this snapshot (or unchanged since one that was)
    EXCLUDED = "excluded"  # listed, not read: vendored, generated, binary, too large (with why)
    UNSUPPORTED = "unsupported"  # no reader for its format yet
    INACCESSIBLE = "inaccessible"  # its contents aren't here: a submodule, or no access


class RepoSnapshot(UUIDPrimaryKeyMixin, WorkspaceScopedMixin, Base):
    __tablename__ = "repo_snapshots"
    __table_args__ = (UniqueConstraint("project_id", "commit_sha", "policy_version"),)

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    repo_full_name: Mapped[str] = mapped_column(String(200))
    commit_sha: Mapped[str] = mapped_column(String(40))
    policy_version: Mapped[str] = mapped_column(String(32))  # the classification rules it was taken with
    path_count: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RepoPath(UUIDPrimaryKeyMixin, WorkspaceScopedMixin, Base):
    __tablename__ = "repo_paths"
    __table_args__ = (
        UniqueConstraint("snapshot_id", "path"),
        Index("ix_repo_paths_snapshot_status", "snapshot_id", "status"),
    )

    snapshot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("repo_snapshots.id", ondelete="CASCADE"))
    path: Mapped[str] = mapped_column(Text)
    size: Mapped[int] = mapped_column(Integer)
    blob: Mapped[str] = mapped_column(String(40))  # git's object id: its content's identity
    language: Mapped[str | None] = mapped_column(String(32))
    kinds: Mapped[list[str]] = mapped_column(ARRAY(String(24)))
    domains: Mapped[list[str]] = mapped_column(ARRAY(String(24)))
    status: Mapped[PathStatus] = mapped_column(str_enum(PathStatus, 16))
    reason: Mapped[str | None] = mapped_column(String(300))
    # When the skill read it, and in which agent run (kept for unchanged content across snapshots).
    analyzed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    analyzed_run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
