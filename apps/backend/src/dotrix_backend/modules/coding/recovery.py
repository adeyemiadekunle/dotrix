"""Recovering a coding run whose outcome is uncertain (`recovery_required`).

What GitHub shows decides it, never a guess. A run records its branch and the exact commit before it
pushes (`CodingWorker._prepare_publication`), so:

- the branch at that commit: the push landed. With its PR (found on GitHub, or the session's), the
  run is done; without one, the PR is opened now, as the approved run would have.
- no commit recorded, the branch missing, or still at the turn's base: nothing was published, and
  the turn runs again (a new attempt under a new lease), at most `MAX_ATTEMPTS` times in all.
- the branch anywhere else: something else moved it. A person looks, and discards the run.

Opening the PR or running the turn again needs the person who asked for it to still be allowed to
instruct Kai. Called by a person (Recover in the product) or by the worker's sweep once per run.
"""
from __future__ import annotations

import asyncio
import enum
import logging
import uuid
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from dotrix_backend.core.settings import Settings
from dotrix_backend.modules.audit.models import AuthorType
from dotrix_backend.modules.audit.service import AuditLog
from dotrix_backend.modules.code.checkouts import remove_tree
from dotrix_backend.modules.connectors.github_app import GitHubApp, PullRequest
from dotrix_backend.modules.connectors.models import ConnectedRepo, GitHubInstallation
from dotrix_backend.modules.workspaces.permissions import Permission, can
from dotrix_backend.modules.workspaces.repository import MembershipRepository

from . import guard
from .models import CODING_AGENT_NAME, CodingRun, CodingRunEvent, CodingRunStatus, PrState
from .runner import MAX_EVENTS, issue_title, issue_to_review, pr_body
from .tools import tool_for

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 2  # a turn cut off before it published anything runs at most this many times in all

# Records the run's next attempt in the caller's transaction (a dispatch, or a job after commit).
Requeue = Callable[[AsyncSession, CodingRun], Awaitable[None]]


class Recovered(enum.StrEnum):
    ADOPTED_PR = "adopted_pr"  # the push and its PR landed: the run is done
    OPENED_PR = "opened_pr"  # the push landed, its PR didn't: opened now
    RETRIED = "retried"  # nothing was published: the turn runs again
    STOPPED = "stopped"  # someone stopped it: nothing more is published, nothing runs again
    FAILED = "failed"  # nothing was published, and it can't run again
    UNCLEAR = "unclear"  # GitHub doesn't settle it: a person looks and discards the run
    DISCARDED = "discarded"


def lease_live(run: CodingRun) -> bool:
    """Whether a worker may still be working on the run (its lease hasn't run out)."""
    return run.lease_expires_at is not None and run.lease_expires_at > datetime.now(UTC)


