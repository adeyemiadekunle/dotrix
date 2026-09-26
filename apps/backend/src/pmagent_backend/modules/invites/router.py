"""Invites by email or link; accept; revoke (FR-4)."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from pmagent_backend.api.deps import (
    CurrentUser,
    EmailDep,
    SessionDep,
    SettingsDep,
    require_permission,
)
from pmagent_backend.modules.workspaces.models import Membership
from pmagent_backend.modules.workspaces.permissions import Permission
from pmagent_backend.modules.workspaces.schemas import WorkspaceWithRole

from .schemas import (
    AcceptInvite,
    EmailInviteCreate,
    InvitePreview,
    InviteRead,
    LinkInviteCreate,
    LinkInviteCreated,
)
from .service import InviteService


def get_invite_service(session: SessionDep, settings: SettingsDep, email: EmailDep) -> InviteService:
    return InviteService(session, settings, email)


Invites = Annotated[InviteService, Depends(get_invite_service)]
MemberAdmin = Annotated[Membership, Depends(require_permission(Permission.MANAGE_MEMBERS))]

# Managed per workspace: /v1/workspaces/{workspace_id}/invites
workspace_router = APIRouter(prefix="/workspaces/{workspace_id}/invites", tags=["invites"])
# Used by the invitee: /v1/invites/...
router = APIRouter(prefix="/invites", tags=["invites"])


@workspace_router.get("")
async def list_invites(member: MemberAdmin, invites: Invites) -> list[InviteRead]:
    return await invites.list_active(member.workspace_id)


@workspace_router.post("", status_code=status.HTTP_201_CREATED)
async def invite_by_email(
    data: EmailInviteCreate, member: MemberAdmin, user: CurrentUser, invites: Invites
) -> InviteRead:
    return await invites.invite_by_email(member, user, data)


@workspace_router.post("/links", status_code=status.HTTP_201_CREATED)
async def create_invite_link(
    data: LinkInviteCreate, member: MemberAdmin, user: CurrentUser, invites: Invites
) -> LinkInviteCreated:
    return await invites.create_link(member, user, data)


@workspace_router.delete("/{invite_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_invite(invite_id: uuid.UUID, member: MemberAdmin, invites: Invites) -> None:
    await invites.revoke(member.workspace_id, invite_id)


@router.post("/preview")
async def preview_invite(data: AcceptInvite, invites: Invites) -> InvitePreview:
    """No sign-in needed: the accept page shows this before sign-in or sign-up."""
    return await invites.preview(data.token)


@router.post("/accept")
async def accept_invite(data: AcceptInvite, user: CurrentUser, invites: Invites) -> WorkspaceWithRole:
    return await invites.accept(user, data.token)
