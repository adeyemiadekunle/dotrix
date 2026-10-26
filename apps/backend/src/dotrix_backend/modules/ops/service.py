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
from fastapi import Depends, Header
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
from .schemas import OpsLogin, OpsRead, OpsRefresh, OpsSignup, OpsTokens, OpsWorkspace

OPS_TOKEN_TYPE = "ops"
ACCESS_TTL = timedelta(hours=12)
REFRESH_TTL = timedelta(days=30)


def _ops_token(ops_id: uuid.UUID, settings: Settings) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": str(ops_id),
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

    async def _tokens(self, ops: OpsUser, existing: OpsSession | None = None) -> OpsTokens:
        """A new access token + rotated refresh token. The row's hash is replaced, so the
        previous refresh token is dead the moment this is issued."""
        refresh = generate_token()
        now = datetime.now(UTC)
        session = existing or OpsSession(ops_user_id=ops.id, created_at=now)
        session.token_hash = hash_token(refresh)
        session.last_used_at = now
        session.expires_at = now + REFRESH_TTL
        if existing is None:
            self.session.add(session)
        return OpsTokens(
            access_token=_ops_token(ops.id, self.settings),
            refresh_token=refresh,
        )

    async def signup(self, data: OpsSignup) -> OpsTokens:
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
        tokens = await self._tokens(ops)
        await self.session.commit()
        return tokens

    async def login(self, data: OpsLogin) -> OpsTokens:
        ops = await self.session.scalar(select(OpsUser).where(OpsUser.email == data.email.lower()))
        if ops is None or not verify_password(ops.password_hash, data.password):
            raise Unauthorized("Wrong email or password")
        tokens = await self._tokens(ops)
        await self.session.commit()
        return tokens

    async def refresh(self, data: OpsRefresh) -> OpsTokens:
        """Rotate: the presented token is replaced in place, so it's dead once this answers.
        FOR UPDATE serialises concurrent refreshes of one token (two tabs): the loser
        re-reads the row after the winner's commit, finds the hash rotated, and gets a 401."""
        session = await self.session.scalar(
            select(OpsSession).where(OpsSession.token_hash == hash_token(data.refresh_token)).with_for_update()
        )
        now = datetime.now(UTC)
        if session is None or session.revoked_at is not None or session.expires_at <= now:
            raise Unauthorized("Sign in again")
        ops = await self.session.get(OpsUser, session.ops_user_id)
        if ops is None:
            raise Unauthorized("That ops account is gone")
        tokens = await self._tokens(ops, existing=session)
        await self.session.commit()
        return tokens

    async def logout(self, ops: OpsUser, refresh_token: str) -> None:
        """Revoke the session the refresh token belongs to (this ops's only)."""
        session = await self.session.scalar(
            select(OpsSession).where(
                OpsSession.token_hash == hash_token(refresh_token),
                OpsSession.ops_user_id == ops.id,
            )
        )
        if session is not None and session.revoked_at is None:
            session.revoked_at = datetime.now(UTC)
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
    session: SessionDep, settings: SettingsDep, authorization: Annotated[str | None, Header()] = None
) -> OpsUser:
    """Bearer ops token -> the ops account. Never an app user."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise Unauthorized("Sign in to the Ops app first")
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
        raise Unauthorized("Invalid or expired ops token") from exc
    if claims.get("type") != OPS_TOKEN_TYPE:
        raise Unauthorized("Not an ops token")
    ops = await session.get(OpsUser, uuid.UUID(claims["sub"]))
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
