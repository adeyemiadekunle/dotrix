from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from dotrix_backend.modules.auth.schemas import Email
from dotrix_backend.modules.workspaces.models import Role, WorkspaceKind

from .models import InviteKind

# Owners are made by changing roles or transferring ownership, never by invite.
InvitableRole = Literal[Role.ADMIN, Role.MEMBER, Role.GUEST]
# A shared link can end up anywhere, so it can't grant admin.
LinkRole = Literal[Role.MEMBER, Role.GUEST]


class EmailInviteCreate(BaseModel):
    email: Email
    role: InvitableRole = Role.MEMBER


class LinkInviteCreate(BaseModel):
    role: LinkRole = Role.MEMBER
    max_uses: int | None = Field(default=None, ge=1, le=1000)
    expires_in_days: int = Field(default=7, ge=1, le=30)


class InviteRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: InviteKind
    email: str | None
    role: Role
    created_at: datetime
    expires_at: datetime
    max_uses: int | None
    use_count: int


class LinkInviteCreated(InviteRead):
    """Returned once, at creation: the only time the link's token is visible."""

    url: str


class InvitePreview(BaseModel):
    """What the accept page shows before the user signs in or accepts."""

    workspace_name: str
    workspace_kind: WorkspaceKind
    role: Role
    invited_by: str | None
    email: str | None  # for email invites, so the page can say who it's for
    expires_at: datetime


class AcceptInvite(BaseModel):
    token: str = Field(max_length=256)

