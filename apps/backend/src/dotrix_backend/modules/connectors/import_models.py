"""Reviewed GitHub import snapshots and permanent source identities, scoped to a project."""
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from dotrix_backend.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, WorkspaceScopedMixin


class GitHubImportPreview(UUIDPrimaryKeyMixin, TimestampMixin, WorkspaceScopedMixin, Base):
    __tablename__ = "github_import_previews"
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    requested_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    binding_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("connected_repos.id", ondelete="CASCADE"))
    github_repo_id: Mapped[int] = mapped_column(BigInteger)
    snapshot: Mapped[dict] = mapped_column(JSONB)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    selection_digest: Mapped[str | None] = mapped_column(String(64))
    result: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))


class GitHubImportedIssue(UUIDPrimaryKeyMixin, TimestampMixin, WorkspaceScopedMixin, Base):
    __tablename__ = "github_imported_issues"
    __table_args__ = (UniqueConstraint("project_id", "github_repo_id", "github_issue_id"),)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    github_repo_id: Mapped[int] = mapped_column(BigInteger)
    github_issue_id: Mapped[int] = mapped_column(BigInteger)
    source_number: Mapped[int] = mapped_column(BigInteger)
    source_url: Mapped[str] = mapped_column(String(500))
    # Keep the source tombstone after a task is deleted: retries never resurrect it.
    issue_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("issues.id", ondelete="SET NULL"))
    issue_key: Mapped[str] = mapped_column(String(24))
    imported_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
