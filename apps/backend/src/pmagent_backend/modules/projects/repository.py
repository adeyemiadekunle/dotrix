from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Project


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

    async def list(self, workspace_id: uuid.UUID, *, repo_url: str | None = None) -> list[Project]:
        stmt = select(Project).where(Project.workspace_id == workspace_id)
        if repo_url is not None:
            stmt = stmt.where(Project.repo_url == repo_url)
        return list(await self.session.scalars(stmt.order_by(Project.key)))
