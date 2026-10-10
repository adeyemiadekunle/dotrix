"""Project access for routes under /v1/workspaces/{workspace_id}/projects/{project_id}.

No `from __future__ import annotations` here: the dependency's annotation uses the
closure variable `permission`, which FastAPI can't resolve from a string annotation.
"""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends

from dotrix_backend.api.deps import SessionDep, require_permission
from dotrix_backend.core.errors import NotFound
from dotrix_backend.modules.workspaces.models import Membership
from dotrix_backend.modules.workspaces.permissions import Permission

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
        # Guests see no projects; a restricted project is hidden from members not added to it.
        project = await ProjectRepository(session).visible(member, project_id)
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
