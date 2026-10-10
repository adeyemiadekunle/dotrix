import pytest

from dotrix_backend.modules.workspaces.models import Role
from dotrix_backend.modules.workspaces.permissions import Permission, has_permission

P = Permission

# Rows of the PRD "Roles and permissions" table: (permission, owner, admin, member, guest).
MATRIX = [
    (P.VIEW, True, True, True, True),
    (P.CHAT, True, True, True, False),
    (P.EDIT_ISSUES, True, True, True, False),
    (P.EDIT_KNOWLEDGE, True, True, False, False),  # members: grantable per workspace
    (P.APPROVE_ACTIONS, True, True, False, False),  # members: grantable per workspace
    (P.INSTRUCT_CODING_AGENT, True, True, False, False),
    (P.MANAGE_PROJECTS, True, True, False, False),  # setup: members only link
    (P.MANAGE_MEMBERS, True, True, False, False),
    (P.MANAGE_BILLING, True, False, False, False),
    (P.VIEW_USAGE, True, True, False, False),  # agent runs' token counts (spend)
    (P.CHOOSE_MODEL, True, True, False, False),  # members: grantable per workspace
]


@pytest.mark.parametrize(("permission", "owner", "admin", "member", "guest"), MATRIX)
def test_role_matrix(permission: Permission, owner: bool, admin: bool, member: bool, guest: bool) -> None:
    expected = {Role.OWNER: owner, Role.ADMIN: admin, Role.MEMBER: member, Role.GUEST: guest}
    for role, allowed in expected.items():
        assert has_permission(role, permission) is allowed, (role, permission)


def test_every_permission_is_covered() -> None:
    assert {row[0] for row in MATRIX} | {P.MANAGE_WORKSPACE} == set(Permission)
