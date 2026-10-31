"""Coding runs (agents v2 step 5c): an issue handed to Claude Code or Codex, which edits a
checkout of the project's repo in a sandbox; the platform pushes a new branch and opens a PR.

A run is asked for by someone who may instruct the coding agent, and starts only once someone
who may approve agent changes approves it (it may be the same person). The agent never holds
the GitHub token: it edits files in the sandbox, and the worker reads its changes back as a
patch, checks them (no `.dotrix/`, no CI configuration), commits, pushes, and opens the PR.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from dotrix_backend.db.base import Base, UUIDPrimaryKeyMixin, WorkspaceScopedMixin, str_enum
from dotrix_backend.modules.issues.models import AgentAssignee

# The coding agent as people meet it: one teammate beside Nova and the specialists, whatever engine
# codes for it (OpenCode; Claude Code and Codex as the server's fallbacks). Engines stay a detail.
CODING_AGENT_NAME = "Kai"


class CodingAgent(enum.StrEnum):
    """The coding tools we wrap; which one runs follows the model key the server has."""

    CLAUDE_CODE = "claude-code"
    CODEX = "codex"
    OPENCODE = "opencode"  # any provider's model (`DOTRIX_CODING_OPENCODE_MODEL`)
    FX = "fx"  # an OpenAI-compatible provider's model, its default `DOTRIX_CODING_FX_MODEL`

    @property
    def assignee(self) -> AgentAssignee:
        """Who an issue shows as working on it: Kai, the built-in coding agent, whichever engine
        codes (issues once given to `claude-code` or `codex` by name keep them)."""
        return AgentAssignee.CODING_AGENT


class CodingRunStatus(enum.StrEnum):
    AWAITING_APPROVAL = "awaiting_approval"
    REJECTED = "rejected"
    QUEUED = "queued"
    RUNNING = "running"
    # Manual: the turn's changes (checked by the guard, not pushed) wait for a person to accept them;
    # accepted, they're pushed (a publish-only job), rejected, discarded. Nothing has left the worker.
    CHANGES_READY = "changes_ready"
    PR_OPENED = "pr_opened"  # done: the PR is up, a person reviews and merges it
    NO_CHANGES = "no_changes"  # done: the agent changed nothing
    FAILED = "failed"
    RECOVERY_REQUIRED = "recovery_required"  # outcome may be external; inspect before another turn
    STOPPED = "stopped"


class CodingOrigin(enum.StrEnum):
    START = "start"  # someone pressed "Start coding"
    ASSIGNED = "assigned"  # someone assigned the issue to a coding tool
    FOLLOW_UP = "follow_up"  # a follow-up in an existing session


class CodingLocation(enum.StrEnum):
    """Where a turn codes. Either way the platform keeps its record, approvals, and events, and
    pushes what's accepted with the GitHub App: a local turn hands back a patch, never pushes."""

    CLOUD = "cloud"  # a worker's sandbox, on a checkout of the connected repo
    LOCAL = "local"  # the requester's own computer (`dotrix runner`), in a worktree of their checkout


class CodingSessionState(enum.StrEnum):
    WARM = "warm"  # its sandbox is up, between turns
    IDLE = "idle"  # no sandbox: the next turn starts one and resumes from the saved transcript
    CLOSED = "closed"  # closed by hand: its sandbox is gone, its transcript kept (a new turn resumes)


class PrState(enum.StrEnum):
    OPEN = "open"
    MERGED = "merged"
    CLOSED = "closed"


ACTIVE = frozenset({
    CodingRunStatus.AWAITING_APPROVAL, CodingRunStatus.QUEUED,
    CodingRunStatus.RUNNING, CodingRunStatus.RECOVERY_REQUIRED, CodingRunStatus.CHANGES_READY,
})
# Waiting on a person's decision: to start, or to push what it changed.
WAITING = frozenset({CodingRunStatus.AWAITING_APPROVAL, CodingRunStatus.CHANGES_READY})


