"""Invites by email or link; accept; revoke (FR-4)."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from dotrix_backend.api.deps import (
    CurrentUser,
    EmailDep,
    SessionDep,
    SettingsDep,
    require_permission,
)
from dotrix_backend.core.openapi import errors
from dotrix_backend.modules.workspaces.models import Membership
from dotrix_backend.modules.workspaces.permissions import Permission
from dotrix_backend.modules.workspaces.schemas import WorkspaceWithRole

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
workspace_router = APIRouter(
    prefix="/workspaces/{workspace_id}/invites",
    tags=["invites"],
    responses=errors(401, 403, 404),
)
# Used by the invitee: /v1/invites/...
router = APIRouter(prefix="/invites", tags=["invites"])


@workspace_router.get("")
async def list_invites(member: MemberAdmin, invites: Invites) -> list[InviteRead]:
    """Pending invites: not accepted, revoked, expired, or used up. Owners and admins."""
    return await invites.list_active(member.workspace_id)


@workspace_router.post("", status_code=status.HTTP_201_CREATED, responses=errors(409, 422))
async def invite_by_email(
    data: EmailInviteCreate, member: MemberAdmin, user: CurrentUser, invites: Invites
) -> InviteRead:
    """Email an invite (valid 7 days, single use, only for that address). Inviting the same
    address again replaces the earlier invite. Owners and admins, and only in an organisation
    (409 `invites_need_organization` in a personal workspace)."""
    return await invites.invite_by_email(member, user, data)


@workspace_router.post(
    "/links", status_code=status.HTTP_201_CREATED, responses=errors(409, 422)
)
async def create_invite_link(
    data: LinkInviteCreate, member: MemberAdmin, user: CurrentUser, invites: Invites
) -> LinkInviteCreated:
    """Create a shareable invite link (member or guest only). The `url` is returned only
    here. Owners and admins, and only in an organisation (409 `invites_need_organization` in
    a personal workspace)."""
    return await invites.create_link(member, user, data)


@workspace_router.delete("/{invite_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_invite(invite_id: uuid.UUID, member: MemberAdmin, invites: Invites) -> None:
    """Revoke an email invite or link. Owners and admins."""
    await invites.revoke(member, invite_id)


@router.post("/preview", responses=errors(400, 422))
async def preview_invite(data: AcceptInvite, invites: Invites) -> InvitePreview:
    """No sign-in needed: the accept page shows this before sign-in or sign-up."""
    return await invites.preview(data.token)


@router.post("/accept", responses=errors(400, 401, 403, 422))
async def accept_invite(data: AcceptInvite, user: CurrentUser, invites: Invites) -> WorkspaceWithRole:
    """Join the workspace. Email invites must be accepted by the invited address (403
    otherwise). If you're already a member, your role doesn't change."""
    return await invites.accept(user, data.token)
