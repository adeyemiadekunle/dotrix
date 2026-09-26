"""Project access for routes under /v1/workspaces/{workspace_id}/projects/{project_id}.

No `from __future__ import annotations` here: the dependency's annotation uses the
closure variable `permission`, which FastAPI can't resolve from a string annotation.
"""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends

from pmagent_backend.api.deps import SessionDep, require_permission
from pmagent_backend.core.errors import NotFound
from pmagent_backend.modules.workspaces.models import Membership, Role
from pmagent_backend.modules.workspaces.permissions import Permission

from .models import Project
from .repository import ProjectRepository


@dataclass(frozen=True)
class ProjectAccess:
    project: Project
    member: Membership


def require_project_permission(
    permission: Permission,
) -> Callable[..., Awaitable[ProjectAccess]]:
    async def dependency(
        project_id: uuid.UUID,
        member: Annotated[Membership, Depends(require_permission(permission))],
        session: SessionDep,
    ) -> ProjectAccess:
        # Guests will see only projects they're invited to; until project-level access
        # exists, they see none.
        project = None
        if member.role is not Role.GUEST:
            project = await ProjectRepository(session).get(member.workspace_id, project_id)
        if project is None:
            raise NotFound("Project not found")
        return ProjectAccess(project, member)

    return dependency


ProjectViewer = Annotated[ProjectAccess, Depends(require_project_permission(Permission.VIEW))]
ProjectManager = Annotated[
    ProjectAccess, Depends(require_project_permission(Permission.MANAGE_PROJECTS))
]
KnowledgeEditor = Annotated[
    ProjectAccess, Depends(require_project_permission(Permission.EDIT_KNOWLEDGE))
]
KnowledgeExporter = Annotated[
    ProjectAccess, Depends(require_project_permission(Permission.MANAGE_WORKSPACE))
]
