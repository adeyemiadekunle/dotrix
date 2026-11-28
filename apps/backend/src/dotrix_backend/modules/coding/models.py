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
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
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
    work_mode: Mapped[str] = mapped_column(String(8), default="build", server_default="build")
    plan_result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    execution_plan: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    skill_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    task_records: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    __tablename__ = "coding_runs"

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    issue_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("issues.id", ondelete="CASCADE"), index=True)
    issue_key: Mapped[str] = mapped_column(String(24))
    task_title: Mapped[str | None] = mapped_column(String(200))
    source_repo_id: Mapped[int | None] = mapped_column(BigInteger)
    source_sha: Mapped[str | None] = mapped_column(String(40))
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
    # The image the session's environment pinned: a digest reference on OpenShell (up to a registry path's length).
    environment_image_id: Mapped[str | None] = mapped_column(String(512))
    environment_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    # The network policy its session pinned when the session's first turn was admitted (coding/network.py): the
    # hosts besides the model API, kept by every follow-up. None: a run from before sessions pinned one.
    network_snapshot: Mapped[list[str] | None] = mapped_column(JSONB(none_as_null=True))
    # The host secrets its session pinned with its first turn (secrets.py): names, hosts and headers, never values,
    # which are read when the turn runs. None: a run from before sessions pinned them (none).
    secret_snapshot: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB(none_as_null=True))
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
    cloud_checkpoint: Mapped[str | None] = mapped_column(Text, deferred=True)
    pending_patch: Mapped[str | None] = mapped_column(Text, deferred=True)
    # The same patch, byte for byte (files that aren't UTF-8 text survive). `pending_patch` (text) is
    # read only for turns that were already waiting before this column existed.
    pending_patch_bytes: Mapped[bytes | None] = mapped_column(LargeBinary, deferred=True)
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
    kind: Mapped[str] = mapped_column(String(32))  # step, text, tool, output, output-error, error, background-<state>
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
    issue_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("issues.id", ondelete="CASCADE"), index=True)
    agent: Mapped[CodingAgent] = mapped_column(str_enum(CodingAgent, 16))
    state: Mapped[CodingSessionState] = mapped_column(str_enum(CodingSessionState, 16), default=CodingSessionState.IDLE)
    claude_session: Mapped[uuid.UUID] = mapped_column(Uuid)  # Claude Code's --session-id / --resume
    # SHA-256 of the system profile (Kai's contract) the engine's session started with, for engines that take one
    # (fx): a resumed turn must find the same profile in its saved state.
    profile_digest: Mapped[str | None] = mapped_column(String(64))
    # Retain the binding even if the runner is revoked, so a second checkout cannot take over.
    local_worktree_runner_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
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


class CodingInputKind(enum.StrEnum):
    STEER = "steer"  # into the turn that's working now, at its next step (fx)
    QUEUE = "queue"  # the session's next turn, once nothing in it is waiting or working


class CodingInputStatus(enum.StrEnum):
    PENDING = "pending"  # not yet handed to the engine (a steer) or not yet a turn (queued)
    SENDING = "sending"  # a steer in the turn's inbox, or sent to the engine, not yet taken
    ACCEPTED = "accepted"  # the engine gave a steer to the model
    DELIVERED = "delivered"  # a steer's turn ended with it taken, or a queued message became a turn
    CANCELLED = "cancelled"  # cancelled by the person, or by Stop
    REJECTED = "rejected"  # refused: by the engine, or because the session couldn't take it


