"""The web app's session routes (`/api/...`, served on the web app's origin).

Not part of the versioned API (`/v1`), nor of its OpenAPI schema: browsers call these, the CLI
and integrations use bearer tokens. Signing in puts the session into httpOnly cookies
(`session.py`); `/api/auth/refresh` trades the refresh cookie for a new pair. The GitHub routes
are top-level redirects: they keep their `state` in short-lived httpOnly cookies scoped to their
own paths, and send the browser on (to GitHub, or back into the app with `?github=` or
`?github_error=`).
"""
from __future__ import annotations

import json
import re
import uuid
from typing import Any
from urllib.parse import urlencode, urlsplit

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials

from pmagent_backend.api.deps import SessionDep, SettingsDep, get_current_user
from pmagent_backend.core import security
from pmagent_backend.core.errors import DomainError, Unauthorized
from pmagent_backend.core.settings import Settings
from pmagent_backend.modules.auth.github import GitHubDep
from pmagent_backend.modules.auth.limits import LOGIN, SIGNUP, ThrottleDep
from pmagent_backend.modules.auth.models import User
from pmagent_backend.modules.auth.profile import ProfileService
from pmagent_backend.modules.auth.router import Auth
from pmagent_backend.modules.auth.schemas import (
    EmailSignupFinish,
    LoginRequest,
    SignupRequest,
    TokenPair,
    TokenRequest,
)
from pmagent_backend.modules.auth.service import AuthService
from pmagent_backend.modules.calendar.router import Calendars, calendar_feed
from pmagent_backend.modules.connectors.github_app import get_github_app
from pmagent_backend.modules.connectors.schemas import InstallationAdd
from pmagent_backend.modules.connectors.service import ConnectorService
from pmagent_backend.modules.workspaces.permissions import Permission, can
from pmagent_backend.modules.workspaces.repository import MembershipRepository

from .session import (
    ACCESS_COOKIE,
    REFRESH_COOKIE,
    clear_session,
    require_web_header,
    set_session,
    shared_refresh,
)

# Every POST here needs X-Requested-With (see session.py): a page on another site can't sign
# you in to its account, or out of yours.
router = APIRouter(prefix="/api", include_in_schema=False, dependencies=[Depends(require_web_header)])

GITHUB_STATE_COOKIE = "pm_github_state"
GITHUB_STATE_PATH = "/api/auth/github"
GITHUB_INSTALL_COOKIE = "pm_github_install"
GITHUB_INSTALL_PATH = "/api/github"
INSTALL_URL = re.compile(r"^https://github\.com/apps/[\w-]+/installations/new$")
UUID_RE = re.compile(r"^[0-9a-f-]{36}$", re.IGNORECASE)


# -- sign in, sign up, refresh, sign out ---------------------------------------------------


@router.post("/auth/login", status_code=status.HTTP_204_NO_CONTENT)
async def web_login(data: LoginRequest, auth: Auth, settings: SettingsDep, throttle: ThrottleDep) -> Response:
    await throttle(LOGIN, data.email)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    set_session(response, await auth.login(data), settings)
    return response


@router.post("/auth/signup", status_code=status.HTTP_201_CREATED)
async def web_signup(data: SignupRequest, auth: Auth, settings: SettingsDep, throttle: ThrottleDep) -> Response:
    await throttle(SIGNUP, data.email)
    created = await auth.signup(data)
    response = JSONResponse(created.user.model_dump(mode="json"), status_code=status.HTTP_201_CREATED)
    set_session(response, created.tokens, settings)
    return response


@router.post("/auth/magic-link", status_code=status.HTTP_204_NO_CONTENT)
async def web_magic_link(data: TokenRequest, auth: Auth, settings: SettingsDep) -> Response:
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    set_session(response, await auth.sign_in_with_magic_link(data.token), settings)
    return response


@router.post("/auth/signup-link", status_code=status.HTTP_201_CREATED)
async def web_signup_link(
    data: EmailSignupFinish, auth: Auth, settings: SettingsDep, throttle: ThrottleDep
) -> Response:
    await throttle(SIGNUP, await auth.email_signup_address(data.token))
    created = await auth.finish_email_signup(data.token, data.display_name)
    response = JSONResponse(created.user.model_dump(mode="json"), status_code=status.HTTP_201_CREATED)
    set_session(response, created.tokens, settings)
    return response


async def _refreshed(request: Request, auth: AuthService) -> TokenPair | None:
    """A new pair for the refresh cookie (shared with requests refreshing at the same time)."""
    token = request.cookies.get(REFRESH_COOKIE)
    if not token:
        return None

    async def do(refresh_token: str) -> TokenPair | None:
        try:
            return await auth.refresh(refresh_token)
        except Unauthorized:
            return None

    return await shared_refresh.refresh(token, do)


