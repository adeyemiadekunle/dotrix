"""Coding runs on a project's issues: Claude Code or Codex in a sandbox, a PR at the end."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from dotrix_backend.api.deps import SessionDep, SettingsDep, require_permission
from dotrix_backend.core.jobs import Jobs, get_jobs
from dotrix_backend.core.openapi import errors
from dotrix_backend.core.storage import BlobStorage, get_storage, optional_storage
from dotrix_backend.modules.connectors.github_app import GitHubApp, get_github_app
from dotrix_backend.modules.projects.deps import (
    ProjectAccess,
    ProjectViewer,
    require_project_permission,
)
from dotrix_backend.modules.workspaces.models import Membership
from dotrix_backend.modules.workspaces.permissions import Permission

from .local import LocalRunners
from .schemas import (
    CodingAvailability,
    CodingClaimed,
    CodingDecision,
    CodingEventPage,
    CodingFollowUp,
    CodingRecover,
    CodingRevert,
    CodingRunCreate,
    CodingRunnerCreate,
    CodingRunnerRead,
    CodingRunRead,
    CodingSessionRead,
    CodingSessionUpdate,
    RunnerHeartbeat,
    RunnerHeartbeatRead,
    RunnerResult,
)
from .service import CodingService

router = APIRouter(
    prefix="/workspaces/{workspace_id}/projects/{project_id}/coding",
    tags=["coding"],
    responses=errors(401, 404),
)

CodingInstructor = Annotated[
    ProjectAccess, Depends(require_project_permission(Permission.INSTRUCT_CODING_AGENT))
]
CodingApprover = Annotated[ProjectAccess, Depends(require_project_permission(Permission.APPROVE_ACTIONS))]


def get_coding_service(
    session: SessionDep, settings: SettingsDep, jobs: Annotated[Jobs, Depends(get_jobs)]
) -> CodingService:
    return CodingService(session, settings, jobs)


Coding = Annotated[CodingService, Depends(get_coding_service)]


@router.get("")
async def coding_availability(access: ProjectViewer, coding: Coding) -> CodingAvailability:
    """Whether this project's issues can be coded here, by which tool, and if not, why not.
    Anyone who sees the project."""
    return await coding.availability(access.project, access.member.user_id)


@router.post("/issues/{key}/runs", status_code=status.HTTP_201_CREATED, responses=errors(403, 409, 422))
async def start_coding(key: str, data: CodingRunCreate, access: CodingInstructor, coding: Coding) -> CodingRunRead:
    """Ask for a coding run on an issue: Kai, the coding agent, codes it in a sandbox on a new
    branch, and the platform opens a PR. It waits for someone who may approve agent changes;
    the brief it will get is in the run. People who may instruct the coding agent. 409
    `coding_unavailable` (not set up, or no connected repo), `coding_busy` (one is already open)."""
    return await coding.start(access, key, data)


@router.get("/runs")
async def list_coding_runs(
    access: ProjectViewer, coding: Coding, issue: Annotated[str | None, Query(max_length=24)] = None
) -> list[CodingRunRead]:
    """The project's coding runs, newest first (one issue's with `issue=KEY`). Anyone who sees the project."""
    return await coding.list(access, issue)


@router.get("/runs/{coding_run_id}")
async def get_coding_run(coding_run_id: uuid.UUID, access: ProjectViewer, coding: Coding) -> CodingRunRead:
    """A coding run with what the agent has done so far (poll it while it runs)."""
    return await coding.get(access, coding_run_id)


@router.get("/runs/{coding_run_id}/events")
async def list_coding_run_events(
    coding_run_id: uuid.UUID, access: ProjectViewer, coding: Coding,
    after: Annotated[int, Query(ge=-1, description="Events after this `seq` (-1: from the start)")] = -1,
    limit: Annotated[int, Query(ge=1, le=1000)] = 500,
) -> CodingEventPage:
    """Every event of a coding run, oldest first, a page at a time (the run itself keeps only the
    latest). Poll with `after` set to the last `seq` you have. Anyone who sees the project."""
    return await coding.events(access, coding_run_id, after, limit)


@router.get(
    "/runs/{coding_run_id}/screenshots/{index}",
    responses={**errors(503), 200: {"content": {"image/png": {}, "image/jpeg": {}}, "description": "The image"}},
    response_class=Response,
)
async def get_coding_screenshot(
    coding_run_id: uuid.UUID, index: int, access: ProjectViewer, coding: Coding, storage: Annotated[BlobStorage, Depends(get_storage)]
) -> Response:
    """A screenshot the agent's browser captured in a coding run (the run lists them). Anyone who sees the project."""
    data, content_type = await coding.screenshot(access, coding_run_id, index, storage)
    return Response(content=data, media_type=content_type, headers={"Cache-Control": "private, max-age=3600"})


