from __future__ import annotations

import uuid
from datetime import datetime
from types import SimpleNamespace
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .models import Role, WorkspaceKind
from .permissions import MEMBER_GRANTABLE, Permission, effective_permissions, granted_to_members

WorkspaceName = Field(min_length=1, max_length=100)


class WorkspaceCreate(BaseModel):
    name: str = WorkspaceName
    # Personal workspaces are created automatically at sign-up, one per user; a new one is an
    # organisation.
    kind: Literal[WorkspaceKind.ORGANIZATION] = WorkspaceKind.ORGANIZATION


class WorkspaceUpdate(BaseModel):
    """Only the fields you send change."""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    member_permissions: list[Permission] | None = Field(
        default=None,
        description="What members may do beyond chatting, brainstorming, and working the board: any of "
        "`knowledge:write` (edit documents), `agents:approve` (approve agent changes), `agents:code` "
        "(instruct the coding agent). Empty: owners and admins only.",
    )

    @field_validator("member_permissions")
    @classmethod
    def _grantable(cls, value: list[Permission] | None) -> list[Permission] | None:
        if value is None:
            return None
        refused = [p.value for p in value if p not in MEMBER_GRANTABLE]
        if refused:
            raise ValueError(f"Members can't be granted: {', '.join(refused)}")
        return sorted(set(value), key=list(Permission).index)


class WorkspaceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    kind: WorkspaceKind = Field(description="personal (just you) or organization (a team that invites people)")
    created_at: datetime
    member_permissions: list[Permission] = Field(
        default_factory=list, description="What this workspace lets members do beyond the defaults"
    )

    @field_validator("member_permissions", mode="before")
    @classmethod
    def _known(cls, value: object) -> object:
        return sorted(granted_to_members(SimpleNamespace(member_permissions=value)), key=list(Permission).index)


class WorkspaceWithRole(WorkspaceRead):
    role: Role
    permissions: list[Permission] = Field(
        default_factory=list,
        description="What you can do here: your role's permissions plus what the workspace grants members",
    )

    @classmethod
    def of(cls, workspace: object, role: Role) -> WorkspaceWithRole:
        mine = effective_permissions(SimpleNamespace(role=role, workspace=workspace))
        return cls(
            **WorkspaceRead.model_validate(workspace).model_dump(),
            role=role,
            permissions=mine,
        )


class MemberRead(BaseModel):
    user_id: uuid.UUID
    email: str
    display_name: str
    title: str | None = Field(description="What they do")
    avatar_updated_at: datetime | None = Field(description="When their photo last changed; null without one")
    role: Role
    joined_at: datetime
    sees_all_projects: bool = Field(description="Owners and admins see every project")
    project_ids: list[uuid.UUID] = Field(
        description="The projects they see, among those you see (restricted ones only if they were added)"
    )


class MemberRoleUpdate(BaseModel):
    role: Role


class OwnershipTransfer(BaseModel):
    user_id: uuid.UUID


class OrganizationConversion(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100, description="A new name, e.g. the team's")
