"""A project's automations: agents that run on a schedule or when something happens."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from dotrix_backend.api.deps import SessionDep, SettingsDep
from dotrix_backend.core.openapi import errors
from dotrix_backend.modules.agents.router import get_runner
from dotrix_backend.modules.agents.runner import AgentRunner
from dotrix_backend.modules.projects.deps import ProjectManager, ProjectViewer

from .schemas import AutomationCreate, AutomationRead, AutomationUpdate
from .service import AutomationService

router = APIRouter(
    prefix="/workspaces/{workspace_id}/projects/{project_id}/automations",
    tags=["automations"],
    responses=errors(401, 404),
)


def _service(session: SessionDep, settings: SettingsDep, runner: AgentRunner) -> AutomationService:
    return AutomationService(session, runner, workspace_daily_runs=settings.automation_daily_runs,
                             workspace_daily_tokens=settings.automation_daily_tokens)


def get_automation_service(
    session: SessionDep, settings: SettingsDep, runner: Annotated[AgentRunner, Depends(get_runner)]
) -> AutomationService:
    return _service(session, settings, runner)


Automations = Annotated[AutomationService, Depends(get_automation_service)]


@router.get("")
async def list_automations(access: ProjectViewer, automations: Automations) -> list[AutomationRead]:
    """The project's automations: what each does, when it runs, and how its last run went.
    Anyone who sees the project."""
    return await automations.list(access.project)


@router.post("", status_code=status.HTTP_201_CREATED, responses=errors(403, 422))
async def create_automation(data: AutomationCreate, access: ProjectManager, automations: Automations) -> AutomationRead:
    """Set an agent to run on its own: on `events` (people's issue and document changes,
    approved agent changes, pushes; never an agent's own) and/or a schedule (`schedule_hour`
    UTC, every day or on `schedule_weekday`). Its runs are instructed by you and see what you
    see; their changes wait for approval. At most `max_runs_per_day` when it has one. Owners and admins."""
    return await automations.create(access, data)


@router.patch("/{automation_id}", responses=errors(403, 422))
async def update_automation(
    automation_id: uuid.UUID, data: AutomationUpdate, access: ProjectManager, automations: Automations
) -> AutomationRead:
    """Change an automation, or turn it off and on (`enabled`). Owners and admins."""
    return await automations.update(access, automation_id, data)


@router.delete("/{automation_id}", status_code=status.HTTP_204_NO_CONTENT, responses=errors(403))
async def delete_automation(automation_id: uuid.UUID, access: ProjectManager, automations: Automations) -> None:
    """Delete an automation; its past runs stay in Chat. Owners and admins."""
    await automations.delete(access, automation_id)


@router.post("/{automation_id}/run", responses=errors(403))
async def run_automation(automation_id: uuid.UUID, access: ProjectManager, automations: Automations) -> AutomationRead:
    """Run it once now. If it can't (its daily limit, its last run still going), `last_error`
    says why. Owners and admins."""
    return await automations.run_now(access, automation_id)

