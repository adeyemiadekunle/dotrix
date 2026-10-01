"""A project's activity feed: issue changes, document versions, agent runs, and decisions."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from pmagent_backend.api.deps import SessionDep, require_permission
from pmagent_backend.core.openapi import errors
from pmagent_backend.modules.projects.deps import ProjectViewer
from pmagent_backend.modules.workspaces.models import Membership
from pmagent_backend.modules.workspaces.permissions import Permission

from .schemas import ActivityItem
from .service import ActivityService

router = APIRouter(
    prefix="/workspaces/{workspace_id}/projects/{project_id}/activity",
    tags=["activity"],
    responses=errors(401, 404),
)


@router.get("", responses=errors(422))
async def list_project_activity(
    access: ProjectViewer,
    session: SessionDep,
    before: datetime | None = Query(default=None, description="Only items older than this (the last `at` you have)"),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[ActivityItem]:
    """What people and agents did in the project, newest first: issues created, changed,
    commented on, or claimed; documents changed; and, for people who can chat with the agents,
    agent runs and approval decisions. Page back with `before`."""
    return await ActivityService(session).project(access, before=before, limit=limit)


workspace_router = APIRouter(prefix="/workspaces/{workspace_id}/activity", tags=["activity"], responses=errors(401, 404))


@workspace_router.get("", responses=errors(403, 422))
async def list_workspace_activity(
    member: Annotated[Membership, Depends(require_permission(Permission.VIEW))],
    session: SessionDep,
    before: datetime | None = Query(default=None, description="Only items older than this (the last `at` you have)"),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[ActivityItem]:
    """The same feed as a project's, across every project in the workspace you can see, each
    item with its project. Page back with `before`."""
    return await ActivityService(session).workspace(member, before=before, limit=limit)