@router.post("/auth/refresh", status_code=status.HTTP_204_NO_CONTENT)
async def web_refresh(request: Request, auth: Auth, settings: SettingsDep) -> Response:
    tokens = await _refreshed(request, auth)
    if tokens is None:
        response = JSONResponse(
            {"type": "about:blank", "title": "Unauthorized", "status": 401, "detail": "Your session ended. Sign in again."},
            status_code=status.HTTP_401_UNAUTHORIZED,
            media_type="application/problem+json",
        )
        clear_session(response)
        return response
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    set_session(response, tokens, settings)
    return response


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def web_logout(request: Request, auth: Auth) -> Response:
    token = request.cookies.get(REFRESH_COOKIE)
    if token:
        await auth.logout(token)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_session(response)
    return response


# -- calendar feeds subscribed before the move to Vite --------------------------------------


@router.get("/v1/calendar/{feed}")
async def web_calendar_feed_before_vite(feed: str, calendars: Calendars) -> Response:
    """Calendar apps keep polling the address they were given, which was
    `{app}/api/v1/calendar/{secret}.ics` (through the old web server's API proxy)."""
    return await calendar_feed(feed, calendars)


# -- GitHub: sign in, link to your account, install the app ---------------------------------


def safe_next_path(next_path: str | None) -> str:
    """A path on this site to go to afterwards, or "/" (never another site)."""
    if next_path and next_path.startswith("/") and not next_path.startswith(("//", "/\\")):
        return next_path
    return "/"


def _with_query(path: str, params: dict[str, str]) -> str:
    parts = urlsplit(path)
    query = "&".join(q for q in (parts.query, urlencode(params)) if q)
    return f"{parts.path}?{query}" if query else parts.path


def _redirect(location: str) -> RedirectResponse:
    # Relative locations resolve against the web app's own address (requests reach us through it).
    return RedirectResponse(location, status_code=status.HTTP_303_SEE_OTHER)


def _login_with_error(message: str, next_path: str) -> RedirectResponse:
    params = {"error": message} | ({"next": next_path} if next_path != "/" else {})
    return _redirect(_with_query("/login", params))


def _read_cookie(request: Request, name: str) -> dict[str, Any]:
    try:
        value = json.loads(request.cookies.get(name) or "{}")
    except ValueError:
        return {}  # a mangled cookie counts as none
    return value if isinstance(value, dict) else {}


@router.get("/auth/github")
async def web_github_start(request: Request, settings: SettingsDep, github: GitHubDep) -> RedirectResponse:
    """Step 1: send the browser to GitHub, keeping `state` and where to go after in a cookie.
    `?link=1` links the GitHub account to the person signed in (Settings → Profile); `?install=
    <workspace id>:<installation id>` proves they manage an installation they just made."""
    params = request.query_params
    next_path = safe_next_path(params.get("next"))
    link = params.get("link") == "1"
    match = re.fullmatch(r"([0-9a-f-]{36}):(\d+)", params.get("install") or "", re.IGNORECASE)
    install = {"workspace": match[1], "installation_id": int(match[2])} if match else None
    if not github.configured:
        message = "Sign-in with GitHub isn't available right now."
        if link or install:
            return _redirect(_with_query(next_path, {"github_error": message}))
        return _login_with_error(message, next_path)
    state = security.generate_token()
    response = _redirect(github.authorize_url(state))
    response.set_cookie(
        GITHUB_STATE_COOKIE,
        json.dumps({"state": state, "next": next_path, "link": link, "install": install}),
        max_age=10 * 60,
        path=GITHUB_STATE_PATH,
        httponly=True,
        secure=settings.env == "production",
        # Lax: sent on GitHub's top-level redirect back here, never on cross-site subrequests.
        samesite="lax",
    )
    return response


@router.get("/auth/github/callback")
async def web_github_callback(
    request: Request, auth: Auth, session: SessionDep, settings: SettingsDep, github: GitHubDep
) -> RedirectResponse:
    """Step 2: GitHub sends the browser back with a code. Check the state matches the one this
    browser started with (so nobody can sign you in to their account), then sign in, link, or
    add the installation, as the sign-in started."""
    params = request.query_params
    saved = _read_cookie(request, GITHUB_STATE_COOKIE)
    next_path = safe_next_path(saved.get("next"))
    in_app = bool(saved.get("link") or saved.get("install"))

    def finish(response: RedirectResponse) -> RedirectResponse:
        response.delete_cookie(GITHUB_STATE_COOKIE, path=GITHUB_STATE_PATH)
        return response

    def fail(message: str) -> RedirectResponse:
        if in_app:
            return finish(_redirect(_with_query(next_path, {"github_error": message})))
        return finish(_login_with_error(message, next_path))

    if params.get("error"):
        cancelled = params.get("error") == "access_denied"
        return fail("GitHub sign-in was cancelled." if cancelled else "GitHub sign-in didn't work. Try again.")
    code = params.get("code")
    if not code or not saved.get("state") or params.get("state") != saved["state"]:
        return fail("That GitHub sign-in expired or came from another browser. Try again.")

    if in_app:
        user, refreshed = await _cookie_user(request, session, settings, auth)
        if user is None:
            return fail("Your session ended. Sign in and try again.")
        try:
            if saved.get("link"):
                await ProfileService(session).link_github(user, await github.profile(code))
                done = {"github": "linked"}
            else:
                await _add_installation(session, settings, user, saved["install"], code, github)
                done = {"github": "installed"}
        except DomainError as error:
            response = fail(error.detail)
        else:
            response = finish(_redirect(_with_query(next_path, done)))
        if refreshed:
            set_session(response, refreshed, settings)
        return response

    try:
        tokens = await auth.sign_in_with_github(await github.profile(code))
    except DomainError as error:
        return fail(error.detail)
    response = finish(_redirect(next_path))
    set_session(response, tokens, settings)
    return response


