from __future__ import annotations

import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from pmagent_backend.core.errors import Conflict
from pmagent_backend.modules.auth.models import User
from pmagent_backend.modules.knowledge.service import KnowledgeService
from pmagent_engine.layout import skeleton

from .models import Project
from .repository import ProjectRepository
from .schemas import ProjectCreate, ProjectRead, ProjectUpdate


class KeyTaken(Conflict):
    code = "key_taken"


class RepoTaken(Conflict):
    code = "repo_taken"


class ProjectService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.projects = ProjectRepository(session)

    async def create(
        self, workspace_id: uuid.UUID, user: User, data: ProjectCreate, *, default_model: str
    ) -> ProjectRead:
        """Create the project and its `.pmagent/` skeleton (agent rules included) in one go."""
        if await self.projects.key_exists(workspace_id, data.key):
            raise KeyTaken(f"This workspace already has a project with key {data.key}")
        if data.repo_url and (existing := await self.projects.list(workspace_id, repo_url=data.repo_url)):
            raise RepoTaken(
                f"{existing[0].key} already uses {data.repo_url}; link to it instead of creating another"
            )
        project = Project(
            workspace_id=workspace_id,
            key=data.key,
            name=data.name,
            description=data.description,
            source=data.source,
            repo_url=data.repo_url,
            model=data.model or default_model,
            created_by_id=user.id,
        )
        self.projects.add(project)
        try:
            await self.session.flush()
        except IntegrityError as exc:  # concurrent create with the same key
            raise KeyTaken(f"This workspace already has a project with key {data.key}") from exc
        await KnowledgeService(self.session).scaffold(
            project, skeleton(data.name, data.description, readme=data.readme)
        )
        await self.session.commit()
        await self.session.refresh(project)  # scaffolding bumped the revision (and updated_at)
        return ProjectRead.model_validate(project)

    async def list(self, workspace_id: uuid.UUID, *, repo_url: str | None = None) -> list[ProjectRead]:
        projects = await self.projects.list(workspace_id, repo_url=repo_url)
        return [ProjectRead.model_validate(p) for p in projects]

    async def update(self, project: Project, data: ProjectUpdate) -> ProjectRead:
        if data.name is not None:
            project.name = data.name
        if data.description is not None:
            project.description = data.description
        if data.model is not None:
            project.model = data.model
        if "repo_url" in data.model_fields_set and data.repo_url != project.repo_url:
            if data.repo_url and (
                taken := [p for p in await self.projects.list(project.workspace_id, repo_url=data.repo_url)
                          if p.id != project.id]
            ):
                raise RepoTaken(f"{taken[0].key} already uses {data.repo_url}")
            project.repo_url = data.repo_url
        await self.session.commit()
        await self.session.refresh(project)  # updated_at is set by the database
        return ProjectRead.model_validate(project)
