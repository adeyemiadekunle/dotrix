from __future__ import annotations

import enum
import uuid

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from pmagent_backend.db.base import (
    Base,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    WorkspaceScopedMixin,
    str_enum,
)

DEFAULT_MODEL = "anthropic:claude-sonnet-5"


class ProjectSource(enum.StrEnum):
    NEW_REPO = "new_repo"  # `init`: a new code repo
    EXISTING_REPO = "existing_repo"  # `connect`: an existing repo
    DOCS_ONLY = "docs_only"  # no code (yet), or not software


class Project(UUIDPrimaryKeyMixin, TimestampMixin, WorkspaceScopedMixin, Base):
    __tablename__ = "projects"
    __table_args__ = (UniqueConstraint("workspace_id", "key"),)

    # Short uppercase key, e.g. "KUN": prefixes issue keys (KUN-42). Never changes.
    key: Mapped[str] = mapped_column(String(10))
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(String(500), default="", server_default="")
    source: Mapped[ProjectSource] = mapped_column(str_enum(ProjectSource, 20))
    repo_url: Mapped[str | None] = mapped_column(String(500))
    model: Mapped[str] = mapped_column(String(100), default=DEFAULT_MODEL)
    # A cheaper model for the specialists and for summarising long conversations; null: `model`.
    specialist_model: Mapped[str | None] = mapped_column(String(100))
    # Tokens one agent run may use (input + output, all its steps); null: the server's default.
    token_budget: Mapped[int | None]
    # Bumped on every .pmagent/ change; lets the CLI mirror pull only what changed.
    knowledge_revision: Mapped[int] = mapped_column(default=0, server_default="0")
    # Next issue number (KUN-<n>). Incremented under a row lock; numbers are never reused.
    next_issue_number: Mapped[int] = mapped_column(default=1, server_default="1")
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
