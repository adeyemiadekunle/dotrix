from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .models import ActionToken, ActionTokenPurpose, RefreshToken, User


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add(self, user: User) -> None:
        self.session.add(user)

    async def get(self, user_id: uuid.UUID) -> User | None:
        return await self.session.get(User, user_id)

    async def get_by_email(self, email: str) -> User | None:
        return await self.session.scalar(select(User).where(User.email == email))


class RefreshTokenRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add(self, token: RefreshToken) -> None:
        self.session.add(token)

    async def get_by_hash_for_update(self, token_hash: str) -> RefreshToken | None:
        # Locked so two concurrent refreshes with the same token can't both rotate it.
        return await self.session.scalar(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash).with_for_update()
        )

    async def revoke_family(self, family_id: uuid.UUID, now: datetime) -> None:
        await self.session.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )

    async def revoke_all_for_user(self, user_id: uuid.UUID, now: datetime) -> None:
        await self.session.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )


class ActionTokenRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add(self, token: ActionToken) -> None:
        self.session.add(token)

    async def get_by_hash_for_update(
        self, token_hash: str, purpose: ActionTokenPurpose
    ) -> ActionToken | None:
        return await self.session.scalar(
            select(ActionToken)
            .where(ActionToken.token_hash == token_hash, ActionToken.purpose == purpose)
            .with_for_update()
        )

    async def invalidate(self, user_id: uuid.UUID, purpose: ActionTokenPurpose, now: datetime) -> None:
        """Mark outstanding tokens used, so only the newest emailed link works."""
        await self.session.execute(
            update(ActionToken)
            .where(
                ActionToken.user_id == user_id,
                ActionToken.purpose == purpose,
                ActionToken.used_at.is_(None),
            )
            .values(used_at=now)
        )
