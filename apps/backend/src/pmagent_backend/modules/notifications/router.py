"""Your notifications in a workspace: approvals and checkpoints waiting, assignments, findings."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from pmagent_backend.api.deps import CurrentUser, SessionDep, require_permission
from pmagent_backend.core.openapi import errors
from pmagent_backend.modules.workspaces.models import Membership
from pmagent_backend.modules.workspaces.permissions import Permission

from .models import NotificationKind
from .schemas import MarkRead, NotificationCounts, NotificationRead, NotificationSettings
from .service import NotificationService

router = APIRouter(
    prefix="/workspaces/{workspace_id}/notifications", tags=["notifications"], responses=errors(401, 403, 404)
)

Member = Annotated[Membership, Depends(require_permission(Permission.VIEW))]


@router.get("", responses=errors(422))
async def list_notifications(
    member: Member,
    session: SessionDep,
    kind: NotificationKind | None = Query(default=None, description="Only this kind"),
    unread: bool = Query(default=False, description="Only ones you haven't marked read"),
    before: datetime | None = Query(default=None, description="Only older than this (the last `created_at` you have)"),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[NotificationRead]:
    """Your notifications in this workspace, newest first, about projects you can still see.
    Approvals and checkpoints say whether they've been decided since (`resolved`)."""
    return await NotificationService(session).list(member, kind=kind, unread=unread, before=before, limit=limit)


@router.get("/counts")
async def get_notification_counts(member: Member, session: SessionDep) -> NotificationCounts:
    """How many notifications still need you, in total and by kind: approvals and checkpoints
    until they're decided (read or not), the others until you've read them."""
    return await NotificationService(session).counts(member)


@router.post("/read", responses=errors(422))
async def mark_notifications_read(member: Member, session: SessionDep, data: MarkRead) -> NotificationCounts:
    """Mark notifications read: the ones in `ids`, or `all` (of one `kind`, if given). Ids that
    aren't yours are ignored. Returns the new counts."""
    return await NotificationService(session).mark_read(member, data)


settings_router = APIRouter(prefix="/me/notification-settings", tags=["notifications"], responses=errors(401))


@settings_router.get("")
async def get_notification_settings(user: CurrentUser, session: SessionDep) -> NotificationSettings:
    """Which notifications you get, in every workspace you're in."""
    return await NotificationService(session).settings(user)


@settings_router.put("", responses=errors(422))
async def update_notification_settings(
    data: NotificationSettings, user: CurrentUser, session: SessionDep
) -> NotificationSettings:
    """Turn mentions, assignments, or findings off or on. Turned-off kinds stop showing and
    counting at once, earlier ones included. Approvals and checkpoints always come through."""
    return await NotificationService(session).update_settings(user, data)
