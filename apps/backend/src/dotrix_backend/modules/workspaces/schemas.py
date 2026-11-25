from __future__ import annotations

import uuid
from datetime import datetime
from types import SimpleNamespace
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationInfo,
    field_validator,
    model_validator,
)

from .approval_modes import ApprovalMode, cap_of, lowest
from .models import Role, WorkspaceKind
from .permissions import MEMBER_GRANTABLE, Permission, effective_permissions, granted_to_members

WorkspaceName = Field(min_length=1, max_length=100)


class WorkspaceCreate(BaseModel):
    name: str = WorkspaceName
    # Personal workspaces are created automatically at sign-up, one per user; a new one is an
    # team workspace.
    kind: Literal[WorkspaceKind.TEAM] = WorkspaceKind.TEAM


class FirstWorkspaceChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["personal", "team"] = "personal"
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)] | None = None

    @model_validator(mode="after")
    def team_name(self):
        if self.kind == "team" and not self.name:
            raise ValueError("Give the team a name")
        if self.kind == "personal" and self.name is not None:
            raise ValueError("Use Team setup to create or rename a Team workspace")
        return self


class WorkspaceUpdate(BaseModel):
    """Only the fields you send change."""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    member_permissions: list[Permission] | None = Field(
        default=None,
        description="Additional Member grants. `agents:approve` delegates approval of eligible work "
        "requested by other people. `agents:code` is also accepted for existing configurations.",
    )
    unattended_paused: bool | None = Field(
        default=None,
        description="Pause every agent's changes without approval (owners and admins); only owners resume them",
    )
    approval_mode_cap: ApprovalMode | None = Field(
        default=None,
        description="The highest approval mode people may work in: `manual` (every change waits for a yes), "
        "`accept_edits` (what a person asks for goes through, and coding starts at once), `auto` (the same, and "
        "checkpoints don't pause). Owners raise it; owners and admins lower it",
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
    kind: WorkspaceKind = Field(description="personal (just you) or team (a shared workspace)")
    created_at: datetime
    member_permissions: list[Permission] = Field(
        default_factory=list, description="What this workspace lets members do beyond the defaults"
    )
    unattended_paused: bool = Field(
        default=False, description="Agents' standing rules to act without approval are paused: every change asks"
    )
    approval_mode_cap: ApprovalMode = Field(
        default=ApprovalMode.MANUAL,
        description="The highest approval mode people may work in here (Manual while changes without approval "
        "are paused)",
    )
    default_approval_mode: ApprovalMode = Field(
        default=ApprovalMode.MANUAL, validate_default=True,
        description="What a new conversation or coding session starts on in the app: Accept edits in a personal "
        "workspace, Manual in a Team workspace (never above the cap)",
    )

    @field_validator("approval_mode_cap", mode="before")
    @classmethod
    def _cap(cls, value: object, info: ValidationInfo) -> ApprovalMode:
        # Read from the workspace: its owners' choice (or null), turned into the cap in effect.
        return cap_of(SimpleNamespace(
            kind=info.data.get("kind"), unattended_paused=info.data.get("unattended_paused"), approval_mode_cap=value,
        ))

    @field_validator("default_approval_mode", mode="before")
    @classmethod
    def _default(cls, value: object, info: ValidationInfo) -> ApprovalMode:
        cap = info.data.get("approval_mode_cap", ApprovalMode.MANUAL)
        wanted = ApprovalMode.ACCEPT_EDITS if info.data.get("kind") is WorkspaceKind.PERSONAL else ApprovalMode.MANUAL
        return lowest(wanted, cap)

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


class StorageRead(BaseModel):
    used_bytes: int = Field(description="Document originals plus task attachments")
    limit_bytes: int | None = Field(description="Null: no limit")
    documents_bytes: int = Field(description="Uploaded document originals")
    attachments_bytes: int = Field(description="Task attachments")


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
