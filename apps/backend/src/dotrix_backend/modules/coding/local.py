"""Local coding: a person's own computer codes their turns (`dotrix runner` in a checkout).

The platform keeps what it keeps for a cloud turn (the run, its approvals, events, and outcome), and
pushes what's accepted itself, with the GitHub App, in the worker's publish-only pass: the runner
only ever hands back a patch. So the computer never holds a GitHub token, nor a provider key from
the platform (it codes with the tools signed in there), and every rule a cloud turn keeps holds:
the guard on what it changed (checked here, and again before the push), Manual's accept gate, Stop,
the lease and its fencing, recovery.

A runner claims only its owner's turns, in the projects it has checkouts of: an agent never codes
beyond the rights of the person it acts for, and on their machine, only for them.
"""
from __future__ import annotations

import asyncio
import subprocess
import tempfile
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dotrix_backend.core.errors import Conflict, NotFound, Unprocessable
from dotrix_backend.core.jobs import Jobs
from dotrix_backend.core.model_prices import cost_of
from dotrix_backend.core.settings import Settings
from dotrix_backend.modules.audit.models import AuthorType
from dotrix_backend.modules.audit.service import AuditLog
from dotrix_backend.modules.projects.repository import ProjectRepository
from dotrix_backend.modules.workspaces.approval_modes import ApprovalMode
from dotrix_backend.modules.workspaces.models import Membership
from dotrix_backend.modules.workspaces.permissions import Permission, can
from dotrix_backend.modules.workspaces.repository import MembershipRepository

from . import guard
from .models import (
    CODING_AGENT_NAME,
    CodingAgent,
    CodingLocation,
    CodingRun,
    CodingRunner,
    CodingRunStatus,
)
from .runner import add_events, finish_run, issue_title, ready_for_acceptance
from .schemas import (
    CodingClaim,
    CodingClaimed,
    CodingRunnerCreate,
    CodingRunnerRead,
    RunnerEvent,
    RunnerHeartbeat,
    RunnerHeartbeatRead,
    RunnerResult,
)
from .service import CodingService

ONLINE = timedelta(minutes=2)  # a runner polls every few seconds; unseen this long, it's offline


class LeaseLost(Conflict):
    """This runner no longer holds the turn (stopped, recovered, or claimed again): it stops writing."""

    code = "lease_lost"


