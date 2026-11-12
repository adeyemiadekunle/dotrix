"""The admin console's API (apps/admin, under /v1/admin): its own accounts and sign-in, then the
platform's observability across every workspace, never what people wrote, and never the app
users' session."""
from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Cookie, Depends, Query, Request, Response, status

from dotrix_backend.api.deps import EmailDep, SessionDep, SettingsDep
from dotrix_backend.core.errors import Forbidden, Unauthorized
from dotrix_backend.core.openapi import errors
from dotrix_backend.core.ratelimit import client_ip
from dotrix_backend.core.settings import Settings
from dotrix_backend.modules.admin.platform import AdminRunService, PlatformObserve
from dotrix_backend.modules.admin.schemas import (
    AuditPage,
    CodingBreakdown,
    DayStats,
    FailureReport,
    ModelUsage,
    PlatformCounts,
    PlatformHealth,
    RunPage,
    StorageLimitUpdate,
    WorkspaceUsage,
)
from dotrix_backend.modules.auth.limits import LOGIN, ThrottleDep
from dotrix_backend.modules.knowledge.models import AuthorType

from . import trail
from .accounts import AdminAccounts
from .alerts import listing as alert_listing
from .schemas import (
    AdminAlerts,
    AdminBootstrap,
    AdminInviteAccept,
    AdminInviteCreate,
    AdminInvitePreview,
    AdminInvitePreviewRequest,
    AdminInviteRead,
    AdminListed,
    AdminLogin,
    AdminLoginChallenge,
    AdminLoginVerify,
    AdminPasswordChange,
    AdminRead,
    AdminRecoveryCodes,
    AdminSignup,
    AdminTrailEvent,
    AdminTrailPage,
    AdminTwoFactorCode,
    AdminTwoFactorStart,
    AdminUpdate,
)
from .service import AdminDep, AdminService, EnrollingAdminDep, OwnerDep, session_id_of


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


def _ip(request: Request, settings: Settings) -> str:
    return client_ip(request, settings.trusted_proxies)


def get_admin_service(request: Request, session: SessionDep, settings: SettingsDep) -> AdminService:
    return AdminService(session, settings, request.app.state.secrets)


Service = Annotated[AdminService, Depends(get_admin_service)]


@router.get("/bootstrap")
async def admin_bootstrap(svc: Service) -> AdminBootstrap:
    """Whether admin sign-up is open (no admin account exists and, on a deployed server, the
    bootstrap token is configured), and whether the form must ask for that token."""
    return AdminBootstrap(enabled=await svc.bootstrap_available(), token_required=svc.token_required())


@router.post("/signup", status_code=status.HTTP_201_CREATED, responses=errors(403, 422, 429))
async def admin_signup(
    data: AdminSignup, svc: Service, response: Response, throttle: ThrottleDep, request: Request
) -> None:
    """Bootstrap the first admin account with the deployment's bootstrap token. The console is
    for whoever operates the deployment, not app users — sign-up closes once the first account
    exists. Rate-limited per IP."""
    await throttle(LOGIN, data.email)
    access, refresh = await svc.signup(data, _ip(request, svc.settings))
    _set_session(response, access, refresh, svc.settings)


@router.post(
    "/login",
    status_code=status.HTTP_200_OK,
    response_model=AdminLoginChallenge,
    responses={**errors(422, 429), 204: {"description": "Signed in: the session cookies are set"}},
)
async def admin_login(
    data: AdminLogin, svc: Service, response: Response, throttle: ThrottleDep, request: Request
) -> AdminLoginChallenge | Response:
    """Sign the admin in: its own email and password, never an app session. Without a second factor
    this answers 204 and sets the session cookies. With one it sets nothing and answers 200 with a
    challenge to send, with a code, to `/login/verify`. Rate-limited per IP and per email (10
    attempts in 15 minutes)."""
    await throttle(LOGIN, data.email)
    result = await svc.login(data, _ip(request, svc.settings))
    if isinstance(result, AdminLoginChallenge):
        return result
    signed_in = Response(status_code=status.HTTP_204_NO_CONTENT)
    _set_session(signed_in, result[0], result[1], svc.settings)
    return signed_in


