"""Admin accounts: created once with the deployment's bootstrap token, then a separate sign-in.

Refresh tokens live in `admin_sessions`, one active token per session, rotated on every
use — a replayed token gets a 401."""
from __future__ import annotations

import hmac
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

import jwt
from fastapi import Cookie, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from dotrix_backend.api.deps import SessionDep, SettingsDep
from dotrix_backend.core.errors import Forbidden, NotFound, Unauthorized
from dotrix_backend.core.security import generate_token, hash_password, hash_token, verify_password
from dotrix_backend.core.settings import Settings
from dotrix_backend.modules.audit.service import AuditLog
from dotrix_backend.modules.knowledge.models import AuthorType
from dotrix_backend.modules.workspaces.models import Workspace

from .models import AdminSession, AdminUser
from .schemas import AdminLogin, AdminRead, AdminSignup

ADMIN_TOKEN_TYPE = "admin"
ACCESS_TTL = timedelta(hours=12)
REFRESH_TTL = timedelta(days=30)


def _admin_token(admin_id: uuid.UUID, session_id: uuid.UUID, settings: Settings) -> str:
    """The access token names its session (`sid`), so signing out kills it at once — a bare
    JWT would otherwise stay valid for up to 12 hours after logout."""
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": str(admin_id),
            "sid": str(session_id),
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

    async def _tokens(self, admin: AdminUser, existing: AdminSession | None = None) -> tuple[str, str]:
        """Rotate the refresh token; the router sets both tokens as httpOnly cookies."""
        refresh = generate_token()
        now = datetime.now(UTC)
        session = existing or AdminSession(admin_user_id=admin.id, created_at=now)
        session.token_hash = hash_token(refresh)
        session.last_used_at = now
        session.expires_at = now + REFRESH_TTL
        if existing is None:
            self.session.add(session)
        await self.session.flush()  # the access token's sid is this row's id
        return _admin_token(admin.id, session.id, self.settings), refresh

    async def set_storage_limit(self, admin: AdminUser, workspace_id: uuid.UUID, megabytes: int | None) -> None:
        """Set (0: unlimited) or clear (null: the deployment's default) one workspace's upload
        storage limit. Audited in the workspace's log with the old and new values."""
        workspace = await self.session.get(Workspace, workspace_id)
        if workspace is None:
            raise NotFound("Workspace not found")
        if workspace.storage_limit_mb != megabytes:
            AuditLog(self.session).record(
                workspace_id=workspace.id, action="workspace.storage_limit_updated", actor_type=AuthorType.SYSTEM,
                target=workspace.slug,
                details={"from_mb": workspace.storage_limit_mb, "to_mb": megabytes, "admin_id": str(admin.id)},
            )
            workspace.storage_limit_mb = megabytes
        await self.session.commit()

    def token_required(self) -> bool:
        return self.settings.admin_bootstrap_token is not None or self.settings.is_deployed

    async def bootstrap_available(self) -> bool:
        """Sign-up is open only while no admin account exists, and on a deployed server only
        when its bootstrap token is configured: the console is for whoever operates the
        deployment, never for app users."""
        if self.settings.is_deployed and self.settings.admin_bootstrap_token is None:
            return False
        return not await self.session.scalar(select(func.count(AdminUser.id)))

    async def signup(self, data: AdminSignup) -> tuple[str, str]:
        # One sign-up at a time, so two requests can't both find "no admin yet".
        await self.session.execute(select(func.pg_advisory_xact_lock(func.hashtextextended("admin:bootstrap", 0))))
        if not await self.bootstrap_available():
            raise Forbidden("Admin sign-up is closed")
        expected = self.settings.admin_bootstrap_token
        if expected is not None and not hmac.compare_digest(
            expected.get_secret_value().encode(), (data.bootstrap_token or "").encode()
        ):
            raise Forbidden("Admin sign-up is closed")
        admin = AdminUser(
            email=data.email.lower(),
            name=data.name,
            password_hash=hash_password(data.password),
            created_at=datetime.now(UTC),
            role="owner",
        )
        self.session.add(admin)
        await self.session.flush()
        pair = await self._tokens(admin)
        await self.session.commit()
        return pair

    async def login(self, data: AdminLogin) -> tuple[str, str]:
        admin = await self.session.scalar(select(AdminUser).where(AdminUser.email == data.email.lower()))
        if admin is None or admin.disabled_at is not None or not verify_password(admin.password_hash, data.password):
            raise Unauthorized("Wrong email or password")
        pair = await self._tokens(admin)
        await self.session.commit()
        return pair

    async def refresh(self, refresh_token: str) -> tuple[str, str]:
        """Rotate: the presented token is replaced in place, so it's dead once this answers.
        FOR UPDATE serialises concurrent refreshes of one token (two tabs): the loser
        re-reads the row after the winner's commit, finds the hash rotated, and gets a 401."""
        session = await self.session.scalar(
            select(AdminSession).where(AdminSession.token_hash == hash_token(refresh_token)).with_for_update()
        )
        now = datetime.now(UTC)
        if session is None or session.revoked_at is not None or session.expires_at <= now:
            raise Unauthorized("Sign in again")
        admin = await self.session.get(AdminUser, session.admin_user_id)
        if admin is None or admin.disabled_at is not None:
            raise Unauthorized("That admin account is gone")
        pair = await self._tokens(admin, existing=session)
        await self.session.commit()
        return pair

    async def logout(self, admin: AdminUser, access_token: str) -> None:
        """Revoke the access token's session, even if its refresh cookie was lost."""
        claims = jwt.decode(
            access_token,
            self.settings.jwt_secret.get_secret_value(),
            algorithms=["HS256"],
            issuer=self.settings.jwt_issuer,
        )
        session_id = uuid.UUID(claims["sid"])
        admin_session = await self.session.get(AdminSession, session_id, with_for_update=True)
        if admin_session is not None and admin_session.admin_user_id == admin.id and admin_session.revoked_at is None:
            admin_session.revoked_at = datetime.now(UTC)
            await self.session.commit()

    async def read(self, admin: AdminUser) -> AdminRead:
        return AdminRead(id=admin.id, email=admin.email, name=admin.name, role=admin.role, created_at=admin.created_at)


