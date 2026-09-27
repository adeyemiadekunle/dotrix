from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .models import Role, WorkspaceKind

WorkspaceName = Field(min_length=1, max_length=100)


class WorkspaceCreate(BaseModel):
    name: str = WorkspaceName
    # Personal workspaces are created automatically at sign-up, one per user.
    kind: Literal[WorkspaceKind.TEAM, WorkspaceKind.BUSINESS] = WorkspaceKind.TEAM


class WorkspaceUpdate(BaseModel):
    name: str = WorkspaceName


class WorkspaceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    kind: WorkspaceKind
    organization_id: uuid.UUID | None = None
    created_at: datetime


class WorkspaceWithRole(WorkspaceRead):
    role: Role
    via_organization: bool = Field(
        default=False, description="You have this role because you own the workspace's organisation"
    )

    @classmethod
    def of(cls, workspace: object, role: Role, via_organization: bool = False) -> WorkspaceWithRole:
        return cls(
            **WorkspaceRead.model_validate(workspace).model_dump(), role=role, via_organization=via_organization
        )


class MemberRead(BaseModel):
    user_id: uuid.UUID
    email: str
    display_name: str
    role: Role
    joined_at: datetime


class MemberRoleUpdate(BaseModel):
    role: Role


class OwnershipTransfer(BaseModel):
    user_id: uuid.UUID
