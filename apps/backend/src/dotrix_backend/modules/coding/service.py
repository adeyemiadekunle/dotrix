"""Asking for, approving, and stopping coding runs; the work itself is `runner.py`."""
from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from uuid_utils.compat import uuid7

from dotrix_backend.core.crypto import Secrets
from dotrix_backend.core.errors import Conflict, Forbidden, NotFound, Unprocessable
from dotrix_backend.core.jobs import Jobs, QueuedJobs
from dotrix_backend.core.settings import Settings
from dotrix_backend.core.storage import BlobStorage, StorageUnavailable
from dotrix_backend.modules.agents.queue import RunQueue
from dotrix_backend.modules.audit.models import AuthorType
from dotrix_backend.modules.audit.service import AuditLog
from dotrix_backend.modules.auth.models import User
from dotrix_backend.modules.connectors.github_app import GitHubApp, GitHubAppClient
from dotrix_backend.modules.connectors.models import ConnectedRepo
from dotrix_backend.modules.execution.models import RunDispatch
from dotrix_backend.modules.execution.service import RunDispatcher, record_dispatch
from dotrix_backend.modules.issues.models import AgentAssignee, Issue, IssueStatus, IssueType
from dotrix_backend.modules.issues.schemas import IssueRead, IssueUpdate
from dotrix_backend.modules.issues.service import IssueActor, IssueService
from dotrix_backend.modules.model_keys.service import run_keys
from dotrix_backend.modules.notifications.notify import Notifier
from dotrix_backend.modules.projects.deps import ProjectAccess
from dotrix_backend.modules.projects.models import Project
from dotrix_backend.modules.projects.repository import visible_to
from dotrix_backend.modules.workspaces.approval_modes import ApprovalMode, effective, goes_through
from dotrix_backend.modules.workspaces.models import Membership
from dotrix_backend.modules.workspaces.permissions import Permission, can

from .brief import build_brief
from .models import (
    ACTIVE,
    CODING_AGENT_NAME,
    WAITING,
    CodingAgent,
    CodingLocation,
    CodingOrigin,
    CodingRun,
    CodingRunEvent,
    CodingRunner,
    CodingRunStatus,
    CodingSession,
    CodingSessionState,
    PrState,
)
from .recovery import Recovered, discard, lease_live, recover
from .runner import needs_worker
from .schemas import (
    CodingAvailability,
    CodingDecision,
    CodingEvent,
    CodingEventPage,
    CodingEventRead,
    CodingFollowUp,
    CodingRecover,
    CodingRevert,
    CodingRunCreate,
    CodingRunRead,
    CodingScreenshot,
    CodingSessionRead,
    CodingSessionUpdate,
    CodingToolOption,
)
from .tools import choose_agent, engine_for, kai_models, model_for, models_for, run_key, tool_for

MAX_LISTED = 50
logger = logging.getLogger(__name__)
MAX_SESSION_RUNS = 500  # recent runs read to list a workspace's sessions
CODING_AGENTS = frozenset({AgentAssignee.CODING_AGENT, AgentAssignee.CLAUDE_CODE, AgentAssignee.CODEX})


STATUS_WORDS = {
    CodingRunStatus.NO_CHANGES: "It changed nothing.", CodingRunStatus.FAILED: "It failed.",
    CodingRunStatus.RECOVERY_REQUIRED: "Its result needs reconciliation.",
    CodingRunStatus.STOPPED: "It was stopped.", CodingRunStatus.REJECTED: "It was rejected.",
    CodingRunStatus.PR_OPENED: "It opened the PR.",
}


def visible_runs(member: Membership) -> Any:
    """The coding runs `member` sees: theirs (sessions are private, like conversations), and, when
    they may approve agent changes, those waiting on that decision (to start, or to push)."""
    clause = CodingRun.requested_by_id == member.user_id
    if can(member, Permission.APPROVE_ACTIONS):
        clause = or_(clause, CodingRun.status.in_(WAITING))
    return clause


def _sees(run: CodingRun, member: Membership) -> bool:
    return run.requested_by_id == member.user_id or (
        run.status in WAITING and can(member, Permission.APPROVE_ACTIONS))


def _earlier(turn: CodingRun) -> str:
    """What an earlier turn did, for the next turn's brief."""
    said = turn.summary or turn.error or STATUS_WORDS[turn.status]
    if turn.status is CodingRunStatus.REJECTED and turn.summary:
        return f"(its changes were rejected and never pushed: they're not on the branch) {said}"
    return said


class CodingUnavailable(Conflict):
    code = "coding_unavailable"


class CodingBusy(Conflict):
    code = "coding_busy"