@router.post("/login/verify", status_code=status.HTTP_204_NO_CONTENT, responses=errors(401, 422, 429))
async def admin_login_verify(
    data: AdminLoginVerify, svc: Service, response: Response, throttle: ThrottleDep, request: Request
) -> None:
    """The second step of sign-in: the challenge from `/login` and a 6-digit authenticator code or
    a recovery code (each works once). Sets the session cookies. Rate-limited like sign-in."""
    admin = await svc.challenged_admin(data.challenge)
    await throttle(LOGIN, admin.email)
    access, refresh = await svc.verify_second_factor(admin, data.code, _ip(request, svc.settings))
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
    admin: EnrollingAdminDep,
    svc: Service,
    response: Response,
    request: Request,
    dtx_admin_access: Annotated[str | None, Cookie()] = None,
) -> None:
    """Sign out: revoke the access token's session, then clear both cookies."""
    if dtx_admin_access:
        await svc.logout(admin, dtx_admin_access, _ip(request, svc.settings))
    _clear_session(response)


@router.get("/me")
async def admin_me(admin: EnrollingAdminDep, svc: Service) -> AdminRead:
    """Who's signed in, and whether a second factor is set up (`must_enrol`: only the set-up routes work until it is)."""
    return await svc.read(admin)


@router.post("/me/two-factor/start", responses=errors(403, 409, 503))
async def start_two_factor(admin: EnrollingAdminDep, svc: Service) -> AdminTwoFactorStart:
    """Begin setting up an authenticator app: a new secret (shown once, stored encrypted) and its
    otpauth:// link. It counts only after `/me/two-factor/confirm`. Needs DOTRIX_ENCRYPTION_KEY."""
    return await svc.start_two_factor(admin)


@router.post("/me/two-factor/confirm", responses=errors(401, 409, 422))
async def confirm_two_factor(
    data: AdminTwoFactorCode, admin: EnrollingAdminDep, svc: Service, request: Request
) -> AdminRecoveryCodes:
    """Finish the set-up with a current code from the app. Answers ten single-use recovery codes,
    shown only this once; this session is a full one from then on."""
    return await svc.confirm_two_factor(admin, data.code, _ip(request, svc.settings))


@router.post("/me/two-factor/recovery-codes", responses=errors(401, 403, 422))
async def replace_recovery_codes(
    data: AdminTwoFactorCode, admin: AdminDep, svc: Service, request: Request
) -> AdminRecoveryCodes:
    """Replace your recovery codes (the old ones stop working) with ten new ones, shown once. Needs a current authenticator code."""
    return await svc.replace_recovery_codes(admin, data.code, _ip(request, svc.settings))


def get_admin_accounts(session: SessionDep, settings: SettingsDep, email: EmailDep) -> AdminAccounts:
    return AdminAccounts(session, settings, email)


Accounts = Annotated[AdminAccounts, Depends(get_admin_accounts)]


@router.get("/admins", responses=errors(403))
async def list_admins(owner: OwnerDep, accounts: Accounts) -> list[AdminListed]:
    """Every admin account with its role, state and last sign-in. Owners only."""
    return await accounts.list()


@router.post("/admins/invites", status_code=status.HTTP_201_CREATED, responses=errors(403, 409, 422, 429))
async def invite_admin(
    data: AdminInviteCreate, owner: OwnerDep, accounts: Accounts, throttle: ThrottleDep, request: Request
) -> AdminInviteRead:
    """Invite someone by email as an owner or a viewer: a link valid for 72 hours, usable once.
    An earlier pending invite for the same address is revoked. Owners only. The token is never in
    the response, except the link's path when `DOTRIX_ADMIN_URL` is not set and nothing could be emailed."""
    await throttle(LOGIN, data.email)
    return await accounts.invite(owner, data, _ip(request, accounts.settings))


