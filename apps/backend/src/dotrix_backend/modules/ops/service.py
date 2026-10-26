"""Ops accounts: create by proving workspace ownership once, then a separate sign-in.

The ops token (`type=ops`, 12h) only ever reaches the workspace it was proven on: the
ops reads as its owner (a pseudo-membership, role OWNER), so every scoped query stays
inside it. Refresh tokens live in `ops_sessions`, one active token per session, rotated on
every use — a replayed token gets a 401."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

import jwt
from fastapi import Cookie, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dotrix_backend.api.deps import SessionDep, SettingsDep
from dotrix_backend.core.errors import Conflict, NotFound, Unauthorized
from dotrix_backend.core.security import generate_token, hash_password, hash_token, verify_password
from dotrix_backend.core.settings import Settings
from dotrix_backend.modules.auth.repository import UserRepository
from dotrix_backend.modules.workspaces.models import Membership, Role, Workspace, WorkspaceKind
from dotrix_backend.modules.workspaces.schemas import WorkspaceCreate, WorkspaceWithRole
from dotrix_backend.modules.workspaces.service import WorkspaceService

from .models import OpsSession, OpsUser
from .schemas import OpsLogin, OpsRead, OpsSignup, OpsWorkspace

OPS_TOKEN_TYPE = "ops"
ACCESS_TTL = timedelta(hours=12)
REFRESH_TTL = timedelta(days=30)


def _ops_token(ops_id: uuid.UUID, session_id: uuid.UUID, settings: Settings) -> str:
    """The access token names its session (`sid`), so signing out kills it at once — a bare
    JWT would otherwise stay valid for up to 12 hours after logout."""
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": str(ops_id),
            "sid": str(session_id),
            "type": OPS_TOKEN_TYPE,
            "iss": settings.jwt_issuer,
            "iat": now,
            "exp": now + ACCESS_TTL,
        },
        settings.jwt_secret.get_secret_value(),
        algorithm="HS256",
    )


class OpsService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    async def _tokens(self, ops: OpsUser, existing: OpsSession | None = None) -> tuple[str, str]:
        """Rotate the refresh token; the router sets both tokens as httpOnly cookies."""
        refresh = generate_token()
        now = datetime.now(UTC)
        session = existing or OpsSession(ops_user_id=ops.id, created_at=now)
        session.token_hash = hash_token(refresh)
        session.last_used_at = now
        session.expires_at = now + REFRESH_TTL
        if existing is None:
            self.session.add(session)
        await self.session.flush()  # the access token's sid is this row's id
        return _ops_token(ops.id, session.id, self.settings), refresh

    async def signup(self, data: OpsSignup) -> tuple[str, str]:
        """The owner's own credentials create the ops once; afterwards only the ops's sign in."""
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
        if await self.session.scalar(select(OpsUser).where(OpsUser.email == data.email.lower())):
            raise Conflict("That email already has an ops account")
        ops = OpsUser(
            workspace_id=workspace.id,
            user_id=user.id,
            email=data.email.lower(),
            name=data.name,
            password_hash=hash_password(data.password),
            created_at=datetime.now(UTC),
        )
        self.session.add(ops)
        await self.session.flush()  # the session row and the JWT both need ops.id
        pair = await self._tokens(ops)
        await self.session.commit()
        return pair

    async def login(self, data: OpsLogin) -> tuple[str, str]:
        ops = await self.session.scalar(select(OpsUser).where(OpsUser.email == data.email.lower()))
        if ops is None or not verify_password(ops.password_hash, data.password):
            raise Unauthorized("Wrong email or password")
        pair = await self._tokens(ops)
        await self.session.commit()
        return pair

    async def refresh(self, refresh_token: str) -> tuple[str, str]:
        """Rotate: the presented token is replaced in place, so it's dead once this answers.
        FOR UPDATE serialises concurrent refreshes of one token (two tabs): the loser
        re-reads the row after the winner's commit, finds the hash rotated, and gets a 401."""
        session = await self.session.scalar(
            select(OpsSession).where(OpsSession.token_hash == hash_token(refresh_token)).with_for_update()
        )
        now = datetime.now(UTC)
        if session is None or session.revoked_at is not None or session.expires_at <= now:
            raise Unauthorized("Sign in again")
        ops = await self.session.get(OpsUser, session.ops_user_id)
        if ops is None:
            raise Unauthorized("That ops account is gone")
        pair = await self._tokens(ops, existing=session)
        await self.session.commit()
        return pair

    async def logout(self, ops: OpsUser, access_token: str) -> None:
        """Revoke the access token's session, even if its refresh cookie was lost."""
        claims = jwt.decode(
            access_token,
            self.settings.jwt_secret.get_secret_value(),
            algorithms=["HS256"],
            issuer=self.settings.jwt_issuer,
        )
        session_id = uuid.UUID(claims["sid"])
        ops_session = await self.session.get(OpsSession, session_id, with_for_update=True)
        if ops_session is not None and ops_session.ops_user_id == ops.id and ops_session.revoked_at is None:
            ops_session.revoked_at = datetime.now(UTC)
            await self.session.commit()

    async def create_organization(self, ops: OpsUser, data: WorkspaceCreate) -> WorkspaceWithRole:
        """The owner's own organisation — created, never converted: the workspace this ops is
        bound to stays a personal workspace."""
        owner = await UserRepository(self.session).get(ops.user_id)
        if owner is None:
            raise NotFound("The account that proved the workspace is gone")
        return await WorkspaceService(self.session).create(owner, data)

    async def read(self, ops: OpsUser) -> OpsRead:
        workspace = await self.session.get(Workspace, ops.workspace_id)
        if workspace is None:
            raise NotFound("The workspace is gone")
        return OpsRead(
            id=ops.id,
            email=ops.email,
            name=ops.name,
            workspace=OpsWorkspace(id=workspace.id, name=workspace.name, slug=workspace.slug, kind=workspace.kind.value),
            created_at=ops.created_at,
        )


