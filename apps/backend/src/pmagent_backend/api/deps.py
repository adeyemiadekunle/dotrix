"""Shared FastAPI dependencies: session, settings, current user, workspace access.

Workspace routes take `workspace_id` in the path and depend on
`require_permission(...)`. A user who isn't a member gets 404, not 403, so
workspace IDs can't be probed.
"""
from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from pmagent_backend.core import security
from pmagent_backend.core.email import EmailSender, get_email_sender
from pmagent_backend.core.errors import Forbidden, NotFound, Unauthorized
from pmagent_backend.core.settings import Settings
from pmagent_backend.db.session import get_session
from pmagent_backend.modules.auth.models import User
from pmagent_backend.modules.auth.repository import UserRepository
from pmagent_backend.modules.workspaces.models import Membership
from pmagent_backend.modules.workspaces.permissions import Permission, has_permission
from pmagent_backend.modules.workspaces.repository import MembershipRepository


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_app_settings)]
EmailDep = Annotated[EmailSender, Depends(get_email_sender)]

_bearer = HTTPBearer(auto_error=False, description="Access token from /v1/auth/login")


async def get_current_user(
    session: SessionDep,
    settings: SettingsDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    if credentials is None:
        raise Unauthorized("Not signed in")
    user_id = security.decode_access_token(
        credentials.credentials,
        secret=settings.jwt_secret.get_secret_value(),
        issuer=settings.jwt_issuer,
    )
    user = await UserRepository(session).get(user_id)
    if user is None or not user.is_active:
        raise Unauthorized("Invalid or expired access token")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


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
        if not has_permission(membership.role, permission):
            raise Forbidden(f"Your role ({membership.role}) can't do this ({permission})")
        return membership

    return dependency