@router.get("/admins/invites", responses=errors(403))
async def list_admin_invites(owner: OwnerDep, accounts: Accounts) -> list[AdminInviteRead]:
    """Invites not yet accepted, revoked or expired. Owners only."""
    return await accounts.pending_invites()


@router.delete("/admins/invites/{invite_id}", status_code=status.HTTP_204_NO_CONTENT, responses=errors(403, 404, 422))
async def revoke_admin_invite(invite_id: uuid.UUID, owner: OwnerDep, accounts: Accounts, request: Request) -> None:
    """Revoke a pending invite. Owners only."""
    await accounts.revoke_invite(owner, invite_id, _ip(request, accounts.settings))


@router.post("/invites/preview", responses=errors(400, 422, 429))
async def preview_admin_invite(
    data: AdminInvitePreviewRequest, accounts: Accounts, throttle: ThrottleDep
) -> AdminInvitePreview:
    """The email and role an invite is for, without using it up. No sign-in. The token goes in the body."""
    await throttle(LOGIN, data.token)
    invite = await accounts.preview(data.token)
    return AdminInvitePreview(email=invite.email, role=invite.role)


@router.post("/invites/accept", status_code=status.HTTP_204_NO_CONTENT, responses=errors(400, 409, 422, 429))
async def accept_admin_invite(
    data: AdminInviteAccept, accounts: Accounts, response: Response, throttle: ThrottleDep, request: Request
) -> None:
    """Use an invite up: create the admin with the invite's email and role, and sign it in. No sign-in needed."""
    await throttle(LOGIN, data.token)
    access, refresh = await accounts.accept(data, _ip(request, accounts.settings))
    _set_session(response, access, refresh, accounts.settings)


@router.patch("/admins/{admin_id}", responses=errors(403, 404, 409, 422))
async def update_admin(
    admin_id: uuid.UUID, data: AdminUpdate, owner: OwnerDep, accounts: Accounts, request: Request
) -> AdminListed:
    """Change an admin's role, or disable or re-enable them (disabling signs them out everywhere).
    The last active owner can't be demoted or disabled. Owners only."""
    return await accounts.update(owner, admin_id, data, _ip(request, accounts.settings))


@router.delete("/admins/{admin_id}", status_code=status.HTTP_204_NO_CONTENT, responses=errors(403, 404, 409, 422))
async def remove_admin(admin_id: uuid.UUID, owner: OwnerDep, accounts: Accounts, request: Request) -> None:
    """Delete an admin account and its sessions. The last active owner can't be removed. Owners only."""
    await accounts.remove(owner, admin_id, _ip(request, accounts.settings))


@router.post("/admins/{admin_id}/two-factor/reset", status_code=status.HTTP_204_NO_CONTENT, responses=errors(403, 404, 409, 422))
async def reset_admin_two_factor(
    admin_id: uuid.UUID, owner: OwnerDep, accounts: Accounts, request: Request, settings: SettingsDep
) -> None:
    """Clear another admin's second factor and sign them out (they lost their device); they set one
    up again at their next sign-in. Owners only, and never your own: use the server's command line."""
    await accounts.reset_two_factor(owner, admin_id, _ip(request, settings))


@router.post("/me/password", status_code=status.HTTP_204_NO_CONTENT, responses=errors(403, 422))
async def change_admin_password(
    data: AdminPasswordChange,
    admin: AdminDep,
    accounts: Accounts,
    request: Request,
    dtx_admin_access: Annotated[str | None, Cookie()] = None,
) -> None:
    """Change your own password (at least 12 characters). Your other sessions are signed out; this one stays."""
    assert dtx_admin_access
    await accounts.change_password(
        admin, data.current_password, data.new_password, session_id_of(dtx_admin_access, accounts.settings),
        _ip(request, accounts.settings),
    )


