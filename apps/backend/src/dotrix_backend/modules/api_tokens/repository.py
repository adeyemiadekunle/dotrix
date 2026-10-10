from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import ApiToken, DeviceAuthorization, DeviceStatus


class ApiTokenRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add(self, token: ApiToken) -> None:
        self.session.add(token)

    async def get_by_hash(self, token_hash: str) -> ApiToken | None:
        return await self.session.scalar(select(ApiToken).where(ApiToken.token_hash == token_hash))

    async def get_for_user(self, user_id: uuid.UUID, token_id: uuid.UUID) -> ApiToken | None:
        return await self.session.scalar(
            select(ApiToken).where(ApiToken.user_id == user_id, ApiToken.id == token_id)
        )

    async def list_for_user(self, user_id: uuid.UUID) -> list[ApiToken]:
        result = await self.session.scalars(
            select(ApiToken)
            .where(ApiToken.user_id == user_id, ApiToken.revoked_at.is_(None))
            .order_by(ApiToken.created_at.desc())
        )
        return list(result)


class DeviceAuthorizationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add(self, device: DeviceAuthorization) -> None:
        self.session.add(device)

    async def get_pending_by_user_code(
        self, user_code: str, *, for_update: bool = False
    ) -> DeviceAuthorization | None:
        stmt = select(DeviceAuthorization).where(
            DeviceAuthorization.user_code == user_code,
            DeviceAuthorization.status == DeviceStatus.PENDING,
        )
        if for_update:
            stmt = stmt.with_for_update()
        return await self.session.scalar(stmt)

    async def get_by_device_code_hash_for_update(self, code_hash: str) -> DeviceAuthorization | None:
        return await self.session.scalar(
            select(DeviceAuthorization)
            .where(DeviceAuthorization.device_code_hash == code_hash)
            .with_for_update()
        )

    async def delete_stale(self, before: datetime) -> int:
        """Cleanup: sign-in attempts that expired before `before`, whatever their outcome
        (a device that got its token has an API token row of its own)."""
        result = await self.session.execute(delete(DeviceAuthorization).where(DeviceAuthorization.expires_at < before))
        return result.rowcount
