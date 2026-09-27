"""Role → permission matrix from the PRD ("Roles and permissions").

Routes declare the permission they need (`require_permission(...)`); nothing
checks roles directly. Rows the PRD marks "configurable" for Member use the
defaults below until per-workspace overrides exist.
"""
from __future__ import annotations

import enum

from .models import Role


class Permission(enum.StrEnum):
    VIEW = "workspace:view"  # projects, board, briefings
    CHAT = "agents:chat"  # Chat Mode
    EDIT_ISSUES = "issues:write"
    EDIT_KNOWLEDGE = "knowledge:write"  # edit .pmagent/ files directly (agent-rules: MANAGE_WORKSPACE)
    APPROVE_ACTIONS = "agents:approve"  # instruct Action Mode, approve writes
    INSTRUCT_CODING_AGENT = "agents:code"
    # Project setup: create projects, add their external docs, draft the architecture.
    MANAGE_PROJECTS = "projects:manage"
    MANAGE_WORKSPACE = "workspace:manage"  # rename, settings
    MANAGE_MEMBERS = "members:manage"  # invite, remove, change roles
    MANAGE_BILLING = "workspace:billing"  # billing, plan, delete workspace


_ALL = frozenset(Permission)

ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.OWNER: _ALL,
    Role.ADMIN: _ALL - {Permission.MANAGE_BILLING},
    Role.MEMBER: frozenset(
        {
            Permission.VIEW,
            Permission.CHAT,
            Permission.EDIT_ISSUES,
            Permission.EDIT_KNOWLEDGE,
            Permission.APPROVE_ACTIONS,  # PRD: ✓ (configurable)
            # MANAGE_PROJECTS: PRD "configurable"; off, so connecting a repo on a member's
            # machine links to the owner's project instead of creating another one.
            # INSTRUCT_CODING_AGENT: PRD: configurable; off by default
        }
    ),
    # Guests see only projects they're invited to; project scoping lands with projects.
    Role.GUEST: frozenset({Permission.VIEW}),
}


def has_permission(role: Role, permission: Permission) -> bool:
    return permission in ROLE_PERMISSIONS[role]
