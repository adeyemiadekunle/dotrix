"""Projects (FR-9). Each project's `.pmagent/` lives under .../knowledge (modules/knowledge)."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from pmagent_backend.api.deps import CurrentUser, SessionDep, SettingsDep, require_permission
from pmagent_backend.core.errors import Unprocessable
from pmagent_backend.core.openapi import errors
from pmagent_backend.modules.workspaces.models import Membership, Role
from pmagent_backend.modules.workspaces.permissions import Permission

from .deps import ProjectManager, ProjectViewer
from .repo_urls import normalize_repo_url
from .schemas import ProjectCreate, ProjectMove, ProjectRead, ProjectUpdate
from .service import ProjectService

router = APIRouter(
    prefix="/workspaces/{workspace_id}/projects",
    tags=["projects"],
    responses=errors(401, 404),
)

Viewer = Annotated[Membership, Depends(require_permission(Permission.VIEW))]
Creator = Annotated[Membership, Depends(require_permission(Permission.MANAGE_PROJECTS))]


@router.get("", responses=errors(422))
async def list_projects(
    member: Viewer,
    session: SessionDep,
    repo_url: str | None = Query(
        default=None,
        description="Only the project for this repo remote (any form: https, ssh, with or without .git)",
    ),
) -> list[ProjectRead]:
    """Projects in the workspace, by key. `repo_url` finds the project a local checkout belongs to."""
    if member.role is Role.GUEST:
        return []  # project-level guest access comes later
    try:
        wanted = normalize_repo_url(repo_url) if repo_url else None
    except ValueError as exc:
        raise Unprocessable(str(exc)) from exc
    return await ProjectService(session).list(member.workspace_id, repo_url=wanted)


@router.post("", status_code=status.HTTP_201_CREATED, responses=errors(403, 409, 422))
async def create_project(
    data: ProjectCreate,
    member: Creator,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
) -> ProjectRead:
    """Set up a project from a new repo, an existing repo, or docs only (owners and admins).
    Its `.pmagent/` is created with the full folder structure and the default agent rules.
    The key (e.g. `KUN`) prefixes issue keys and can't be changed; 409 if it's taken, and 409
    `repo_taken` if a project in this workspace already uses the repo."""
    return await ProjectService(session).create(
        member.workspace_id, user, data, default_model=settings.default_model
    )


@router.get("/{project_id}")
async def get_project(access: ProjectViewer) -> ProjectRead:
    """A project, including its current knowledge revision."""
    return ProjectRead.model_validate(access.project)


@router.patch("/{project_id}", responses=errors(403, 409, 422))
async def update_project(
    data: ProjectUpdate, access: ProjectManager, session: SessionDep
) -> ProjectRead:
    """Rename a project, change its description or its agents' model, or link or unlink its repo
    (one project per repo in a workspace: 409 if another has it). The key can't change."""
    return await ProjectService(session).update(access.project, data)


@router.post("/{project_id}/move", responses=errors(403, 409, 422))
async def move_project(data: ProjectMove, access: ProjectManager, session: SessionDep) -> ProjectRead:
    """Move a project, with its knowledge, issues, documents, and conversations, to another
    workspace: from your personal workspace into an organisation's, or back. You need to set up
    projects in both (owners and admins). 409 if the other workspace already has a project with
    its key or repo, or while one of its agent runs is working or waiting for approval. People
    who can't see it there are unassigned from its issues (logged) and stop watching them; linked
    checkouts follow the move on their next command."""
    return await ProjectService(session).move(access.project, access.member, data.workspace_id)