@router.post("/sessions/{session_id}/close", status_code=status.HTTP_204_NO_CONTENT, responses=errors(403, 409))
async def close_coding_session(session_id: uuid.UUID, access: ProjectViewer, coding: Coding) -> None:
    """Close a coding session: its sandbox kept between turns goes; its transcript, branch, and PR
    stay, and a new turn opens it again and resumes. Whoever started it, or owners and admins."""
    await coding.close_session(access, session_id)


@router.patch("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT, responses=errors(403, 422))
async def update_coding_session(session_id: uuid.UUID, data: CodingSessionUpdate, access: ProjectViewer, coding: Coding) -> None:
    """Rename, pin, or archive a coding session. Whoever started it, or owners and admins."""
    await coding.update_session(access, session_id, data)


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT, responses=errors(403, 409, 503))
async def delete_coding_session(
    session_id: uuid.UUID, access: ProjectViewer, coding: Coding, storage: Annotated[BlobStorage | None, Depends(optional_storage)]
) -> None:
    """Delete a coding session: its turns, their events and screenshots, and its saved transcript.
    Its branch and PR stay on GitHub, and the audit log keeps what happened. Whoever started it, or
    owners and admins; 409 while a turn waits or works."""
    await coding.delete_session(access, session_id, storage)


@router.post("/runs/{coding_run_id}/decision", responses=errors(403, 409))
async def decide_coding_run(
    coding_run_id: uuid.UUID, data: CodingDecision, access: CodingApprover, coding: Coding
) -> CodingRunRead:
    """Approve a coding run (it starts, and the issue is assigned to the tool) or reject it,
    with a reason; or, for a Manual turn whose changes are ready (`changes_ready`), accept them
    (they're pushed, and the PR opened or updated) or reject them (discarded, nothing pushed).
    People who may approve agent changes."""
    return await coding.decide(access, coding_run_id, data)


@router.post("/runs/{coding_run_id}/revert", status_code=status.HTTP_201_CREATED, responses=errors(403, 409, 422))
async def revert_coding_run(
    coding_run_id: uuid.UUID, data: CodingRevert, access: CodingInstructor, coding: Coding
) -> CodingRunRead:
    """Revert a pushed turn: a new turn in its session whose commit undoes it on the session's
    branch (never forced; the PR keeps its history). It waits for approval like any turn, and the
    agent doesn't run. Whoever started the session. 409 when its PR is merged or closed, the
    session has moved to a new branch, it's reverted already, or a turn waits or works."""
    return await coding.revert(access, coding_run_id, data)


@router.post("/runs/{coding_run_id}/stop", responses=errors(403, 409))
async def stop_coding_run(coding_run_id: uuid.UUID, access: ProjectViewer, coding: Coding) -> CodingRunRead:
    """Request that a waiting or running coding turn stop. A push already in flight may need
    reconciliation. Whoever asked for it, or owners and admins."""
    return await coding.stop(access, coding_run_id)


@router.post("/runs/{coding_run_id}/recover", responses=errors(403, 409, 503))
async def recover_coding_run(
    coding_run_id: uuid.UUID, data: CodingRecover, access: ProjectViewer, coding: Coding,
    app: Annotated[GitHubApp, Depends(get_github_app)],
) -> CodingRunRead:
    """Settle a coding run whose outcome is uncertain (`recovery_required`), once its worker's lease has
    run out: check GitHub (the push landed: its PR is adopted, or opened; nothing was published: the
    turn runs again, twice at most), or discard it. Whoever asked for it, or owners and admins."""
    return await coding.recover(access, coding_run_id, data, app)


@router.get("/sessions/{session_id}")
async def get_coding_session(session_id: uuid.UUID, access: ProjectViewer, coding: Coding) -> list[CodingRunRead]:
    """A coding session's turns, first to latest: each a run with what the agent did. Sessions are
    private like conversations: whoever started it, and approvers while a turn waits on them."""
    return await coding.session_turns(access, session_id)


