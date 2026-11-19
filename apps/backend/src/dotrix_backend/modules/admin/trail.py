"""The admin console's trail: an append-only record of admin sign-ins and changes.

`record` never commits: it joins the caller's unit of work, so an event exists exactly when
its change committed. Never pass a password, token, code or invite link."""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import AdminEvent, AdminUser


def record(
    session: AsyncSession,
    action: str,
    *,
    admin: AdminUser | None = None,
    actor_email: str | None = None,
    target_email: str | None = None,
    workspace: str | None = None,
    ip: str | None = None,
) -> None:
    session.add(
        AdminEvent(
            action=action,
            admin_user_id=admin.id if admin is not None else None,
            actor_email=actor_email if actor_email is not None else (admin.email if admin is not None else None),
            target_email=target_email,
            workspace=workspace,
            ip=ip,
            created_at=datetime.now(UTC),
        )
    )


async def page(
    session: AsyncSession, *, action: str | None = None, offset: int = 0, limit: int = 25
) -> tuple[list[AdminEvent], int]:
    query = select(AdminEvent)
    if action:
        escaped = action.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        query = query.where(AdminEvent.action.like(f"{escaped}%", escape="\\"))
    total = await session.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = await session.scalars(query.order_by(AdminEvent.created_at.desc(), AdminEvent.id.desc()).offset(offset).limit(limit))
    return list(rows.all()), total


async def delete_older(session: AsyncSession, cutoff: datetime) -> int:
    """Retention: drop events older than the cutoff. Returns how many."""
    result = await session.execute(delete(AdminEvent).where(AdminEvent.created_at < cutoff))
    return result.rowcount or 0  # type: ignore[attr-defined]
