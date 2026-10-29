"""Agent runs and their approvals (FR-35, FR-36).

A run is one message to the Project Manager on a conversation thread. The
agent team runs in the background; its state is checkpointed per thread (LangGraph),
so a paused run resumes exactly where it stopped. When an agent wants to write,
the run pauses with one approval per pending action; a permitted person decides
them all, and the run resumes.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from dotrix_backend.db.base import Base, UUIDPrimaryKeyMixin, WorkspaceScopedMixin, str_enum

if TYPE_CHECKING:
    from dotrix_backend.modules.research.models import ResearchSource


class RunKind(enum.StrEnum):
    CHAT = "chat"
    BRIEFING = "briefing"  # read-only: any write is rejected automatically


class WorkMode(enum.StrEnum):
    """How the person is working in the conversation (dotrix_engine.work_modes). Changes wait for
    approval in every mode; only Build engages Kai (agents/work_modes.py)."""

    DISCUSS = "discuss"  # advice
    PLAN = "plan"  # a versioned plan (conversation_plans)
    BUILD = "build"  # what they asked: code goes to Kai
    REVIEW = "review"  # what changed, with its evidence


class ChatRuntime(enum.StrEnum):
    DEEPAGENTS = "deepagents"
    FX = "fx"


class RunStatus(enum.StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    WAITING_CHILDREN = "waiting_children"
    WAITING_DEPENDENCY = "waiting_dependency"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


ACTIVE_STATUSES = (RunStatus.QUEUED, RunStatus.RUNNING, RunStatus.AWAITING_APPROVAL, RunStatus.WAITING_CHILDREN, RunStatus.WAITING_DEPENDENCY)


class ApprovalStatus(enum.StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class AgentRun(UUIDPrimaryKeyMixin, WorkspaceScopedMixin, Base):
    __tablename__ = "agent_runs"
    __table_args__ = (UniqueConstraint("parent_run_id", "delegation_key", "task_key"), UniqueConstraint("outcome_key"))

    parent_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agent_runs.id"), index=True)
    delegation_key: Mapped[str | None] = mapped_column(String(200))
    task_key: Mapped[str | None] = mapped_column(String(40))
    depends_on: Mapped[list[str] | None] = mapped_column(JSONB)
    task_mutates: Mapped[bool] = mapped_column(default=False, server_default="false")
    task_result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    waiting_interrupts: Mapped[dict[str, str] | None] = mapped_column(JSONB)
    orchestration: Mapped[bool] = mapped_column(default=False, server_default="false")
    source: Mapped[str] = mapped_column(String(24), default="user", server_default="user")
    outcome_key: Mapped[str | None] = mapped_column(String(160))
    review_context: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    # The project it's about; null for a conversation across projects (or about none), which
    # lists its projects in `project_ids` and is read-only (workspace_runs.py).
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    project_ids: Mapped[list[uuid.UUID] | None] = mapped_column(ARRAY(Uuid))
    thread_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    kind: Mapped[RunKind] = mapped_column(str_enum(RunKind, 16))
    status: Mapped[RunStatus] = mapped_column(str_enum(RunStatus, 24))
    # Each start/resume/continue has one immutable worker dispatch operation.
    dispatch_generation: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # The attempt working on it now (each start, resume, or recovery takes the next token) and
    # until when, renewed while it works; a lapsed lease means its worker stopped (the sweep
    # resumes it from its last checkpoint). A newer token fences an older attempt off.
    lease_token: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    message: Mapped[str] = mapped_column(Text)
    # The conversation's title, on its first run only (a placeholder, then the model's title).
    title: Mapped[str | None] = mapped_column(String(120))
    reply: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    # Why it failed, when that's something to act on: "model_limit" (a provider refused for its
    # rate limit, quota, or credit) or "interrupted" (its worker stopped, again and again). Such a
    # run can be continued from where it stopped.
    error_kind: Mapped[str | None] = mapped_column(String(32))
    resumes_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # when the limit resets, if said
    continue_at_reset: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # The person who instructed the run; recorded as "instructed by" on every write.
    requested_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    # Who leads the run: None for Auto (the Project Manager), or a specialist's role.
    agent: Mapped[str | None] = mapped_column(String(32))
    # The version of that agent's definition the run used; null for an unchanged built-in.
    agent_version: Mapped[int | None] = mapped_column(Integer)
    # A pipeline the leading agent follows for this run instead of its own
    # (dotrix_engine.pipelines.MODES: triaging a report, reviewing an issue); null: its own.
    mode: Mapped[str | None] = mapped_column(String(32))
    # How the person was working when they sent it; null: as before work modes (every tool, writes
    # approved one by one), which the CLI and API clients that don't send one still get.
    work_mode: Mapped[WorkMode | None] = mapped_column(str_enum(WorkMode, 16))
    # The approval mode in effect when it was sent (workspaces/approval_modes.py: manual,
    # accept_edits, auto); null: Manual. The runner checks it again when it works.
    approval_mode: Mapped[str | None] = mapped_column(String(16))
    # Started by an automation (modules/automations), not a person at the time; still instructed
    # by the person who set the automation up (requested_by_id).
    automation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("automations.id", ondelete="SET NULL"), index=True
    )
    # The conversation's model, fixed when it starts (every run of a thread has the same one).
    # Null only on conversations from before models were chosen: they use the project's.
    conversation_model: Mapped[str | None] = mapped_column(String(100))
    # Fixed at conversation creation; recovered runs never switch runtime.
    chat_runtime: Mapped[ChatRuntime] = mapped_column(
        str_enum(ChatRuntime, 16), default=ChatRuntime.DEEPAGENTS, server_default="deepagents"
    )
    # The project's model when the run last worked, and the tokens it used over all its steps
    # (start, then resuming after approvals), the title included.
    model: Mapped[str | None] = mapped_column(String(100))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    cached_input_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    model_calls: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Where the tokens went (usage.merge_breakdown): by agent, tool results, files read.
    usage: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    # The run's token budget when it last worked (null: no limit).
    token_budget: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    approvals: Mapped[list[AgentApproval]] = relationship(
        back_populates="run", order_by="AgentApproval.created_at, AgentApproval.position", lazy="raise"
    )
    # (Not named `outputs`: AgentRunRead builds its `outputs` from these, with each item's index.)
    output_rows: Mapped[list[AgentRunOutput]] = relationship(order_by="AgentRunOutput.created_at", lazy="raise")
    # The web pages its agents found or read (research/models.py), by id: S1, S2, ...
    source_rows: Mapped[list[ResearchSource]] = relationship(order_by="ResearchSource.number", lazy="raise")


class AgentApproval(UUIDPrimaryKeyMixin, WorkspaceScopedMixin, Base):
    __tablename__ = "agent_approvals"

    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    # Order within one pause; decisions are sent back in this order.
    position: Mapped[int]
    interrupt_id: Mapped[str | None] = mapped_column(String(128))
    tool: Mapped[str] = mapped_column(String(64))
    # The handle of the agent whose change this is (null before agents said so, and checkpoints).
    agent: Mapped[str | None] = mapped_column(String(32))
    args: Mapped[dict[str, Any]] = mapped_column(JSONB)
    target: Mapped[str | None] = mapped_column(String(400))  # e.g. the file path
    diff: Mapped[str | None] = mapped_column(Text)  # for file writes: what would change
    status: Mapped[ApprovalStatus] = mapped_column(str_enum(ApprovalStatus, 16))
    reason: Mapped[str | None] = mapped_column(String(500))
    decided_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    run: Mapped[AgentRun] = relationship(back_populates="approvals", lazy="raise")


class AgentRuntimeBinding(UUIDPrimaryKeyMixin, WorkspaceScopedMixin, Base):
    """An experimental runtime session pinned to one private run and its configuration."""

    __tablename__ = "agent_runtime_bindings"
    __table_args__ = (UniqueConstraint("run_id"), UniqueConstraint("runtime", "session_id"))

    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"))
    runtime: Mapped[str] = mapped_column(String(32))
    runtime_version: Mapped[str] = mapped_column(String(80))
    config_digest: Mapped[str] = mapped_column(String(64))
    session_id: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ConversationPlan(UUIDPrimaryKeyMixin, WorkspaceScopedMixin, Base):
    """A version of a conversation's plan, saved in Plan mode (`save_plan`): what Build works from.
    Seen by whoever sees the conversation."""

    __tablename__ = "conversation_plans"
    __table_args__ = (UniqueConstraint("thread_id", "version"),)

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    thread_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    version: Mapped[int] = mapped_column(Integer)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str] = mapped_column(Text)
    acceptance_criteria: Mapped[list[str]] = mapped_column(JSONB)
    # [{"title", "detail", "depends_on": [task numbers, from 1]}]
    tasks: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    open_questions: Mapped[list[str]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AgentRunOutput(UUIDPrimaryKeyMixin, WorkspaceScopedMixin, Base):
    """A run's structured result (docs/agents-v2.md §4.6): the items the leading agent recorded
    with `submit_result`, in its contract's output schema, each with what people did with it."""

    __tablename__ = "agent_run_outputs"

    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    agent: Mapped[str] = mapped_column(String(32))  # the handle that recorded it
    schema_name: Mapped[str] = mapped_column("schema", String(32))  # finding, plan, report, ...
    # [{"data": {...}, "state": "open" | "done" | "dismissed", "reason", "link", "acted_by_id", "acted_at"}]
    items: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    # A report saved as a research note: the note's path in `.dotrix/` (null: not saved).
    note: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RunEventKind(enum.StrEnum):
    STEP = "step"  # an attempt at a step began (start, resume, continue; recovered or not): its text starts over
    TEXT = "text"  # a piece of the reply, as written (coalesced: about a second's worth)
    ACTIVITY = "activity"  # what the agents were doing ("Reading roadmap.md")
    STATUS = "status"  # the run's outcome for the step: awaiting_approval, completed, failed
    TASK = "task"


class AgentRunEvent(UUIDPrimaryKeyMixin, WorkspaceScopedMixin, Base):
    """What a run did, as it happened, kept after it (events.py): a client that reconnects, or
    reloads, picks up where it was (`seq`), and the steps stay readable once the run is done."""

    __tablename__ = "agent_run_events"
    __table_args__ = (UniqueConstraint("run_id", "seq"),)

    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(Integer)  # 1, 2, … per run
    attempt: Mapped[int] = mapped_column(Integer)  # the run's lease token when it was written
    kind: Mapped[RunEventKind] = mapped_column(str_enum(RunEventKind, 16))
    data: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
