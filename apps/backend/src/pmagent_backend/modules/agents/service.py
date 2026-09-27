from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from uuid_utils.compat import uuid7

from pmagent_backend.core.errors import Conflict, Forbidden, NotFound, Unprocessable
from pmagent_backend.modules.audit.service import AuditLog
from pmagent_backend.modules.auth.models import User
from pmagent_backend.modules.knowledge.models import AuthorType
from pmagent_backend.modules.projects.deps import ProjectAccess
from pmagent_backend.modules.projects.models import Project
from pmagent_backend.modules.workspaces.permissions import Permission, has_permission

from .models import ACTIVE_STATUSES, AgentApproval, AgentRun, ApprovalStatus, RunKind, RunStatus
from .runner import BRIEFING_PROMPT, AgentRunner
from .schemas import (
    AgentRunRead,
    ApprovalRead,
    ArchitectureDraftRequest,
    DecisionsRequest,
    RunCreate,
    ThreadRead,
    ThreadRename,
    WorkspaceApprovalRead,
)
from .titles import placeholder_title

# The architecture is set up by owners and admins; only they approve changes to it.
PROTECTED_PREFIXES = ("/pmagent/architecture/",)

ARCHITECTURE_DRAFT_PROMPT = """Project setup: draft the architecture overview.

Have architecture-agent read what we know: /pmagent/project.md, /pmagent/requirements/,
the ingested docs under /pmagent/docs/normalized/, and the repository summary below if
there is one. Then write /pmagent/architecture/overview.md: the stack, the main
components and how they relate, the core data model, external integrations, and open
questions. If an overview already exists, update it: keep what is still right and say
what changed. This is an explicit instruction to make that change (Action Mode); the
write will wait for approval."""


class ThreadBusy(Conflict):
    code = "thread_busy"


class NotAwaitingApproval(Conflict):
    code = "not_awaiting_approval"


def _now() -> datetime:
    return datetime.now(UTC)