class LocalRunners:
    def __init__(self, session: AsyncSession, settings: Settings, jobs: Jobs) -> None:
        self.session, self.settings, self.jobs = session, settings, jobs

    # -- the runner itself ------------------------------------------------------------------

    async def register(self, member: Membership, data: CodingRunnerCreate) -> CodingRunnerRead:
        """Register this computer (again: the same name updates it), with the projects it serves."""
        now = datetime.now(UTC)
        visible = {p.id for p in await ProjectRepository(self.session).list(member.workspace_id, member=member)}
        projects = [str(p) for p in data.project_ids if p in visible]
        runner = await self.session.scalar(select(CodingRunner).where(
            CodingRunner.workspace_id == member.workspace_id, CodingRunner.user_id == member.user_id,
            CodingRunner.name == data.name,
        ).with_for_update())
        if runner is None:
            runner = CodingRunner(id=uuid.uuid4(), workspace_id=member.workspace_id, user_id=member.user_id,
                                  name=data.name, created_at=now)
            self.session.add(runner)
        runner.platform, runner.tools, runner.isolation = data.platform, [t.value for t in data.tools], data.isolation
        runner.project_ids, runner.last_seen_at, runner.revoked_at = projects, now, None
        await self.session.flush()
        AuditLog(self.session).record(
            workspace_id=member.workspace_id, action="coding.runner_registered", target=runner.name,
            actor_type=AuthorType.USER, actor_user_id=member.user_id,
            details={"runner_id": str(runner.id), "isolation": runner.isolation, "projects": len(projects)},
        )
        await self.session.commit()
        return _read(runner)

    async def list(self, member: Membership) -> list[CodingRunnerRead]:
        """Your computers here, last seen first."""
        rows = await self.session.scalars(select(CodingRunner).where(
            CodingRunner.workspace_id == member.workspace_id, CodingRunner.user_id == member.user_id,
            CodingRunner.revoked_at.is_(None),
        ).order_by(CodingRunner.last_seen_at.desc()))
        return [_read(r) for r in rows]

    async def revoke(self, member: Membership, runner_id: uuid.UUID) -> None:
        """Stop a computer from claiming turns; a turn it holds now needs recovery once its lease lapses."""
        runner = await self._own(member, runner_id)
        runner.revoked_at = datetime.now(UTC)
        AuditLog(self.session).record(
            workspace_id=member.workspace_id, action="coding.runner_revoked", target=runner.name,
            actor_type=AuthorType.USER, actor_user_id=member.user_id, details={"runner_id": str(runner.id)},
        )
        await self.session.commit()

    # -- its turns --------------------------------------------------------------------------

    async def claim(self, member: Membership, runner_id: uuid.UUID) -> CodingClaimed:
        """The oldest approved local turn of yours in a project this runner serves, now held by it
        (a new lease). Also its heartbeat: being asked is being seen."""
        runner = await self._own(member, runner_id)
        now = datetime.now(UTC)
        runner.last_seen_at = now
        run = await self.session.scalar(select(CodingRun).where(
            CodingRun.workspace_id == member.workspace_id, CodingRun.requested_by_id == member.user_id,
            CodingRun.location == CodingLocation.LOCAL, CodingRun.status == CodingRunStatus.QUEUED,
            CodingRun.accepted_at.is_(None), CodingRun.revert_of.is_(None), CodingRun.stop_requested.is_(False),
            CodingRun.project_id.in_([uuid.UUID(p) for p in runner.project_ids] or [uuid.uuid4()]),
        ).order_by(CodingRun.created_at).limit(1).with_for_update(skip_locked=True))
        if run is None:
            await self.session.commit()
            return CodingClaimed(run=None)
        # Checked now, not when it was asked for: they may have lost the project or the right since.
        project = await ProjectRepository(self.session).get(run.workspace_id, run.project_id)
        still = await MembershipRepository(self.session).get(run.workspace_id, member.user_id)
        if project is None or still is None or not can(still, Permission.INSTRUCT_CODING_AGENT) \
                or not await ProjectRepository(self.session).can_see(project, member.user_id):
            finish_run(self.session, run, CodingRunStatus.FAILED,
                       error=f"Whoever asked for this run can no longer instruct {CODING_AGENT_NAME} here.")
            await self.session.commit()
            return CodingClaimed(run=None)
        if runner.tools and run.agent.value not in runner.tools:
            run.agent = CodingAgent(runner.tools[0])  # it codes with what that computer has
        run.status, run.started_at, run.runner_id, run.runner_name = CodingRunStatus.RUNNING, now, runner.id, runner.name
        run.lease_token += 1
        run.lease_expires_at = now + timedelta(seconds=self.settings.coding_lease_seconds)
        isolation = "isolated by srt" if runner.isolation == "srt" else "a worktree only, not isolated"
        add_events(run, self.session, step=f"On {runner.name} ({isolation})")
        claim = CodingClaim(
            run_id=run.id, project_id=run.project_id, session_id=run.session_id, lease_token=run.lease_token,
            lease_seconds=self.settings.coding_lease_seconds, issue_key=run.issue_key,
            title=await issue_title(self.session, run), turn=run.turn, brief=run.brief, tool=run.agent,
            repo_full_name=run.repo_full_name, base_branch=run.base_branch, branch=run.branch,
        )
        await self.session.commit()
        return CodingClaimed(run=claim)

    async def heartbeat(
        self, member: Membership, runner_id: uuid.UUID, run_id: uuid.UUID, data: RunnerHeartbeat,
    ) -> RunnerHeartbeatRead:
        """Renew the lease, keep what the agent did, and say whether to stop."""
        runner, run = await self._held(member, runner_id, run_id, data.lease_token)
        now = datetime.now(UTC)
        runner.last_seen_at = now
        run.lease_expires_at = now + timedelta(seconds=self.settings.coding_lease_seconds)
        if data.base_sha:
            run.base_sha = data.base_sha
        if data.worktree:
            run.worktree = data.worktree
        add_events(run, self.session, events=_events(data.events))
        stop = run.stop_requested
        await self.session.commit()
        return RunnerHeartbeatRead(stop=stop)

    async def result(self, member: Membership, runner_id: uuid.UUID, run_id: uuid.UUID, data: RunnerResult) -> None:
        """The turn's outcome. Changes go through the guard here (and again before the push): in
        Manual they wait for a person; otherwise they're accepted, by whoever asked, and pushed."""
        runner, run = await self._held(member, runner_id, run_id, data.lease_token)
        runner.last_seen_at = datetime.now(UTC)
        run.lease_expires_at = None
        add_events(run, self.session, events=_events(data.events))
        if data.input_tokens is not None:
            run.input_tokens, run.output_tokens = data.input_tokens, data.output_tokens or 0
            # No cost from the tool (Codex, fx): priced from the tokens, without the cache split the runner doesn't send.
            run.cost_usd = data.cost_usd if data.cost_usd is not None else cost_of(
                run.model, input_tokens=run.input_tokens, output_tokens=run.output_tokens,
                overrides=self.settings.model_prices)
        if data.base_sha:
            run.base_sha = data.base_sha
        summary = (data.summary or "").strip() or None
        dispatch = None
        if data.outcome == "stopped" or (run.stop_requested and data.outcome == "changes"):
            finish_run(self.session, run, CodingRunStatus.STOPPED, error="Stopped by a person", summary=summary)
        elif data.outcome == "failed":
            finish_run(self.session, run, CodingRunStatus.FAILED, error=data.error or "The coding tool failed",
                       summary=summary)
        elif data.outcome == "no_changes" or not (data.patch or "").strip():
            finish_run(self.session, run, CodingRunStatus.NO_CHANGES, summary=summary)
        else:
            patch = data.patch or ""
            if len(patch.encode()) > guard.MAX_PATCH_BYTES:
                raise Unprocessable(f"The changes are larger than {guard.MAX_PATCH_BYTES // 1_000_000} MB")
            if not run.base_sha:
                raise Unprocessable("Report the commit the changes are on (base_sha)")
            paths, files = await patch_files(patch)
            reasons = guard.check(paths)
            if not paths:
                finish_run(self.session, run, CodingRunStatus.FAILED, error="The changes weren't a patch git can read",
                           summary=summary)
            elif reasons:
                finish_run(self.session, run, CodingRunStatus.FAILED, error="Not pushed: " + "; ".join(reasons[:5]),
                           summary=summary)
            elif run.approval_mode == ApprovalMode.MANUAL.value:
                await ready_for_acceptance(self.session, run, patch, files, summary)
            else:
                # Accept edits and Auto: their instruction is the acceptance, as for a cloud turn.
                run.pending_patch, run.files_changed, run.summary = patch, files, summary or run.summary
                run.accepted_by_id, run.accepted_at = run.requested_by_id, datetime.now(UTC)
                run.status = CodingRunStatus.QUEUED
                add_events(run, self.session, step="Pushing the changes from the platform")
                AuditLog(self.session).record(
                    workspace_id=run.workspace_id, project_id=run.project_id, action="coding.changes_accepted",
                    target=run.issue_key, actor_type=AuthorType.USER, actor_user_id=run.requested_by_id,
                    instructed_by_id=run.requested_by_id, approved_by_id=run.requested_by_id,
                    details={"run_id": str(run.id), "approval_mode": run.approval_mode, "location": "local"},
                )
                coding = CodingService(self.session, self.settings, self.jobs)
                dispatch = coding._dispatch(self.session, run)
        await self.session.commit()
        if run.status is CodingRunStatus.QUEUED:
            await CodingService(self.session, self.settings, self.jobs)._send(run, dispatch)

    # -- helpers ----------------------------------------------------------------------------

    async def _own(self, member: Membership, runner_id: uuid.UUID) -> CodingRunner:
        runner = await self.session.scalar(select(CodingRunner).where(
            CodingRunner.workspace_id == member.workspace_id, CodingRunner.id == runner_id,
            CodingRunner.user_id == member.user_id, CodingRunner.revoked_at.is_(None),
        ).with_for_update())
        if runner is None:
            raise NotFound("Runner not found (revoked? register it again with `dotrix runner`)")
        return runner

    async def _held(
        self, member: Membership, runner_id: uuid.UUID, run_id: uuid.UUID, token: int,
    ) -> tuple[CodingRunner, CodingRun]:
        runner = await self._own(member, runner_id)
        run = await self.session.scalar(select(CodingRun).where(
            CodingRun.workspace_id == member.workspace_id, CodingRun.id == run_id,
            CodingRun.requested_by_id == member.user_id,
        ).with_for_update())
        if run is None:
            raise NotFound("Coding run not found")
        if run.runner_id != runner.id or run.lease_token != token or run.status is not CodingRunStatus.RUNNING:
            raise LeaseLost("This runner no longer holds the turn: stop, and leave the worktree as it is")
        return runner, run