async def _cookie_user(
    request: Request, session: SessionDep, settings: Settings, auth: AuthService
) -> tuple[User | None, TokenPair | None]:
    """Who's signed in, from the session cookies (refreshing them if the access token expired)."""
    refreshed = None
    token = request.cookies.get(ACCESS_COOKIE)
    for attempt in range(2):
        if token:
            try:
                credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
                return await get_current_user(request, session, settings, credentials), refreshed
            except Unauthorized:
                pass
        if attempt == 0:
            refreshed = await _refreshed(request, auth)
            token = refreshed.access_token if refreshed else None
    return None, None


async def _add_installation(
    session: SessionDep, settings: Settings, user: User, install: dict[str, Any], code: str, github: GitHubDep
) -> None:
    """The app was just installed: GitHub confirms this person manages the installation, and
    they must be an owner or admin of the workspace it's for (like the API's route)."""
    workspace_id = uuid.UUID(str(install["workspace"]))
    membership = await MembershipRepository(session).get(workspace_id, user.id)
    if membership is None or not can(membership, Permission.MANAGE_PROJECTS):
        raise Unauthorized("Only the workspace's owners and admins can add GitHub accounts.")
    data = InstallationAdd(installation_id=int(install["installation_id"]), code=code)
    await ConnectorService(session, get_github_app(settings)).add_installation(membership, data, github)


@router.get("/github/install")
async def web_github_install(request: Request, settings: SettingsDep) -> RedirectResponse:
    """Install the GitHub App (Settings → GitHub), step 1: remember which workspace it's for in a
    short httpOnly cookie, then go to GitHub's install page. GitHub comes back to /api/github/setup."""
    params = request.query_params
    next_path = safe_next_path(params.get("next"))
    workspace = params.get("workspace") or ""
    install_url = params.get("install_url") or ""
    # Only GitHub's own install pages: never an open redirect.
    if not UUID_RE.match(workspace) or not INSTALL_URL.match(install_url):
        return _redirect(_with_query(next_path, {"github_error": "That install link isn't right. Try again from Settings."}))
    state = security.generate_token()
    response = _redirect(f"{install_url}?{urlencode({'state': state})}")
    response.set_cookie(
        GITHUB_INSTALL_COOKIE,
        json.dumps({"state": state, "workspace": workspace, "next": next_path}),
        max_age=30 * 60,
        path=GITHUB_INSTALL_PATH,
        httponly=True,
        secure=settings.env == "production",
        samesite="lax",
    )
    return response


@router.get("/github/setup")
async def web_github_setup(request: Request) -> RedirectResponse:
    """Step 2: GitHub's "Setup URL" sends the browser here with the new installation's id. Check
    it's the install this browser started, then sign in with GitHub in install mode, so the API
    can confirm this person manages it. An updated installation needs nothing: back to Settings."""
    params = request.query_params
    saved = _read_cookie(request, GITHUB_INSTALL_COOKIE)
    next_path = safe_next_path(saved.get("next"))

    def back(location: str) -> RedirectResponse:
        response = _redirect(location)
        response.delete_cookie(GITHUB_INSTALL_COOKIE, path=GITHUB_INSTALL_PATH)
        return response

    if params.get("setup_action") == "update":
        return back(_with_query(next_path, {"github": "updated"}))
    installation = params.get("installation_id") or ""
    if (
        not saved.get("workspace")
        or not saved.get("state")
        or params.get("state") != saved["state"]
        or not installation.isdigit()
        or int(installation) <= 0
    ):
        message = "That GitHub install expired or came from another browser. Start it again from Settings."
        return back(_with_query(next_path, {"github_error": message}))
    return back(_with_query("/api/auth/github", {"install": f"{saved['workspace']}:{installation}", "next": next_path}))
