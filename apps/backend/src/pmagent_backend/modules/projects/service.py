from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from pmagent_backend.core.errors import Conflict, Forbidden, NotFound
from pmagent_backend.modules.agents.models import (
    ACTIVE_STATUSES,
    AgentApproval,
    AgentRun,
    AgentRunOutput,
)
from pmagent_backend.modules.audit.service import AuditLog
from pmagent_backend.modules.auth.models import User
from pmagent_backend.modules.auth.repository import UserRepository
from pmagent_backend.modules.connectors.models import ConnectedRepo
from pmagent_backend.modules.documents.models import Document
from pmagent_backend.modules.issues.models import (
    Issue,
    IssueAttachment,
    IssueEvent,
    IssueEventKind,
    IssueStar,
    IssueWatcher,
)
from pmagent_backend.modules.knowledge.models import AuthorType, KnowledgeFile, KnowledgeVersion
from pmagent_backend.modules.knowledge.service import KnowledgeService
from pmagent_backend.modules.research.models import ResearchSource
from pmagent_backend.modules.search.models import KnowledgeChunk
from pmagent_backend.modules.teams.models import TeamProject
from pmagent_backend.modules.workspaces.models import Membership, Role
from pmagent_backend.modules.workspaces.permissions import Permission, can
from pmagent_backend.modules.workspaces.repository import MembershipRepository
from pmagent_engine.layout import skeleton

from .models import Project, ProjectAccessLevel, ProjectMember, ProjectStar
from .repository import ProjectRepository, visible_to
from .schemas import ProjectCreate, ProjectMemberRead, ProjectRead, ProjectUpdate


class KeyTaken(Conflict):
    code = "key_taken"


class RepoTaken(Conflict):
    code = "repo_taken"