class CodingService:
    def __init__(self, session: AsyncSession, settings: Settings, jobs: Jobs, *, secrets: Secrets | None = None) -> None:
        self.session, self.settings, self.jobs = session, settings, jobs
        self.secrets = secrets or Secrets.from_settings(settings)

    async def _keys(self, project: Project, user_id: uuid.UUID | None) -> dict[str, str]:
        keys = await run_keys(self.session, self.secrets, project.workspace_id, user_id)
        return keys.keys

    async def _selection(
        self, project: Project, user_id: uuid.UUID, location: CodingLocation, *,
        agent: CodingAgent | None = None, model: str | None = None, fixed: bool = False,
    ) -> tuple[CodingAgent, str | None]:
        user = await self.session.get(User, user_id)
        preferred = user.default_coding_tool if user else None
        if location is CodingLocation.LOCAL:
            runner, reason = await self.local_availability(project, user_id)
            if reason or not runner or not runner.tools:
                raise CodingUnavailable(reason or "No coding tool is installed on your computer")
            selected = agent or (CodingAgent(preferred) if preferred in runner.tools else CodingAgent(runner.tools[0]))
            if selected.value not in runner.tools:
                raise CodingUnavailable("The coding tool you picked isn't installed on your computer")
            return selected, model if fixed else None
        keys = await self._keys(project, user_id)
        # A new session codes on the model picked, else the person's default model; the engine follows it.
        if agent is None and not fixed:
            choices = kai_models(self.settings, set(keys))
            default = user.default_model if user else None
            wanted = model if model is not None else (default if default in choices else None)
            if wanted is not None:
                if wanted not in choices:
                    raise Unprocessable("Choose one of your models (Account → Your models)")
                agent, model = engine_for(self.settings, wanted, set(keys), preferred), wanted
        selected = agent or choose_agent(
            self.settings, set(keys), preferred=preferred, preferred_model=user.default_model if user else None,
        )
        if selected is None:
            raise CodingUnavailable("Connect a model provider in Account → Your models before coding")
        chosen = model if fixed or model is not None else model_for(
            self.settings, selected, set(keys), preferred_model=user.default_model if user else None,
        )
        if not fixed and model is not None:
            if model not in models_for(self.settings, selected, set(keys)):
                raise Unprocessable("Choose an available provider:model")
        if selected is CodingAgent.FX and not self.settings.coding_fx and not fixed:
            raise CodingUnavailable("That coding tool isn't available on this server")
        tool = tool_for(selected, chosen, self.settings)
        if tool is None or not run_key(tool, self.settings, keys):
            raise CodingUnavailable(f"Connect a compatible provider key in Account → Your models to code with {CODING_AGENT_NAME}")
        return selected, chosen

    async def availability(self, project: Project, user_id: uuid.UUID | None) -> CodingAvailability:
        """Whether `user_id` (who asks for the run, and whose own key it may use) can code here."""
        keys = await self._keys(project, user_id)
        providers = set(keys)
        user = await self.session.get(User, user_id) if user_id else None
        agent = choose_agent(self.settings, providers, preferred=user.default_coding_tool if user else None,
                             preferred_model=user.default_model if user else None)
        tools = []
        for candidate in CodingAgent:
            if candidate is CodingAgent.FX and not self.settings.coding_fx:
                continue  # opt-in: not offered at all while off
            model = model_for(self.settings, candidate, providers, preferred_model=user.default_model if user else None)
            tool = tool_for(candidate, model, self.settings)
            usable = tool is not None and bool(run_key(tool, self.settings, keys))
            tools.append(CodingToolOption(
                agent=candidate, available=usable, model=model,
                models=models_for(self.settings, candidate, providers),
                reason=None if usable else "Connect a compatible provider in Account → Your models",
            ))
        sandbox = None if self.settings.coding_sandbox == "off" else self.settings.coding_sandbox
        reason = None
        if sandbox is None:
            reason = "Coding runs aren't set up on this server (DOTRIX_CODING_SANDBOX)"
        elif agent is None:
            reason = "Connect your own model provider in Account → Your models"
        elif not GitHubAppClient(self.settings).configured:
            reason = "The dotrix GitHub App isn't set up on this server"
        elif await self._repo(project) is None:
            reason = "Connect the project's GitHub repository first (project settings → Repository)"
        runner, local_reason = await self.local_availability(project, user_id)
        # What a new session offers: every model you can code on, starting from your default model.
        models = kai_models(self.settings, providers)
        default_model = user.default_model if user and user.default_model in models else None
        if default_model is None and agent is not None:
            fallback = model_for(self.settings, agent, providers, preferred_model=user.default_model if user else None)
            default_model = fallback if fallback in models else next(iter(models), None)
        return CodingAvailability(available=reason is None, agent=agent, sandbox=sandbox, reason=reason,
                                  models=models, default_model=default_model,
                                  local_available=local_reason is None, local_runner=runner.name if runner else None,
                                  local_reason=local_reason, tools=tools, default_tool=agent,
                                  local_tools=[CodingAgent(t) for t in runner.tools] if runner else [])

    async def local_availability(self, project: Project, user_id: uuid.UUID | None) -> tuple[CodingRunner | None, str | None]:
        """Whether `user_id` can code here on their own computer: the runner that would (the one seen
        last), or why not. Its result is pushed by the platform, so the repo must be connected."""
        runner = await self.session.scalar(select(CodingRunner).where(
            CodingRunner.workspace_id == project.workspace_id, CodingRunner.user_id == user_id,
            CodingRunner.revoked_at.is_(None), CodingRunner.project_ids.contains([str(project.id)]),
        ).order_by(CodingRunner.last_seen_at.desc()).limit(1)) if user_id else None
        if runner is None:
            return None, f"Run `dotrix runner` in a checkout of {project.key} on your computer first"
        return runner, await self._publishable(project)

    async def _publishable(self, project: Project) -> str | None:
        """Why the platform can't push to the project's repository (None: it can): what a local turn
        and a revert need, whatever coding is set up on the server."""
        if not GitHubAppClient(self.settings).configured:
            return "The dotrix GitHub App isn't set up on this server"
        if await self._repo(project) is None:
            return "Connect the project's GitHub repository first (project settings → Repository)"
        return None

    async def start(
        self, access: ProjectAccess, key: str, data: CodingRunCreate, *,
        thread_id: uuid.UUID | None = None, plan_id: uuid.UUID | None = None,
        origin_run_id: uuid.UUID | None = None,
    ) -> CodingRunRead:
        """Ask for a coding run on an issue: a new session, waiting for an approval (or started at
        once, when the person's approval mode lets it go through). From a conversation in Build mode:
        that conversation, and the plan version it builds from."""
        if thread_id:
            await self.session.scalar(select(Project).where(Project.workspace_id == access.member.workspace_id,
                                                           Project.id == access.project.id).with_for_update())
            busy = await self.session.scalar(select(CodingRun.id).where(
                CodingRun.workspace_id == access.member.workspace_id, CodingRun.thread_id == thread_id,
                CodingRun.status.in_(ACTIVE)).limit(1))
            if busy:
                raise CodingBusy("Kai already has an active turn in this conversation")
        issue = await self._codable(access.project, access.member.user_id, key, location=data.location)
        run = await self._create(access.project, access.member, issue, data.note, CodingOrigin.START,
                                 approval=data.approval_mode, location=data.location,
                                 requested_agent=data.agent, requested_model=data.model)
        run.thread_id, run.plan_id = thread_id, plan_id
        run.origin_run_id = origin_run_id
        return await self._settle(access, run)

    async def start_for_assignment(self, access: ProjectAccess, key: str) -> CodingRunRead | None:
        """An issue was just assigned to a coding tool: start a session in the background (waiting for
        an approval as always), when coding is available and the person may instruct the coding agent.
        Quietly nothing otherwise: the assignment stands either way."""
        if not can(access.member, Permission.INSTRUCT_CODING_AGENT):
            return None
        try:
            issue = await self._codable(access.project, access.member.user_id, key)
        except (CodingUnavailable, CodingBusy, Conflict, Unprocessable):
            return None
        run = await self._create(access.project, access.member, issue, None, CodingOrigin.ASSIGNED)
        await self.session.commit()
        return self._read(run, access)

    async def follow_up(self, access: ProjectAccess, session_id: uuid.UUID, data: CodingFollowUp, *,
                        origin_run_id: uuid.UUID | None = None) -> CodingRunRead:
        """Another turn in a session: the same agent, on the session's branch, pushing to its PR
        (or opening one, if no turn has yet). It waits for an approval like the first."""
        # Where the session codes, unless told: its latest turn that coded (a revert codes nowhere).
        location = data.location or next(
            (t.location for t in reversed(await self._turns(access, session_id)) if t.revert_of is None),
            CodingLocation.CLOUD,
        )
        turns, issue, with_branch, earlier = await self._next_turn(access, session_id, location=location)
        thread_id = turns[-1].thread_id
        if thread_id:
            await self.session.scalar(select(Project).where(Project.workspace_id == access.member.workspace_id,
                                                           Project.id == access.project.id).with_for_update())
            if await self.session.scalar(select(CodingRun.id).where(
                CodingRun.workspace_id == access.member.workspace_id, CodingRun.thread_id == thread_id,
                CodingRun.status.in_(ACTIVE)).limit(1)):
                raise CodingBusy("Kai already has an active turn in this conversation")
        previous = next(t for t in reversed(turns) if t.revert_of is None)
        selection = await self._selection(access.project, access.member.user_id, location,
                                          agent=previous.agent, model=previous.model, fixed=True)
        run = await self._create(
            access.project, access.member, issue, data.message, CodingOrigin.FOLLOW_UP,
            session_id=session_id, turn=turns[-1].turn + 1, earlier=earlier, carry=with_branch,
            approval=data.approval_mode, location=location, selection=selection,
        )
        run.thread_id, run.plan_id = thread_id, turns[-1].plan_id
        run.origin_run_id = origin_run_id or turns[-1].origin_run_id
        return await self._settle(access, run)

    async def revert(self, access: ProjectAccess, run_id: uuid.UUID, data: CodingRevert) -> CodingRunRead:
        """Undo a pushed turn: a new turn whose commit reverts it on the session's branch (never a
        force-push, so the PR keeps its history). It waits for an approval like any turn; the agent
        doesn't run."""
        target = await self._get(access, run_id)
        if target.status is not CodingRunStatus.PR_OPENED or not target.commit_sha:
            raise Conflict("Only a turn that pushed its changes can be reverted")
        if target.pr_state in (PrState.MERGED, PrState.CLOSED):
            raise Conflict("Its PR is merged or closed: revert it on GitHub")
        # Wherever the session codes, a revert is a publish-only pass on the platform.
        turns, issue, with_branch, earlier = await self._next_turn(access, target.session_id,
                                                                   location=CodingLocation.CLOUD, publish_only=True)
        if any(t.revert_of == target.id and t.status is CodingRunStatus.PR_OPENED for t in turns):
            raise Conflict(f"Turn {target.turn} is already reverted")
        if with_branch is None or with_branch.branch != target.branch:
            raise Conflict("The session has moved on to a new branch: revert it on GitHub")
        run = await self._create(
            access.project, access.member, issue, f"Revert turn {target.turn} ({target.commit_sha[:7]})",
            CodingOrigin.FOLLOW_UP, session_id=target.session_id, turn=turns[-1].turn + 1, earlier=earlier,
            carry=with_branch, approval=data.approval_mode, location=CodingLocation.CLOUD, agent=target.agent,
        )
        run.revert_of = target.id
        return await self._settle(access, run)

    async def _next_turn(
        self, access: ProjectAccess, session_id: uuid.UUID, *, location: CodingLocation, publish_only: bool = False,
    ) -> tuple[list[CodingRun], IssueRead, CodingRun | None, list[tuple[int, str]]]:
        """What a new turn in a session builds on: its turns, its issue, the branch and PR it carries
        on (None: a new one from the default branch), and what the earlier turns did."""
        turns = await self._turns(access, session_id)
        if turns[0].requested_by_id != access.member.user_id:
            raise Forbidden("Only whoever started this session can continue it")
        if any(t.status in ACTIVE for t in turns):
            raise CodingBusy("This session has a turn waiting or working; follow up once it's done")
        issue = await self._codable(access.project, access.member.user_id, turns[-1].issue_key, location=location,
                                    publish_only=publish_only)
        with_branch = next((t for t in reversed(turns) if t.branch and t.pr_number), None)
        if with_branch is not None and with_branch.pr_state in (PrState.MERGED, PrState.CLOSED):
            with_branch = None  # its PR is merged or closed: this turn starts a new branch and PR from the default branch
        earlier = [(t.turn, _earlier(t)) for t in turns
                   if t.status not in (CodingRunStatus.REJECTED, CodingRunStatus.STOPPED) or t.summary]
        return turns, issue, with_branch, earlier

    async def _settle(self, access: ProjectAccess, run: CodingRun) -> CodingRunRead:
        """Commit a new turn: it waits for an approval, or starts at once under the person's mode."""
        if not goes_through(ApprovalMode(run.approval_mode)):
            await self.session.commit()
            return self._read(run, access)
        # Their instruction is the approval (their mode needs the right to approve agent changes).
        run.decided_by_id, run.decided_at = access.member.user_id, datetime.now(UTC)
        run.decision_reason = f"Started at once ({run.approval_mode.replace('_', ' ')})"
        dispatch = await self._queue(access, run)
        await self.session.commit()
        await self._send(run, dispatch)
        await self.session.refresh(run)
        return self._read(run, access)

    async def _codable(
        self, project: Project, user_id: uuid.UUID, key: str, *, busy_ok: bool = False,
        location: CodingLocation = CodingLocation.CLOUD, publish_only: bool = False,
    ) -> IssueRead:
        if publish_only:  # a revert: the platform pushes it, no coding tool runs anywhere
            if why := await self._publishable(project):
                raise CodingUnavailable(why)
        elif location is CodingLocation.LOCAL:
            _, why = await self.local_availability(project, user_id)
            if why:
                raise CodingUnavailable(why)
        else:
            available = await self.availability(project, user_id)
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
        carry: CodingRun | None = None, approval: ApprovalMode | None = None,
        location: CodingLocation = CodingLocation.CLOUD, agent: CodingAgent | None = None,
        requested_agent: CodingAgent | None = None, requested_model: str | None = None,
        selection: tuple[CodingAgent, str | None] | None = None,
    ) -> CodingRun:
        model: str | None = None
        if agent is not None:  # a revert: the session's engine, on record only (nothing runs it)
            pass
        else:
            agent, model = selection or await self._selection(
                project, member.user_id, location, agent=requested_agent, model=requested_model,
            )
        repo = await self._repo(project)
        assert repo is not None
        run_id = uuid7()
        run = CodingRun(
            id=run_id, session_id=session_id or run_id,  # a new session is named after its first turn
            workspace_id=project.workspace_id, project_id=project.id, issue_id=issue.id, issue_key=issue.key,
            turn=turn, origin=origin, agent=agent, model=model, location=location,
            status=CodingRunStatus.AWAITING_APPROVAL,
            brief=await build_brief(self.session, project, issue, note, earlier, user_id=member.user_id),
            note=note, repo_full_name=repo.full_name, base_branch=repo.default_branch,
            requested_by_id=member.user_id, created_at=datetime.now(UTC),
            # The mode this turn was asked in, as far as the workspace and the person allow.
            approval_mode=effective(approval, member).value,
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
        if goes_through(ApprovalMode(run.approval_mode)):
            return run  # it starts at once: nobody waits on it
        await Notifier(self.session).coding_waiting(
            project, run.id, issue.id, f"Coding {issue.key}: {issue.title}", run.created_at, agent.value,
            requester_id=member.user_id,
        )
        return run

    async def decide(self, access: ProjectAccess, run_id: uuid.UUID, data: CodingDecision) -> CodingRunRead:
        """Approve (it's queued for the worker) or reject a run that waits for approval."""
        run = await self._get(access, run_id, for_update=True)
        if run.status is CodingRunStatus.CHANGES_READY:
            return await self._decide_changes(access, run, data)
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
        dispatch = await self._queue(access, run)
        await self.session.commit()
        await self._send(run, dispatch)
        await self.session.refresh(run)
        return self._read(run, access)

    async def _decide_changes(self, access: ProjectAccess, run: CodingRun, data: CodingDecision) -> CodingRunRead:
        """Manual: accept a turn's checked changes (they're pushed, and the PR opened or updated) or
        reject them (discarded: nothing reached GitHub)."""
        now = datetime.now(UTC)
        if run.requested_by_id and run.requested_by_id != access.member.user_id:
            title = await self.session.scalar(select(Issue.title).where(Issue.id == run.issue_id)) or run.issue_key
            Notifier(self.session).decided(
                access.project, run.requested_by_id, None, f"Changes for {run.issue_key}: {title}", now,
                approved=int(data.decision == "approve"), rejected=int(data.decision == "reject"), reason=data.reason,
                actor_user_id=access.member.user_id, coding_run_id=run.id,
            )
        if data.decision == "reject":
            run.status, run.finished_at, run.pending_patch = CodingRunStatus.REJECTED, now, None
            run.error = "Its changes were rejected" + (f": {data.reason}" if data.reason else "")
            self._audit(access.project, access, "coding.changes_rejected", run)
            await self.session.commit()
            return self._read(run, access)
        run.accepted_by_id, run.accepted_at, run.status = access.member.user_id, now, CodingRunStatus.QUEUED
        self._audit(access.project, access, "coding.changes_accepted", run)
        dispatch = self._dispatch(self.session, run)
        await self.session.commit()
        await self._send(run, dispatch)
        await self.session.refresh(run)
        return self._read(run, access)

    async def _queue(self, access: ProjectAccess, run: CodingRun) -> RunDispatch | None:
        """An approved run, queued (not committed): the issue is Kai's, audited, its dispatch recorded."""
        # The run codes on its requester's keys (or computer), not the approver's; a revert codes nowhere.
        if run.revert_of is not None:
            if why := await self._publishable(access.project):
                raise CodingUnavailable(why)
        elif run.location is CodingLocation.LOCAL:
            _, why = await self.local_availability(access.project, run.requested_by_id)
            if why:
                raise CodingUnavailable(why)
            await self._selection(access.project, run.requested_by_id, run.location,
                                  agent=run.agent, model=run.model, fixed=True)
        else:
            available = await self.availability(access.project, run.requested_by_id)
            if not available.available:
                raise CodingUnavailable(available.reason or "Coding runs aren't available")
            await self._selection(access.project, run.requested_by_id, run.location,
                                  agent=run.agent, model=run.model, fixed=True)
        run.status = CodingRunStatus.QUEUED
        # The issue is the coding tool's now (its own rules: it may move it to review, never done).
        issue = await IssueService(self.session).get(access.project, run.issue_key)
        change = IssueUpdate(assignee_agent=run.agent.assignee, assignee_user_id=None,
                             note=f"Coding run approved: {CODING_AGENT_NAME} is working on it")
        if issue.status is not IssueStatus.IN_PROGRESS:
            change.status = IssueStatus.IN_PROGRESS
        await IssueService(self.session).update(
            access.project, run.issue_key, IssueActor(access.member, coding_instructed=True), change, commit=False,
        )
        self._audit(access.project, access, "coding.approved", run)
        return self._dispatch(self.session, run)

    async def recover(self, access: ProjectAccess, run_id: uuid.UUID, data: CodingRecover, app: GitHubApp) -> CodingRunRead:
        """Settle a run whose outcome is uncertain: check GitHub (adopt or open its PR, or run the
        turn again when nothing was published), or discard it after looking yourself."""
        run = await self._get(access, run_id, for_update=True)
        if not self._can_stop(run, access):
            raise Forbidden("Only whoever asked for this run, or an owner or admin, can recover it")
        if run.status is not CodingRunStatus.RECOVERY_REQUIRED:
            raise Conflict("This coding run doesn't need recovering")
        if lease_live(run):
            raise Conflict("Its worker may still be working on it; try again in a couple of minutes")
        if data.action == "discard":
            await discard(self.session, run, by=access.member.user_id)
        else:
            dispatches: list[RunDispatch | None] = []

            async def requeue(session: AsyncSession, run: CodingRun) -> None:
                dispatches.append(self._dispatch(session, run))

            if await recover(self.session, app, self.settings, run, requeue, by=access.member.user_id) \
                    is Recovered.RETRIED:
                await self._send(run, dispatches[0])
        await self.session.refresh(run)
        return self._read(run, access)

    def _dispatch(self, session: AsyncSession, run: CodingRun) -> RunDispatch | None:
        """A queued run's dispatch, in the caller's transaction, when a worker runs it."""
        if not needs_worker(run):
            return None  # a local turn: its runner claims it
        if isinstance(self.jobs, QueuedJobs):
            return record_dispatch(session, run, {}, queue_name=self.jobs.queue_name)
        return None

    async def _send(self, run: CodingRun, dispatch: RunDispatch | None) -> None:
        """After the commit: wake the worker, or run it here (a local turn: its runner claims it)."""
        if not needs_worker(run):
            return
        if dispatch is not None:
            # The service's transaction is complete; use a fresh session for the
            # best-effort publication. The worker sweep recovers any missed wake-up.
            assert isinstance(self.jobs, QueuedJobs)
            if self.jobs.session_factory is not None:
                await RunDispatcher(
                    self.jobs.session_factory, RunQueue(self.jobs.redis, self.jobs.queue_name),
                ).kick(dispatch.workspace_id, dispatch.id)
        else:
            await self.jobs.enqueue("run_coding", run_id=str(run.id))

    async def stop(self, access: ProjectAccess, run_id: uuid.UUID) -> CodingRunRead:
        run = await self._get(access, run_id, for_update=True)
        if not self._can_stop(run, access):
            raise Forbidden("Only whoever asked for this run, or an owner or admin, can stop it")
        if run.status is CodingRunStatus.RECOVERY_REQUIRED:
            raise Conflict("Its outcome is uncertain: recover it (check GitHub, or discard it) instead")
        if run.status not in ACTIVE:
            raise Conflict("This coding run has finished")
        run.stop_requested = True  # a running one: the worker sees it within seconds and stops the agent
        if run.status is CodingRunStatus.CHANGES_READY:
            run.status, run.finished_at, run.pending_patch = CodingRunStatus.STOPPED, datetime.now(UTC), None
            run.error = "Stopped: its changes were discarded, never pushed"
        elif run.status is not CodingRunStatus.RUNNING:
            run.status, run.finished_at = CodingRunStatus.STOPPED, datetime.now(UTC)
            run.error = "Stopped before it started"
        self._audit(access.project, access, "coding.stop_requested", run)
        await self.session.commit()
        return self._read(run, access)

    async def list(self, access: ProjectAccess, issue_key: str | None) -> list[CodingRunRead]:
        query = select(CodingRun).where(CodingRun.project_id == access.project.id, visible_runs(access.member))
        if issue_key:
            query = query.where(CodingRun.issue_key == issue_key.strip().upper())
        runs = await self.session.scalars(query.order_by(CodingRun.created_at.desc()).limit(MAX_LISTED))
        return [self._read(run, access) for run in runs]

    async def run_for(self, access: ProjectAccess, run_id: uuid.UUID) -> CodingRun:
        """A run you may see (as for every read: yours, or one waiting on your decision)."""
        return await self._get(access, run_id)

    async def get(self, access: ProjectAccess, run_id: uuid.UUID) -> CodingRunRead:
        return self._read(await self._get(access, run_id), access)

    async def events(self, access: ProjectAccess, run_id: uuid.UUID, after: int, limit: int) -> CodingEventPage:
        """A run's events after `seq` `after` (-1: from the start), oldest first, a page at a time."""
        run = await self._get(access, run_id)
        rows = (await self.session.scalars(
            select(CodingRunEvent)
            .where(CodingRunEvent.workspace_id == run.workspace_id, CodingRunEvent.run_id == run.id, CodingRunEvent.seq > after)
            .order_by(CodingRunEvent.seq).limit(limit + 1)
        )).all()
        page = rows[:limit]
        return CodingEventPage(
            events=[CodingEventRead(seq=e.seq, at=e.at, kind=e.kind, text=e.text, ref=e.ref) for e in page],
            next=page[-1].seq if len(rows) > limit else None,
        )

    async def close_session(self, access: ProjectAccess, session_id: uuid.UUID) -> None:
        """Close a session: its sandbox kept between turns goes (the worker drops it); its transcript,
        branch, and PR stay, and a new turn opens it again and resumes. Whoever started it, or owners and admins."""
        turns = await self._turns(access, session_id)
        if not self._can_stop(turns[0], access):
            raise Forbidden("Only whoever started the session, or owners and admins, can close it")
        if any(t.status in ACTIVE for t in turns):
            raise CodingBusy("A turn is waiting or working: stop it first")
        row = await self.session.get(CodingSession, session_id)
        if row is not None and row.workspace_id == access.project.workspace_id and row.state is not CodingSessionState.CLOSED:
            row.state, row.closed_at = CodingSessionState.CLOSED, datetime.now(UTC)
            self._audit(access.project, access, "coding.session_closed", turns[-1])
            await self.session.commit()

    async def update_session(self, access: ProjectAccess, session_id: uuid.UUID, data: CodingSessionUpdate) -> None:
        """Rename, pin, or archive a session. Whoever started it, or owners and admins."""
        row = await self._own_session(access, session_id)
        now = datetime.now(UTC)
        if data.title is not None:
            row.title = data.title.strip() or None
        if data.pinned is not None:
            row.pinned_at = now if data.pinned else None
        if data.archived is not None:
            row.archived_at = now if data.archived else None
        await self.session.commit()

    async def delete_session(self, access: ProjectAccess, session_id: uuid.UUID, storage: BlobStorage | None) -> None:
        """Delete a session: its turns, their events and screenshots, and its saved transcript. Its
        branch and PR stay on GitHub, and the audit log keeps what happened. Whoever started it, or
        owners and admins; not while a turn waits or works."""
        row = await self._own_session(access, session_id)
        turns = await self._turns(access, session_id)
        if any(t.status in ACTIVE for t in turns):
            raise CodingBusy("A turn is waiting or working: stop it first")
        keys = [s["key"] for t in turns for s in (t.screenshots or [])] + ([row.transcript_key] if row.transcript_key else [])
        if keys and storage is None:
            raise StorageUnavailable("File storage isn't configured, so its files can't be deleted")
        self._audit(access.project, access, "coding.session_deleted", turns[-1])
        for turn in turns:
            await self.session.delete(turn)
        await self.session.delete(row)
        await self.session.commit()
        for key in keys:  # after the commit: a file left behind is harmless, a session pointing at a gone one isn't
            try:
                await storage.delete(key)  # type: ignore[union-attr]
            except Exception:
                logger.warning("couldn't delete a coding session's file", exc_info=True)

    async def _own_session(self, access: ProjectAccess, session_id: uuid.UUID) -> CodingSession:
        turns = await self._turns(access, session_id)
        if not self._can_stop(turns[0], access):
            raise Forbidden("Only whoever started the session, or owners and admins, can change it")
        row = await self.session.get(CodingSession, session_id)
        if row is None or row.workspace_id != access.project.workspace_id:
            raise NotFound("Coding session not found")
        return row

    async def screenshot(self, access: ProjectAccess, run_id: uuid.UUID, index: int, storage: BlobStorage) -> tuple[bytes, str]:
        """One of the screenshots the agent's browser captured in a turn: its bytes and type."""
        run = await self._get(access, run_id)
        shots = list(run.screenshots or [])
        if not 0 <= index < len(shots):
            raise NotFound("Screenshot not found")
        return await storage.get(shots[index]["key"]), shots[index]["content_type"]

    async def session_turns(self, access: ProjectAccess, session_id: uuid.UUID) -> list[CodingRunRead]:
        """A session's turns, first to latest."""
        return [self._read(run, access) for run in await self._turns(access, session_id)]

    async def sessions(self, member: Membership, archived: bool | None = False) -> list[CodingSessionRead]:
        """The workspace's coding sessions across the projects you can see, latest activity first."""
        rows = (await self.session.execute(
            select(CodingRun, Project.key, Project.name, Issue.title)
            .join(Project, Project.id == CodingRun.project_id)
            .join(Issue, Issue.id == CodingRun.issue_id)
            .where(CodingRun.workspace_id == member.workspace_id, Project.workspace_id == member.workspace_id,
                   visible_to(member.user_id, member.role),
                   CodingRun.session_id.in_(select(CodingRun.session_id).where(
                       CodingRun.workspace_id == member.workspace_id, visible_runs(member))))
            .order_by(CodingRun.created_at.desc())
            .limit(MAX_SESSION_RUNS)
        )).all()
        sessions: dict[uuid.UUID, CodingSessionRead] = {}
        rows_by_id = {
            r.id: r for r in await self.session.scalars(select(CodingSession).where(
                CodingSession.workspace_id == member.workspace_id, CodingSession.id.in_({r[0].session_id for r in rows})
            ))
        }
        for run, project_key, project_name, issue_title in rows:  # newest first: the first seen is the latest turn
            found = sessions.get(run.session_id)
            if found is None:
                sessions[run.session_id] = CodingSessionRead(
                    session_id=run.session_id, project_id=run.project_id, project_key=project_key,
                    project_name=project_name, issue_key=run.issue_key, issue_title=issue_title, agent=run.agent,
                    status=run.status, turns=run.turn, branch=run.branch, pr_number=run.pr_number,
                    pr_url=run.pr_url, pr_state=run.pr_state, started_at=run.created_at, location=run.location,
                    updated_at=run.finished_at or run.started_at or run.created_at,
                )
            else:
                found.started_at = run.created_at
            # Its conversation, for whoever's it is (conversations are private: nobody else gets its id).
            if run.thread_id is not None and run.requested_by_id == member.user_id:
                sessions[run.session_id].thread_id = run.thread_id
        for sid, read in sessions.items():
            row = rows_by_id.get(sid)
            if row is not None:
                read.state, read.pinned, read.archived = row.state, row.pinned_at is not None, row.archived_at is not None
                read.title = row.title or read.issue_title
            else:
                read.title = read.issue_title
        shown = [s for s in sessions.values() if s.archived == archived] if archived is not None else list(sessions.values())
        # Pinned first, then the latest activity.
        return sorted(shown, key=lambda s: (s.pinned, s.updated_at), reverse=True)

    # -- helpers -------------------------------------------------------------------------

    async def _repo(self, project: Project) -> ConnectedRepo | None:
        return await self.session.scalar(
            select(ConnectedRepo).where(ConnectedRepo.project_id == project.id,
                                        ConnectedRepo.workspace_id == project.workspace_id)
        )

    async def _turns(self, access: ProjectAccess, session_id: uuid.UUID) -> list[CodingRun]:
        """A session's turns, when you may see it (any of its turns: see `_sees`)."""
        turns = list(await self.session.scalars(
            select(CodingRun).where(CodingRun.project_id == access.project.id, CodingRun.session_id == session_id)
            .order_by(CodingRun.turn).execution_options(populate_existing=True)
        ))
        if not turns or not any(_sees(t, access.member) for t in turns):
            raise NotFound("Coding session not found")
        return turns

    async def _get(self, access: ProjectAccess, run_id: uuid.UUID, *, for_update: bool = False) -> CodingRun:
        query = select(CodingRun).where(CodingRun.project_id == access.project.id, CodingRun.id == run_id)
        if for_update:
            query = query.with_for_update()
        run = await self.session.scalar(query.execution_options(populate_existing=True))
        if run is None or not _sees(run, access.member):
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
            events=[CodingEvent.model_validate(e) for e in run.events or []], event_count=run.event_count,
            summary=run.summary, error=run.error,
            input_tokens=run.input_tokens if usage else None, output_tokens=run.output_tokens if usage else None,
            cost_usd=run.cost_usd if usage else None, requested_by_id=run.requested_by_id,
            decided_by_id=run.decided_by_id, decision_reason=run.decision_reason, review_run_id=run.review_run_id,
            review_thread_id=run.review_thread_id,
            created_at=run.created_at, decided_at=run.decided_at, started_at=run.started_at,
            finished_at=run.finished_at,
            can_decide=run.status in WAITING and can(access.member, Permission.APPROVE_ACTIONS),
            can_revert=run.status is CodingRunStatus.PR_OPENED and run.commit_sha is not None
            and run.pr_state not in (PrState.MERGED, PrState.CLOSED) and run.requested_by_id == access.member.user_id
            and can(access.member, Permission.INSTRUCT_CODING_AGENT),
            accepted_by_id=run.accepted_by_id, accepted_at=run.accepted_at, revert_of=run.revert_of,
            location=run.location, runner_name=run.runner_name, runner_id=run.runner_id,
            worktree=run.worktree if run.requested_by_id == access.member.user_id else None,
            can_stop=run.status in ACTIVE and run.status is not CodingRunStatus.RECOVERY_REQUIRED
            and self._can_stop(run, access),
            can_recover=run.status is CodingRunStatus.RECOVERY_REQUIRED and self._can_stop(run, access),
            thread_id=run.thread_id, plan_id=run.plan_id, approval_mode=run.approval_mode or "manual",
        )

    def _audit(self, project: Project, access: ProjectAccess, action: str, run: CodingRun) -> None:
        AuditLog(self.session).record(
            workspace_id=project.workspace_id, project_id=project.id, action=action, target=run.issue_key,
            actor_type=AuthorType.USER, actor_user_id=access.member.user_id,
            instructed_by_id=run.requested_by_id, approved_by_id=run.decided_by_id,
            details={"run_id": str(run.id), "agent": run.agent.value, "reason": run.decision_reason,
                     "approval_mode": run.approval_mode or "manual"},
        )
