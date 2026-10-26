"""Admin accounts: create by proving workspace ownership once, then a separate sign-in.

The admin token (`type=admin`, 12h) only ever reaches the workspace it was proven on: the
admin reads as its owner (a pseudo-membership, role OWNER), so every scoped query stays
inside it. Refresh tokens live in `admin_sessions`, one active token per session, rotated on
every use — a replayed token gets a 401."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

import jwt
from fastapi import Depends, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dotrix_backend.api.deps import SessionDep, SettingsDep
from dotrix_backend.core.errors import Conflict, NotFound, Unauthorized
from dotrix_backend.core.security import generate_token, hash_password, hash_token, verify_password
from dotrix_backend.core.settings import Settings
from dotrix_backend.modules.auth.repository import UserRepository
from dotrix_backend.modules.workspaces.models import Membership, Role, Workspace, WorkspaceKind

from .models import AdminSession, AdminUser
from .schemas import AdminLogin, AdminRead, AdminRefresh, AdminSignup, AdminTokens, AdminWorkspace

ADMIN_TOKEN_TYPE = "admin"
ACCESS_TTL = timedelta(hours=12)
REFRESH_TTL = timedelta(days=30)


def _admin_token(admin_id: uuid.UUID, settings: Settings) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": str(admin_id),
            "type": ADMIN_TOKEN_TYPE,
            "iss": settings.jwt_issuer,
            "iat": now,
            "exp": now + ACCESS_TTL,
        },
        settings.jwt_secret.get_secret_value(),
        algorithm="HS256",
    )


class AdminService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    async def _tokens(self, admin: AdminUser, existing: AdminSession | None = None) -> AdminTokens:
        """A new access token + rotated refresh token. The row's hash is replaced, so the
        previous refresh token is dead the moment this is issued."""
        refresh = generate_token()
        now = datetime.now(UTC)
        session = existing or AdminSession(admin_user_id=admin.id, created_at=now)
        session.token_hash = hash_token(refresh)
        session.last_used_at = now
        session.expires_at = now + REFRESH_TTL
        if existing is None:
            self.session.add(session)
        return AdminTokens(
            access_token=_admin_token(admin.id, self.settings),
            refresh_token=refresh,
        )

    async def signup(self, data: AdminSignup) -> AdminTokens:
        """The owner's own credentials create the admin once; afterwards only the admin's sign in."""
        user = await UserRepository(self.session).get_by_email(data.owner_email.lower())
        if user is None or not verify_password(user.password_hash, data.owner_password):
            raise Unauthorized("The workspace owner's sign-in didn't check out")
        # Phase 1: a personal workspace only — pick it explicitly, since owners may also own
        # an organisation (e.g. after converting, which leaves them a new personal one too).
        workspace = await self.session.scalar(
            select(Workspace)
            .join(Membership, Membership.workspace_id == Workspace.id)
            .where(
                Membership.user_id == user.id,
                Membership.role == Role.OWNER,
                Workspace.kind == WorkspaceKind.PERSONAL,
            )
        )
        if workspace is None:
            raise Conflict("That account owns no personal workspace")
        if await self.session.scalar(select(AdminUser).where(AdminUser.email == data.email.lower())):
            raise Conflict("That email already has an admin account")
        admin = AdminUser(
            workspace_id=workspace.id,
            user_id=user.id,
            email=data.email.lower(),
            name=data.name,
            password_hash=hash_password(data.password),
            created_at=datetime.now(UTC),
        )
        self.session.add(admin)
        await self.session.flush()  # the session row and the JWT both need admin.id
        tokens = await self._tokens(admin)
        await self.session.commit()
        return tokens

    async def login(self, data: AdminLogin) -> AdminTokens:
        admin = await self.session.scalar(select(AdminUser).where(AdminUser.email == data.email.lower()))
        if admin is None or not verify_password(admin.password_hash, data.password):
            raise Unauthorized("Wrong email or password")
        tokens = await self._tokens(admin)
        await self.session.commit()
        return tokens

    async def refresh(self, data: AdminRefresh) -> AdminTokens:
        """Rotate: the presented token is replaced in place, so it's dead once this answers."""
        session = await self.session.scalar(
            select(AdminSession).where(AdminSession.token_hash == hash_token(data.refresh_token))
        )
        now = datetime.now(UTC)
        if session is None or session.revoked_at is not None or session.expires_at <= now:
            raise Unauthorized("Sign in again")
        admin = await self.session.get(AdminUser, session.admin_user_id)
        if admin is None:
            raise Unauthorized("That admin account is gone")
        tokens = await self._tokens(admin, existing=session)
        await self.session.commit()
        return tokens

    async def logout(self, admin: AdminUser, refresh_token: str) -> None:
        """Revoke the session the refresh token belongs to (this admin's only)."""
        session = await self.session.scalar(
            select(AdminSession).where(
                AdminSession.token_hash == hash_token(refresh_token),
                AdminSession.admin_user_id == admin.id,
            )
        )
        if session is not None and session.revoked_at is None:
            session.revoked_at = datetime.now(UTC)
            await self.session.commit()

    async def read(self, admin: AdminUser) -> AdminRead:
        workspace = await self.session.get(Workspace, admin.workspace_id)
        if workspace is None:
            raise NotFound("The workspace is gone")
        return AdminRead(
            id=admin.id,
            email=admin.email,
            name=admin.name,
            workspace=AdminWorkspace(id=workspace.id, name=workspace.name, slug=workspace.slug, kind=workspace.kind.value),
            created_at=admin.created_at,
        )


async def get_admin(
    session: SessionDep, settings: SettingsDep, authorization: Annotated[str | None, Header()] = None
) -> AdminUser:
    """Bearer admin token -> the admin account. Never an app user."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise Unauthorized("Sign in to the Admin app first")
    token = authorization.split(None, 1)[1]
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=["HS256"],
            issuer=settings.jwt_issuer,
            options={"require": ["sub", "exp", "iat", "iss"]},
        )
    except jwt.PyJWTError as exc:
        raise Unauthorized("Invalid or expired admin token") from exc
    if claims.get("type") != ADMIN_TOKEN_TYPE:
        raise Unauthorized("Not an admin token")
    admin = await session.get(AdminUser, uuid.UUID(claims["sub"]))
    if admin is None:
        raise Unauthorized("That admin account is gone")
    return admin


AdminDep = Annotated[AdminUser, Depends(get_admin)]


async def admin_member(session: AsyncSession, admin: AdminUser) -> Membership:
    """The admin reads as the workspace's owner (a pseudo-membership, never persisted)."""
    return Membership(
        id=uuid.uuid4(),
        workspace_id=admin.workspace_id,
        user_id=admin.user_id,
        role=Role.OWNER,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
