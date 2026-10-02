"""Workspace rules: what every project's agents follow, set once for the workspace."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path

from pmagent_backend.api.deps import SessionDep, require_permission
from pmagent_backend.core.openapi import errors
from pmagent_backend.modules.workspaces.models import Membership
from pmagent_backend.modules.workspaces.permissions import Permission

from .schemas import WorkspaceRuleRead, WorkspaceRuleSave
from .service import WorkspaceRules

router = APIRouter(prefix="/workspaces/{workspace_id}/rules", tags=["agents"], responses=errors(401, 404))

Viewer = Annotated[Membership, Depends(require_permission(Permission.VIEW))]
Manager = Annotated[Membership, Depends(require_permission(Permission.MANAGE_WORKSPACE))]
Handle = Annotated[str, Path(pattern=r"^[a-z][a-z0-9-]{1,30}$", description='"base" or an agent\'s handle')]


@router.get("")
async def list_workspace_rules(member: Viewer, session: SessionDep) -> list[WorkspaceRuleRead]:
    """The rules every project's agents follow: "base" for all of them, and per agent. A
    project's own agent-rules/ come after them, so the project's win where they differ."""
    return await WorkspaceRules(session).list(member.workspace_id)


@router.put("/{handle}", responses=errors(403, 409, 422))
async def save_workspace_rule(
    handle: Handle, data: WorkspaceRuleSave, member: Manager, session: SessionDep
) -> WorkspaceRuleRead:
    """Set the rules for every agent ("base") or one agent, in every project (owners and admins;
    audited `workspace_rules.saved` with what it replaced). Empty content removes them. 409
    `rules_changed` if they changed since `base_version`."""
    return await WorkspaceRules(session).save(member, handle, data)
