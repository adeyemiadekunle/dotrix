from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from pmagent_backend.core.errors import Conflict, Forbidden, NotFound
from pmagent_backend.modules.agents.models import ACTIVE_STATUSES, AgentApproval, AgentRun
from pmagent_backend.modules.audit.service import AuditLog
from pmagent_backend.modules.auth.models import User
from pmagent_backend.modules.documents.models import Document
from pmagent_backend.modules.issues.models import Issue, IssueEvent, IssueEventKind, IssueWatcher
from pmagent_backend.modules.knowledge.models import AuthorType, KnowledgeFile, KnowledgeVersion
from pmagent_backend.modules.knowledge.service import KnowledgeService
from pmagent_backend.modules.organizations.models import OrgMembership, OrgRole
from pmagent_backend.modules.search.models import KnowledgeChunk
from pmagent_backend.modules.workspaces.models import Membership, Role, Workspace
from pmagent_backend.modules.workspaces.permissions import Permission, can
from pmagent_backend.modules.workspaces.repository import MembershipRepository
from pmagent_engine.layout import skeleton

from .models import Project
from .repository import ProjectRepository
from .schemas import ProjectCreate, ProjectRead, ProjectUpdate


class KeyTaken(Conflict):
    code = "key_taken"


class RepoTaken(Conflict):
    code = "repo_taken"


# Everything a project owns that carries its workspace, moved with it. Audit events stay: each
# workspace's log keeps what happened while the project was there.
_PROJECT_ROWS = (KnowledgeFile, KnowledgeVersion, Issue, AgentRun, AgentApproval, Document, KnowledgeChunk)


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
        if "specialist_model" in data.model_fields_set:
            project.specialist_model = data.specialist_model
        if "token_budget" in data.model_fields_set:
            project.token_budget = data.token_budget
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

    async def move(self, project: Project, actor: Membership, target_id: uuid.UUID) -> ProjectRead:
        """Move a project, with everything in it, to another workspace where you can set up
        projects (owners and admins in both). Its key and repo must be free there, and no agent
        run may be working or waiting on an approval."""
        target = await MembershipRepository(self.session).effective(target_id, actor.user_id)
        if target is None:
            raise NotFound("Workspace not found")
        if not can(target, Permission.MANAGE_PROJECTS):
            raise Forbidden(f"Your role there ({target.role}) can't add projects")
        source_id = project.workspace_id
        if target_id == source_id:
            raise Conflict("The project is already in that workspace")
        project = await self.projects.get(source_id, project.id, for_update=True)
        assert project is not None  # the route found it
        if await self.projects.key_exists(target_id, project.key):
            raise KeyTaken(f"{target.workspace.name} already has a project with key {project.key}")
        if project.repo_url and await self.projects.list(target_id, repo_url=project.repo_url):
            raise RepoTaken(f"{target.workspace.name} already has a project for {project.repo_url}")
        active = await self.session.scalar(
            select(AgentRun.id).where(AgentRun.project_id == project.id, AgentRun.status.in_(ACTIVE_STATUSES)).limit(1)
        )
        if active is not None:
            raise Conflict("An agent run is still working or waiting for approval; stop it or decide it first")

        for model in _PROJECT_ROWS:
            await self.session.execute(
                update(model).where(model.project_id == project.id).values(workspace_id=target_id)
            )
        issues = select(Issue.id).where(Issue.project_id == project.id).scalar_subquery()
        await self.session.execute(
            update(IssueEvent).where(IssueEvent.issue_id.in_(issues)).values(workspace_id=target_id)
        )
        project.workspace_id = target_id
        unassigned, unwatched = await self._drop_people_who_cant_see(project, target_id, actor)
        audit = AuditLog(self.session)
        for workspace_id, direction, other in (
            (source_id, "project.moved_out", target_id), (target_id, "project.moved_in", source_id)
        ):
            audit.record(
                workspace_id=workspace_id, project_id=project.id, action=direction, target=project.key,
                actor_type=AuthorType.USER, actor_user_id=actor.user_id,
                details={
                    "from": str(source_id), "to": str(target_id), "other_workspace": str(other),
                    "unassigned": unassigned, "watchers_removed": unwatched,
                },
            )
        await self.session.commit()
        await self.session.refresh(project)
        return ProjectRead.model_validate(project)

    async def _drop_people_who_cant_see(
        self, project: Project, workspace_id: uuid.UUID, actor: Membership
    ) -> tuple[int, int]:
        """After a move, nobody stays assigned to or watching an issue they can no longer see:
        the new workspace's members (not guests) and its organisation's owners can. Each
        unassignment is written to the issue's log. Returns (unassigned, watchers removed)."""
        members = select(Membership.user_id).where(
            Membership.workspace_id == workspace_id, Membership.role != Role.GUEST
        )
        org_owners = (
            select(OrgMembership.user_id)
            .join(Workspace, Workspace.organization_id == OrgMembership.organization_id)
            .where(Workspace.id == workspace_id, OrgMembership.role == OrgRole.OWNER)
        )
        can_see = members.union(org_owners).scalar_subquery()
        issues = select(Issue.id).where(Issue.project_id == project.id).scalar_subquery()

        stranded = list(
            await self.session.scalars(
                select(Issue).where(
                    Issue.project_id == project.id,
                    Issue.assignee_user_id.is_not(None),
                    Issue.assignee_user_id.not_in(can_see),
                )
            )
        )
        now = datetime.now(UTC)
        for issue in stranded:
            self.session.add(
                IssueEvent(
                    workspace_id=workspace_id, issue_id=issue.id, kind=IssueEventKind.UPDATED,
                    author_user_id=actor.user_id, changes={"assignee_user_id": [str(issue.assignee_user_id), None]},
                    created_at=now,
                )
            )
            issue.assignee_user_id = None
            issue.updated_at = now
        watchers = await self.session.execute(
            delete(IssueWatcher).where(IssueWatcher.issue_id.in_(issues), IssueWatcher.user_id.not_in(can_see))
        )
        return len(stranded), watchers.rowcount or 0
