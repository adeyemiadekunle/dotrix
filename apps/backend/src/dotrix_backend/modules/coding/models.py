"""Coding runs (agents v2 step 5c): an issue handed to Claude Code or Codex, which edits a
checkout of the project's repo in a sandbox; the platform pushes a new branch and opens a PR.

A run is asked for by someone who may instruct the coding agent, and starts only once someone
who may approve agent changes approves it (it may be the same person). The agent never holds
the GitHub token: it edits files in the sandbox, and the worker reads its changes back as a
patch, checks them (no `.dotrix/`, no workflows), commits, pushes, and opens the PR.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from dotrix_backend.db.base import Base, UUIDPrimaryKeyMixin, WorkspaceScopedMixin, str_enum


class CodingAgent(enum.StrEnum):
    """The coding tools we wrap; which one runs follows the model key the server has."""

    CLAUDE_CODE = "claude-code"
    CODEX = "codex"


class CodingRunStatus(enum.StrEnum):
    AWAITING_APPROVAL = "awaiting_approval"
    REJECTED = "rejected"
    QUEUED = "queued"
    RUNNING = "running"
    PR_OPENED = "pr_opened"  # done: the PR is up, a person reviews and merges it
    NO_CHANGES = "no_changes"  # done: the agent changed nothing
    FAILED = "failed"
    STOPPED = "stopped"


class CodingOrigin(enum.StrEnum):
    START = "start"  # someone pressed "Start coding"
    ASSIGNED = "assigned"  # someone assigned the issue to a coding tool
    FOLLOW_UP = "follow_up"  # a follow-up in an existing session


class PrState(enum.StrEnum):
    OPEN = "open"
    MERGED = "merged"
    CLOSED = "closed"


ACTIVE = frozenset({CodingRunStatus.AWAITING_APPROVAL, CodingRunStatus.QUEUED, CodingRunStatus.RUNNING})


class CodingRun(UUIDPrimaryKeyMixin, WorkspaceScopedMixin, Base):
    __tablename__ = "coding_runs"

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    issue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("issues.id", ondelete="CASCADE"), index=True)
    issue_key: Mapped[str] = mapped_column(String(24))
    # A session is a run and its follow-ups (turns), on one branch and one PR: the first turn's id.
    session_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    turn: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    origin: Mapped[CodingOrigin] = mapped_column(
        str_enum(CodingOrigin, 16), default=CodingOrigin.START, server_default=CodingOrigin.START.value
    )
    agent: Mapped[CodingAgent] = mapped_column(str_enum(CodingAgent, 16))
    model: Mapped[str | None] = mapped_column(String(100))  # the tool's own default when null
    status: Mapped[CodingRunStatus] = mapped_column(str_enum(CodingRunStatus, 24), index=True)
    # What the agent is told: the issue, its acceptance criteria, linked documents (as data).
    # Fixed when asked for, so the approver sees exactly what will be sent.
    brief: Mapped[str] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)  # what the person asking added

    repo_full_name: Mapped[str] = mapped_column(String(200))
    base_branch: Mapped[str] = mapped_column(String(200))
    base_sha: Mapped[str | None] = mapped_column(String(40))
    branch: Mapped[str | None] = mapped_column(String(200))
    commit_sha: Mapped[str | None] = mapped_column(String(40))
    pr_number: Mapped[int | None] = mapped_column(Integer)
    pr_url: Mapped[str | None] = mapped_column(String(300))
    pr_state: Mapped[PrState | None] = mapped_column(str_enum(PrState, 16))  # kept current by the webhook
    files_changed: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, server_default="[]")
    # What the agent's browser captured in this turn: {key (in storage), name, size, content_type}.
    screenshots: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, server_default="[]")
    # What the agent did, as it happened: [{"at", "kind": "text"|"tool"|"step"|"error", "text"}].
    events: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, server_default="[]")
    summary: Mapped[str | None] = mapped_column(Text)  # the agent's last message
    error: Mapped[str | None] = mapped_column(String(1000))

    input_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    cost_usd: Mapped[float | None] = mapped_column(Numeric(10, 4, asdecimal=False))

    requested_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    decided_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    decision_reason: Mapped[str | None] = mapped_column(String(1000))
    stop_requested: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    review_run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)  # the Reviewer's run on the PR
    review_thread_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)  # its conversation, to open in Chat

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
