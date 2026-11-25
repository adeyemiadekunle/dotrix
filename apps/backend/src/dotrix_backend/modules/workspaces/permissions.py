"""Role → permission matrix from the PRD ("Roles and permissions").

Routes declare the permission they need (`require_permission(...)`); nothing
checks roles directly. Members chat, brainstorm, and work the board; changing the project's
documents (directly or by approving an agent's change) is for owners and admins. A workspace
can grant members some of that back (`Workspace.member_permissions`): the PRD's
"configurable" rows. Check with `can(membership, permission)`, which applies them.
"""
from __future__ import annotations

import enum
import uuid
from typing import Any

from .models import Role, WorkspaceKind


class Permission(enum.StrEnum):
    VIEW = "workspace:view"  # projects, board, briefings
    CHAT = "agents:chat"  # Chat Mode
    EDIT_ISSUES = "issues:write"
    EDIT_KNOWLEDGE = "knowledge:write"  # edit .dotrix/ files directly (agent-rules: MANAGE_WORKSPACE)
    APPROVE_ACTIONS = "agents:approve"  # instruct Action Mode, approve writes
    INSTRUCT_CODING_AGENT = "agents:code"
    # Project setup: create projects, add their external docs, draft the architecture.
    MANAGE_PROJECTS = "projects:manage"
    MANAGE_WORKSPACE = "workspace:manage"  # rename, settings
    MANAGE_MEMBERS = "members:manage"  # invite, remove, change roles
    MANAGE_BILLING = "workspace:billing"  # billing, plan, delete workspace
    VIEW_USAGE = "usage:view"  # agent runs' token counts and model (spend)


_ALL = frozenset(Permission)

ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.OWNER: _ALL,
    Role.ADMIN: _ALL - {Permission.MANAGE_BILLING},
    Role.MEMBER: frozenset(
        {
            Permission.VIEW,
            Permission.CHAT,  # chat and brainstorm; a change they ask for waits for an owner or admin
            Permission.EDIT_ISSUES,
            # Team Members can use Codes and approve their runs by default.
            # MANAGE_PROJECTS: off, so connecting a repo on a member's machine links to the
            # owner's project instead of creating another one.
        }
    ),
    # Guests see the workspace, not its projects.
    Role.GUEST: frozenset({Permission.VIEW}),
}


# What a workspace may grant its members on top of the defaults.
MEMBER_GRANTABLE = frozenset(
    {
        Permission.APPROVE_ACTIONS,
        Permission.INSTRUCT_CODING_AGENT,
    }
)


def has_permission(role: Role, permission: Permission) -> bool:
    """The role's defaults only. Prefer `can`, which also applies the workspace's grants."""
    return permission in ROLE_PERMISSIONS[role]


def granted_to_members(workspace: Any) -> frozenset[Permission]:
    values = getattr(workspace, "member_permissions", None) or []
    return frozenset(Permission(v) for v in values if v in {p.value for p in MEMBER_GRANTABLE})


def can(membership: Any, permission: Permission) -> bool:
    """Whether this membership allows `permission`, counting what the workspace grants its members."""
    if has_permission(membership.role, permission):
        return True
    if membership.role is not Role.MEMBER:
        return False
    workspace = membership.workspace
    if workspace.kind is WorkspaceKind.TEAM and permission in (Permission.INSTRUCT_CODING_AGENT, Permission.APPROVE_ACTIONS):
        return True
    return permission in granted_to_members(workspace)


def can_approve_others(membership: Any) -> bool:
    """Cross-user approvals require the role's permission or explicit delegation."""
    if has_permission(membership.role, Permission.APPROVE_ACTIONS):
        return True
    return membership.role is Role.MEMBER and Permission.APPROVE_ACTIONS in granted_to_members(membership.workspace)


def can_approve_run(membership: Any, requester_id: uuid.UUID | None) -> bool:
    return can_approve_others(membership) or (
        requester_id == membership.user_id and can(membership, Permission.APPROVE_ACTIONS)
    )


def can_manage_issues(membership: Any) -> bool:
    """Issue creation and assignment are reserved for Owners and Admins."""
    return membership.role in (Role.OWNER, Role.ADMIN)


def effective_permissions(membership: Any) -> list[Permission]:
    return [p for p in Permission if can(membership, p)]