class AgentService:
    def __init__(self, session: AsyncSession, runner: AgentRunner) -> None:
        self.session = session
        self.runner = runner

    async def create_run(
        self,
        access: ProjectAccess,
        data: RunCreate,
        kind: RunKind = RunKind.CHAT,
        *,
        title: str | None = None,
    ) -> AgentRunRead:
        """Start a run. A new thread gets a title: `title` if given (built-in requests), else a
        placeholder from the message that the runner replaces with the model's title."""
        project, member = access.project, access.member
        self.runner.model_factory(project)  # fail fast (503) if the model can't run
        thread_id = data.thread_id or uuid7()
        if data.thread_id is not None:
            await self._check_thread(project.id, data.thread_id)
        now = _now()
        run = AgentRun(
            id=uuid7(),
            workspace_id=project.workspace_id,
            project_id=project.id,
            thread_id=thread_id,
            kind=kind,
            status=RunStatus.QUEUED,
            message=data.message,
            title=(title or placeholder_title(data.message)) if data.thread_id is None else None,
            requested_by_id=member.user_id,
            created_at=now,
            updated_at=now,
        )
        self.session.add(run)
        AuditLog(self.session).record(
            workspace_id=project.workspace_id,
            project_id=project.id,
            action="agent_run.started",
            target=str(run.id),
            actor_type=AuthorType.USER,
            actor_user_id=member.user_id,
            instructed_by_id=member.user_id,
            details={"kind": kind.value, "thread_id": str(thread_id)},
        )
        await self.session.commit()
        await self.runner.start(run.id, data.message, name_thread=data.thread_id is None and title is None)
        return await self.get(access, run.id)

    async def architecture_draft(
        self, access: ProjectAccess, data: ArchitectureDraftRequest
    ) -> AgentRunRead:
        """Owner/admin project setup: never triggered by connecting a repo."""
        message = ARCHITECTURE_DRAFT_PROMPT
        if data.repo_summary:
            message += f"\n\nRepository summary (from the owner's machine):\n\n{data.repo_summary}"
        AuditLog(self.session).record(
            workspace_id=access.project.workspace_id,
            project_id=access.project.id,
            action="project.architecture_draft",
            target="architecture/overview.md",
            actor_type=AuthorType.USER,
            actor_user_id=access.member.user_id,
            details={"with_repo_summary": bool(data.repo_summary)},
        )
        return await self.create_run(access, RunCreate(message=message), title="Architecture overview draft")

    async def briefing(self, access: ProjectAccess) -> AgentRunRead:
        return await self.create_run(
            access, RunCreate(message=BRIEFING_PROMPT), RunKind.BRIEFING, title="Daily briefing"
        )

    async def get(self, access: ProjectAccess, run_id: uuid.UUID) -> AgentRunRead:
        run = await self.session.scalar(
            select(AgentRun)
            .options(selectinload(AgentRun.approvals))
            .where(AgentRun.project_id == access.project.id, AgentRun.id == run_id)
            .execution_options(populate_existing=True)
        )
        if run is None:
            raise NotFound("Run not found")
        return AgentRunRead.model_validate(run)

    async def list(
        self, access: ProjectAccess, *, thread_id: uuid.UUID | None, limit: int
    ) -> list[AgentRunRead]:
        stmt = (
            select(AgentRun)
            .options(selectinload(AgentRun.approvals))
            .where(AgentRun.project_id == access.project.id)
        )
        if thread_id is not None:
            stmt = stmt.where(AgentRun.thread_id == thread_id)
        stmt = stmt.order_by(AgentRun.created_at.desc()).limit(limit)
        return [AgentRunRead.model_validate(r) for r in await self.session.scalars(stmt)]

    async def pending_approvals(self, access: ProjectAccess) -> list[ApprovalRead]:
        result = await self.session.scalars(
            select(AgentApproval)
            .where(
                AgentApproval.project_id == access.project.id,
                AgentApproval.status == ApprovalStatus.PENDING,
            )
            .order_by(AgentApproval.created_at, AgentApproval.position)
        )
        return [ApprovalRead.model_validate(a) for a in result]

    async def workspace_pending(self, workspace_id: uuid.UUID) -> list[WorkspaceApprovalRead]:
        """Every pending action in the workspace's projects, oldest first."""
        rows = await self.session.execute(
            select(AgentApproval, Project.key, Project.name, AgentRun.message, AgentRun.requested_by_id)
            .join(Project, Project.id == AgentApproval.project_id)
            .join(AgentRun, AgentRun.id == AgentApproval.run_id)
            .where(Project.workspace_id == workspace_id, AgentApproval.status == ApprovalStatus.PENDING)
            .order_by(AgentApproval.created_at, AgentApproval.position)
        )
        return [
            WorkspaceApprovalRead(
                **ApprovalRead.model_validate(approval).model_dump(),
                project_id=approval.project_id,
                project_key=key,
                project_name=name,
                run_message=message,
                requested_by_id=requested_by_id,
            )
            for approval, key, name, message, requested_by_id in rows
        ]

    async def decide(
        self, access: ProjectAccess, run_id: uuid.UUID, data: DecisionsRequest
    ) -> AgentRunRead:
        """Approve or reject every pending action of a paused run, then resume it."""
        member = access.member
        run = await self.session.scalar(
            select(AgentRun)
            .where(AgentRun.project_id == access.project.id, AgentRun.id == run_id)
            .with_for_update()
        )
        if run is None:
            raise NotFound("Run not found")
        if run.status is not RunStatus.AWAITING_APPROVAL:
            raise NotAwaitingApproval(f"This run is {run.status}, not waiting for approval")

        pending = list(
            await self.session.scalars(
                select(AgentApproval)
                .where(AgentApproval.run_id == run.id, AgentApproval.status == ApprovalStatus.PENDING)
                .order_by(AgentApproval.position)
            )
        )
        protected = [a.target for a in pending if (a.target or "").startswith(PROTECTED_PREFIXES)]
        if protected and not has_permission(member.role, Permission.MANAGE_PROJECTS):
            raise Forbidden(
                f"Changes to the project's architecture ({', '.join(protected)}) need an owner or "
                "admin to approve; the run is waiting for them"
            )
        by_id = {d.approval_id: d for d in data.decisions}
        if len(by_id) != len(data.decisions) or set(by_id) != {a.id for a in pending}:
            raise Unprocessable(
                "Send exactly one decision for each pending approval of this run "
                f"({len(pending)} pending)"
            )

        now, audit = _now(), AuditLog(self.session)
        for approval in pending:
            decision = by_id[approval.id]
            approval.status = (
                ApprovalStatus.APPROVED if decision.decision == "approve" else ApprovalStatus.REJECTED
            )
            approval.reason = decision.reason
            approval.decided_by_id, approval.decided_at = member.user_id, now
            audit.record(
                workspace_id=run.workspace_id,
                project_id=run.project_id,
                action=f"approval.{approval.status.value}",
                target=approval.target or approval.tool,
                actor_type=AuthorType.USER,
                actor_user_id=member.user_id,
                instructed_by_id=run.requested_by_id,
                approved_by_id=member.user_id if decision.decision == "approve" else None,
                details={"tool": approval.tool, "run_id": str(run.id), "reason": decision.reason},
            )
        run.status, run.updated_at = RunStatus.QUEUED, now
        await self.session.commit()

        await self.runner.resume(
            run.id,
            interrupt_ids=[a.interrupt_id for a in pending],
            decisions=[(by_id[a.id].decision, by_id[a.id].reason) for a in pending],
            approved_by_id=member.user_id,
        )
        return await self.get(access, run.id)

    async def stop(self, access: ProjectAccess, run_id: uuid.UUID) -> AgentRunRead:
        """Stop a run that's still working. Whoever asked can stop it, and so can owners and
        admins. What the agents already wrote (after approval) stays; the conversation can
        continue with a new message."""
        member = access.member
        run = await self.session.scalar(
            select(AgentRun)
            .where(AgentRun.project_id == access.project.id, AgentRun.id == run_id)
            .with_for_update()
        )
        if run is None:
            raise NotFound("Run not found")
        if run.status not in (RunStatus.QUEUED, RunStatus.RUNNING):
            raise Conflict("Only a run that's still working can be stopped")
        if run.requested_by_id != member.user_id and not has_permission(member.role, Permission.MANAGE_PROJECTS):
            raise Forbidden("Only whoever asked, or an owner or admin, can stop this run")
        user = await self.session.get(User, member.user_id)
        reason = f"Stopped by {user.display_name if user else 'a member'}"
        AuditLog(self.session).record(
            workspace_id=run.workspace_id,
            project_id=run.project_id,
            action="agent_run.stopped",
            target=str(run.id),
            actor_type=AuthorType.USER,
            actor_user_id=member.user_id,
        )
        await self.session.commit()
        await self.runner.stop(run.id, reason)
        # If nothing recorded the stop (it hadn't started, or was cut off by a restart), do it.
        await self.session.refresh(run)
        if run.status in (RunStatus.QUEUED, RunStatus.RUNNING):
            run.status, run.error = RunStatus.FAILED, reason
            run.updated_at = run.finished_at = _now()
            await self.session.commit()
        return await self.get(access, run.id)

    async def rename_thread(self, access: ProjectAccess, thread_id: uuid.UUID, data: ThreadRename) -> ThreadRead:
        """A conversation's title lives on its first run."""
        first = await self.session.scalar(
            select(AgentRun)
            .where(AgentRun.project_id == access.project.id, AgentRun.thread_id == thread_id)
            .order_by(AgentRun.created_at)
            .limit(1)
            .with_for_update()
        )
        if first is None:
            raise NotFound("Conversation not found")
        first.title = data.title.strip()
        await self.session.commit()
        return ThreadRead(thread_id=thread_id, title=first.title)

    async def check_run(self, access: ProjectAccess, run_id: uuid.UUID) -> None:
        found = await self.session.scalar(
            select(AgentRun.id).where(AgentRun.project_id == access.project.id, AgentRun.id == run_id)
        )
        if found is None:
            raise NotFound("Run not found")

    async def _check_thread(self, project_id: uuid.UUID, thread_id: uuid.UUID) -> None:
        runs = list(
            await self.session.scalars(
                select(AgentRun.status).where(
                    AgentRun.project_id == project_id, AgentRun.thread_id == thread_id
                )
            )
        )
        if not runs:
            raise NotFound("Thread not found in this project")
        if any(status in ACTIVE_STATUSES for status in runs):
            raise ThreadBusy(
                "This thread has a run in progress or waiting for approval; finish it first"
            )
