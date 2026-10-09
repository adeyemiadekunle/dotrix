"""Agents as data: the workspace's agents and each project's overrides (docs/agents-v2.md §4.8).

Everyone who sees the workspace (or project) sees its agents; owners and admins change them.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, status

from pmagent_backend.api.deps import SessionDep, SettingsDep, require_permission
from pmagent_backend.core.openapi import errors
from pmagent_backend.modules.agents.llm import available_models
from pmagent_backend.modules.model_keys.deps import Connected, Personal
from pmagent_backend.modules.projects.deps import ProjectManager, ProjectViewer
from pmagent_backend.modules.workspaces.models import Membership
from pmagent_backend.modules.workspaces.permissions import Permission

from .preferences import AgentPreferences
from .schemas import (
    AgentCatalog,
    AgentPreferenceRead,
    AgentPreferenceSave,
    AgentRead,
    AgentSave,
    AgentVersionRead,
)
from .service import AgentDefinitionService, catalog_read

router = APIRouter(prefix="/workspaces/{workspace_id}/agents", tags=["agents"], responses=errors(401, 404))
project_router = APIRouter(
    prefix="/workspaces/{workspace_id}/projects/{project_id}/agents", tags=["agents"], responses=errors(401, 404)
)

Viewer = Annotated[Membership, Depends(require_permission(Permission.VIEW))]
Manager = Annotated[Membership, Depends(require_permission(Permission.MANAGE_WORKSPACE))]
Handle = Annotated[str, Path(pattern=r"^[a-z][a-z0-9-]{1,30}$", description="The agent's handle, e.g. research")]


# -- the workspace's agents ----------------------------------------------------------------


@router.get("")
async def list_agents(member: Viewer, session: SessionDep) -> list[AgentRead]:
    """The workspace's agents: the six built-ins (as they are here) and its custom agents."""
    return await AgentDefinitionService(session).list(member.workspace_id)


@router.get("/catalog")
async def get_agent_catalog(member: Viewer) -> AgentCatalog:
    """What an agent can be given: tools, the actions autonomy rules name, access levels, and
    issue types."""
    return catalog_read()


@router.get("/{handle}")
async def get_agent(handle: Handle, member: Viewer, session: SessionDep) -> AgentRead:
    """One of the workspace's agents."""
    return await AgentDefinitionService(session).get(member.workspace_id, None, handle)


@router.put("/{handle}", responses=errors(403, 409, 422))
async def save_agent(
    handle: Handle, data: AgentSave, member: Manager, session: SessionDep, settings: SettingsDep,
    connected: Connected,
) -> AgentRead:
    """Create a custom agent, or change one (a built-in's first change makes it customised).
    Owners and admins; only owners let an agent act without asking (`allow`). Each save is a new
    version; send the `version` you edited as `base_version` (409 `agent_changed` otherwise).
    422 `invalid_agent` with the reason when the contract breaks a rule."""
    return await AgentDefinitionService(session).save(
        member, None, handle, data, available_models=available_models(settings, connected=connected)
    )


@router.delete("/{handle}", status_code=status.HTTP_204_NO_CONTENT, responses=errors(403))
async def delete_agent(handle: Handle, member: Manager, session: SessionDep) -> None:
    """Remove a custom agent, or reset a built-in to its default. Its history is kept."""
    await AgentDefinitionService(session).delete(member, None, handle)


@router.get("/{handle}/versions")
async def list_agent_versions(handle: Handle, member: Viewer, session: SessionDep) -> list[AgentVersionRead]:
    """Every saved version of an agent here, newest first."""
    return await AgentDefinitionService(session).versions(member.workspace_id, None, handle)


@router.post("/{handle}/versions/{version}/restore", responses=errors(403, 409, 422))
async def restore_agent_version(
    handle: Handle, version: int, member: Manager, session: SessionDep, settings: SettingsDep,
    connected: Connected,
) -> AgentRead:
    """Make an earlier version the current one (saved as a new version)."""
    return await AgentDefinitionService(session).restore(
        member, None, handle, version, available_models=available_models(settings, connected=connected)
    )


