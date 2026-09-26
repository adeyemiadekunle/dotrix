from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pmagent_backend.modules.knowledge.models import AuthorType

from .models import AuditEvent
from .schemas import AuditEventRead


class AuditLog:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def record(
        self,
        *,
        workspace_id: uuid.UUID,
        action: str,
        actor_type: AuthorType,
        project_id: uuid.UUID | None = None,
        target: str | None = None,
        actor_user_id: uuid.UUID | None = None,
        agent: str | None = None,
        instructed_by_id: uuid.UUID | None = None,
        approved_by_id: uuid.UUID | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Add an event to the current transaction; it commits with the change it records."""
        self.session.add(
            AuditEvent(
                workspace_id=workspace_id,
                project_id=project_id,
                action=action,
                target=target,
                actor_type=actor_type,
                actor_user_id=actor_user_id,
                agent=agent,
                instructed_by_id=instructed_by_id,
                approved_by_id=approved_by_id,
                details=details or {},
                created_at=datetime.now(UTC),
            )
        )

    async def list(
        self,
        workspace_id: uuid.UUID,
        *,
        project_id: uuid.UUID | None = None,
        action: str | None = None,
        before: datetime | None = None,
        limit: int = 50,
    ) -> list[AuditEventRead]:
        stmt = select(AuditEvent).where(AuditEvent.workspace_id == workspace_id)
        if project_id is not None:
            stmt = stmt.where(AuditEvent.project_id == project_id)
        if action is not None:
            stmt = stmt.where(AuditEvent.action == action)
        if before is not None:
            stmt = stmt.where(AuditEvent.created_at < before)
        stmt = stmt.order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc()).limit(limit)
        return [AuditEventRead.model_validate(e) for e in await self.session.scalars(stmt)]
