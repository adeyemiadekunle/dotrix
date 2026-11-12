"""Admin console accounts, created and recovered from the server's command line.

These functions never commit: the caller owns the unit of work."""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from dotrix_backend.core.errors import Conflict, NotFound, Unprocessable
from dotrix_backend.core.security import hash_password

from .models import AdminSession, AdminUser

MIN_PASSWORD_LENGTH = 12


async def create_admin(session: AsyncSession, *, email: str, name: str, password: str) -> AdminUser:
    email = email.strip().lower()
    if len(password) < MIN_PASSWORD_LENGTH:
        raise Unprocessable(f"The password must be at least {MIN_PASSWORD_LENGTH} characters")
    if await session.scalar(select(AdminUser.id).where(AdminUser.email == email)) is not None:
        raise Conflict("An admin with this email already exists")
    admin = AdminUser(email=email, name=name, password_hash=hash_password(password), created_at=datetime.now(UTC))
    session.add(admin)
    await session.flush()
    return admin


async def reset_admin_password(session: AsyncSession, *, email: str, password: str) -> AdminUser:
    """Set a new password and sign the admin out everywhere."""
    if len(password) < MIN_PASSWORD_LENGTH:
        raise Unprocessable(f"The password must be at least {MIN_PASSWORD_LENGTH} characters")
    admin = await session.scalar(select(AdminUser).where(AdminUser.email == email.strip().lower()))
    if admin is None:
        raise NotFound("No admin with this email")
    admin.password_hash = hash_password(password)
    await session.execute(
        update(AdminSession)
        .where(AdminSession.admin_user_id == admin.id, AdminSession.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
    await session.flush()
    return admin


async def list_admins(session: AsyncSession) -> list[AdminUser]:
    return list((await session.scalars(select(AdminUser).order_by(AdminUser.created_at))).all())
