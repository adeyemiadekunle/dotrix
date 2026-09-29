from __future__ import annotations

import uuid

from sqlalchemy import ColumnElement, exists, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from pmagent_backend.modules.workspaces.models import Membership, Role

from .models import Project, ProjectAccessLevel, ProjectMember


def visible_to(user_id: uuid.UUID, role: Role) -> ColumnElement[bool]:
    """SQL condition: `Project` is visible to someone with this role in its workspace. Guests see
    no projects; owners and admins see all; members see open ones and restricted ones they're in."""
    if role is Role.GUEST:
        return Project.id.is_(None)  # nothing
    if role in (Role.OWNER, Role.ADMIN):
        return true()
    return or_(
        Project.access == ProjectAccessLevel.WORKSPACE,
        exists().where(ProjectMember.project_id == Project.id, ProjectMember.user_id == user_id),
    )


class ProjectRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add(self, project: Project) -> None:
        self.session.add(project)

    async def get(
        self, workspace_id: uuid.UUID, project_id: uuid.UUID, *, for_update: bool = False
    ) -> Project | None:
        stmt = select(Project).where(Project.workspace_id == workspace_id, Project.id == project_id)
        if for_update:
            # populate_existing: refresh an already-loaded Project with the locked row's values.
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        return await self.session.scalar(stmt)

    async def key_exists(self, workspace_id: uuid.UUID, key: str) -> bool:
        found = await self.session.scalar(
            select(Project.id).where(Project.workspace_id == workspace_id, Project.key == key)
        )
        return found is not None

    async def visible(self, member: Membership, project_id: uuid.UUID) -> Project | None:
        """The project, if `member` can see it (else None: a 404 to them)."""
        return await self.session.scalar(
            select(Project).where(
                Project.workspace_id == member.workspace_id,
                Project.id == project_id,
                visible_to(member.user_id, member.role),
            )
        )

    async def can_see(self, project: Project, user_id: uuid.UUID) -> bool:
        """Whether this person (by their membership of the project's workspace) can see it."""
        role = await self.session.scalar(
            select(Membership.role).where(
                Membership.workspace_id == project.workspace_id, Membership.user_id == user_id
            )
        )
        if role is None:
            return False
        found = await self.session.scalar(
            select(Project.id).where(Project.id == project.id, visible_to(user_id, role))
        )
        return found is not None

    async def list(
        self, workspace_id: uuid.UUID, *, repo_url: str | None = None, member: Membership | None = None
    ) -> list[Project]:
        """Projects in a workspace; with `member`, only those they can see."""
        stmt = select(Project).where(Project.workspace_id == workspace_id)
        if member is not None:
            stmt = stmt.where(visible_to(member.user_id, member.role))
        if repo_url is not None:
            stmt = stmt.where(Project.repo_url == repo_url)
        return list(await self.session.scalars(stmt.order_by(Project.key)))
