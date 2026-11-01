"""The admin console's API (apps/admin, under /v1/ops): its own accounts and sign-in, then the
platform's observability across every workspace, never what people wrote, and never the app
users' session."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Cookie, Depends, Query, Request, Response, status

from dotrix_backend.api.deps import SessionDep, SettingsDep
from dotrix_backend.core.errors import Forbidden, Unauthorized
from dotrix_backend.core.openapi import errors
from dotrix_backend.core.settings import Settings
from dotrix_backend.modules.auth.limits import LOGIN, ThrottleDep
from dotrix_backend.modules.observe.platform import PlatformObserve
from dotrix_backend.modules.observe.schemas import (
    CodingBreakdown,
    DayStats,
    FailureReport,
    ObservedRun,
    PlatformAuditEvent,
    PlatformCounts,
    PlatformHealth,
    WorkspaceUsage,
)
from dotrix_backend.modules.observe.service import ObserveService

from .schemas import OpsBootstrap, OpsLogin, OpsRead, OpsSignup
from .service import OpsDep, OpsService


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


@router.get("/bootstrap")
async def ops_bootstrap(svc: Service) -> OpsBootstrap:
    """Whether ops sign-up is open: true only while no ops account exists."""
    return OpsBootstrap(enabled=await svc.bootstrap_available())


@router.post("/signup", status_code=status.HTTP_201_CREATED, responses=errors(403, 422, 429))
async def ops_signup(data: OpsSignup, svc: Service, response: Response, throttle: ThrottleDep) -> None:
    """Bootstrap the first ops account. The console is for whoever operates the deployment,
    not app users — sign-up closes once the first account exists. Rate-limited per IP."""
    await throttle(LOGIN, data.email)
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
    """Who's signed in."""
    return await svc.read(ops)


def get_observe(session: SessionDep, settings: SettingsDep) -> ObserveService:
    return ObserveService(session, settings)


Observe = Annotated[ObserveService, Depends(get_observe)]


def get_platform(session: SessionDep, settings: SettingsDep) -> PlatformObserve:
    return PlatformObserve(session, settings)


Platform = Annotated[PlatformObserve, Depends(get_platform)]
Days = Annotated[int, Query(ge=1, le=90, description="How many days back")]


@router.get("/observe/health", responses=errors(422))
async def observe_health(ops: OpsDep, request: Request, platform: Platform) -> PlatformHealth:
    """Is the deployment working: the database's answer time, the run queue and when a worker last
    took from it, running and stuck runs, runs waiting to be recovered, sandboxes, and runners."""
    return await platform.health(request.app.version)


@router.get("/observe/counts", responses=errors(422))
async def observe_counts(ops: OpsDep, platform: Platform, days: Days = 7) -> PlatformCounts:
    """How big the deployment is: workspaces and people (all, new, active in the window), projects, documents."""
    return await platform.counts(days)


@router.get("/observe/trends", responses=errors(422))
async def observe_trends(ops: OpsDep, platform: Platform, days: Days = 14) -> list[DayStats]:
    """Each UTC day: chat runs and coding turns started and failed, tokens, coding cost, and sign-ups."""
    return await platform.trends(days)


@router.get("/observe/failures", responses=errors(422))
async def observe_failures(ops: OpsDep, platform: Platform, days: Days = 7) -> FailureReport:
    """What failed in the window: chat runs by error kind and by model, and every failure grouped by its
    error's first line, most frequent first."""
    return await platform.failures(days)


@router.get("/observe/coding", responses=errors(422))
async def observe_coding(ops: OpsDep, platform: Platform, days: Days = 7) -> list[CodingBreakdown]:
    """Coding turns by engine and by where they ran: outcomes, PRs, time to finish (p50, p95), tokens and cost."""
    return await platform.coding(days)


@router.get("/observe/workspaces", responses=errors(422))
async def observe_workspaces(
    ops: OpsDep, platform: Platform, days: Days = 7, limit: int = Query(default=50, ge=1, le=200)
) -> list[WorkspaceUsage]:
    """Workspaces by their use in the window: runs, failures, tokens, coding cost, size, and the latest run."""
    return await platform.workspaces(days, limit)


@router.get("/observe/runs", responses=errors(403, 422))
async def observe_runs(
    ops: OpsDep,
    observe: Observe,
    kind: Literal["chat", "coding"] | None = None,
    failed: bool = Query(default=False, description="Only failed runs (and coding turns waiting to be recovered)"),
    before: datetime | None = None,
    before_id: uuid.UUID | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[ObservedRun]:
    """Run history across the platform: chat and coding merged, newest first, named by workspace,
    project and issue (never a conversation's words). Page backwards with `before` + `before_id`
    (the last row's `created_at` and `id`) so ties aren't skipped."""
    return await observe.platform_runs(kind=kind, failed=failed, before=before, before_id=before_id, limit=limit)


@router.get("/audit", responses=errors(403, 422))
async def audit(
    ops: OpsDep,
    platform: Platform,
    action: str | None = Query(default=None, max_length=100, description="Actions starting with this, e.g. `coding.`"),
    before: datetime | None = None,
    limit: int = Query(default=100, ge=1, le=200),
) -> list[PlatformAuditEvent]:
    """Audit events across the whole platform, newest first: the action, who, and which workspace,
    without the details (they can carry words people wrote)."""
    return await platform.audit(action=action, before=before, limit=limit)

