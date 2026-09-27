"""What each organisation role may do. None of these grant access to a workspace's content:
that always needs membership of the workspace itself."""
from __future__ import annotations

import enum

from .models import OrgRole


class OrgPermission(enum.StrEnum):
    VIEW = "org:view"  # the organisation, its members, and your own workspaces in it
    MANAGE_PEOPLE = "org:people"  # add/remove org members; place them into org workspaces
    MANAGE_WORKSPACES = "org:workspaces"  # create, attach, detach workspaces; see all workspace names
    MANAGE_ORG = "org:manage"  # rename the organisation
    OWN = "org:own"  # billing, owners, deleting the organisation (later)


ORG_ROLE_PERMISSIONS: dict[OrgRole, frozenset[OrgPermission]] = {
    OrgRole.OWNER: frozenset(OrgPermission),
    OrgRole.ADMIN: frozenset(OrgPermission) - {OrgPermission.OWN},
    OrgRole.MEMBER: frozenset({OrgPermission.VIEW}),
}


def has_org_permission(role: OrgRole, permission: OrgPermission) -> bool:
    return permission in ORG_ROLE_PERMISSIONS[role]
