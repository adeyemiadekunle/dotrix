import pytest

from pmagent_backend.modules.workspaces.models import Role
from pmagent_backend.modules.workspaces.permissions import Permission, has_permission

P = Permission

# Rows of the PRD "Roles and permissions" table: (permission, owner, admin, member, guest).
MATRIX = [
    (P.VIEW, True, True, True, True),
    (P.CHAT, True, True, True, False),
    (P.EDIT_ISSUES, True, True, True, False),
    (P.APPROVE_ACTIONS, True, True, True, False),
    (P.INSTRUCT_CODING_AGENT, True, True, False, False),
    (P.MANAGE_PROJECTS, True, True, True, False),
    (P.MANAGE_MEMBERS, True, True, False, False),
    (P.MANAGE_BILLING, True, False, False, False),
]


@pytest.mark.parametrize(("permission", "owner", "admin", "member", "guest"), MATRIX)
def test_role_matrix(permission: Permission, owner: bool, admin: bool, member: bool, guest: bool) -> None:
    expected = {Role.OWNER: owner, Role.ADMIN: admin, Role.MEMBER: member, Role.GUEST: guest}
    for role, allowed in expected.items():
        assert has_permission(role, permission) is allowed, (role, permission)


def test_every_permission_is_covered() -> None:
    assert {row[0] for row in MATRIX} | {P.MANAGE_WORKSPACE} == set(Permission)
