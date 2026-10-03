"""Asking for, approving, and stopping coding runs; the work itself is `runner.py`."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pmagent_backend.core.errors import Conflict, Forbidden, NotFound, Unprocessable
from pmagent_backend.core.jobs import Jobs
from pmagent_backend.core.settings import Settings
from pmagent_backend.modules.audit.models import AuthorType
from pmagent_backend.modules.audit.service import AuditLog
from pmagent_backend.modules.connectors.github_app import GitHubAppClient
from pmagent_backend.modules.connectors.models import ConnectedRepo
from pmagent_backend.modules.issues.models import AgentAssignee, IssueStatus, IssueType
from pmagent_backend.modules.issues.schemas import IssueUpdate
from pmagent_backend.modules.issues.service import IssueActor, IssueService
from pmagent_backend.modules.projects.deps import ProjectAccess
from pmagent_backend.modules.projects.models import Project
from pmagent_backend.modules.workspaces.permissions import Permission, can

from .brief import build_brief
from .models import ACTIVE, CodingRun, CodingRunStatus
from .schemas import CodingAvailability, CodingDecision, CodingEvent, CodingRunCreate, CodingRunRead
from .tools import choose_agent, model_for

MAX_LISTED = 50


class CodingUnavailable(Conflict):
    code = "coding_unavailable"


class CodingBusy(Conflict):
    code = "coding_busy"


class CodingService:
    def __init__(self, session: AsyncSession, settings: Settings, jobs: Jobs) -> None:
        self.session, self.settings, self.jobs = session, settings, jobs

    async def availability(self, project: Project) -> CodingAvailability:
        agent = choose_agent(self.settings)
        sandbox = None if self.settings.coding_sandbox == "off" else self.settings.coding_sandbox
        reason = None
        if sandbox is None:
            reason = "Coding runs aren't set up on this server (PMAGENT_CODING_SANDBOX)"
        elif agent is None:
            reason = "The server needs an Anthropic key (Claude Code) or an OpenAI key (Codex)"
        elif not GitHubAppClient(self.settings).configured:
            reason = "The pmagent GitHub App isn't set up on this server"
        elif await self._repo(project) is None:
            reason = "Connect the project's GitHub repository first (project settings → Repository)"
        return CodingAvailability(available=reason is None, agent=agent, sandbox=sandbox, reason=reason)

    async def start(self, access: ProjectAccess, key: str, data: CodingRunCreate) -> CodingRunRead:
        """Ask for a coding run on an issue; it waits for an approval."""
        project = access.project
        available = await self.availability(project)
        if not available.available or available.agent is None:
            raise CodingUnavailable(available.reason or "Coding runs aren't available")
        issue = await IssueService(self.session).get(project, key)
        if issue.type is IssueType.EPIC:
            raise Unprocessable("An epic is too big for one coding run: start one on each of its stories")
        if issue.status is IssueStatus.DONE:
            raise Conflict(f"{issue.key} is done")
        busy = await self.session.scalar(
            select(CodingRun.id).where(CodingRun.issue_id == issue.id, CodingRun.status.in_(ACTIVE))
        )
        if busy is not None:
            raise CodingBusy(f"{issue.key} already has a coding run waiting or working")
        repo = await self._repo(project)
        assert repo is not None
        run = CodingRun(
            workspace_id=project.workspace_id, project_id=project.id, issue_id=issue.id, issue_key=issue.key,
            agent=available.agent, model=model_for(self.settings, available.agent),
            status=CodingRunStatus.AWAITING_APPROVAL, brief=await build_brief(self.session, project, issue, data.note),
            note=data.note, repo_full_name=repo.full_name, base_branch=repo.default_branch,
            requested_by_id=access.member.user_id, created_at=datetime.now(UTC),
        )
        self.session.add(run)
        await self.session.flush()
        self._audit(project, access, "coding.requested", run)
        await self.session.commit()
        return self._read(run, access)

    async def decide(self, access: ProjectAccess, run_id: uuid.UUID, data: CodingDecision) -> CodingRunRead:
        """Approve (it's queued for the worker) or reject a run that waits for approval."""
        run = await self._get(access.project, run_id, for_update=True)
        if run.status is not CodingRunStatus.AWAITING_APPROVAL:
            raise Conflict("This coding run isn't waiting for a decision")
        run.decided_by_id, run.decided_at = access.member.user_id, datetime.now(UTC)
        run.decision_reason = data.reason
        if data.decision == "reject":
            run.status, run.finished_at = CodingRunStatus.REJECTED, datetime.now(UTC)
            self._audit(access.project, access, "coding.rejected", run)
            await self.session.commit()
            return self._read(run, access)
        available = await self.availability(access.project)
        if not available.available:
            raise CodingUnavailable(available.reason or "Coding runs aren't available")
        run.status = CodingRunStatus.QUEUED
        # The issue is the coding tool's now (its own rules: it may move it to review, never done).
        issue = await IssueService(self.session).get(access.project, run.issue_key)
        change = IssueUpdate(assignee_agent=AgentAssignee(run.agent.value), assignee_user_id=None,
                             note=f"Coding run approved: {run.agent.value} is working on it")
        if issue.status is not IssueStatus.IN_PROGRESS:
            change.status = IssueStatus.IN_PROGRESS
        await IssueService(self.session).update(access.project, run.issue_key, IssueActor(access.member), change)
        self._audit(access.project, access, "coding.approved", run)
        await self.session.commit()
        await self.jobs.enqueue("run_coding", run_id=str(run.id))
        await self.session.refresh(run)
        return self._read(run, access)

    async def stop(self, access: ProjectAccess, run_id: uuid.UUID) -> CodingRunRead:
        run = await self._get(access.project, run_id, for_update=True)
        if not self._can_stop(run, access):
            raise Forbidden("Only whoever asked for this run, or an owner or admin, can stop it")
        if run.status not in ACTIVE:
            raise Conflict("This coding run has finished")
        run.stop_requested = True  # a running one: the worker sees it within seconds and stops the agent
        if run.status is not CodingRunStatus.RUNNING:
            run.status, run.finished_at = CodingRunStatus.STOPPED, datetime.now(UTC)
            run.error = "Stopped before it started"
        self._audit(access.project, access, "coding.stop_requested", run)
        await self.session.commit()
        return self._read(run, access)

    async def list(self, access: ProjectAccess, issue_key: str | None) -> list[CodingRunRead]:
        query = select(CodingRun).where(CodingRun.project_id == access.project.id)
        if issue_key:
            query = query.where(CodingRun.issue_key == issue_key.strip().upper())
        runs = await self.session.scalars(query.order_by(CodingRun.created_at.desc()).limit(MAX_LISTED))
        return [self._read(run, access) for run in runs]

    async def get(self, access: ProjectAccess, run_id: uuid.UUID) -> CodingRunRead:
        return self._read(await self._get(access.project, run_id), access)

    # -- helpers -------------------------------------------------------------------------

    async def _repo(self, project: Project) -> ConnectedRepo | None:
        return await self.session.scalar(
            select(ConnectedRepo).where(ConnectedRepo.project_id == project.id,
                                        ConnectedRepo.workspace_id == project.workspace_id)
        )

    async def _get(self, project: Project, run_id: uuid.UUID, *, for_update: bool = False) -> CodingRun:
        query = select(CodingRun).where(CodingRun.project_id == project.id, CodingRun.id == run_id)
        if for_update:
            query = query.with_for_update()
        run = await self.session.scalar(query.execution_options(populate_existing=True))
        if run is None:
            raise NotFound("Coding run not found")
        return run

    @staticmethod
    def _can_stop(run: CodingRun, access: ProjectAccess) -> bool:
        return run.requested_by_id == access.member.user_id or can(access.member, Permission.MANAGE_PROJECTS)

    def _read(self, run: CodingRun, access: ProjectAccess) -> CodingRunRead:
        usage = can(access.member, Permission.VIEW_USAGE)
        return CodingRunRead(
            id=run.id, project_id=run.project_id, issue_key=run.issue_key, agent=run.agent, model=run.model,
            status=run.status, brief=run.brief, note=run.note, repo_full_name=run.repo_full_name,
            base_branch=run.base_branch, base_sha=run.base_sha, branch=run.branch, commit_sha=run.commit_sha,
            pr_number=run.pr_number, pr_url=run.pr_url, files_changed=list(run.files_changed or []),
            events=[CodingEvent.model_validate(e) for e in run.events or []], summary=run.summary, error=run.error,
            input_tokens=run.input_tokens if usage else None, output_tokens=run.output_tokens if usage else None,
            cost_usd=run.cost_usd if usage else None, requested_by_id=run.requested_by_id,
            decided_by_id=run.decided_by_id, decision_reason=run.decision_reason, review_run_id=run.review_run_id,
            review_thread_id=run.review_thread_id,
            created_at=run.created_at, decided_at=run.decided_at, started_at=run.started_at,
            finished_at=run.finished_at,
            can_decide=run.status is CodingRunStatus.AWAITING_APPROVAL and can(access.member, Permission.APPROVE_ACTIONS),
            can_stop=run.status in ACTIVE and self._can_stop(run, access),
        )

    def _audit(self, project: Project, access: ProjectAccess, action: str, run: CodingRun) -> None:
        AuditLog(self.session).record(
            workspace_id=project.workspace_id, project_id=project.id, action=action, target=run.issue_key,
            actor_type=AuthorType.USER, actor_user_id=access.member.user_id,
            instructed_by_id=run.requested_by_id, approved_by_id=run.decided_by_id,
            details={"run_id": str(run.id), "agent": run.agent.value, "reason": run.decision_reason},
        )