# Everything a project owns that carries its workspace, moved with it. Audit events stay: each
# workspace's log keeps what happened while the project was there. The web page cache stays
# too: it belongs to the workspace, not the project.
_PROJECT_ROWS = (
    KnowledgeFile, KnowledgeVersion, Issue, AgentRun, AgentApproval, AgentRunOutput, ResearchSource, Document,
    KnowledgeChunk, ProjectMember, IssueAttachment,
)


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
            access=data.access,
            icon=data.icon,
            color=data.color,
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

    async def list(self, member: Membership, *, repo_url: str | None = None) -> list[ProjectRead]:
        projects = await self.projects.list(member.workspace_id, repo_url=repo_url, member=member)
        return [ProjectRead.model_validate(p) for p in projects]

    async def update(self, project: Project, data: ProjectUpdate, actor: Membership) -> ProjectRead:
        if data.access is not None and data.access is not project.access:
            self._audit(actor, project, "project.access_changed", **{"from": project.access.value, "to": data.access.value})
            project.access = data.access
            if data.access is ProjectAccessLevel.RESTRICTED:
                await self._drop_people_who_cant_see(project, project.workspace_id, actor)
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
        if "health" in data.model_fields_set:
            project.health = data.health
        if "target_date" in data.model_fields_set:
            project.target_date = data.target_date
        if data.status is not None:
            project.status = data.status
        if "icon" in data.model_fields_set:
            project.icon = data.icon
        if "color" in data.model_fields_set:
            project.color = data.color
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

    # -- stars (per person) --------------------------------------------------------------

    async def starred(self, member: Membership) -> list[uuid.UUID]:
        """The projects this person starred here, among those they can still see."""
        ids = await self.session.scalars(
            select(ProjectStar.project_id)
            .join(Project, Project.id == ProjectStar.project_id)
            .where(
                ProjectStar.workspace_id == member.workspace_id,
                ProjectStar.user_id == member.user_id,
                visible_to(member.user_id, member.role),
            )
            .order_by(ProjectStar.created_at)
        )
        return list(ids)

    async def star(self, project: Project, member: Membership, starred: bool) -> None:
        existing = await self.session.scalar(
            select(ProjectStar).where(ProjectStar.project_id == project.id, ProjectStar.user_id == member.user_id)
        )
        if starred and existing is None:
            self.session.add(ProjectStar(workspace_id=project.workspace_id, project_id=project.id, user_id=member.user_id))
        elif not starred and existing is not None:
            await self.session.delete(existing)
        await self.session.commit()

    async def move(self, project: Project, actor: Membership, target_id: uuid.UUID) -> ProjectRead:
        """Move a project, with everything in it, to another workspace where you can set up
        projects (owners and admins in both). Its key and repo must be free there, and no agent
        run may be working or waiting on an approval."""
        target = await MembershipRepository(self.session).get(target_id, actor.user_id)
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

        # Its repo was reached through this workspace's GitHub installation: connect it again there.
        await self.session.execute(delete(ConnectedRepo).where(ConnectedRepo.project_id == project.id))
        # Stars are per workspace (a sidebar's order there); people star it again where it went.
        await self.session.execute(delete(ProjectStar).where(ProjectStar.project_id == project.id))
        moving = select(Issue.id).where(Issue.project_id == project.id).scalar_subquery()
        await self.session.execute(delete(IssueStar).where(IssueStar.issue_id.in_(moving)))
        # Teams belong to a workspace: it joins one of the new workspace's teams there, if any.
        await self.session.execute(delete(TeamProject).where(TeamProject.project_id == project.id))
        for model in _PROJECT_ROWS:
            await self.session.execute(
                update(model).where(model.project_id == project.id).values(workspace_id=target_id)
            )
        issues = select(Issue.id).where(Issue.project_id == project.id).scalar_subquery()
        await self.session.execute(
            update(IssueEvent).where(IssueEvent.issue_id.in_(issues)).values(workspace_id=target_id)
        )
        project.workspace_id = target_id
        # Only people in the new workspace stay on a restricted project's list.
        await self.session.execute(
            delete(ProjectMember).where(
                ProjectMember.project_id == project.id,
                ProjectMember.user_id.not_in(select(Membership.user_id).where(Membership.workspace_id == target_id)),
            )
        )
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
        the new workspace's members (not guests), and for a restricted project only its owners,
        admins, and the people added to it. Each unassignment is written to the issue's log.
        Returns (unassigned, watchers removed)."""
        who = select(Membership.user_id).where(Membership.workspace_id == workspace_id, Membership.role != Role.GUEST)
        if project.access is ProjectAccessLevel.RESTRICTED:
            added = select(ProjectMember.user_id).where(ProjectMember.project_id == project.id)
            who = who.where(or_(Membership.role.in_((Role.OWNER, Role.ADMIN)), Membership.user_id.in_(added)))
        can_see = who.scalar_subquery()
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

    # -- who can see a project -------------------------------------------------------------

    async def members(self, project: Project) -> list[ProjectMemberRead]:
        """Everyone who can see the project, and why: their role (owners and admins), the
        workspace (an open project), or being added to it (a restricted one)."""
        rows = await MembershipRepository(self.session).list_with_users(project.workspace_id)
        added = set(
            await self.session.scalars(select(ProjectMember.user_id).where(ProjectMember.project_id == project.id))
        )
        out = []
        for membership, user in rows:
            if membership.role is Role.GUEST:
                continue
            if membership.role in (Role.OWNER, Role.ADMIN):
                via = "role"
            elif project.access is ProjectAccessLevel.WORKSPACE:
                via = "workspace"
            elif membership.user_id in added:
                via = "added"
            else:
                continue
            out.append(
                ProjectMemberRead(
                    user_id=user.id, email=user.email, display_name=user.display_name,
                    role=membership.role, via=via, added=membership.user_id in added,
                )
            )
        return out

    async def add_member(self, project: Project, actor: Membership, user_id: uuid.UUID) -> list[ProjectMemberRead]:
        """Add someone from the workspace (not a guest) to the project's people. It matters once
        the project is restricted; adding them again changes nothing."""
        membership = await MembershipRepository(self.session).get(project.workspace_id, user_id)
        if membership is None:
            raise NotFound("No such person in this workspace")
        if membership.role is Role.GUEST:
            raise Conflict("Guests don't see projects; change their role first")
        exists = await self.session.scalar(
            select(ProjectMember.id).where(ProjectMember.project_id == project.id, ProjectMember.user_id == user_id)
        )
        if exists is None:
            self.session.add(
                ProjectMember(
                    workspace_id=project.workspace_id, project_id=project.id, user_id=user_id,
                    added_by_id=actor.user_id,
                )
            )
            await self._audit_person(actor, project, "project.member_added", user_id)
            await self.session.commit()
        return await self.members(project)

    async def remove_member(self, project: Project, actor: Membership, user_id: uuid.UUID) -> None:
        """Take someone off the project's people. On a restricted project they lose sight of it
        (unless they're an owner or admin), and are unassigned from its issues and stop watching."""
        removed = await self.session.execute(
            delete(ProjectMember).where(ProjectMember.project_id == project.id, ProjectMember.user_id == user_id)
        )
        if not removed.rowcount:
            raise NotFound("That person wasn't added to this project")
        await self._audit_person(actor, project, "project.member_removed", user_id)
        await self._drop_people_who_cant_see(project, project.workspace_id, actor)
        await self.session.commit()

    def _audit(self, actor: Membership, project: Project, action: str, **details: object) -> None:
        AuditLog(self.session).record(
            workspace_id=project.workspace_id, project_id=project.id, action=action, target=project.key,
            actor_type=AuthorType.USER, actor_user_id=actor.user_id, details=details,
        )

    async def _audit_person(self, actor: Membership, project: Project, action: str, user_id: uuid.UUID) -> None:
        user = await UserRepository(self.session).get(user_id)
        AuditLog(self.session).record(
            workspace_id=project.workspace_id, project_id=project.id, action=action,
            target=user.email if user else str(user_id), actor_type=AuthorType.USER, actor_user_id=actor.user_id,
            details={"user_id": str(user_id), "project": project.key},
        )
