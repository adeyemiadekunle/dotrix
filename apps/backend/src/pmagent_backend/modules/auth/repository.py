from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .models import ActionToken, ActionTokenPurpose, EmailSignup, OAuthAccount, RefreshToken, User


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add(self, user: User) -> None:
        self.session.add(user)

    async def get(self, user_id: uuid.UUID) -> User | None:
        return await self.session.get(User, user_id)

    async def get_by_email(self, email: str) -> User | None:
        return await self.session.scalar(select(User).where(User.email == email))


class OAuthAccountRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add(self, account: OAuthAccount) -> None:
        self.session.add(account)

    async def get(self, provider: str, provider_user_id: str) -> OAuthAccount | None:
        return await self.session.scalar(
            select(OAuthAccount).where(
                OAuthAccount.provider == provider, OAuthAccount.provider_user_id == provider_user_id
            )
        )


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

    async def delete_stale(self, before: datetime) -> int:
        """Cleanup: tokens that expired before `before`. (Revoked tokens are kept until then,
        so presenting one still revokes its whole family.)"""
        result = await self.session.execute(delete(RefreshToken).where(RefreshToken.expires_at < before))
        return result.rowcount


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

    async def delete_stale(self, before: datetime) -> int:
        """Cleanup: email-link tokens used or expired before `before`."""
        result = await self.session.execute(
            delete(ActionToken).where(or_(ActionToken.expires_at < before, ActionToken.used_at < before))
        )
        return result.rowcount


class EmailSignupRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add(self, signup: EmailSignup) -> None:
        self.session.add(signup)

    async def get_by_hash_for_update(self, token_hash: str) -> EmailSignup | None:
        return await self.session.scalar(
            select(EmailSignup).where(EmailSignup.token_hash == token_hash).with_for_update()
        )

    async def get_by_hash(self, token_hash: str) -> EmailSignup | None:
        return await self.session.scalar(select(EmailSignup).where(EmailSignup.token_hash == token_hash))

    async def invalidate(self, email: str, now: datetime) -> None:
        """Mark outstanding links for this address used, so only the newest works."""
        await self.session.execute(
            update(EmailSignup)
            .where(EmailSignup.email == email, EmailSignup.used_at.is_(None))
            .values(used_at=now)
        )

    async def delete_stale(self, before: datetime) -> int:
        """Cleanup: sign-up links used or expired before `before`."""
        result = await self.session.execute(
            delete(EmailSignup).where(or_(EmailSignup.expires_at < before, EmailSignup.used_at < before))
        )
        return result.rowcount
