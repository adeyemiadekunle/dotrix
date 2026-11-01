"""The admin console's API (apps/admin, under /v1/admin): its own accounts and sign-in, then the
platform's observability across every workspace, never what people wrote, and never the app
users' session."""
from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Cookie, Depends, Query, Request, Response, status

from dotrix_backend.api.deps import SessionDep, SettingsDep
from dotrix_backend.core.errors import Forbidden, Unauthorized
from dotrix_backend.core.openapi import errors
from dotrix_backend.core.settings import Settings
from dotrix_backend.modules.admin.platform import AdminRunService, PlatformObserve
from dotrix_backend.modules.admin.schemas import (
    AuditPage,
    CodingBreakdown,
    DayStats,
    FailureReport,
    PlatformCounts,
    PlatformHealth,
    RunPage,
    WorkspaceUsage,
)
from dotrix_backend.modules.auth.limits import LOGIN, ThrottleDep

from .schemas import AdminBootstrap, AdminLogin, AdminRead, AdminSignup
from .service import AdminDep, AdminService


def require_admin_header(request: Request) -> None:
    if request.method not in ("GET", "HEAD", "OPTIONS") and not request.headers.get("X-Requested-With"):
        raise Forbidden("Admin requests need the X-Requested-With header")


router = APIRouter(prefix="/admin", tags=["admin"], responses=errors(401), dependencies=[Depends(require_admin_header)])

# Both tokens stay in httpOnly cookies, never in a response body or browser storage.
ACCESS_COOKIE = "dtx_admin_access"
REFRESH_COOKIE = "dtx_admin_refresh"
ACCESS_PATH = "/v1/admin"
REFRESH_PATH = "/v1/admin/refresh"


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


def get_admin_service(session: SessionDep, settings: SettingsDep) -> AdminService:
    return AdminService(session, settings)


Service = Annotated[AdminService, Depends(get_admin_service)]


@router.get("/bootstrap")
async def admin_bootstrap(svc: Service) -> AdminBootstrap:
    """Whether admin sign-up is open: true only while no admin account exists."""
    return AdminBootstrap(enabled=await svc.bootstrap_available())


@router.post("/signup", status_code=status.HTTP_201_CREATED, responses=errors(403, 422, 429))
async def admin_signup(data: AdminSignup, svc: Service, response: Response, throttle: ThrottleDep) -> None:
    """Bootstrap the first admin account. The console is for whoever operates the deployment,
    not app users — sign-up closes once the first account exists. Rate-limited per IP."""
    await throttle(LOGIN, data.email)
    access, refresh = await svc.signup(data)
    _set_session(response, access, refresh, svc.settings)


@router.post("/login", status_code=status.HTTP_204_NO_CONTENT, responses=errors(422, 429))
async def admin_login(data: AdminLogin, svc: Service, response: Response, throttle: ThrottleDep) -> None:
    """Sign the admin in: its own email and password, never an app session. Rate-limited per
    IP and per email (10 attempts in 15 minutes)."""
    await throttle(LOGIN, data.email)
    access, refresh = await svc.login(data)
    _set_session(response, access, refresh, svc.settings)


@router.post("/refresh", status_code=status.HTTP_204_NO_CONTENT)
async def admin_refresh(
    svc: Service,
    response: Response,
    dtx_admin_refresh: Annotated[str | None, Cookie()] = None,
) -> None:
    """Trade the refresh-token cookie for a new access token. The cookie rotates with it:
    the one you sent is dead from now on (the row is locked while it rotates)."""
    if not dtx_admin_refresh:
        raise Unauthorized("Sign in to the Admin app first")
    access, refresh = await svc.refresh(dtx_admin_refresh)
    _set_session(response, access, refresh, svc.settings)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def admin_logout(
    admin: AdminDep,
    svc: Service,
    response: Response,
    dtx_admin_access: Annotated[str | None, Cookie()] = None,
) -> None:
    """Sign out: revoke the access token's session, then clear both cookies."""
    if dtx_admin_access:
        await svc.logout(admin, dtx_admin_access)
    _clear_session(response)


