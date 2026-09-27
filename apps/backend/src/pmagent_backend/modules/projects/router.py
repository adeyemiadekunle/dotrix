"""Projects (FR-9). Each project's `.pmagent/` lives under .../knowledge (modules/knowledge)."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status

from pmagent_backend.api.deps import CurrentUser, SessionDep, SettingsDep, require_permission
from pmagent_backend.core.openapi import errors
from pmagent_backend.modules.workspaces.models import Membership, Role
from pmagent_backend.modules.workspaces.permissions import Permission

from .deps import ProjectManager, ProjectViewer
from .schemas import ProjectCreate, ProjectRead, ProjectUpdate
from .service import ProjectService

router = APIRouter(
    prefix="/workspaces/{workspace_id}/projects",
    tags=["projects"],
    responses=errors(401, 404),
)

Viewer = Annotated[Membership, Depends(require_permission(Permission.VIEW))]
Creator = Annotated[Membership, Depends(require_permission(Permission.MANAGE_PROJECTS))]


@router.get("")
async def list_projects(member: Viewer, session: SessionDep) -> list[ProjectRead]:
    """Projects in the workspace, by key."""
    if member.role is Role.GUEST:
        return []  # project-level guest access comes later
    return await ProjectService(session).list(member.workspace_id)


@router.post("", status_code=status.HTTP_201_CREATED, responses=errors(403, 409, 422))
async def create_project(
    data: ProjectCreate,
    member: Creator,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
) -> ProjectRead:
    """Create a project from a new repo, an existing repo, or docs only. Its `.pmagent/` is
    created with the full folder structure and the default agent rules. The key (e.g. `KUN`)
    prefixes issue keys and can't be changed; 409 if the workspace already uses it."""
    return await ProjectService(session).create(
        member.workspace_id, user, data, default_model=settings.default_model
    )


@router.get("/{project_id}")
async def get_project(access: ProjectViewer) -> ProjectRead:
    """A project, including its current knowledge revision."""
    return ProjectRead.model_validate(access.project)


@router.patch("/{project_id}", responses=errors(403, 422))
async def update_project(
    data: ProjectUpdate, access: ProjectManager, session: SessionDep
) -> ProjectRead:
    """Rename a project, or change its description or its agents' model. The key can't change."""
    return await ProjectService(session).update(access.project, data)
