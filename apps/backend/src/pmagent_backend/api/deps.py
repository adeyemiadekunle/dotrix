"""Shared FastAPI dependencies: session, settings, current user, workspace access.

Callers authenticate with a bearer token: either a short-lived access token
from login (a "session"), or an API token (`pmat_...`) from device login or
/v1/me/tokens. API tokens act as the user, narrowed by scopes; a read-only
token can't make changes, and API tokens can't mint more credentials.

Workspace routes take `workspace_id` in the path and depend on
`require_permission(...)`. A user who isn't a member gets 404, not 403, so
workspace IDs can't be probed.
"""
from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Annotated, Literal

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from pmagent_backend.core import security
from pmagent_backend.core.email import EmailSender, get_email_sender
from pmagent_backend.core.errors import Forbidden, NotFound, Unauthorized
from pmagent_backend.core.jobs import Jobs, get_jobs
from pmagent_backend.core.settings import Settings
from pmagent_backend.db.session import get_session
from pmagent_backend.modules.api_tokens.models import Scope
from pmagent_backend.modules.api_tokens.service import ApiTokenService, is_api_token
from pmagent_backend.modules.auth.models import User
from pmagent_backend.modules.auth.repository import AuthSessionRepository, UserRepository
from pmagent_backend.modules.workspaces.models import Membership
from pmagent_backend.modules.workspaces.permissions import Permission, can
from pmagent_backend.modules.workspaces.repository import MembershipRepository


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_app_settings)]
EmailDep = Annotated[EmailSender, Depends(get_email_sender)]
JobsDep = Annotated[Jobs, Depends(get_jobs)]

_bearer = HTTPBearer(
    auto_error=False, description="Access token from /v1/auth/login, or an API token (pmat_...)"
)
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

AuthMethod = Literal["session", "api_token"]


async def get_current_user(
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    if credentials is None:
        raise Unauthorized("Not signed in")
    bearer = credentials.credentials
    method: AuthMethod
    if is_api_token(bearer):
        token = await ApiTokenService(session).authenticate(bearer)
        if Scope.WRITE not in token.scopes and request.method not in _SAFE_METHODS:
            raise Forbidden("This API token is read-only")
        user_id, method = token.user_id, "api_token"
    else:
        claims = security.decode_access_claims(
            bearer, secret=settings.jwt_secret.get_secret_value(), issuer=settings.jwt_issuer
        )
        user_id, method = claims.user_id, "session"
        if claims.session_id is not None:
            # A signed-out browser or app loses access at once, not when its token expires.
            if await AuthSessionRepository(session).signed_out(claims.session_id):
                raise Unauthorized("This session was signed out")
            request.state.session_id = claims.session_id
    user = await UserRepository(session).get(user_id)
    if user is None or not user.is_active:
        raise Unauthorized("Invalid or expired credentials")
    request.state.auth_method = method
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_session_user(request: Request, user: CurrentUser) -> User:
    """For actions an API token must never do, like creating credentials."""
    if request.state.auth_method != "session":
        raise Forbidden("Sign in to the web app to do this; API tokens can't")
    return user


SessionUser = Annotated[User, Depends(get_session_user)]


async def get_membership(
    workspace_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> Membership:
    membership = await MembershipRepository(session).get(workspace_id, user.id)
    if membership is None:
        raise NotFound("Workspace not found")
    return membership


def require_permission(permission: Permission) -> Callable[..., Awaitable[Membership]]:
    async def dependency(
        membership: Annotated[Membership, Depends(get_membership)],
    ) -> Membership:
        if not can(membership, permission):
            raise Forbidden(f"Your role ({membership.role}) can't do this ({permission})")
        return membership

    return dependency
