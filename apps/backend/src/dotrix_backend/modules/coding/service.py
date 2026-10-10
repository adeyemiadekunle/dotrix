"""Asking for, approving, and stopping coding runs; the work itself is `runner.py`."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from uuid_utils.compat import uuid7

from dotrix_backend.core.errors import Conflict, Forbidden, NotFound, Unprocessable
from dotrix_backend.core.jobs import Jobs
from dotrix_backend.core.settings import Settings
from dotrix_backend.core.storage import BlobStorage
from dotrix_backend.modules.audit.models import AuthorType
from dotrix_backend.modules.audit.service import AuditLog
from dotrix_backend.modules.connectors.github_app import GitHubAppClient
from dotrix_backend.modules.connectors.models import ConnectedRepo
from dotrix_backend.modules.issues.models import AgentAssignee, Issue, IssueStatus, IssueType
from dotrix_backend.modules.issues.schemas import IssueRead, IssueUpdate
from dotrix_backend.modules.issues.service import IssueActor, IssueService
from dotrix_backend.modules.notifications.notify import Notifier
from dotrix_backend.modules.projects.deps import ProjectAccess
from dotrix_backend.modules.projects.models import Project
from dotrix_backend.modules.projects.repository import visible_to
from dotrix_backend.modules.workspaces.models import Membership
from dotrix_backend.modules.workspaces.permissions import Permission, can

from .brief import build_brief
from .models import ACTIVE, CodingOrigin, CodingRun, CodingRunStatus
from .schemas import (
    CodingAvailability,
    CodingDecision,
    CodingEvent,
    CodingFollowUp,
    CodingRunCreate,
    CodingRunRead,
    CodingScreenshot,
    CodingSessionRead,
)
from .tools import choose_agent, model_for

MAX_LISTED = 50
MAX_SESSION_RUNS = 500  # recent runs read to list a workspace's sessions
CODING_AGENTS = frozenset({AgentAssignee.CODING_AGENT, AgentAssignee.CLAUDE_CODE, AgentAssignee.CODEX})


STATUS_WORDS = {
    CodingRunStatus.NO_CHANGES: "It changed nothing.", CodingRunStatus.FAILED: "It failed.",
    CodingRunStatus.STOPPED: "It was stopped.", CodingRunStatus.REJECTED: "It was rejected.",
    CodingRunStatus.PR_OPENED: "It opened the PR.",
}


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
            reason = "Coding runs aren't set up on this server (DOTRIX_CODING_SANDBOX)"
        elif agent is None:
            reason = "The server needs an Anthropic key (Claude Code) or an OpenAI key (Codex)"
        elif not GitHubAppClient(self.settings).configured:
            reason = "The dotrix GitHub App isn't set up on this server"
        elif await self._repo(project) is None:
            reason = "Connect the project's GitHub repository first (project settings → Repository)"
        return CodingAvailability(available=reason is None, agent=agent, sandbox=sandbox, reason=reason)

    async def start(self, access: ProjectAccess, key: str, data: CodingRunCreate) -> CodingRunRead:
        """Ask for a coding run on an issue: a new session, waiting for an approval."""
        issue = await self._codable(access.project, key)
        run = await self._create(access.project, access.member, issue, data.note, CodingOrigin.START)
        await self.session.commit()
        return self._read(run, access)

    async def start_for_assignment(self, access: ProjectAccess, key: str) -> CodingRunRead | None:
        """An issue was just assigned to a coding tool: start a session in the background (waiting for
        an approval as always), when coding is available and the person may instruct the coding agent.
        Quietly nothing otherwise: the assignment stands either way."""
        if not can(access.member, Permission.INSTRUCT_CODING_AGENT):
            return None
        try:
            issue = await self._codable(access.project, key)
        except (CodingUnavailable, CodingBusy, Conflict, Unprocessable):
            return None
        run = await self._create(access.project, access.member, issue, None, CodingOrigin.ASSIGNED)
        await self.session.commit()
        return self._read(run, access)

    async def follow_up(self, access: ProjectAccess, session_id: uuid.UUID, data: CodingFollowUp) -> CodingRunRead:
        """Another turn in a session: the same agent, on the session's branch, pushing to its PR
        (or opening one, if no turn has yet). It waits for an approval like the first."""
        turns = await self._turns(access.project, session_id)
        if any(t.status in ACTIVE for t in turns):
            raise CodingBusy("This session has a turn waiting or working; follow up once it's done")
        latest = turns[-1]
        issue = await self._codable(access.project, latest.issue_key, busy_ok=False)
        with_branch = next((t for t in reversed(turns) if t.branch and t.pr_number), None)
        earlier = [(t.turn, t.summary or t.error or STATUS_WORDS[t.status]) for t in turns
                   if t.status not in (CodingRunStatus.REJECTED, CodingRunStatus.STOPPED) or t.summary]
        run = await self._create(
            access.project, access.member, issue, data.message, CodingOrigin.FOLLOW_UP,
            session_id=session_id, turn=latest.turn + 1, earlier=earlier, carry=with_branch,
        )
        await self.session.commit()
        return self._read(run, access)

    async def _codable(self, project: Project, key: str, *, busy_ok: bool = False) -> IssueRead:
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
        if busy is not None and not busy_ok:
            raise CodingBusy(f"{issue.key} already has a coding run waiting or working")
        return issue

    async def _create(
        self, project: Project, member: Membership, issue: IssueRead, note: str | None, origin: CodingOrigin, *,
        session_id: uuid.UUID | None = None, turn: int = 1, earlier: list[tuple[int, str]] | None = None,
        carry: CodingRun | None = None,
    ) -> CodingRun:
        agent = choose_agent(self.settings)
        assert agent is not None
        repo = await self._repo(project)
        assert repo is not None
        run_id = uuid7()
        run = CodingRun(
            id=run_id, session_id=session_id or run_id,  # a new session is named after its first turn
            workspace_id=project.workspace_id, project_id=project.id, issue_id=issue.id, issue_key=issue.key,
            turn=turn, origin=origin, agent=agent, model=model_for(self.settings, agent),
            status=CodingRunStatus.AWAITING_APPROVAL,
            brief=await build_brief(self.session, project, issue, note, earlier),
            note=note, repo_full_name=repo.full_name, base_branch=repo.default_branch,
            requested_by_id=member.user_id, created_at=datetime.now(UTC),
        )
        if carry is not None:  # the session's branch and PR: this turn builds on them
            run.branch, run.pr_number, run.pr_url, run.pr_state = carry.branch, carry.pr_number, carry.pr_url, carry.pr_state
        self.session.add(run)
        await self.session.flush()
        AuditLog(self.session).record(
            workspace_id=project.workspace_id, project_id=project.id, action="coding.requested", target=run.issue_key,
            actor_type=AuthorType.USER, actor_user_id=member.user_id, instructed_by_id=member.user_id,
            details={"run_id": str(run.id), "session_id": str(run.session_id), "turn": turn,
                     "origin": origin.value, "agent": agent.value},
        )
        await Notifier(self.session).coding_waiting(
            project, run.id, issue.id, f"Coding {issue.key}: {issue.title}", run.created_at, agent.value,
            requester_id=member.user_id,
        )
        return run

    async def decide(self, access: ProjectAccess, run_id: uuid.UUID, data: CodingDecision) -> CodingRunRead:
        """Approve (it's queued for the worker) or reject a run that waits for approval."""
        run = await self._get(access.project, run_id, for_update=True)
        if run.status is not CodingRunStatus.AWAITING_APPROVAL:
            raise Conflict("This coding run isn't waiting for a decision")
        run.decided_by_id, run.decided_at = access.member.user_id, datetime.now(UTC)
        run.decision_reason = data.reason
        if run.requested_by_id and run.requested_by_id != access.member.user_id:
            title = await self.session.scalar(select(Issue.title).where(Issue.id == run.issue_id)) or run.issue_key
            Notifier(self.session).decided(
                access.project, run.requested_by_id, None, f"Coding {run.issue_key}: {title}", run.decided_at,
                approved=int(data.decision == "approve"), rejected=int(data.decision == "reject"), reason=data.reason,
                actor_user_id=access.member.user_id, coding_run_id=run.id,
            )
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

    async def screenshot(self, access: ProjectAccess, run_id: uuid.UUID, index: int, storage: BlobStorage) -> tuple[bytes, str]:
        """One of the screenshots the agent's browser captured in a turn: its bytes and type."""
        run = await self._get(access.project, run_id)
        shots = list(run.screenshots or [])
        if not 0 <= index < len(shots):
            raise NotFound("Screenshot not found")
        return await storage.get(shots[index]["key"]), shots[index]["content_type"]

    async def session_turns(self, access: ProjectAccess, session_id: uuid.UUID) -> list[CodingRunRead]:
        """A session's turns, first to latest."""
        return [self._read(run, access) for run in await self._turns(access.project, session_id)]

    async def sessions(self, member: Membership) -> list[CodingSessionRead]:
        """The workspace's coding sessions across the projects you can see, latest activity first."""
        rows = (await self.session.execute(
            select(CodingRun, Project.key, Project.name, Issue.title)
            .join(Project, Project.id == CodingRun.project_id)
            .join(Issue, Issue.id == CodingRun.issue_id)
            .where(CodingRun.workspace_id == member.workspace_id, Project.workspace_id == member.workspace_id,
                   visible_to(member.user_id, member.role))
            .order_by(CodingRun.created_at.desc())
            .limit(MAX_SESSION_RUNS)
        )).all()
        sessions: dict[uuid.UUID, CodingSessionRead] = {}
        for run, project_key, project_name, issue_title in rows:  # newest first: the first seen is the latest turn
            found = sessions.get(run.session_id)
            if found is None:
                sessions[run.session_id] = CodingSessionRead(
                    session_id=run.session_id, project_id=run.project_id, project_key=project_key,
                    project_name=project_name, issue_key=run.issue_key, issue_title=issue_title, agent=run.agent,
                    status=run.status, turns=run.turn, branch=run.branch, pr_number=run.pr_number,
                    pr_url=run.pr_url, pr_state=run.pr_state, started_at=run.created_at,
                    updated_at=run.finished_at or run.started_at or run.created_at,
                )
            else:
                found.started_at = run.created_at
        return sorted(sessions.values(), key=lambda s: s.updated_at, reverse=True)

    # -- helpers -------------------------------------------------------------------------

    async def _repo(self, project: Project) -> ConnectedRepo | None:
        return await self.session.scalar(
            select(ConnectedRepo).where(ConnectedRepo.project_id == project.id,
                                        ConnectedRepo.workspace_id == project.workspace_id)
        )

    async def _turns(self, project: Project, session_id: uuid.UUID) -> list[CodingRun]:
        turns = list(await self.session.scalars(
            select(CodingRun).where(CodingRun.project_id == project.id, CodingRun.session_id == session_id)
            .order_by(CodingRun.turn).execution_options(populate_existing=True)
        ))
        if not turns:
            raise NotFound("Coding session not found")
        return turns

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
            session_id=run.session_id, turn=run.turn, origin=run.origin, pr_state=run.pr_state,
            status=run.status, brief=run.brief, note=run.note, repo_full_name=run.repo_full_name,
            base_branch=run.base_branch, base_sha=run.base_sha, branch=run.branch, commit_sha=run.commit_sha,
            pr_number=run.pr_number, pr_url=run.pr_url, files_changed=list(run.files_changed or []),
            screenshots=[
                CodingScreenshot(index=i, name=s["name"], size=s["size"], content_type=s["content_type"])
                for i, s in enumerate(run.screenshots or [])
            ],
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
