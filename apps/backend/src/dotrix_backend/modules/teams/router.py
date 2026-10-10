"""Teams: groups of people in a workspace, and the projects each looks after."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from dotrix_backend.api.deps import SessionDep, require_permission
from dotrix_backend.core.openapi import errors
from dotrix_backend.modules.workspaces.models import Membership
from dotrix_backend.modules.workspaces.permissions import Permission

from .schemas import TeamCreate, TeamRead, TeamUpdate
from .service import TeamService

router = APIRouter(prefix="/workspaces/{workspace_id}/teams", tags=["teams"], responses=errors(401, 404))

Viewer = Annotated[Membership, Depends(require_permission(Permission.VIEW))]
Manager = Annotated[Membership, Depends(require_permission(Permission.MANAGE_MEMBERS))]
ProjectSetup = Annotated[Membership, Depends(require_permission(Permission.MANAGE_PROJECTS))]


@router.get("")
async def list_teams(member: Viewer, session: SessionDep) -> list[TeamRead]:
    """The workspace's teams, by name, with the people in each and the projects each looks after
    (only projects you can see)."""
    return await TeamService(session).list(member)


@router.post("", status_code=status.HTTP_201_CREATED, responses=errors(403, 409, 422))
async def create_team(data: TeamCreate, member: Manager, session: SessionDep) -> TeamRead:
    """Create a team. Names are unique in the workspace. Owners and admins."""
    return await TeamService(session).create(member, data)


@router.patch("/{team_id}", responses=errors(403, 409, 422))
async def update_team(team_id: uuid.UUID, data: TeamUpdate, member: Manager, session: SessionDep) -> TeamRead:
    """Rename a team or change its description, icon, or colour. Owners and admins."""
    return await TeamService(session).update(member, team_id, data)


@router.delete("/{team_id}", status_code=status.HTTP_204_NO_CONTENT, responses=errors(403))
async def delete_team(team_id: uuid.UUID, member: Manager, session: SessionDep) -> None:
    """Delete a team. Its people stay in the workspace, and its projects stay, in no team."""
    await TeamService(session).delete(member, team_id)


@router.put("/{team_id}/members/{user_id}", responses=errors(403))
async def add_team_member(team_id: uuid.UUID, user_id: uuid.UUID, member: Manager, session: SessionDep) -> TeamRead:
    """Put a member of the workspace in this team. They leave the team they were in: one team each."""
    return await TeamService(session).add_member(member, team_id, user_id)


@router.delete("/{team_id}/members/{user_id}", responses=errors(403))
async def remove_team_member(
    team_id: uuid.UUID, user_id: uuid.UUID, member: Manager, session: SessionDep
) -> TeamRead:
    """Take a person out of this team; they stay in the workspace."""
    return await TeamService(session).remove_member(member, team_id, user_id)


@router.put("/{team_id}/projects/{project_id}", responses=errors(403))
async def add_team_project(
    team_id: uuid.UUID, project_id: uuid.UUID, member: ProjectSetup, session: SessionDep
) -> TeamRead:
    """Put a project under this team. It leaves the team it was under: one team each. Whoever
    sets up projects (owners and admins)."""
    return await TeamService(session).add_project(member, team_id, project_id)


@router.delete("/{team_id}/projects/{project_id}", responses=errors(403))
async def remove_team_project(
    team_id: uuid.UUID, project_id: uuid.UUID, member: ProjectSetup, session: SessionDep
) -> TeamRead:
    """Take a project out from under this team; it stays in the workspace, in no team."""
    return await TeamService(session).remove_project(member, team_id, project_id)