# -- a project's agents (overrides and project-only agents) ---------------------------------


@project_router.get("")
async def list_project_agents(access: ProjectViewer, session: SessionDep) -> list[AgentRead]:
    """The agents this project's runs use: its overrides, else the workspace's, else the built-ins."""
    return await AgentDefinitionService(session).list(access.member.workspace_id, access.project.id)


@project_router.get("/{handle}")
async def get_project_agent(handle: Handle, access: ProjectViewer, session: SessionDep) -> AgentRead:
    """One agent as this project's runs use it."""
    return await AgentDefinitionService(session).get(access.member.workspace_id, access.project.id, handle)


@project_router.put("/{handle}", responses=errors(403, 409, 422))
async def save_project_agent(
    handle: Handle, data: AgentSave, access: ProjectManager, session: SessionDep, settings: SettingsDep,
    connected: Connected,
) -> AgentRead:
    """Override an agent for this project only, or create an agent only this project has."""
    return await AgentDefinitionService(session).save(
        access.member, access.project.id, handle, data,
        available_models=available_models(settings, access.project.model, connected=connected),
    )


@project_router.delete("/{handle}", status_code=status.HTTP_204_NO_CONTENT, responses=errors(403))
async def delete_project_agent(handle: Handle, access: ProjectManager, session: SessionDep) -> None:
    """Drop this project's override (the workspace's agent applies again), or remove an agent
    only this project had."""
    await AgentDefinitionService(session).delete(access.member, access.project.id, handle)


@project_router.get("/{handle}/versions")
async def list_project_agent_versions(
    handle: Handle, access: ProjectViewer, session: SessionDep
) -> list[AgentVersionRead]:
    """Every saved version of this project's override, newest first."""
    return await AgentDefinitionService(session).versions(access.member.workspace_id, access.project.id, handle)


@project_router.post("/{handle}/versions/{version}/restore", responses=errors(403, 409, 422))
async def restore_project_agent_version(
    handle: Handle, version: int, access: ProjectManager, session: SessionDep, settings: SettingsDep,
    connected: Connected,
) -> AgentRead:
    """Make an earlier version of this project's override the current one."""
    return await AgentDefinitionService(session).restore(
        access.member, access.project.id, handle, version,
        available_models=available_models(settings, access.project.model, connected=connected),
    )


mine_router = APIRouter(prefix="/workspaces/{workspace_id}/my-agents", tags=["agents"], responses=errors(401, 404))

Chatter = Annotated[Membership, Depends(require_permission(Permission.CHAT))]


@mine_router.get("")
async def list_my_agent_preferences(member: Chatter, session: SessionDep) -> list[AgentPreferenceRead]:
    """Your own preferences for this workspace's agents: extra instructions and a model, for the
    runs you start. Agents you haven't touched aren't listed."""
    return await AgentPreferences(session).list(member)


@mine_router.put("/{handle}", responses=errors(403, 422))
async def save_my_agent_preference(
    handle: Handle, data: AgentPreferenceSave, member: Chatter, session: SessionDep, settings: SettingsDep,
    connected: Connected, personal: Personal,
) -> AgentPreferenceRead:
    """How you like an agent to work (up to 2,000 characters, added to its instructions) and its
    model, for the runs you start. Within limits: it can't change the agent's tools, folder
    access, or what it may do without asking. A model needs the workspace's permission to
    choose models, unless your own key runs it (403). Empty instructions and no model: removed."""
    return await AgentPreferences(session).save(
        member, handle, data, available=available_models(settings, connected=connected), personal=personal
    )


@mine_router.delete("/{handle}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_my_agent_preference(handle: Handle, member: Chatter, session: SessionDep) -> None:
    """Back to the agent as the workspace set it up, for your runs."""
    await AgentPreferences(session).remove(member, handle)
