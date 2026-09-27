from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from pmagent_backend.modules.auth.schemas import Email
from pmagent_backend.modules.workspaces.models import Role, WorkspaceKind

from .models import OrgRole

OrgName = Field(min_length=1, max_length=100)


class OrgCreate(BaseModel):
    name: str = OrgName


class OrgUpdate(BaseModel):
    name: str = OrgName


class OrgRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    created_at: datetime


class OrgWithRole(OrgRead):
    role: OrgRole


class OrgMemberRead(BaseModel):
    user_id: uuid.UUID
    email: str
    display_name: str
    role: OrgRole
    joined_at: datetime


class OrgMemberAdd(BaseModel):
    email: Email
    role: OrgRole = OrgRole.MEMBER


class OrgMemberRoleUpdate(BaseModel):
    role: OrgRole


class OrgWorkspaceRead(BaseModel):
    """What an organisation sees of a workspace: its name and size, never its content."""

    id: uuid.UUID
    name: str
    slug: str
    kind: WorkspaceKind
    created_at: datetime
    members: int
    projects: int
    your_role: Role | None = Field(description="Your role in the workspace, or null if you're not in it")


class OrgWorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    kind: Literal[WorkspaceKind.TEAM, WorkspaceKind.BUSINESS] = WorkspaceKind.BUSINESS
    owner_user_id: uuid.UUID | None = Field(
        default=None, description="Who owns the new workspace (an org member). Defaults to you."
    )


class AttachWorkspace(BaseModel):
    workspace_id: uuid.UUID


# Owners are made in the workspace (at creation or by transfer), not placed by the organisation.
PlaceableRole = Literal[Role.ADMIN, Role.MEMBER, Role.GUEST]


class WorkspacePlacement(BaseModel):
    role: PlaceableRole = Role.MEMBER
