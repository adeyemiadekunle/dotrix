"""Workspaces, members, roles, ownership transfer (FR-2, FR-3, FR-4). Invites: modules/invites."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from pmagent_backend.api.deps import CurrentUser, SessionDep, require_permission
from pmagent_backend.core.openapi import errors
from pmagent_backend.modules.auth.router import IMAGE_RESPONSE, image

from .models import Membership
from .permissions import Permission
from .schemas import (
    MemberRead,
    MemberRoleUpdate,
    OrganizationConversion,
    OwnershipTransfer,
    WorkspaceCreate,
    WorkspaceUpdate,
    WorkspaceWithRole,
)
from .service import WorkspaceService

router = APIRouter(prefix="/workspaces", tags=["workspaces"], responses=errors(401))

Viewer = Annotated[Membership, Depends(require_permission(Permission.VIEW))]
WorkspaceAdmin = Annotated[Membership, Depends(require_permission(Permission.MANAGE_WORKSPACE))]
MemberAdmin = Annotated[Membership, Depends(require_permission(Permission.MANAGE_MEMBERS))]
Owner = Annotated[Membership, Depends(require_permission(Permission.MANAGE_BILLING))]


@router.get("")
async def list_workspaces(user: CurrentUser, session: SessionDep) -> list[WorkspaceWithRole]:
    """Workspaces you belong to, with your role in each."""
    return await WorkspaceService(session).list_for_user(user)


@router.post("", status_code=status.HTTP_201_CREATED, responses=errors(422))
async def create_workspace(
    data: WorkspaceCreate, user: CurrentUser, session: SessionDep
) -> WorkspaceWithRole:
    """Create an organisation (a workspace for a team: invites, roles, many projects); you
    become its owner. Your personal workspace was created at sign-up."""
    return await WorkspaceService(session).create(user, data)


@router.get("/{workspace_id}", responses=errors(404))
async def get_workspace(member: Viewer) -> WorkspaceWithRole:
    """A workspace you belong to."""
    return WorkspaceWithRole.of(member.workspace, member.role)


@router.post("/{workspace_id}/convert-to-organization", responses=errors(403, 404, 409, 422))
async def convert_to_organization(
    data: OrganizationConversion, member: Owner, session: SessionDep
) -> WorkspaceWithRole:
    """Turn your personal workspace into an organisation, with its projects, so it can invite
    people; optionally rename it. You get a new, empty personal workspace. Owners only; 409 if
    it's already an organisation."""
    return await WorkspaceService(session).convert_to_organization(member, data)


@router.patch("/{workspace_id}", responses=errors(403, 404, 422))
async def update_workspace(
    data: WorkspaceUpdate, member: WorkspaceAdmin, session: SessionDep
) -> WorkspaceWithRole:
    """Rename a workspace, or change what members may do beyond chatting, brainstorming, and
    working the board (`member_permissions`). Owners and admins."""
    return await WorkspaceService(session).update(member, data)


@router.get("/{workspace_id}/members", responses=errors(404))
async def list_members(member: Viewer, session: SessionDep) -> list[MemberRead]:
    """Everyone in the workspace, with their roles, what they do, and the projects they see
    (among the ones you see)."""
    return await WorkspaceService(session).list_members(member.workspace_id, member)


@router.get(
    "/{workspace_id}/members/{user_id}/avatar",
    response_class=Response,
    responses=IMAGE_RESPONSE | errors(404),
)
async def get_member_avatar(user_id: uuid.UUID, member: Viewer, session: SessionDep) -> Response:
    """A colleague's profile photo. 404 without one, or if they aren't in this workspace."""
    avatar = await WorkspaceService(session).avatar(member, user_id)
    return image(avatar.content_type, avatar.content)


@router.patch("/{workspace_id}/members/{user_id}", responses=errors(403, 404, 409, 422))
async def change_member_role(
    user_id: uuid.UUID, data: MemberRoleUpdate, member: MemberAdmin, session: SessionDep
) -> MemberRead:
    """Change someone's role. Owners and admins; only owners can grant or change the owner
    role, and a workspace always keeps at least one owner (409)."""
    return await WorkspaceService(session).change_role(member, user_id, data.role)


@router.post("/{workspace_id}/transfer-ownership", responses=errors(403, 404, 409, 422))
async def transfer_ownership(
    data: OwnershipTransfer, member: MemberAdmin, session: SessionDep
) -> MemberRead:
    """Owner only: the target becomes owner and you become admin."""
    return await WorkspaceService(session).transfer_ownership(member, data.user_id)


@router.delete(
    "/{workspace_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=errors(403, 404, 409),
)
async def remove_member(user_id: uuid.UUID, member: Viewer, session: SessionDep) -> None:
    """Admins remove others; any member can remove themselves (leave)."""
    await WorkspaceService(session).remove_member(member, user_id)
