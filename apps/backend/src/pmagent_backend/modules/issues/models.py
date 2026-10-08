"""Jira-style issues (FR-29, FR-32). The PRD's field list, parent rules, and workflow.

An issue's assignee and reporter are each either a person or an agent, never both.
`issue_events` is the append-only log: every change (old -> new), comment, and
claim, with its author.
"""
from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB  # PG ARRAY: supports @> (contains)
from sqlalchemy.orm import Mapped, mapped_column

from pmagent_backend.db.base import Base, UUIDPrimaryKeyMixin, WorkspaceScopedMixin, str_enum


class IssueType(enum.StrEnum):
    EPIC = "epic"
    STORY = "story"
    TASK = "task"
    BUG = "bug"
    SPIKE = "spike"
    SUB_TASK = "sub-task"


class IssueStatus(enum.StrEnum):
    BACKLOG = "backlog"  # not planned yet; never "ready"
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    REVIEW = "review"
    DONE = "done"


class Priority(enum.StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"
    NONE = "none"  # no priority set (sorts last)


class Recurrence(enum.StrEnum):
    """How often a finished issue comes back (a new issue, due one interval later)."""

    DAILY = "daily"
    WEEKLY = "weekly"
    BIWEEKLY = "biweekly"
    MONTHLY = "monthly"


class AgentAssignee(enum.StrEnum):
    """Agents that appear as assignable members."""

    CODING_AGENT = "coding-agent"  # the built-in coding agent
    CLAUDE_CODE = "claude-code"
    CODEX = "codex"


# Which parent types each type may have (PRD "Issue types and hierarchy").
PARENT_TYPES: dict[IssueType, frozenset[IssueType]] = {
    IssueType.EPIC: frozenset(),
    IssueType.STORY: frozenset({IssueType.EPIC}),
    IssueType.TASK: frozenset({IssueType.EPIC}),
    IssueType.BUG: frozenset({IssueType.EPIC}),
    IssueType.SPIKE: frozenset({IssueType.EPIC}),
    IssueType.SUB_TASK: frozenset({IssueType.STORY, IssueType.TASK, IssueType.BUG}),
}
PARENT_REQUIRED = frozenset({IssueType.SUB_TASK})
# Stories need acceptance criteria and bugs need repro steps, so both need a description.
DESCRIPTION_REQUIRED = frozenset({IssueType.STORY, IssueType.BUG})
PRIORITY_ORDER = {Priority.URGENT: 0, Priority.HIGH: 1, Priority.MEDIUM: 2, Priority.LOW: 3, Priority.NONE: 4}


class Issue(UUIDPrimaryKeyMixin, WorkspaceScopedMixin, Base):
    __tablename__ = "issues"
    __table_args__ = (
        UniqueConstraint("project_id", "number"),
        CheckConstraint(
            "assignee_user_id IS NULL OR assignee_agent IS NULL", name="one_assignee"
        ),
        CheckConstraint(
            "reporter_user_id IS NULL OR reporter_agent IS NULL", name="one_reporter"
        ),
        CheckConstraint("parent_id IS NULL OR parent_id <> id", name="not_own_parent"),
        # Board and backlog queries (FR-30: under a second at 5,000 issues).
        Index("ix_issues_project_id_status", "project_id", "status"),
        Index("ix_issues_project_id_rank", "project_id", "rank"),
        Index("ix_issues_labels", "labels", postgresql_using="gin"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    number: Mapped[int]
    key: Mapped[str] = mapped_column(String(24))  # "KUN-42", denormalised for lookups and display
    type: Mapped[IssueType] = mapped_column(str_enum(IssueType, 16))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    status: Mapped[IssueStatus] = mapped_column(str_enum(IssueStatus, 16))
    priority: Mapped[Priority] = mapped_column(str_enum(Priority, 16))
    assignee_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    assignee_agent: Mapped[AgentAssignee | None] = mapped_column(str_enum(AgentAssignee, 32))
    reporter_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    reporter_agent: Mapped[str | None] = mapped_column(String(32))
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("issues.id", ondelete="SET NULL"), index=True
    )
    estimate: Mapped[float | None] = mapped_column(Numeric(8, 2, asdecimal=False))
    due: Mapped[date | None] = mapped_column(Date)
    scheduled: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    labels: Mapped[list[str]] = mapped_column(ARRAY(String(64)), default=list, server_default="{}")
    components: Mapped[list[str]] = mapped_column(
        ARRAY(String(64)), default=list, server_default="{}"
    )
    # PRs, commits, docs, ADRs: [{"kind": "pr", "url": "...", "title": "..."}]
    links: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, server_default="[]")
    # Its steps, in order: [{"id": "s1", "title": "...", "done": false, "due": null, "assignee_user_id": null}]
    checklist: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, server_default="[]")
    # Finishing it makes the next one, due one interval later; once only (`repeated_as` keeps its key).
    recurrence: Mapped[Recurrence | None] = mapped_column(str_enum(Recurrence, 16))
    repeated_as: Mapped[str | None] = mapped_column(String(24))
    # Backlog order: lower first. New issues go to the bottom; reorder takes a midpoint.
    rank: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IssueDependency(Base):
    """`issue` is blocked by `depends_on` until that one is done."""

    __tablename__ = "issue_dependencies"
    __table_args__ = (CheckConstraint("issue_id <> depends_on_id", name="not_self"),)

    issue_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("issues.id", ondelete="CASCADE"), primary_key=True
    )
    depends_on_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("issues.id", ondelete="CASCADE"), primary_key=True, index=True
    )


class IssueWatcher(Base):
    __tablename__ = "issue_watchers"

    issue_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("issues.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )


class IssueEventKind(enum.StrEnum):
    CREATED = "created"
    UPDATED = "updated"
    COMMENTED = "commented"
    CLAIMED = "claimed"


class IssueEvent(UUIDPrimaryKeyMixin, WorkspaceScopedMixin, Base):
    __tablename__ = "issue_events"

    issue_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("issues.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[IssueEventKind] = mapped_column(str_enum(IssueEventKind, 16))
    author_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    author_agent: Mapped[str | None] = mapped_column(String(32))
    body: Mapped[str | None] = mapped_column(Text)  # comment text
    changes: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)  # {field: [old, new]}
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class IssueAttachment(UUIDPrimaryKeyMixin, WorkspaceScopedMixin, Base):
    """A file added to an issue. The bytes live in object storage, like documents' originals,
    but nothing converts it: any file type, from anyone who may edit issues."""

    __tablename__ = "issue_attachments"

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    issue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("issues.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(255))
    size: Mapped[int]
    storage_key: Mapped[str] = mapped_column(String(600), unique=True)
    uploaded_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class IssueStar(UUIDPrimaryKeyMixin, WorkspaceScopedMixin, Base):
    """An issue someone starred for themselves (their Favorites); nobody else sees it."""

    __tablename__ = "issue_stars"
    __table_args__ = (UniqueConstraint("user_id", "issue_id"),)

    issue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("issues.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
