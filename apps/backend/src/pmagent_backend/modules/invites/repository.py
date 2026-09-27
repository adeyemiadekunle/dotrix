from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from .models import Invite, InviteKind


class InviteRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add(self, invite: Invite) -> None:
        self.session.add(invite)

    async def get(self, workspace_id: uuid.UUID, invite_id: uuid.UUID) -> Invite | None:
        return await self.session.scalar(
            select(Invite).where(Invite.workspace_id == workspace_id, Invite.id == invite_id)
        )

    async def get_by_hash(self, token_hash: str, *, for_update: bool = False) -> Invite | None:
        stmt = (
            select(Invite)
            .options(joinedload(Invite.workspace))
            .where(Invite.token_hash == token_hash)
        )
        if for_update:
            stmt = stmt.with_for_update(of=Invite)
        return await self.session.scalar(stmt)

    async def list_active(self, workspace_id: uuid.UUID, now: datetime) -> list[Invite]:
        result = await self.session.scalars(
            select(Invite)
            .where(
                Invite.workspace_id == workspace_id,
                Invite.revoked_at.is_(None),
                Invite.expires_at > now,
                or_(
                    (Invite.kind == InviteKind.EMAIL) & Invite.accepted_at.is_(None),
                    (Invite.kind == InviteKind.LINK)
                    & (Invite.max_uses.is_(None) | (Invite.use_count < Invite.max_uses)),
                ),
            )
            .order_by(Invite.created_at.desc())
        )
        return list(result)

    async def revoke_pending_for_email(
        self, workspace_id: uuid.UUID, email: str, now: datetime
    ) -> None:
        """Re-inviting an address replaces its earlier invite."""
        await self.session.execute(
            update(Invite)
            .where(
                Invite.workspace_id == workspace_id,
                Invite.email == email,
                Invite.accepted_at.is_(None),
                Invite.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )

    async def delete_stale(self, before: datetime) -> int:
        """Cleanup, across workspaces (deleting only): invites that expired, were revoked, or
        were accepted before `before`. The audit log keeps the history."""
        result = await self.session.execute(
            delete(Invite).where(
                or_(Invite.expires_at < before, Invite.revoked_at < before, Invite.accepted_at < before)
            )
        )
        return result.rowcount
