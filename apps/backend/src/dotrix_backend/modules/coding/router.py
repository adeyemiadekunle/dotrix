"""Coding runs on a project's issues: Claude Code or Codex in a sandbox, a PR at the end."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from dotrix_backend.api.deps import SessionDep, SettingsDep, require_permission
from dotrix_backend.core.jobs import Jobs, get_jobs
from dotrix_backend.core.openapi import errors
from dotrix_backend.core.storage import BlobStorage, get_storage, optional_storage
from dotrix_backend.modules.projects.deps import (
    ProjectAccess,
    ProjectViewer,
    require_project_permission,
)
from dotrix_backend.modules.workspaces.models import Membership
from dotrix_backend.modules.workspaces.permissions import Permission

from .schemas import (
    CodingAvailability,
    CodingDecision,
    CodingEventPage,
    CodingFollowUp,
    CodingRunCreate,
    CodingRunRead,
    CodingSessionRead,
    CodingSessionUpdate,
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
    return await coding.availability(access.project)


@router.post("/issues/{key}/runs", status_code=status.HTTP_201_CREATED, responses=errors(403, 409, 422))
async def start_coding(key: str, data: CodingRunCreate, access: CodingInstructor, coding: Coding) -> CodingRunRead:
    """Ask for a coding run on an issue: Claude Code (or Codex) codes it in a sandbox on a new
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
    with a reason. People who may approve agent changes."""
    return await coding.decide(access, coding_run_id, data)


@router.post("/runs/{coding_run_id}/stop", responses=errors(403, 409))
async def stop_coding_run(coding_run_id: uuid.UUID, access: ProjectViewer, coding: Coding) -> CodingRunRead:
    """Stop a coding run that waits or works; nothing is pushed. Whoever asked for it, or owners and admins."""
    return await coding.stop(access, coding_run_id)


@router.get("/sessions/{session_id}")
async def get_coding_session(session_id: uuid.UUID, access: ProjectViewer, coding: Coding) -> list[CodingRunRead]:
    """A coding session's turns, first to latest: each a run with what the agent did. Anyone who sees the project."""
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