@router.get("/me")
async def admin_me(admin: AdminDep, svc: Service) -> AdminRead:
    """Who's signed in."""
    return await svc.read(admin)


def get_admin_runs(session: SessionDep, settings: SettingsDep) -> AdminRunService:
    return AdminRunService(session, settings)


AdminRuns = Annotated[AdminRunService, Depends(get_admin_runs)]


def get_platform(session: SessionDep, settings: SettingsDep) -> PlatformObserve:
    return PlatformObserve(session, settings)


Platform = Annotated[PlatformObserve, Depends(get_platform)]
Days = Annotated[int, Query(ge=1, le=90, description="How many days back")]


@router.get("/observe/health", responses=errors(422))
async def observe_health(admin: AdminDep, request: Request, platform: Platform) -> PlatformHealth:
    """Is the deployment working: the database's answer time, the run queue and when a worker last
    took from it, running and stuck runs, runs waiting to be recovered, sandboxes, and runners."""
    return await platform.health(request.app.version)


@router.get("/observe/counts", responses=errors(422))
async def observe_counts(admin: AdminDep, platform: Platform, days: Days = 7) -> PlatformCounts:
    """How big the deployment is: workspaces and people (all, new, active in the window), projects, documents."""
    return await platform.counts(days)


@router.get("/observe/trends", responses=errors(422))
async def observe_trends(admin: AdminDep, platform: Platform, days: Days = 14) -> list[DayStats]:
    """Each UTC day: chat runs and coding turns started and failed, tokens, coding cost, and sign-ups."""
    return await platform.trends(days)


@router.get("/observe/failures", responses=errors(422))
async def observe_failures(admin: AdminDep, platform: Platform, days: Days = 7) -> FailureReport:
    """What failed in the window: chat runs by error kind and by model, and every failure grouped by its
    error's first line, most frequent first."""
    return await platform.failures(days)


@router.get("/observe/coding", responses=errors(422))
async def observe_coding(admin: AdminDep, platform: Platform, days: Days = 7) -> list[CodingBreakdown]:
    """Coding turns by engine and by where they ran: outcomes, PRs, time to finish (p50, p95), tokens and cost."""
    return await platform.coding(days)


@router.get("/observe/workspaces", responses=errors(422))
async def observe_workspaces(
    admin: AdminDep, platform: Platform, days: Days = 7, limit: int = Query(default=50, ge=1, le=200)
) -> list[WorkspaceUsage]:
    """Workspaces by their use in the window: runs, failures, tokens, coding cost, size, and the latest run."""
    return await platform.workspaces(days, limit)


@router.get("/observe/runs", responses=errors(403, 422))
async def observe_runs(
    admin: AdminDep,
    runs: AdminRuns,
    kind: Literal["chat", "coding"] | None = None,
    failed: bool = Query(default=False, description="Only failed runs (and coding turns waiting to be recovered)"),
    offset: int = Query(default=0, ge=0, le=10_000, description="Skip this many runs: the page times its size"),
    limit: int = Query(default=25, ge=1, le=200),
) -> RunPage:
    """A page of the run history across the platform, with the total: chat and coding merged,
    newest first, named by workspace, project and issue (never a conversation's words)."""
    return await runs.platform_runs(kind=kind, failed=failed, offset=offset, limit=limit)


@router.get("/audit", responses=errors(403, 422))
async def audit(
    admin: AdminDep,
    platform: Platform,
    action: str | None = Query(default=None, max_length=100, description="Actions starting with this, e.g. `coding.`"),
    offset: int = Query(default=0, ge=0, le=100_000, description="Skip this many events: the page times its size"),
    limit: int = Query(default=25, ge=1, le=200),
) -> AuditPage:
    """A page of audit events across the whole platform, newest first, with the total: the action,
    who, and which workspace, without the details (they can carry words people wrote)."""
    return await platform.audit(action=action, offset=offset, limit=limit)

