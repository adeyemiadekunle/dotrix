"""Teams in a workspace: create, rename, delete; who is in each, and which projects each looks
after. Everyone sees the teams; owners and admins change them (members:manage), and whoever sets
up projects (projects:manage) puts a project under a team. One team each, for people and projects.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from dotrix_backend.core.errors import Conflict, NotFound
from dotrix_backend.modules.audit.service import AuditLog
from dotrix_backend.modules.knowledge.models import AuthorType
from dotrix_backend.modules.projects.models import Project
from dotrix_backend.modules.projects.repository import ProjectRepository, visible_to
from dotrix_backend.modules.workspaces.models import Membership

from .models import Team, TeamMember, TeamProject
from .schemas import TeamCreate, TeamRead, TeamUpdate


class TeamNameTaken(Conflict):
    code = "team_name_taken"


class TeamService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list(self, member: Membership) -> list[TeamRead]:
        """The workspace's teams by name, each with its people and the projects `member` can see."""
        teams = list(
            await self.session.scalars(
                select(Team).where(Team.workspace_id == member.workspace_id).order_by(Team.name, Team.id)
            )
        )
        people, projects = await self._links(member, [t.id for t in teams])
        return [self._read(t, people, projects) for t in teams]

    async def create(self, member: Membership, data: TeamCreate) -> TeamRead:
        await self._check_name(member.workspace_id, data.name)
        team = Team(workspace_id=member.workspace_id, **data.model_dump())
        self.session.add(team)
        await self.session.flush()
        self._audit(member, "team.created", team)
        await self.session.commit()
        return await self.get(member, team.id)

    async def get(self, member: Membership, team_id: uuid.UUID) -> TeamRead:
        team = await self._team(member.workspace_id, team_id)
        people, projects = await self._links(member, [team.id])
        return self._read(team, people, projects)

    async def update(self, member: Membership, team_id: uuid.UUID, data: TeamUpdate) -> TeamRead:
        team = await self._team(member.workspace_id, team_id)
        sent = {k: v for k, v in data.model_dump(exclude_unset=True).items() if v is not None}
        if "name" in sent and sent["name"] != team.name:
            await self._check_name(member.workspace_id, sent["name"])
        changed = {k: [getattr(team, k), v] for k, v in sent.items() if getattr(team, k) != v}
        for field, (_, new) in changed.items():
            setattr(team, field, new)
        if changed:
            self._audit(member, "team.updated", team, {"changes": changed})
            await self.session.commit()
        return await self.get(member, team.id)

    async def delete(self, member: Membership, team_id: uuid.UUID) -> None:
        """Its people stay in the workspace and its projects stay as they are, in no team."""
        team = await self._team(member.workspace_id, team_id)
        self._audit(member, "team.deleted", team)
        await self.session.delete(team)
        await self.session.commit()

    async def add_member(self, member: Membership, team_id: uuid.UUID, user_id: uuid.UUID) -> TeamRead:
        """Put someone in the workspace in this team; they leave the team they were in."""
        team = await self._team(member.workspace_id, team_id)
        await self._check_member(member.workspace_id, user_id)
        current = await self.session.scalar(
            select(TeamMember).where(TeamMember.workspace_id == member.workspace_id, TeamMember.user_id == user_id)
        )
        if current is None or current.team_id != team.id:
            if current is not None:
                await self.session.delete(current)
                await self.session.flush()
            self.session.add(TeamMember(workspace_id=member.workspace_id, team_id=team.id, user_id=user_id))
            self._audit(member, "team.member_added", team, {"user_id": str(user_id)})
            await self.session.commit()
        return await self.get(member, team.id)

    async def remove_member(self, member: Membership, team_id: uuid.UUID, user_id: uuid.UUID) -> TeamRead:
        team = await self._team(member.workspace_id, team_id)
        await self._check_member(member.workspace_id, user_id)
        removed = await self.session.execute(
            delete(TeamMember).where(TeamMember.team_id == team.id, TeamMember.user_id == user_id)
        )
        if removed.rowcount:  # type: ignore[attr-defined]
            self._audit(member, "team.member_removed", team, {"user_id": str(user_id)})
            await self.session.commit()
        return await self.get(member, team.id)

    async def add_project(self, member: Membership, team_id: uuid.UUID, project_id: uuid.UUID) -> TeamRead:
        """Put a project you can see under this team; it leaves the team it was under."""
        team = await self._team(member.workspace_id, team_id)
        project = await self._project(member, project_id)
        current = await self.session.get(TeamProject, project.id)
        if current is None or current.team_id != team.id:
            if current is not None:
                await self.session.delete(current)
                await self.session.flush()
            self.session.add(TeamProject(workspace_id=member.workspace_id, team_id=team.id, project_id=project.id))
            self._audit(member, "team.project_added", team, {"project": project.key}, project_id=project.id)
            await self.session.commit()
        return await self.get(member, team.id)

    async def remove_project(self, member: Membership, team_id: uuid.UUID, project_id: uuid.UUID) -> TeamRead:
        team = await self._team(member.workspace_id, team_id)
        project = await self._project(member, project_id)
        removed = await self.session.execute(
            delete(TeamProject).where(TeamProject.team_id == team.id, TeamProject.project_id == project.id)
        )
        if removed.rowcount:  # type: ignore[attr-defined]
            self._audit(member, "team.project_removed", team, {"project": project.key}, project_id=project.id)
            await self.session.commit()
        return await self.get(member, team.id)

    # -- helpers -----------------------------------------------------------------------

    async def _team(self, workspace_id: uuid.UUID, team_id: uuid.UUID) -> Team:
        team = await self.session.scalar(select(Team).where(Team.workspace_id == workspace_id, Team.id == team_id))
        if team is None:
            raise NotFound("Team not found")
        return team

    async def _check_member(self, workspace_id: uuid.UUID, user_id: uuid.UUID) -> None:
        found = await self.session.scalar(
            select(Membership.id).where(Membership.workspace_id == workspace_id, Membership.user_id == user_id)
        )
        if found is None:
            raise NotFound("Member not found")

    async def _project(self, member: Membership, project_id: uuid.UUID) -> Project:
        project = await ProjectRepository(self.session).visible(member, project_id)
        if project is None:
            raise NotFound("Project not found")
        return project

    async def _check_name(self, workspace_id: uuid.UUID, name: str) -> None:
        taken = await self.session.scalar(select(Team.id).where(Team.workspace_id == workspace_id, Team.name == name))
        if taken is not None:
            raise TeamNameTaken(f"There's already a team called {name}")

    async def _links(
        self, member: Membership, team_ids: list[uuid.UUID]
    ) -> tuple[dict[uuid.UUID, list[uuid.UUID]], dict[uuid.UUID, list[uuid.UUID]]]:
        """Each team's people (still in the workspace) and projects (that `member` can see)."""
        people: dict[uuid.UUID, list[uuid.UUID]] = {}
        projects: dict[uuid.UUID, list[uuid.UUID]] = {}
        if not team_ids:
            return people, projects
        for team_id, user_id in await self.session.execute(
            select(TeamMember.team_id, TeamMember.user_id)
            .join(
                Membership,
                (Membership.workspace_id == TeamMember.workspace_id) & (Membership.user_id == TeamMember.user_id),
            )
            .where(TeamMember.team_id.in_(team_ids))
            .order_by(TeamMember.created_at, TeamMember.user_id)
        ):
            people.setdefault(team_id, []).append(user_id)
        for team_id, project_id in await self.session.execute(
            select(TeamProject.team_id, TeamProject.project_id)
            .join(Project, Project.id == TeamProject.project_id)
            .where(
                TeamProject.team_id.in_(team_ids),
                Project.workspace_id == member.workspace_id,
                visible_to(member.user_id, member.role),
            )
            .order_by(Project.key)
        ):
            projects.setdefault(team_id, []).append(project_id)
        return people, projects

    @staticmethod
    def _read(
        team: Team, people: dict[uuid.UUID, list[uuid.UUID]], projects: dict[uuid.UUID, list[uuid.UUID]]
    ) -> TeamRead:
        return TeamRead.model_validate(team).model_copy(
            update={"member_ids": people.get(team.id, []), "project_ids": projects.get(team.id, [])}
        )

    def _audit(
        self,
        member: Membership,
        action: str,
        team: Team,
        details: dict[str, Any] | None = None,
        *,
        project_id: uuid.UUID | None = None,
    ) -> None:
        AuditLog(self.session).record(
            workspace_id=member.workspace_id, project_id=project_id, action=action, target=team.name,
            actor_type=AuthorType.USER, actor_user_id=member.user_id, details=details or {},
        )