@router.post("/me/sessions/revoke-others", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_other_admin_sessions(
    admin: AdminDep, accounts: Accounts, request: Request, dtx_admin_access: Annotated[str | None, Cookie()] = None
) -> None:
    """Sign out everywhere else, keeping this session."""
    assert dtx_admin_access
    await accounts.revoke_other_sessions(admin, session_id_of(dtx_admin_access, accounts.settings), _ip(request, accounts.settings)
    )


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
    took from it, running and stuck runs, runs waiting to be recovered, sandboxes, and runners, plus Redis, workers,
    file storage, email and the GitHub App, waiting emails and automation events, and coding capacity."""
    return await platform.health(request.app.version, request.app.state)


@router.get("/observe/alerts", responses=errors(422))
async def observe_alerts(admin: AdminDep, session: SessionDep) -> AdminAlerts:
    """What needs an operator now, and what cleared in the last 24 hours. The same conditions are
    emailed to the operators (DOTRIX_ALERT_EMAILS); a condition shows here from the first check that finds it."""
    return await alert_listing(session)


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


@router.get("/observe/models", responses=errors(422))
async def observe_models(admin: AdminDep, platform: Platform, days: Days = 7) -> list[ModelUsage]:
    """Each model's use in the window, chat and coding together: runs, failures, limit stops, tokens and estimated cost."""
    return await platform.models(days)


@router.get("/observe/workspaces", responses=errors(422))
async def observe_workspaces(
    admin: AdminDep, platform: Platform, days: Days = 7, limit: int = Query(default=50, ge=1, le=200)
) -> list[WorkspaceUsage]:
    """Workspaces by their use in the window: runs, failures, tokens, coding cost, size, and the latest run."""
    return await platform.workspaces(days, limit)


@router.put("/storage-limit", status_code=status.HTTP_204_NO_CONTENT, responses=errors(403, 404, 422))
async def set_workspace_storage_limit(
    data: StorageLimitUpdate, admin: OwnerDep, svc: Service, request: Request
) -> None:
    """Set one workspace's limit on uploads (document originals and task attachments), in MB:
    0 is unlimited, null follows the deployment's `DOTRIX_WORKSPACE_STORAGE_MB`. Nothing is deleted
    when it is lowered; the workspace just can't add more until it is under. Audited in the
    workspace's log (`workspace.storage_limit_updated`). Owners only."""
    await svc.set_storage_limit(admin, data.workspace_id, data.storage_limit_mb, _ip(request, svc.settings))


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
    workspace: str | None = Query(default=None, max_length=100, description="Only this workspace, by its slug"),
    actor_type: AuthorType | None = Query(default=None, description="Only events by people, agents or the system"),
    since: date | None = Query(default=None, description="From this day (UTC), inclusive"),
    until: date | None = Query(default=None, description="Up to this day (UTC), inclusive"),
    offset: int = Query(default=0, ge=0, le=100_000, description="Skip this many events: the page times its size"),
    limit: int = Query(default=25, ge=1, le=200),
) -> AuditPage:
    """A page of audit events across the whole platform, newest first, with the total: the action,
    who, and which workspace, without the details (they can carry words people wrote)."""
    return await platform.audit(
        action=action,
        workspace=workspace,
        actor_type=actor_type,
        since=since,
        until=until,
        offset=offset,
        limit=limit,
    )



@router.get("/trail", responses=errors(403, 422))
async def admin_trail(
    owner: OwnerDep,
    session: SessionDep,
    action: str | None = Query(default=None, max_length=64, description="Actions starting with this, e.g. `admin.sign_in`"),
    offset: int = Query(default=0, ge=0, le=100_000, description="Skip this many events: the page times its size"),
    limit: int = Query(default=25, ge=1, le=200),
) -> AdminTrailPage:
    """A page of what admins did in the console, newest first, with the total: sign-ins and failed
    sign-ins, invites, role changes, disabling, removal, password changes, storage limit changes.
    Never a password, token or anything people wrote. Owners only."""
    events, total = await trail.page(session, action=action, offset=offset, limit=limit)
    return AdminTrailPage(items=[AdminTrailEvent.model_validate(e, from_attributes=True) for e in events], total=total)
