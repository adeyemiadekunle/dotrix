"""Workspace observability (Admin): health overview and the unified run history."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query

from dotrix_backend.api.deps import SessionDep, SettingsDep, require_permission
from dotrix_backend.core.openapi import errors
from dotrix_backend.modules.workspaces.models import Membership
from dotrix_backend.modules.workspaces.permissions import Permission

from .schemas import ObservedRun, ObserveOverview
from .service import ObserveService

router = APIRouter(
    prefix="/workspaces/{workspace_id}/observe", tags=["observe"], responses=errors(401, 403, 404)
)

Admin = Annotated[Membership, Depends(require_permission(Permission.VIEW_USAGE))]


def get_observe_service(session: SessionDep, settings: SettingsDep) -> ObserveService:
    return ObserveService(session, settings)


Observe = Annotated[ObserveService, Depends(get_observe_service)]


@router.get("/overview", responses=errors(422))
async def get_overview(member: Admin, observe: Observe) -> ObserveOverview:
    """The workspace's health in one read: counts, run activity, the run queue, stuck runs,
    and providers that last refused for their limits. Owners and admins (a personal workspace's owner)."""
    return await observe.overview(member)


@router.get("/runs", responses=errors(422))
async def list_observed_runs(
    member: Admin,
    observe: Observe,
    kind: Literal["chat", "coding"] | None = Query(default=None, description="Only chat runs, or only coding turns"),
    before: datetime | None = Query(default=None, description="Page backwards: pass the last run's `created_at`"),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[ObservedRun]:
    """The workspace's recent runs in one list — chat and coding merged, newest first — each
    with its status, tokens, cost, and why it failed when it did. Owners and admins."""
    return await observe.runs(member, kind=kind, before=before, limit=limit)