def _read(runner: CodingRunner) -> CodingRunnerRead:
    return CodingRunnerRead(
        id=runner.id, name=runner.name, platform=runner.platform, tools=list(runner.tools or []),
        isolation=runner.isolation, project_ids=[uuid.UUID(p) for p in runner.project_ids or []],
        created_at=runner.created_at, last_seen_at=runner.last_seen_at,
        online=runner.last_seen_at > datetime.now(UTC) - ONLINE,
    )


def _events(events: list[RunnerEvent]) -> list[dict[str, str]]:
    at = datetime.now(UTC).isoformat()
    return [{"at": at, "kind": e.kind, "text": e.text, **({"ref": e.ref} if e.ref else {})} for e in events]


async def patch_files(patch: str) -> tuple[list[str], list[dict[str, object]]]:
    """The paths a patch touches and their line counts, read by git from the patch itself (never
    from what the runner says about it)."""
    def numstat() -> str:
        with tempfile.TemporaryDirectory(prefix="dotrix-patch-") as tmp:
            done = subprocess.run(
                ["git", "apply", "--numstat", "-z", "-"], input=patch.encode(), cwd=Path(tmp),
                capture_output=True, timeout=60, check=False,
            )
        return done.stdout.decode(errors="replace") if done.returncode == 0 else ""

    out = await asyncio.to_thread(numstat)
    paths: list[str] = []
    files: list[dict[str, object]] = []
    entries = out.split("\0")
    i = 0
    while i < len(entries):
        entry = entries[i]
        i += 1
        if not entry.strip():
            continue
        added, removed, path = entry.split("\t", 2)
        if not path:  # a rename: its old and new paths follow (the guard checks both)
            old, path = entries[i], entries[i + 1]
            i += 2
            paths.append(old)
        paths.append(path)
        files.append({"path": path, "added": int(added) if added.isdigit() else 0,
                      "removed": int(removed) if removed.isdigit() else 0})
    return paths, files
