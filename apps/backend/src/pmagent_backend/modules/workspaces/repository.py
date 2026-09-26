from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from pmagent_backend.modules.auth.models import User

from .models import Membership, Role, Workspace, WorkspaceKind


class WorkspaceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add(self, workspace: Workspace) -> None:
        self.session.add(workspace)

    async def list_for_user(self, user_id: uuid.UUID) -> list[tuple[Workspace, Role]]:
        rows = await self.session.execute(
            select(Workspace, Membership.role)
            .join(Membership, Membership.workspace_id == Workspace.id)
            .where(Membership.user_id == user_id)
            .order_by(Workspace.created_at)
        )
        return [(ws, role) for ws, role in rows.all()]

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