class CodingInput(UUIDPrimaryKeyMixin, WorkspaceScopedMixin, Base):
    """A message a person sends a coding session while Kai works: steering the running turn, or queued for the
    next one, as in Claude Code. Private to whoever started the session. A steer the turn didn't take before it
    ended is queued instead, so nothing a person sent is lost; queued messages become one follow-up turn."""

    __tablename__ = "coding_inputs"
    __table_args__ = (UniqueConstraint("workspace_id", "owner_id", "client_id"),)

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    # The session (its first turn's id; its `coding_sessions` row comes once a turn starts). Deleting a session's
    # turns deletes its messages (`run_id`).
    session_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    client_id: Mapped[uuid.UUID] = mapped_column(Uuid)  # the sender's own id: a retry returns the same message
    # The turn working when it was sent, which a steer goes to; then the turn that took it.
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("coding_runs.id", ondelete="CASCADE"), index=True)
    delivered_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("coding_runs.id", ondelete="SET NULL"))
    kind: Mapped[CodingInputKind] = mapped_column(str_enum(CodingInputKind, 16))
    status: Mapped[CodingInputStatus] = mapped_column(str_enum(CodingInputStatus, 16), default=CodingInputStatus.PENDING)
    message: Mapped[str] = mapped_column(Text)
    # A queued message's turn: its work mode and approval mode as the person chose them (else the last turn's).
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    note: Mapped[str | None] = mapped_column(String(200))  # why it was queued instead, cancelled or refused
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CodingSecret(UUIDPrimaryKeyMixin, WorkspaceScopedMixin, Base):
    """A project's host secret (secrets.py): a credential for one host in the project's network policy, kept out of
    the sandbox. The sandbox's command sees a placeholder in the environment variable `name`; the sandbox's proxy
    (Docker Cloud's or OpenShell's) writes the real value into `header` on requests to `host`, after `prefix`.
    Write-only: the value is stored encrypted and never returned.

    A `shared` row is a reference to the workspace's shared secret of the same name (CodingSharedSecret): its host,
    header, prefix and value are that secret's, read when a turn runs; its own columns stay empty. `phase` says who
    gets it: `all` (the setup script and Kai's commands) or `setup` (the setup script only, removed before Kai runs)."""

    __tablename__ = "coding_secrets"
    __table_args__ = (UniqueConstraint("project_id", "name"),)

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(64))  # the environment variable that holds the placeholder
    shared: Mapped[bool] = mapped_column(Boolean, default=False)  # a reference to the workspace's secret `name`
    phase: Mapped[str] = mapped_column(String(16), default="all")  # "all" or "setup"
    host: Mapped[str | None] = mapped_column(String(260))  # one network policy entry: `host` or `host:port`
    header: Mapped[str | None] = mapped_column(String(64))
    prefix: Mapped[str | None] = mapped_column(String(32))  # what comes before the value in the header
    encrypted: Mapped[str | None] = mapped_column(Text)  # Fernet token (core/crypto.py); never returned
    version: Mapped[int] = mapped_column(Integer, default=1)  # raised on every change, so sandboxes aren't reused
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CodingSharedSecret(UUIDPrimaryKeyMixin, WorkspaceScopedMixin, Base):
    """A workspace's shared host secret (secrets.py): kept once by owners and admins, used by a project only when the
    project references it by name (a `shared` CodingSecret). Write-only, like a project's."""

    __tablename__ = "coding_shared_secrets"
    __table_args__ = (UniqueConstraint("workspace_id", "name"),)

    name: Mapped[str] = mapped_column(String(64))
    host: Mapped[str] = mapped_column(String(260))
    header: Mapped[str] = mapped_column(String(64), default="Authorization")
    prefix: Mapped[str] = mapped_column(String(32), default="Bearer ")
    encrypted: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1)
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


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
    isolation: Mapped[str] = mapped_column(String(16), default="none")  # "sbx" (Docker Sandboxes), "srt", or "none" (a worktree only)
    project_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)  # the projects it has checkouts of
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


def waiting_patch(bytes_value: bytes | None, text_value: str | None) -> bytes | None:
    """The patch waiting to be pushed: the exact bytes, or (a turn that waited before they were kept)
    the old text column's value."""
    if bytes_value is not None:
        return bytes(bytes_value)
    return text_value.encode() if text_value is not None else None
