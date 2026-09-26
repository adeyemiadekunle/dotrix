"""Workspaces, members, and roles (FR-2, FR-3). Invites (FR-4) come next."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from pmagent_backend.api.deps import CurrentUser, SessionDep, require_permission

from .models import Membership
from .permissions import Permission
from .schemas import (
    MemberRead,
    MemberRoleUpdate,
    WorkspaceCreate,
    WorkspaceUpdate,
    WorkspaceWithRole,
)
from .service import WorkspaceService

router = APIRouter(prefix="/workspaces", tags=["workspaces"])

Viewer = Annotated[Membership, Depends(require_permission(Permission.VIEW))]
WorkspaceAdmin = Annotated[Membership, Depends(require_permission(Permission.MANAGE_WORKSPACE))]
MemberAdmin = Annotated[Membership, Depends(require_permission(Permission.MANAGE_MEMBERS))]


@router.get("")
async def list_workspaces(user: CurrentUser, session: SessionDep) -> list[WorkspaceWithRole]:
    return await WorkspaceService(session).list_for_user(user)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_workspace(
    data: WorkspaceCreate, user: CurrentUser, session: SessionDep
) -> WorkspaceWithRole:
    return await WorkspaceService(session).create(user, data)


@router.get("/{workspace_id}")
async def get_workspace(member: Viewer) -> WorkspaceWithRole:
    return WorkspaceWithRole.of(member.workspace, member.role)


@router.patch("/{workspace_id}")
async def update_workspace(
    data: WorkspaceUpdate, member: WorkspaceAdmin, session: SessionDep
) -> WorkspaceWithRole:
    return await WorkspaceService(session).update(member, data)


@router.get("/{workspace_id}/members")
async def list_members(member: Viewer, session: SessionDep) -> list[MemberRead]:
    return await WorkspaceService(session).list_members(member.workspace_id)


@router.patch("/{workspace_id}/members/{user_id}")
async def change_member_role(
    user_id: uuid.UUID, data: MemberRoleUpdate, member: MemberAdmin, session: SessionDep
) -> MemberRead:
    return await WorkspaceService(session).change_role(member, user_id, data.role)


@router.delete("/{workspace_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(user_id: uuid.UUID, member: Viewer, session: SessionDep) -> None:
    """Admins remove others; any member can remove themselves (leave)."""
    await WorkspaceService(session).remove_member(member, user_id)