class CodingRun(UUIDPrimaryKeyMixin, WorkspaceScopedMixin, Base):
    __tablename__ = "coding_runs"

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    issue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("issues.id", ondelete="CASCADE"), index=True)
    issue_key: Mapped[str] = mapped_column(String(24))
    # A session is a run and its follow-ups (turns), on one branch and one PR: the first turn's id.
    session_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    turn: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    # Started from a conversation in Build mode: that conversation, and the plan version it built from.
    thread_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    origin_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agent_runs.id"))
    plan_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("conversation_plans.id", ondelete="SET NULL"))
    origin: Mapped[CodingOrigin] = mapped_column(
        str_enum(CodingOrigin, 16), default=CodingOrigin.START, server_default=CodingOrigin.START.value
    )
    agent: Mapped[CodingAgent] = mapped_column(str_enum(CodingAgent, 16))
    model: Mapped[str | None] = mapped_column(String(100))  # the tool's own default when null
    status: Mapped[CodingRunStatus] = mapped_column(str_enum(CodingRunStatus, 24), index=True)
    # The approval mode this turn was asked in (workspaces/approval_modes.py): Manual waits for an
    # approver; Accept edits and Auto start at once, approved by whoever asked.
    approval_mode: Mapped[str] = mapped_column(String(16), default="manual", server_default="manual")
    dispatch_generation: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # The worker's lease while it runs: `lease_token` goes up each time a worker takes the run (so
    # it counts attempts) and fences the earlier one off, whose writes and pushes then stop.
    lease_token: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # When recovery last looked at GitHub for this run (automatic recovery looks once).
    recovery_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # What the agent is told: the issue, its acceptance criteria, linked documents (as data).
    # Fixed when asked for, so the approver sees exactly what will be sent.
    brief: Mapped[str] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)  # what the person asking added

    repo_full_name: Mapped[str] = mapped_column(String(200))
    base_branch: Mapped[str] = mapped_column(String(200))
    base_sha: Mapped[str | None] = mapped_column(String(40))
    # A worker-local recovery reference, not sent to clients. The filesystem may
    # be unavailable after host loss, so its presence does not prove work survived.
    workspace_path: Mapped[str | None] = mapped_column(String(1024))
    branch: Mapped[str | None] = mapped_column(String(200))
    commit_sha: Mapped[str | None] = mapped_column(String(40))
    # The turn's changes while they wait to be accepted (`changes_ready`), as a binary patch on the
    # session's branch; cleared once pushed or rejected. Who accepted them, and when.
    pending_patch: Mapped[str | None] = mapped_column(Text, deferred=True)
    # The turn's changes as a patch against `base_sha`, kept after it's pushed or discarded: the
    # session's Changes and Files show it (pending_patch is only the copy waiting to be pushed).
    diff: Mapped[str | None] = mapped_column(Text, deferred=True)
    accepted_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Set on a pushed turn being reverted: the revert commit goes on the session's branch.
    revert_of: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("coding_runs.id", ondelete="SET NULL"))
    location: Mapped[CodingLocation] = mapped_column(
        str_enum(CodingLocation, 8), default=CodingLocation.CLOUD, server_default=CodingLocation.CLOUD.value
    )
    # A local turn: the runner that claimed it (its lease is the run's, like a worker's).
    runner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("coding_runners.id", ondelete="SET NULL"))
    runner_name: Mapped[str | None] = mapped_column(String(100))  # kept when the runner is revoked
    # A local turn: its worktree's path on that computer (the desktop app opens it), shown only to
    # whoever asked for the turn.
    worktree: Mapped[str | None] = mapped_column(String(1024))
    pr_number: Mapped[int | None] = mapped_column(Integer)
    pr_url: Mapped[str | None] = mapped_column(String(300))
    pr_state: Mapped[PrState | None] = mapped_column(str_enum(PrState, 16))  # kept current by the webhook
    files_changed: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, server_default="[]")
    # What the agent's browser captured in this turn: {key (in storage), name, size, content_type}.
    screenshots: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, server_default="[]")
    # What the agent did, as it happened: [{"at", "kind": "text"|"tool"|"step"|"error", "text"}].
    # The latest events, for quick reads; every one is kept in coding_events (`event_count` of them).
    events: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, server_default="[]")
    event_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
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
    review_posted_url: Mapped[str | None] = mapped_column(String(300))  # the review on GitHub, once posted (github_reviews.py)
    # CI on the turn's commit, from GitHub's check suites: "passed" or "failed" (None: none seen yet).
    ci_state: Mapped[str | None] = mapped_column(String(16))
    ci_sha: Mapped[str | None] = mapped_column(String(40))  # the commit ci_state is for
    ci_review_run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)  # Juno's look at the failure
    ci_review_posted_url: Mapped[str | None] = mapped_column(String(300))  # that look on the PR, once posted

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CodingRunEvent(UUIDPrimaryKeyMixin, WorkspaceScopedMixin, Base):
    """Everything a coding run did, in order (`seq` from 0): what the agent said and did, steps,
    errors. The run keeps only its latest few; this keeps them all, for the session's view."""

    __tablename__ = "coding_events"
    __table_args__ = (UniqueConstraint("run_id", "seq"),)

    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("coding_runs.id", ondelete="CASCADE"), index=True)
    session_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    seq: Mapped[int] = mapped_column(Integer)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    kind: Mapped[str] = mapped_column(String(16))  # step, text, tool, output, output-error, error
    text: Mapped[str] = mapped_column(Text)
    # Pairs a command (`tool`, "Ran …") with its output (`output`, `output-error`): the tool call's id.
    ref: Mapped[str | None] = mapped_column(String(64))