async def recover(
    session: AsyncSession, app: GitHubApp, settings: Settings, run: CodingRun, requeue: Requeue, *,
    by: uuid.UUID | None,
) -> Recovered:
    """Settle a locked `recovery_required` run from what GitHub shows, and commit."""
    assert run.status is CodingRunStatus.RECOVERY_REQUIRED and not lease_live(run)
    run.recovery_checked_at = datetime.now(UTC)
    found = (await session.execute(
        select(ConnectedRepo, GitHubInstallation)
        .join(GitHubInstallation, GitHubInstallation.id == ConnectedRepo.installation_ref)
        .where(ConnectedRepo.project_id == run.project_id, ConnectedRepo.workspace_id == run.workspace_id)
    )).first()
    if found is None:
        return await _settle(session, run, Recovered.UNCLEAR, by, error=(
            "The project's repository was disconnected, so GitHub can't be checked: look at the branch "
            "yourself, then discard this run"))
    repo, installation = found

    # Where the run pushes (the repo, or the app's fork of it) and where its PR goes.
    fork_owner = settings.coding_fork_owner
    token = await app.access_token(installation.installation_id, repository_id=repo.github_repo_id,
                                   write=fork_owner is None, pull_requests=fork_owner is not None)
    push_repo, push_token, head_prefix = repo.full_name, token, ""
    if fork_owner:
        fork_installation = await app.org_installation(fork_owner)
        upstream_owner, name = repo.full_name.split("/", 1)
        fork = await app.fork(fork_installation, repo.full_name, org=fork_owner, name=f"{upstream_owner}-{name}"[:100])
        push_repo, head_prefix = fork.full_name, f"{fork_owner}:"
        push_token = await app.access_token(fork_installation, repository_id=fork.id)

    head = await app.branch_head(push_repo, run.branch, token=push_token) if run.branch else None
    if run.commit_sha and head == run.commit_sha:
        assert run.branch is not None
        if run.pr_number is not None:  # the session's PR, or the PR's reply was saved
            return await _settle(session, run, Recovered.ADOPTED_PR, by, opened=run.turn == 1)
        owner = fork_owner or repo.full_name.split("/", 1)[0]
        pr = await app.find_pull_request(repo.full_name, f"{owner}:{run.branch}", token=token)
        if pr is not None:
            return await _settle(session, run, Recovered.ADOPTED_PR, by, pr=pr)
        if run.stop_requested:  # stopped after its push: what landed stays, the PR isn't opened
            return await _settle(session, run, Recovered.STOPPED, by, error=(
                f"Stopped after pushing {run.branch}; no PR was opened"))
        if (refused := await _refused(session, run)) is not None:
            return await _settle(session, run, Recovered.FAILED, by, error=refused + " The branch is on GitHub.")
        tool = tool_for(run.agent, run.model, settings)
        paths = [f["path"] for f in run.files_changed]
        pr = await app.create_pull_request(
            installation.installation_id, repo.full_name, head=head_prefix + run.branch, base=run.base_branch,
            title=f"{run.issue_key}: {await issue_title(session, run)}",
            body=pr_body(run.summary, run.issue_key, run.id, tool.name if tool else run.agent.value,
                         run.files_changed, guard.ci_sensitive(paths)),
            token=token,
        )
        return await _settle(session, run, Recovered.OPENED_PR, by, pr=pr)

    if run.commit_sha is None or head is None or head == run.base_sha:  # nothing of this turn was published
        if run.stop_requested:
            return await _settle(session, run, Recovered.STOPPED, by, error="Stopped before it published anything")
        # Accepted changes (Manual) are pushed in a pass of their own, with attempts of its own.
        if run.lease_token >= MAX_ATTEMPTS * (2 if run.accepted_at is not None else 1):
            return await _settle(session, run, Recovered.FAILED, by, error=(
                f"Cut off {run.lease_token} times before anything was published; ask {CODING_AGENT_NAME} again"))
        if (refused := await _refused(session, run)) is not None:
            return await _settle(session, run, Recovered.FAILED, by, error=refused)
        stale = run.workspace_path
        if run.pr_number is None:
            run.branch = None  # a new session's branch is named again; a follow-up keeps its session's
        run.commit_sha, run.files_changed, run.workspace_path = None, [], None
        run.status, run.error, run.started_at, run.finished_at = CodingRunStatus.QUEUED, None, None, None
        await requeue(session, run)
        outcome = await _settle(session, run, Recovered.RETRIED, by)
        if stale:  # this host's copy of the cut-off attempt, if the run was cut off here
            await asyncio.to_thread(remove_tree, Path(stale))
        return outcome

    return await _settle(session, run, Recovered.UNCLEAR, by, error=(
        f"{run.branch} has moved on from this turn's commit, so it's unclear whether it was pushed: "
        "look at the branch and PR on GitHub, then discard this run"))


async def recover_uncertain_runs(
    session_factory: Callable[[], AbstractAsyncContextManager[AsyncSession]], app: GitHubApp, settings: Settings,
    requeue: Requeue, *, limit: int = 20,
) -> int:
    """The worker's sweep: settle each uncertain run once, when its lease has run out. What it can't
    settle (GitHub unreachable, the branch moved) waits for a person's Recover."""
    now = datetime.now(UTC)
    async with session_factory() as session:
        candidates = list((await session.execute(select(CodingRun.workspace_id, CodingRun.id).where(
            CodingRun.status == CodingRunStatus.RECOVERY_REQUIRED, CodingRun.recovery_checked_at.is_(None),
            or_(CodingRun.lease_expires_at.is_(None), CodingRun.lease_expires_at < now),
        ).order_by(CodingRun.created_at).limit(limit))).all())
    settled = 0
    for workspace_id, run_id in candidates:
        async with session_factory() as session:
            run = await session.scalar(select(CodingRun).where(
                CodingRun.workspace_id == workspace_id, CodingRun.id == run_id,
            ).with_for_update(skip_locked=True))
            if run is None or run.status is not CodingRunStatus.RECOVERY_REQUIRED \
                    or run.recovery_checked_at is not None or lease_live(run):
                continue
            try:
                await recover(session, app, settings, run, requeue, by=None)
                settled += 1
            except Exception as exc:  # e.g. GitHub unreachable: a person retries with Recover
                logger.warning("coding run %s: automatic recovery failed (%s)", run_id, type(exc).__name__)
                await session.rollback()
                await session.execute(update(CodingRun).where(
                    CodingRun.workspace_id == workspace_id, CodingRun.id == run_id,
                ).values(recovery_checked_at=now))
                await session.commit()
    return settled


