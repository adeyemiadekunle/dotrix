"""Work modes in a project's conversation (dotrix_engine.work_modes): the platform's side.

The mode describes how the person is working; what may happen still comes from what they ask and
its approval, as in every conversation (each change to documents or the board waits for a person,
or an owner's standing rule). What the platform enforces by mode is execution intent: only Build
engages Kai (`start_coding`, and assigning an issue to Kai through the board tools), so asking
how something would be done never starts coding. Plan saves versions of the conversation's plan
(`save_plan`); Review reads this conversation's coding runs (`coding_evidence`). These tools are
the leading agent's alone. No mode (the CLI, older clients): as before, every tool.
"""
from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from uuid_utils.compat import uuid7

from dotrix_backend.core.errors import DomainError
from dotrix_backend.core.settings import Settings
from dotrix_backend.modules.audit.models import AuthorType
from dotrix_backend.modules.audit.service import AuditLog
from dotrix_backend.modules.projects.deps import ProjectAccess
from dotrix_backend.modules.projects.repository import ProjectRepository
from dotrix_backend.modules.workspaces.approval_modes import ApprovalMode
from dotrix_backend.modules.workspaces.permissions import Permission, can
from dotrix_backend.modules.workspaces.repository import MembershipRepository

from .models import ConversationPlan, WorkMode

logger = logging.getLogger(__name__)

EVIDENCE_RUNS = 20  # the latest coding runs `coding_evidence` shows


def codes(mode: WorkMode | None) -> bool:
    """Whether Kai may be engaged in `mode`: in Build, or without a mode (as before work modes)."""
    return mode is None or mode is WorkMode.BUILD


@dataclass(frozen=True)
class ModeContext:
    session_factory: Callable[[], AbstractAsyncContextManager[AsyncSession]]
    settings: Settings | None  # None: coding isn't offered
    workspace_id: uuid.UUID
    project_id: uuid.UUID
    thread_id: uuid.UUID
    run_id: uuid.UUID
    instructed_by_id: uuid.UUID | None
    approval: ApprovalMode | None = None  # the run's approval mode: Kai starts at once when it goes through
    jobs: Any = None  # where a coding run that starts at once goes (None: it waits for an approval)


class PlanTask(BaseModel):
    title: str = Field(max_length=200)
    detail: str = Field(default="", max_length=4000, description="What to do, where, and how to tell it's done")
    depends_on: list[int] = Field(default_factory=list, description="The tasks (numbers, from 1) this one needs first")


class SavePlan(BaseModel):
    title: str = Field(max_length=200)
    summary: str = Field(max_length=4000, description="What we'll build and why, in a few sentences")
    acceptance_criteria: list[str] = Field(max_length=30, description="Each one checkable when it's done")
    tasks: list[PlanTask] = Field(min_length=1, max_length=40, description="In order")
    open_questions: list[str] = Field(default_factory=list, max_length=20)


class StartCoding(BaseModel):
    issue_key: str = Field(max_length=24, description="The issue Kai works on, e.g. KUN-12")
    note: str | None = Field(default=None, max_length=2000,
                             description="What to tell Kai beyond the issue: the plan task, constraints")


def lead_tools(mode: WorkMode | None, ctx: ModeContext) -> list[Any]:
    """The tools the agent talking to the person gets in `mode` (none outside work modes)."""
    if mode is WorkMode.PLAN:
        return [StructuredTool.from_function(
            coroutine=lambda **kw: _save_plan(ctx, SavePlan(**kw)), name="save_plan", args_schema=SavePlan,
            description="Save the plan as the conversation's next version (the person builds from it).",
        )]
    if mode is WorkMode.BUILD and ctx.settings is not None:
        return [StructuredTool.from_function(
            coroutine=lambda **kw: _start_coding(ctx, StartCoding(**kw)), name="start_coding", args_schema=StartCoding,
            description="Ask Kai, the coding agent, to code an issue: a coding run that waits for a person's approval.",
        )]
    if mode is WorkMode.REVIEW:
        async def coding_evidence() -> dict[str, Any]:
            """This conversation's coding runs, latest first: status, branch, PR, files changed, what Kai
            reported, and errors."""
            return await _coding_evidence(ctx)

        return [StructuredTool.from_function(coroutine=coding_evidence, name="coding_evidence")]
    return []


async def _save_plan(ctx: ModeContext, plan: SavePlan) -> dict[str, Any]:
    count = len(plan.tasks)
    for number, task in enumerate(plan.tasks, 1):
        if any(d < 1 or d > count or d == number for d in task.depends_on):
            return {"error": f"Task {number} depends on a task that isn't in the plan (tasks are 1 to {count})"}
    async with ctx.session_factory() as session:
        if not await _sees(session, ctx):
            return {"error": "The project or the person who asked is gone"}
        latest = await session.scalar(select(func.max(ConversationPlan.version)).where(
            ConversationPlan.workspace_id == ctx.workspace_id, ConversationPlan.thread_id == ctx.thread_id,
        ))
        row = ConversationPlan(
            id=uuid7(), workspace_id=ctx.workspace_id, project_id=ctx.project_id, thread_id=ctx.thread_id,
            version=(latest or 0) + 1, run_id=ctx.run_id, title=plan.title, summary=plan.summary,
            acceptance_criteria=plan.acceptance_criteria, tasks=[t.model_dump() for t in plan.tasks],
            open_questions=plan.open_questions, created_at=datetime.now(UTC),
        )
        session.add(row)
        await session.commit()
    return {"saved": f"Plan version {row.version}", "version": row.version}


