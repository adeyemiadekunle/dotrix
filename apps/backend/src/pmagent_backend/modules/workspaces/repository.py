from __future__ import annotations

import uuid

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload
from sqlalchemy.orm.attributes import set_committed_value

from pmagent_backend.modules.auth.models import User
from pmagent_backend.modules.organizations.models import OrgMembership, OrgRole

from .models import Membership, Role, Workspace, WorkspaceKind


class WorkspaceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add(self, workspace: Workspace) -> None:
        self.session.add(workspace)

    async def list_for_user(self, user_id: uuid.UUID) -> list[tuple[Workspace, Role, bool]]:
        """(workspace, role, via_organization): workspaces you're in, plus every workspace of an
        organisation you own (as owner, via the organisation)."""
        rows = await self.session.execute(
            select(Workspace, Membership.role)
            .join(Membership, Membership.workspace_id == Workspace.id)
            .where(Membership.user_id == user_id)
            .order_by(Workspace.created_at)
        )
        mine = [(ws, role, False) for ws, role in rows.all()]
        seen = {ws.id for ws, _, _ in mine}
        owned = await self.session.scalars(
            select(Workspace)
            .join(OrgMembership, _org_owner(user_id))
            .order_by(Workspace.created_at)
        )
        return mine + [(ws, Role.OWNER, True) for ws in owned if ws.id not in seen]

    async def has_personal(self, user_id: uuid.UUID) -> bool:
        count = await self.session.scalar(
            select(func.count())
            .select_from(Workspace)
            .join(Membership, Membership.workspace_id == Workspace.id)
            .where(
                Membership.user_id == user_id,
                Membership.role == Role.OWNER,
                Workspace.kind == WorkspaceKind.PERSONAL,
            )
        )
        return bool(count)


class MembershipRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add(self, membership: Membership) -> None:
        self.session.add(membership)

    async def delete(self, membership: Membership) -> None:
        await self.session.delete(membership)

    async def get(
        self, workspace_id: uuid.UUID, user_id: uuid.UUID, *, for_update: bool = False
    ) -> Membership | None:
        stmt = (
            select(Membership)
            .options(joinedload(Membership.workspace))
            .where(Membership.workspace_id == workspace_id, Membership.user_id == user_id)
        )
        if for_update:
            stmt = stmt.with_for_update(of=Membership)
        return await self.session.scalar(stmt)

    async def effective(self, workspace_id: uuid.UUID, user_id: uuid.UUID) -> Membership | None:
        """Your access to a workspace: your membership, or, if you own the organisation that owns
        the workspace, an implicit owner membership (not stored; `via_organization` is True).
        Org admins and members get nothing here: they need a real membership."""
        member = await self.get(workspace_id, user_id)
        if member is not None:
            return member
        workspace = await self.session.scalar(
            select(Workspace).join(OrgMembership, _org_owner(user_id)).where(Workspace.id == workspace_id)
        )
        if workspace is None:
            return None
        implicit = Membership(workspace_id=workspace.id, user_id=user_id, role=Role.OWNER)
        set_committed_value(implicit, "workspace", workspace)  # not added to the session
        implicit.via_organization = True  # type: ignore[attr-defined]
        return implicit

    async def list_with_users(self, workspace_id: uuid.UUID) -> list[tuple[Membership, User]]:
        rows = await self.session.execute(
            select(Membership, User)
            .join(User, User.id == Membership.user_id)
            .where(Membership.workspace_id == workspace_id)
            .order_by(Membership.created_at)
        )
        return [(m, u) for m, u in rows.all()]

    async def lock_owners(self, workspace_id: uuid.UUID) -> list[Membership]:
        """Owner rows, locked, so concurrent demotions can't remove the last owner."""
        result = await self.session.scalars(
            select(Membership)
            .where(Membership.workspace_id == workspace_id, Membership.role == Role.OWNER)
            .with_for_update()
        )
        return list(result)


def _org_owner(user_id: uuid.UUID):  # noqa: ANN202 - a SQL join condition
    """Join condition: `user_id` owns the organisation that owns the workspace."""
    return and_(
        OrgMembership.organization_id == Workspace.organization_id,
        OrgMembership.user_id == user_id,
        OrgMembership.role == OrgRole.OWNER,
    )