class CodingSession(WorkspaceScopedMixin, Base):
    """A coding session (Phase B): an issue's turns, on one branch and PR, with one Claude Code
    conversation (`claude_session`, resumed each turn from its saved transcript). Its id is its first
    turn's id, which every turn carries as `session_id`."""

    __tablename__ = "coding_sessions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    issue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("issues.id", ondelete="CASCADE"), index=True)
    agent: Mapped[CodingAgent] = mapped_column(str_enum(CodingAgent, 16))
    state: Mapped[CodingSessionState] = mapped_column(str_enum(CodingSessionState, 16), default=CodingSessionState.IDLE)
    claude_session: Mapped[uuid.UUID] = mapped_column(Uuid)  # Claude Code's --session-id / --resume
    transcript_key: Mapped[str | None] = mapped_column(String(300))  # in storage, encrypted
    cost_reported: Mapped[float | None] = mapped_column(Numeric(10, 4, asdecimal=False))  # Claude's running total
    title: Mapped[str | None] = mapped_column(String(200))  # renamed; else its issue's title
    pinned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_active_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Its sandbox asleep between turns (Docker Cloud: stopped, files kept), to wake for the next one: where
    # it is, its key's secret and placeholder, and which key and network it was opened with (a digest).
    sandbox_handle: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    sandbox_slept_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CodingRunner(UUIDPrimaryKeyMixin, WorkspaceScopedMixin, Base):
    """A person's computer that codes their local turns (`dotrix runner` in a checkout). It only ever
    claims its owner's runs, in the projects it serves, and never holds a provider key or GitHub
    token from the platform: it codes with the tools signed in on that machine and hands back a patch."""

    __tablename__ = "coding_runners"
    __table_args__ = (UniqueConstraint("workspace_id", "user_id", "name"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))  # the machine's name, as its owner sees it
    platform: Mapped[str | None] = mapped_column(String(40))  # e.g. "darwin", "linux"
    tools: Mapped[list[str]] = mapped_column(JSONB, default=list)  # coding tools found there, preferred first
    isolation: Mapped[str] = mapped_column(String(16), default="none")  # "srt", or "none" (a worktree only)
    project_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)  # the projects it has checkouts of
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