async def get_admin(
    session: SessionDep, settings: SettingsDep, dtx_admin_access: Annotated[str | None, Cookie()] = None
) -> AdminUser:
    """Cookie-bound admin session -> admin account; app bearer tokens are never accepted."""
    if not dtx_admin_access:
        raise Unauthorized("Sign in to the Admin app first")
    try:
        claims = jwt.decode(
            dtx_admin_access,
            settings.jwt_secret.get_secret_value(),
            algorithms=["HS256"],
            issuer=settings.jwt_issuer,
            options={"require": ["sub", "sid", "exp", "iat", "iss"]},
        )
        admin_id = uuid.UUID(claims["sub"])
        session_id = uuid.UUID(claims["sid"])
    except (jwt.PyJWTError, ValueError, KeyError) as exc:
        raise Unauthorized("Invalid or expired admin token") from exc
    if claims.get("type") != ADMIN_TOKEN_TYPE:
        raise Unauthorized("Not an admin token")
    admin_session = await session.get(AdminSession, session_id)
    now = datetime.now(UTC)
    if (
        admin_session is None
        or admin_session.admin_user_id != admin_id
        or admin_session.revoked_at is not None
        or admin_session.expires_at <= now
    ):
        raise Unauthorized("Sign in to the Admin app again")
    admin = await session.get(AdminUser, admin_id)
    if admin is None:
        raise Unauthorized("That admin account is gone")
    if admin.disabled_at is not None:
        raise Unauthorized("Sign in to the Admin app again")
    return admin


AdminDep = Annotated[AdminUser, Depends(get_admin)]


def session_id_of(access_token: str, settings: Settings) -> uuid.UUID:
    """The session an access token names (it was checked by `get_admin` already)."""
    claims = jwt.decode(
        access_token, settings.jwt_secret.get_secret_value(), algorithms=["HS256"], issuer=settings.jwt_issuer
    )
    return uuid.UUID(claims["sid"])


def require_owner(admin: AdminDep) -> AdminUser:
    if admin.role != "owner":
        raise Forbidden("Only an owner can manage admins")
    return admin


OwnerDep = Annotated[AdminUser, Depends(require_owner)]


