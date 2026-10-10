"""Workspace rules: what every project's agents follow, set once for the workspace."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path

from dotrix_backend.api.deps import SessionDep, require_permission
from dotrix_backend.core.openapi import errors
from dotrix_backend.modules.workspaces.models import Membership
from dotrix_backend.modules.workspaces.permissions import Permission

from .schemas import WorkspaceRuleRead, WorkspaceRuleSave, WorkspaceSkillRead
from .service import WorkspaceRules, WorkspaceSkills

router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["agents"], responses=errors(401, 404))

Viewer = Annotated[Membership, Depends(require_permission(Permission.VIEW))]
Manager = Annotated[Membership, Depends(require_permission(Permission.MANAGE_WORKSPACE))]
Handle = Annotated[str, Path(pattern=r"^[a-z][a-z0-9-]{1,30}$", description='"base" or an agent\'s handle')]


@router.get("/rules")
async def list_workspace_rules(member: Viewer, session: SessionDep) -> list[WorkspaceRuleRead]:
    """The rules every project's agents follow: "base" for all of them, and per agent. A
    project's own agent-rules/ come after them, so the project's win where they differ."""
    return await WorkspaceRules(session).list(member.workspace_id)


@router.put("/rules/{handle}", responses=errors(403, 409, 422))
async def save_workspace_rule(
    handle: Handle, data: WorkspaceRuleSave, member: Manager, session: SessionDep
) -> WorkspaceRuleRead:
    """Set the rules for every agent ("base") or one agent, in every project (owners and admins;
    audited `workspace_rules.saved` with what it replaced). Empty content removes them. 409
    `rules_changed` if they changed since `base_version`."""
    return await WorkspaceRules(session).save(member, handle, data)


SkillName = Annotated[str, Path(pattern=r"^[a-z][a-z0-9-]{1,39}$", description="The skill's name, e.g. write-a-release-note")]


@router.get("/skills")
async def list_workspace_skills(member: Viewer, session: SessionDep) -> list[WorkspaceSkillRead]:
    """Skills every project's agents can use, by name. A project's own skill of the same name
    (agent-rules/skills/) wins over the workspace's."""
    return await WorkspaceSkills(session).list(member.workspace_id)


@router.put("/skills/{name}", responses=errors(403, 409, 422))
async def save_workspace_skill(
    name: SkillName, data: WorkspaceRuleSave, member: Manager, session: SessionDep
) -> WorkspaceSkillRead:
    """Add or change a skill for every project (owners and admins; audited
    `workspace_skill.saved` with what it replaced). Start it with a "Description:" line: that's
    what agents see in their list. Empty content removes it. 409 `skill_changed` if it changed
    since `base_version`."""
    return await WorkspaceSkills(session).save(member, name, data)
