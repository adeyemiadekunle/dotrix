"""The built-in roster and private task activity shared by chat and the agent panel."""
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends

from dotrix_backend.api.deps import SessionDep, require_permission
from dotrix_backend.core.openapi import errors
from dotrix_backend.modules.projects.deps import ProjectViewer
from dotrix_backend.modules.workspaces.models import Membership
from dotrix_backend.modules.workspaces.permissions import Permission

from .team_schemas import AgentActivityRead, SpecialistTaskRead, TeamMemberRead
from .team_service import TeamService

router = APIRouter(tags=["agents"], responses=errors(401, 403, 404))
Viewer = Annotated[Membership, Depends(require_permission(Permission.VIEW))]
Chatter = Annotated[Membership, Depends(require_permission(Permission.CHAT))]


@router.get("/workspaces/{workspace_id}/agent-team")
async def get_builtin_team(member: Viewer, session: SessionDep) -> list[TeamMemberRead]:
    """The seven built-in identities. Kai executes coding rather than a thinking-agent graph."""
    return await TeamService(session).roster(member)


@router.get("/workspaces/{workspace_id}/projects/{project_id}/agent/runs/{run_id}/tasks")
async def list_specialist_tasks(run_id: uuid.UUID, access: ProjectViewer, session: SessionDep) -> list[SpecialistTaskRead]:
    """The private specialist tasks beneath a coordinator's message, with saved results."""
    return await TeamService(session).tasks(access, run_id)


@router.get("/workspaces/{workspace_id}/agent/activity")
async def list_private_agent_activity(member: Chatter, session: SessionDep) -> list[AgentActivityRead]:
    """Recent agent activity in conversations the caller owns, restricted to visible projects."""
    return await TeamService(session).activity(member)