async def get_ops(
    session: SessionDep, settings: SettingsDep, dtx_ops_access: Annotated[str | None, Cookie()] = None
) -> OpsUser:
    """Cookie-bound ops session -> ops account; app bearer tokens are never accepted."""
    if not dtx_ops_access:
        raise Unauthorized("Sign in to the Ops app first")
    try:
        claims = jwt.decode(
            dtx_ops_access,
            settings.jwt_secret.get_secret_value(),
            algorithms=["HS256"],
            issuer=settings.jwt_issuer,
            options={"require": ["sub", "sid", "exp", "iat", "iss"]},
        )
        ops_id = uuid.UUID(claims["sub"])
        session_id = uuid.UUID(claims["sid"])
    except (jwt.PyJWTError, ValueError, KeyError) as exc:
        raise Unauthorized("Invalid or expired ops token") from exc
    if claims.get("type") != OPS_TOKEN_TYPE:
        raise Unauthorized("Not an ops token")
    ops_session = await session.get(OpsSession, session_id)
    now = datetime.now(UTC)
    if (
        ops_session is None
        or ops_session.ops_user_id != ops_id
        or ops_session.revoked_at is not None
        or ops_session.expires_at <= now
    ):
        raise Unauthorized("Sign in to the Ops app again")
    ops = await session.get(OpsUser, ops_id)
    if ops is None:
        raise Unauthorized("That ops account is gone")
    return ops


OpsDep = Annotated[OpsUser, Depends(get_ops)]


async def ops_member(session: AsyncSession, ops: OpsUser) -> Membership:
    """The ops reads as the workspace's owner (a pseudo-membership, never persisted)."""
    return Membership(
        id=uuid.uuid4(),
        workspace_id=ops.workspace_id,
        user_id=ops.user_id,
        role=Role.OWNER,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
