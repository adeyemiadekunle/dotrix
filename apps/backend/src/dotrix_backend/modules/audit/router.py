"""The workspace audit log (FR-5). Owners and admins."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from dotrix_backend.api.deps import SessionDep, require_permission
from dotrix_backend.core.openapi import errors
from dotrix_backend.modules.workspaces.models import Membership
from dotrix_backend.modules.workspaces.permissions import Permission

from .schemas import AuditEventRead
from .service import AuditLog

router = APIRouter(
    prefix="/workspaces/{workspace_id}/audit", tags=["audit"], responses=errors(401, 403, 404)
)

Admin = Annotated[Membership, Depends(require_permission(Permission.MANAGE_WORKSPACE))]


@router.get("", responses=errors(422))
async def list_audit_events(
    member: Admin,
    session: SessionDep,
    project_id: uuid.UUID | None = None,
    action: str | None = Query(default=None, description='e.g. "knowledge.write"'),
    before: datetime | None = Query(
        default=None, description="Page backwards: pass the last event's `created_at`"
    ),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[AuditEventRead]:
    """Newest first: every knowledge change, approval decision, and agent run, with who
    instructed and who approved it."""
    return await AuditLog(session).list(
        member.workspace_id, project_id=project_id, action=action, before=before, limit=limit
    )
