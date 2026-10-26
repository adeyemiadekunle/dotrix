"""The Admin app's API: its own accounts and sign-in, then the workspace's observability
and management — never the app users' session."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, status

from dotrix_backend.api.deps import SessionDep, SettingsDep
from dotrix_backend.core.openapi import errors
from dotrix_backend.modules.audit.schemas import AuditEventRead
from dotrix_backend.modules.audit.service import AuditLog
from dotrix_backend.modules.observe.schemas import ObservedRun, ObserveOverview
from dotrix_backend.modules.observe.service import ObserveService
from dotrix_backend.modules.workspaces.schemas import OrganizationConversion, WorkspaceWithRole
from dotrix_backend.modules.workspaces.service import WorkspaceService

from .schemas import AdminLogin, AdminRead, AdminRefresh, AdminSignup, AdminTokens
from .service import AdminDep, AdminService, admin_member

router = APIRouter(prefix="/admin", tags=["admin"], responses=errors(401))


def get_admin_service(session: SessionDep, settings: SettingsDep) -> AdminService:
    return AdminService(session, settings)


Service = Annotated[AdminService, Depends(get_admin_service)]


@router.post("/signup", status_code=status.HTTP_201_CREATED, responses=errors(409, 422))
async def admin_signup(data: AdminSignup, admins: Service) -> AdminTokens:
    """Create an admin account by proving you own the workspace (your app sign-in). Admin
    accounts are separate from app users: the admin signs in with its own credentials after."""
    return await admins.signup(data)


@router.post("/login", responses=errors(422))
async def admin_login(data: AdminLogin, admins: Service) -> AdminTokens:
    """Sign the admin in: its own email and password, never an app session."""
    return await admins.login(data)


@router.post("/refresh", responses=errors(422))
async def admin_refresh(data: AdminRefresh, admins: Service) -> AdminTokens:
    """Trade the refresh token for a new pair. The refresh token rotates with it: the one you
    sent is dead from now on."""
    return await admins.refresh(data)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, responses=errors(422))
async def admin_logout(data: AdminRefresh, admin: AdminDep, admins: Service) -> None:
    """Sign out: revoke the session this refresh token belongs to."""
    await admins.logout(admin, data.refresh_token)


@router.get("/me")
async def admin_me(admin: AdminDep, admins: Service) -> AdminRead:
    """Who's signed in and the workspace this admin is bound to."""
    return await admins.read(admin)


def get_observe(session: SessionDep, settings: SettingsDep) -> ObserveService:
    return ObserveService(session, settings)


Observe = Annotated[ObserveService, Depends(get_observe)]


@router.get("/observe/overview", responses=errors(403, 422))
async def observe_overview(admin: AdminDep, session: SessionDep, observe: Observe) -> ObserveOverview:
    """The admin's workspace health (the same read the app's owners get)."""
    return await observe.overview(await admin_member(session, admin))


@router.get("/observe/runs", responses=errors(403, 422))
async def observe_runs(
    admin: AdminDep,
    session: SessionDep,
    observe: Observe,
    kind: Literal["chat", "coding"] | None = None,
    before: datetime | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[ObservedRun]:
    """The workspace's run history: chat and coding merged, newest first."""
    return await observe.runs(await admin_member(session, admin), kind=kind, before=before, limit=limit)


@router.get("/audit", responses=errors(403, 422))
async def audit(
    admin: AdminDep,
    session: SessionDep,
    action: str | None = None,
    before: datetime | None = None,
    limit: int = Query(default=100, ge=1, le=200),
) -> list[AuditEventRead]:
    """The workspace's audit log: approvals, writes and decisions, newest first."""
    return await AuditLog(session).list(admin.workspace_id, action=action, before=before, limit=limit)


@router.post("/convert-to-organization", responses=errors(403, 409, 422))
async def admin_convert_to_organization(
    data: OrganizationConversion, admin: AdminDep, session: SessionDep
) -> WorkspaceWithRole:
    """Turn the admin's personal workspace into an organisation, keeping its projects."""
    return await WorkspaceService(session).convert_to_organization(await admin_member(session, admin), data)
