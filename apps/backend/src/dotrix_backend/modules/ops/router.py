"""The Ops app's API: its own accounts and sign-in, then the workspace's observability
and management — never the app users' session."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Cookie, Depends, Query, Request, Response, status

from dotrix_backend.api.deps import SessionDep, SettingsDep
from dotrix_backend.core.errors import Forbidden, Unauthorized
from dotrix_backend.core.openapi import errors
from dotrix_backend.core.settings import Settings
from dotrix_backend.modules.audit.schemas import AuditEventRead
from dotrix_backend.modules.audit.service import AuditLog
from dotrix_backend.modules.auth.limits import LOGIN, ThrottleDep
from dotrix_backend.modules.observe.schemas import ObservedRun, ObserveOverview
from dotrix_backend.modules.observe.service import ObserveService
from dotrix_backend.modules.workspaces.schemas import WorkspaceCreate, WorkspaceWithRole

from .schemas import OpsLogin, OpsRead, OpsSignup
from .service import OpsDep, OpsService, ops_member


def require_ops_header(request: Request) -> None:
    if request.method not in ("GET", "HEAD", "OPTIONS") and not request.headers.get("X-Requested-With"):
        raise Forbidden("Ops requests need the X-Requested-With header")


router = APIRouter(prefix="/ops", tags=["ops"], responses=errors(401), dependencies=[Depends(require_ops_header)])

# Both tokens stay in httpOnly cookies, never in a response body or browser storage.
ACCESS_COOKIE = "dtx_ops_access"
REFRESH_COOKIE = "dtx_ops_refresh"
ACCESS_PATH = "/v1/ops"
REFRESH_PATH = "/v1/ops/refresh"


def _set_session(response: Response, access: str, refresh: str, settings: Settings) -> None:
    response.set_cookie(
        ACCESS_COOKIE, access, max_age=12 * 3600, path=ACCESS_PATH,
        httponly=True, secure=settings.is_deployed, samesite="strict",
    )
    response.set_cookie(
        REFRESH_COOKIE,
        refresh,
        max_age=30 * 24 * 3600,
        path=REFRESH_PATH,
        httponly=True,
        secure=settings.is_deployed,
        samesite="strict",
    )


def _clear_session(response: Response) -> None:
    response.delete_cookie(ACCESS_COOKIE, path=ACCESS_PATH)
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_PATH)


def get_ops_service(session: SessionDep, settings: SettingsDep) -> OpsService:
    return OpsService(session, settings)


Service = Annotated[OpsService, Depends(get_ops_service)]


@router.post("/signup", status_code=status.HTTP_201_CREATED, responses=errors(409, 422, 429))
async def ops_signup(data: OpsSignup, svc: Service, response: Response, throttle: ThrottleDep) -> None:
    """Create an ops account by proving you own the workspace (your app sign-in). Ops
    accounts are separate from app users: the ops signs in with its own credentials after.
    Rate-limited on the owner's email and the client IP, same as sign-in."""
    await throttle(LOGIN, data.owner_email)
    access, refresh = await svc.signup(data)
    _set_session(response, access, refresh, svc.settings)


@router.post("/login", status_code=status.HTTP_204_NO_CONTENT, responses=errors(422, 429))
async def ops_login(data: OpsLogin, svc: Service, response: Response, throttle: ThrottleDep) -> None:
    """Sign the ops in: its own email and password, never an app session. Rate-limited per
    IP and per email (10 attempts in 15 minutes)."""
    await throttle(LOGIN, data.email)
    access, refresh = await svc.login(data)
    _set_session(response, access, refresh, svc.settings)


@router.post("/refresh", status_code=status.HTTP_204_NO_CONTENT)
async def ops_refresh(
    svc: Service,
    response: Response,
    dtx_ops_refresh: Annotated[str | None, Cookie()] = None,
) -> None:
    """Trade the refresh-token cookie for a new access token. The cookie rotates with it:
    the one you sent is dead from now on (the row is locked while it rotates)."""
    if not dtx_ops_refresh:
        raise Unauthorized("Sign in to the Ops app first")
    access, refresh = await svc.refresh(dtx_ops_refresh)
    _set_session(response, access, refresh, svc.settings)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def ops_logout(
    ops: OpsDep,
    svc: Service,
    response: Response,
    dtx_ops_access: Annotated[str | None, Cookie()] = None,
) -> None:
    """Sign out: revoke the access token's session, then clear both cookies."""
    if dtx_ops_access:
        await svc.logout(ops, dtx_ops_access)
    _clear_session(response)


@router.get("/me")
async def ops_me(ops: OpsDep, svc: Service) -> OpsRead:
    """Who's signed in and the workspace this ops is bound to."""
    return await svc.read(ops)


def get_observe(session: SessionDep, settings: SettingsDep) -> ObserveService:
    return ObserveService(session, settings)


Observe = Annotated[ObserveService, Depends(get_observe)]


@router.get("/observe/overview", responses=errors(403, 422))
async def observe_overview(ops: OpsDep, session: SessionDep, observe: Observe) -> ObserveOverview:
    """The ops's workspace health (the same read the app's owners get)."""
    return await observe.overview(await ops_member(session, ops))


@router.get("/observe/runs", responses=errors(403, 422))
async def observe_runs(
    ops: OpsDep,
    session: SessionDep,
    observe: Observe,
    kind: Literal["chat", "coding"] | None = None,
    before: datetime | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[ObservedRun]:
    """The workspace's run history: chat and coding merged, newest first."""
    return await observe.runs(await ops_member(session, ops), kind=kind, before=before, limit=limit)


@router.get("/audit", responses=errors(403, 422))
async def audit(
    ops: OpsDep,
    session: SessionDep,
    action: str | None = None,
    before: datetime | None = None,
    limit: int = Query(default=100, ge=1, le=200),
) -> list[AuditEventRead]:
    """The workspace's audit log: approvals, writes and decisions, newest first."""
    return await AuditLog(session).list(ops.workspace_id, action=action, before=before, limit=limit)


@router.post("/organization", status_code=status.HTTP_201_CREATED, responses=errors(422))
async def ops_create_organization(data: WorkspaceCreate, ops: OpsDep, svc: Service) -> WorkspaceWithRole:
    """Create an organisation workspace owned by your account — a separate workspace, not a
    conversion: the personal workspace this ops is bound to stays personal."""
    return await svc.create_organization(ops, data)
