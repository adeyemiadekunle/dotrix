"""Coding runs on a project's issues: Claude Code or Codex in a sandbox, a PR at the end."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from pmagent_backend.api.deps import SessionDep, SettingsDep
from pmagent_backend.core.jobs import Jobs, get_jobs
from pmagent_backend.core.openapi import errors
from pmagent_backend.modules.projects.deps import (
    ProjectAccess,
    ProjectViewer,
    require_project_permission,
)
from pmagent_backend.modules.workspaces.permissions import Permission

from .schemas import CodingAvailability, CodingDecision, CodingRunCreate, CodingRunRead
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