async def discard(session: AsyncSession, run: CodingRun, *, by: uuid.UUID) -> None:
    """A person ends an uncertain run as failed, having looked at GitHub themselves; and commit."""
    await _settle(session, run, Recovered.DISCARDED, by, error=(
        "Discarded after its outcome was uncertain; whatever reached GitHub stays there"))


async def _refused(session: AsyncSession, run: CodingRun) -> str | None:
    """Why the run may not publish or run again for whoever asked for it (None: it may)."""
    member = await MembershipRepository(session).get(run.workspace_id, run.requested_by_id) \
        if run.requested_by_id else None
    if member is None or not can(member, Permission.INSTRUCT_CODING_AGENT):
        return f"Whoever asked for this run can no longer instruct {CODING_AGENT_NAME}."
    return None


async def _settle(
    session: AsyncSession, run: CodingRun, outcome: Recovered, by: uuid.UUID | None, *,
    error: str | None = None, pr: PullRequest | None = None, opened: bool = True,
) -> Recovered:
    now = datetime.now(UTC)
    if pr is not None:
        run.pr_number, run.pr_url = pr.number, pr.html_url
        run.pr_state = PrState(pr.state)  # it may have been closed or merged since
    if outcome in (Recovered.ADOPTED_PR, Recovered.OPENED_PR):
        run.status, run.finished_at, run.error = CodingRunStatus.PR_OPENED, now, None
    elif outcome in (Recovered.FAILED, Recovered.DISCARDED):
        run.status, run.finished_at, run.error = CodingRunStatus.FAILED, now, error
    elif outcome is Recovered.STOPPED:
        run.status, run.finished_at, run.error = CodingRunStatus.STOPPED, now, error
    elif outcome is Recovered.UNCLEAR:
        run.error = error
    said = {
        Recovered.ADOPTED_PR: f"Recovered: the push landed, PR #{run.pr_number}",
        Recovered.OPENED_PR: f"Recovered: the push landed; opened PR #{run.pr_number}",
        Recovered.RETRIED: "Recovered: nothing was published; running the turn again",
        Recovered.STOPPED: f"Recovered: {error}",
        Recovered.FAILED: f"Recovery ended the run: {error}",
        Recovered.UNCLEAR: "Recovery couldn't tell from GitHub what happened",
        Recovered.DISCARDED: "Discarded after an uncertain outcome",
    }[outcome]
    event = {"at": now.isoformat(), "kind": "step", "text": said}
    session.add(CodingRunEvent(workspace_id=run.workspace_id, run_id=run.id, session_id=run.session_id,
                               seq=run.event_count, at=now, kind="step", text=said))
    run.event_count += 1
    run.events = (list(run.events) + [event])[-MAX_EVENTS:]
    AuditLog(session).record(
        workspace_id=run.workspace_id, project_id=run.project_id, action="coding.recovered", target=run.issue_key,
        actor_type=AuthorType.USER if by else AuthorType.SYSTEM, actor_user_id=by,
        instructed_by_id=run.requested_by_id, approved_by_id=run.decided_by_id,
        details={"run_id": str(run.id), "outcome": outcome.value, "attempts": run.lease_token},
    )
    if run.status is CodingRunStatus.PR_OPENED:
        await issue_to_review(session, run, await issue_title(session, run), opened=opened)
    await session.commit()
    logger.info("coding run %s recovered: %s", run.id, outcome.value)
    return outcome
