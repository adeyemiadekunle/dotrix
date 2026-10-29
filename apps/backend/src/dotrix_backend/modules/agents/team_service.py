"""Resolve the roster and scope task/activity views to the requesting person."""
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dotrix_backend.core.errors import NotFound
from dotrix_backend.modules.agent_definitions.repository import AgentDefinitionRepository
from dotrix_backend.modules.coding.models import CodingRun
from dotrix_backend.modules.projects.deps import ProjectAccess
from dotrix_backend.modules.projects.models import Project
from dotrix_backend.modules.projects.repository import visible_to
from dotrix_backend.modules.workspaces.models import Membership
from dotrix_engine.team import TEAM

from .models import AgentRun
from .privacy import run_openable_by, runs_visible_to
from .specialist_sessions import specialist_result_visible
from .team_schemas import AgentActivityRead, SpecialistTaskRead, TeamMemberRead


class TeamService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def roster(self, member: Membership) -> list[TeamMemberRead]:
        repository = AgentDefinitionRepository(self.session)
        resolved = {agent.spec.handle: agent for agent in await repository.resolve(member.workspace_id)}
        resolved["coding-agent"] = await repository.coding_configuration(member.workspace_id)
        return [TeamMemberRead(**vars(agent), customised=resolved[agent.handle].source == "customised") for agent in TEAM]

    async def tasks(self, access: ProjectAccess, run_id: uuid.UUID) -> list[SpecialistTaskRead]:
        root = await self.session.scalar(select(AgentRun).where(
            AgentRun.workspace_id == access.member.workspace_id, AgentRun.project_id == access.project.id,
            AgentRun.id == run_id, run_openable_by(access.member)))
        if root is None:
            raise NotFound("Run not found")
        tasks = await self.session.scalars(select(AgentRun).where(
            AgentRun.workspace_id == access.member.workspace_id, AgentRun.project_id == access.project.id,
            AgentRun.parent_run_id == run_id, runs_visible_to(access.member)
        ).order_by(AgentRun.created_at, AgentRun.task_key))
        result = []
        for task in tasks:
            fields = {name: getattr(task, name) for name in SpecialistTaskRead.model_fields}
            if not await specialist_result_visible(self.session, task):
                fields.update(message="Specialist details are unavailable", task_result=None,
                              error=None, review_context=None)
            result.append(SpecialistTaskRead.model_validate(fields))
        return result

    async def activity(self, member: Membership) -> list[AgentActivityRead]:
        rows = (await self.session.execute(select(AgentRun, Project.key).join(Project, Project.id == AgentRun.project_id).where(
            AgentRun.workspace_id == member.workspace_id, Project.workspace_id == member.workspace_id,
            runs_visible_to(member), visible_to(member.user_id, member.role),
        ).order_by(AgentRun.updated_at.desc()).limit(100))).all()
        rows = [(run, key) for run, key in rows if await specialist_result_visible(self.session, run)]
        parent_ids = {run.parent_run_id for run, _ in rows if run.parent_run_id}
        parents = {run.id: run for run in await self.session.scalars(select(AgentRun).where(
            AgentRun.workspace_id == member.workspace_id, AgentRun.id.in_(parent_ids), runs_visible_to(member)))}
        activity = [AgentActivityRead(
            run_id=run.id, parent_run_id=run.parent_run_id,
            thread_id=parents[run.parent_run_id].thread_id if run.parent_run_id in parents else run.thread_id,
            project_id=run.project_id, project_key=project_key, agent=run.agent or "project-manager",
            status=run.status, title=(run.title or run.message)[:200], source=run.source, updated_at=run.updated_at,
        ) for run, project_key in rows]
        coding = (await self.session.execute(select(CodingRun, Project.key).join(Project, Project.id == CodingRun.project_id).where(
            CodingRun.workspace_id == member.workspace_id, Project.workspace_id == member.workspace_id,
            CodingRun.requested_by_id == member.user_id, visible_to(member.user_id, member.role),
        ).order_by(CodingRun.created_at.desc()).limit(100))).all()
        activity.extend(AgentActivityRead(
            run_id=run.id, parent_run_id=run.origin_run_id, thread_id=run.thread_id, session_id=run.session_id,
            project_id=run.project_id, project_key=project_key, agent="coding-agent", status=run.status,
            title=f"Coding {run.issue_key}", source="coding", updated_at=run.finished_at or run.started_at or run.created_at,
        ) for run, project_key in coding)
        return sorted(activity, key=lambda item: item.updated_at, reverse=True)[:100]
