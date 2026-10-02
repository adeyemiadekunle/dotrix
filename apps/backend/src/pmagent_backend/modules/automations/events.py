"""Recording what happened, for the automations that listen to it (handled by `run_automations`).

Callers record inside their own transaction, so an event exists exactly when what it describes
was committed. Nothing is written when no enabled automation in the project listens, so the
outbox stays empty for projects without automations.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Automation, AutomationEvent, AutomationEventRow


async def record_event(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    event: AutomationEvent,
    summary: str,
    details: dict[str, Any] | None = None,
) -> None:
    listening = await session.scalar(
        select(Automation.id).where(
            Automation.project_id == project_id,
            Automation.enabled.is_(True),
            Automation.events.any(event.value),
        ).limit(1)
    )
    if listening is None:
        return
    session.add(AutomationEventRow(
        workspace_id=workspace_id, project_id=project_id, event=event, summary=summary[:300],
        details=details or {}, created_at=datetime.now(UTC),
    ))