@router.post("/sessions/{session_id}/turns", status_code=status.HTTP_201_CREATED, responses=errors(403, 409, 422))
async def follow_up_coding_session(
    session_id: uuid.UUID, data: CodingFollowUp, access: CodingInstructor, coding: Coding
) -> CodingRunRead:
    """Continue a session: another turn for the same agent on the session's branch, pushing to its PR
    (or opening one, if no turn has yet). It waits for approval like the first. People who may
    instruct the coding agent. 409 `coding_busy` while a turn waits or works."""
    return await coding.follow_up(access, session_id, data)


workspace_router = APIRouter(prefix="/workspaces/{workspace_id}/coding", tags=["coding"], responses=errors(401, 404))


@workspace_router.get("/sessions")
async def list_coding_sessions(
    member: Annotated[Membership, Depends(require_permission(Permission.VIEW))], coding: Coding,
    archived: Annotated[str, Query(pattern="^(exclude|include|only)$", description="Archived sessions: left out (default), included, or only them")] = "exclude",
) -> list[CodingSessionRead]:
    """The workspace's coding sessions across the projects you can see, pinned first, then the latest
    activity (Chat's Code tab). Guests see none: they see no projects."""
    return await coding.sessions(member, {"exclude": False, "include": None, "only": True}[archived])


def get_local_runners(
    session: SessionDep, settings: SettingsDep, jobs: Annotated[Jobs, Depends(get_jobs)]
) -> LocalRunners:
    return LocalRunners(session, settings, jobs)


Runners = Annotated[LocalRunners, Depends(get_local_runners)]
Instructor = Annotated[Membership, Depends(require_permission(Permission.INSTRUCT_CODING_AGENT))]


@workspace_router.post("/runners", responses=errors(403, 422))
async def register_coding_runner(data: CodingRunnerCreate, member: Instructor, runners: Runners) -> CodingRunnerRead:
    """Register this computer to code your local turns (`dotrix runner`), or update it (the same name):
    its coding tools, whether it isolates them (`srt`), and the projects it has checkouts of (those
    you can't see are left out). It claims only your turns. People who may instruct the coding agent."""
    return await runners.register(member, data)


@workspace_router.get("/runners")
async def list_coding_runners(
    member: Annotated[Membership, Depends(require_permission(Permission.VIEW))], runners: Runners,
) -> list[CodingRunnerRead]:
    """Your computers that code your local turns here, last seen first."""
    return await runners.list(member)


@workspace_router.delete("/runners/{runner_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_coding_runner(
    runner_id: uuid.UUID, member: Annotated[Membership, Depends(require_permission(Permission.VIEW))], runners: Runners,
) -> None:
    """Stop one of your computers from claiming turns. A turn it holds needs recovery once its lease lapses."""
    await runners.revoke(member, runner_id)


@workspace_router.post("/runners/{runner_id}/claim", responses=errors(403))
async def claim_coding_run(runner_id: uuid.UUID, member: Instructor, runners: Runners) -> CodingClaimed:
    """The runner's poll: the oldest approved local turn of yours in a project it serves, now held by
    it under a new lease (`run` is null when none waits). Counts as its heartbeat."""
    return await runners.claim(member, runner_id)


@workspace_router.post("/runners/{runner_id}/runs/{coding_run_id}/heartbeat", responses=errors(403, 409))
async def coding_run_heartbeat(
    runner_id: uuid.UUID, coding_run_id: uuid.UUID, data: RunnerHeartbeat, member: Instructor, runners: Runners,
) -> RunnerHeartbeatRead:
    """Renew a held turn's lease, with what the agent did since (its events) and the commit it codes
    on; says whether to stop. 409 `lease_lost` once this runner no longer holds it."""
    return await runners.heartbeat(member, runner_id, coding_run_id, data)


@workspace_router.post(
    "/runners/{runner_id}/runs/{coding_run_id}/result", status_code=status.HTTP_204_NO_CONTENT,
    responses=errors(403, 409, 422),
)
async def report_coding_result(
    runner_id: uuid.UUID, coding_run_id: uuid.UUID, data: RunnerResult, member: Instructor, runners: Runners,
) -> None:
    """A held turn's outcome: its changes as a patch against `base_sha`, or none, failed, or stopped.
    Changes are checked (no `.dotrix/`, no CI configuration); in Manual they wait for a person to
    accept them, otherwise they're pushed by the platform. 409 `lease_lost` when no longer held."""
    await runners.result(member, runner_id, coding_run_id, data)
