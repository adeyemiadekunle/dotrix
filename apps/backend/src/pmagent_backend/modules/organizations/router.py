"""Organisations own workspaces and manage people across them, without seeing inside them.

No `from __future__ import annotations`: the permission dependency's annotation uses a
closure variable, which FastAPI can't resolve from a string annotation.
"""
import uuid
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import APIRouter, Depends, status

from pmagent_backend.api.deps import CurrentUser, SessionDep
from pmagent_backend.core.errors import Forbidden, NotFound
from pmagent_backend.core.openapi import errors
from pmagent_backend.modules.workspaces.schemas import MemberRead

from .models import OrgMembership
from .permissions import OrgPermission, has_org_permission
from .schemas import (
    AttachWorkspace,
    OrgCreate,
    OrgMemberAdd,
    OrgMemberRead,
    OrgMemberRoleUpdate,
    OrgUpdate,
    OrgWithRole,
    OrgWorkspaceCreate,
    OrgWorkspaceRead,
    WorkspacePlacement,
)
from .service import OrganizationService

router = APIRouter(prefix="/organizations", tags=["organizations"], responses=errors(401))


def require_org_permission(permission: OrgPermission) -> Callable[..., Awaitable[OrgMembership]]:
    async def dependency(org_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> OrgMembership:
        member = await OrganizationService(session).membership(org_id, user.id)
        if member is None:
            raise NotFound("Organisation not found")  # not 403: don't reveal it exists
        if not has_org_permission(member.role, permission):
            raise Forbidden(f"Your organisation role ({member.role}) can't do this ({permission})")
        return member

    return dependency


OrgViewer = Annotated[OrgMembership, Depends(require_org_permission(OrgPermission.VIEW))]
PeopleAdmin = Annotated[OrgMembership, Depends(require_org_permission(OrgPermission.MANAGE_PEOPLE))]
WorkspaceAdmin = Annotated[OrgMembership, Depends(require_org_permission(OrgPermission.MANAGE_WORKSPACES))]
OrgAdmin = Annotated[OrgMembership, Depends(require_org_permission(OrgPermission.MANAGE_ORG))]


@router.get("")
async def list_organizations(user: CurrentUser, session: SessionDep) -> list[OrgWithRole]:
    """Organisations you belong to, with your role."""
    return await OrganizationService(session).list_for_user(user)


@router.post("", status_code=status.HTTP_201_CREATED, responses=errors(422))
async def create_organization(data: OrgCreate, user: CurrentUser, session: SessionDep) -> OrgWithRole:
    """Create an organisation; you become its owner."""
    return await OrganizationService(session).create(user, data)


@router.get("/{org_id}", responses=errors(404))
async def get_organization(member: OrgViewer, session: SessionDep) -> OrgWithRole:
    """An organisation you belong to."""
    return await OrganizationService(session).get(member)


@router.patch("/{org_id}", responses=errors(403, 404, 422))
async def update_organization(data: OrgUpdate, member: OrgAdmin, session: SessionDep) -> OrgWithRole:
    """Rename the organisation. Owners and admins."""
    return await OrganizationService(session).update(member, data)


@router.get("/{org_id}/members", responses=errors(404))
async def list_org_members(member: OrgViewer, session: SessionDep) -> list[OrgMemberRead]:
    """Everyone in the organisation."""
    return await OrganizationService(session).members(member.organization_id)


@router.post("/{org_id}/members", status_code=status.HTTP_201_CREATED, responses=errors(403, 404, 409, 422))
async def add_org_member(data: OrgMemberAdd, member: PeopleAdmin, session: SessionDep) -> OrgMemberRead:
    """Add someone with an account to the organisation. Owners and admins; only owners add owners."""
    return await OrganizationService(session).add_member(member, data)


@router.patch("/{org_id}/members/{user_id}", responses=errors(403, 404, 409, 422))
async def change_org_member_role(
    user_id: uuid.UUID, data: OrgMemberRoleUpdate, member: PeopleAdmin, session: SessionDep
) -> OrgMemberRead:
    """Change someone's organisation role. The organisation always keeps an owner."""
    return await OrganizationService(session).change_role(member, user_id, data.role)


@router.delete("/{org_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT, responses=errors(403, 404, 409))
async def remove_org_member(user_id: uuid.UUID, member: OrgViewer, session: SessionDep) -> None:
    """Remove someone (owners and admins), or leave yourself. They're also removed from every
    workspace in the organisation; anyone who owns one must transfer it first (409)."""
    await OrganizationService(session).remove_member(member, user_id)


@router.get("/{org_id}/workspaces", responses=errors(404))
async def list_org_workspaces(member: OrgViewer, session: SessionDep) -> list[OrgWorkspaceRead]:
    """The organisation's workspaces: names and sizes only. Owners and admins see all of them,
    members see their own. Seeing a workspace's projects still requires being in it."""
    return await OrganizationService(session).workspaces(member)


@router.post("/{org_id}/workspaces", status_code=status.HTTP_201_CREATED, responses=errors(403, 404, 422))
async def create_org_workspace(data: OrgWorkspaceCreate, member: WorkspaceAdmin, session: SessionDep) -> OrgWorkspaceRead:
    """Create a workspace in the organisation, owned by you or another org member."""
    return await OrganizationService(session).create_workspace(member, data)


@router.post("/{org_id}/workspaces/attach", responses=errors(403, 404, 409, 422))
async def attach_workspace(data: AttachWorkspace, member: WorkspaceAdmin, session: SessionDep) -> OrgWorkspaceRead:
    """Bring a workspace you own into the organisation. Its people join the organisation as
    members. A personal workspace becomes a team workspace with its projects, and you get a new,
    empty personal workspace."""
    return await OrganizationService(session).attach(member, data.workspace_id)


@router.post("/{org_id}/workspaces/{workspace_id}/detach", status_code=status.HTTP_204_NO_CONTENT, responses=errors(403, 404))
async def detach_workspace(workspace_id: uuid.UUID, member: WorkspaceAdmin, session: SessionDep) -> None:
    """Take a workspace out of the organisation. Its people stay organisation members."""
    await OrganizationService(session).detach(member, workspace_id)


@router.get("/{org_id}/workspaces/{workspace_id}/members", responses=errors(403, 404))
async def list_org_workspace_members(workspace_id: uuid.UUID, member: PeopleAdmin, session: SessionDep) -> list[MemberRead]:
    """Who is in one of the organisation's workspaces."""
    return await OrganizationService(session).workspace_members(member, workspace_id)


@router.put("/{org_id}/workspaces/{workspace_id}/members/{user_id}", responses=errors(403, 404, 409, 422))
async def place_in_workspace(
    workspace_id: uuid.UUID, user_id: uuid.UUID, data: WorkspacePlacement, member: PeopleAdmin, session: SessionDep
) -> list[MemberRead]:
    """Put an organisation member into one of its workspaces (admin, member, or guest), or change
    their role there. You don't need to be in the workspace yourself."""
    return await OrganizationService(session).place(member, workspace_id, user_id, data.role)


@router.delete(
    "/{org_id}/workspaces/{workspace_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT,
    responses=errors(403, 404, 409),
)
async def remove_from_workspace(workspace_id: uuid.UUID, user_id: uuid.UUID, member: PeopleAdmin, session: SessionDep) -> None:
    """Take someone out of one of the organisation's workspaces (not its owner)."""
    await OrganizationService(session).unplace(member, workspace_id, user_id)