async def _start_coding(ctx: ModeContext, ask: StartCoding) -> dict[str, Any]:
    from dotrix_backend.modules.coding.models import CodingRun, CodingSession, CodingSessionState
    from dotrix_backend.modules.coding.schemas import CodingFollowUp, CodingRunCreate
    from dotrix_backend.modules.coding.service import CodingService

    assert ctx.settings is not None
    async with ctx.session_factory() as session:
        project = await ProjectRepository(session).get(ctx.workspace_id, ctx.project_id)
        member = await MembershipRepository(session).get(ctx.workspace_id, ctx.instructed_by_id) \
            if ctx.instructed_by_id else None
        # Checked now, not when the message was sent: they may have lost the project meanwhile.
        if project is None or member is None or not await ProjectRepository(session).can_see(project, member.user_id):
            return {"error": "The project or the person who asked is gone"}
        if not can(member, Permission.INSTRUCT_CODING_AGENT):
            return {"error": "The person you're working for can't instruct Kai; say so, and suggest who can"}
        plan_id = await session.scalar(select(ConversationPlan.id).where(
            ConversationPlan.workspace_id == ctx.workspace_id, ConversationPlan.thread_id == ctx.thread_id,
        ).order_by(ConversationPlan.version.desc()).limit(1))
        try:
            approval = ctx.approval if ctx.jobs is not None else None
            service = CodingService(session, ctx.settings, ctx.jobs or _NO_JOBS)
            previous = await session.scalar(select(CodingRun).join(CodingSession, CodingSession.id == CodingRun.session_id).where(
                CodingRun.workspace_id == ctx.workspace_id, CodingRun.project_id == ctx.project_id,
                CodingRun.thread_id == ctx.thread_id, CodingRun.issue_key == ask.issue_key,
                CodingSession.state != CodingSessionState.CLOSED, CodingSession.archived_at.is_(None),
            ).order_by(CodingRun.created_at.desc()).limit(1))
            if previous:
                run = await service.follow_up(ProjectAccess(project, member), previous.session_id,
                    CodingFollowUp(message=ask.note or "Continue the instructed work on this issue", approval_mode=approval),
                    origin_run_id=ctx.run_id)
            else:
                run = await service.start(
                    ProjectAccess(project, member), ask.issue_key, CodingRunCreate(note=ask.note, approval_mode=approval),
                    thread_id=ctx.thread_id, plan_id=plan_id, origin_run_id=ctx.run_id,
                )
        except DomainError as exc:  # not available here, busy, no such issue, ...
            return {"error": exc.detail}
        AuditLog(session).record(
            workspace_id=ctx.workspace_id, project_id=ctx.project_id, action="coding.requested_in_conversation",
            target=run.issue_key, actor_type=AuthorType.AGENT, instructed_by_id=member.user_id,
            details={"coding_run_id": str(run.id), "thread_id": str(ctx.thread_id), "run_id": str(ctx.run_id),
                     **({"plan_id": str(plan_id)} if plan_id else {})},
        )
        await session.commit()
    waiting = run.status.value == "awaiting_approval"
    return {"coding_run_id": str(run.id), "issue_key": run.issue_key, "status": run.status.value,
            "said": "Waiting for a person's approval before Kai starts" if waiting
            else "Kai has started (your approval mode lets it start at once); the PR is where it's reviewed"}


async def _coding_evidence(ctx: ModeContext) -> dict[str, Any]:
    from dotrix_backend.modules.coding.models import CodingRun

    async with ctx.session_factory() as session:
        if not await _sees(session, ctx):
            return {"error": "The project or the person who asked is gone"}
        # Every turn of the sessions this conversation started: follow-ups (from the Code tab, say)
        # build on the same branch and PR.
        sessions = select(CodingRun.session_id).where(
            CodingRun.workspace_id == ctx.workspace_id, CodingRun.thread_id == ctx.thread_id,
        )
        runs = list(await session.scalars(select(CodingRun).where(
            CodingRun.workspace_id == ctx.workspace_id, CodingRun.project_id == ctx.project_id,
            CodingRun.session_id.in_(sessions),
        ).order_by(CodingRun.created_at.desc()).limit(EVIDENCE_RUNS)))
    if not runs:
        return {"runs": [], "said": "No coding has been started from this conversation"}
    return {"runs": [{
        "issue_key": r.issue_key, "turn": r.turn, "status": r.status.value, "branch": r.branch,
        "commit": r.commit_sha, "pr": r.pr_url, "pr_state": r.pr_state.value if r.pr_state else None,
        "files_changed": [f"{f['path']} (+{f.get('added', 0)} -{f.get('removed', 0)})" for f in r.files_changed[:60]],
        "kai_reported": (r.summary or "")[:3000] or None, "error": r.error,
    } for r in runs]}


async def _sees(session: AsyncSession, ctx: ModeContext) -> bool:
    """Whether the person the run works for still sees the project (they may have lost it since)."""
    project = await ProjectRepository(session).get(ctx.workspace_id, ctx.project_id)
    return bool(project and ctx.instructed_by_id and await ProjectRepository(session).can_see(project, ctx.instructed_by_id))


class _NoJobs:
    """Asking for a coding run queues nothing (it waits for an approval)."""

    async def enqueue(self, name: str, **kwargs: Any) -> None:
        raise RuntimeError(f"Asking for a coding run never enqueues ({name})")


_NO_JOBS = _NoJobs()
