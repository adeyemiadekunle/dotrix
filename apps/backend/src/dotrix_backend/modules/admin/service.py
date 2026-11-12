"""Admin accounts: created once with the deployment's bootstrap token, then a separate sign-in.

Refresh tokens live in `admin_sessions`, one active token per session, rotated on every
use — a replayed token gets a 401."""
from __future__ import annotations

import hmac
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

import jwt
import pyotp
from fastapi import Cookie, Depends, Request
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from dotrix_backend.api.deps import SessionDep, SettingsDep
from dotrix_backend.core.crypto import Secrets
from dotrix_backend.core.errors import Conflict, Forbidden, NotFound, Unauthorized, Unprocessable
from dotrix_backend.core.security import generate_token, hash_password, hash_token, verify_password
from dotrix_backend.core.settings import Settings
from dotrix_backend.modules.audit.service import AuditLog
from dotrix_backend.modules.knowledge.models import AuthorType
from dotrix_backend.modules.workspaces.models import Workspace

from . import trail
from .models import AdminRecoveryCode, AdminSession, AdminUser
from .schemas import (
    AdminLogin,
    AdminLoginChallenge,
    AdminRead,
    AdminRecoveryCodes,
    AdminSignup,
    AdminTwoFactorStart,
)

ADMIN_TOKEN_TYPE = "admin"
CHALLENGE_TOKEN_TYPE = "admin_2fa"
CHALLENGE_TTL = timedelta(minutes=5)
TOTP_PERIOD = 30
RECOVERY_CODE_COUNT = 10
ISSUER_NAME = "dotrix admin"
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


def _challenge_token(admin_id: uuid.UUID, settings: Settings) -> str:
    """Proof that the password step passed. It has no `sid` and another `type`, so `get_admin`
    refuses it as a session."""
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": str(admin_id),
            "type": CHALLENGE_TOKEN_TYPE,
            "iss": settings.jwt_issuer,
            "iat": now,
            "exp": now + CHALLENGE_TTL,
        },
        settings.jwt_secret.get_secret_value(),
        algorithm="HS256",
    )


def two_factor_enabled(admin: AdminUser) -> bool:
    return admin.totp_enabled_at is not None


def must_enrol(admin: AdminUser, secrets: Secrets) -> bool:
    """An admin without a second factor may only set one up. Without `DOTRIX_ENCRYPTION_KEY` the
    server can't store a secret, so nothing is forced."""
    return secrets.configured and not two_factor_enabled(admin)


class AdminService:
    def __init__(self, session: AsyncSession, settings: Settings, secrets: Secrets | None = None) -> None:
        self.session = session
        self.settings = settings
        self.secrets = secrets or Secrets(None)

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

    async def set_storage_limit(
        self, admin: AdminUser, workspace_id: uuid.UUID, megabytes: int | None, ip: str | None = None
    ) -> None:
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
            trail.record(self.session, "admin.storage_limit_changed", admin=admin, workspace=workspace.slug, ip=ip)
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

    async def signup(self, data: AdminSignup, ip: str | None = None) -> tuple[str, str]:
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
        trail.record(self.session, "admin.created", admin=admin, ip=ip)
        pair = await self._tokens(admin)
        await self.session.commit()
        return pair

    async def login(self, data: AdminLogin, ip: str | None = None) -> tuple[str, str] | AdminLoginChallenge:
        """A session, or (when a second factor is set up) a challenge to answer with a code. A sign-in
        is recorded once it is complete: here, or after the code in `verify_second_factor`."""
        admin = await self.session.scalar(select(AdminUser).where(AdminUser.email == data.email.lower()))
        if admin is None or admin.disabled_at is not None or not verify_password(admin.password_hash, data.password):
            # The failure is kept even though the request fails: its row commits before the error.
            trail.record(self.session, "admin.sign_in_failed", actor_email=data.email.strip().lower()[:320], ip=ip)
            await self.session.commit()
            raise Unauthorized("Wrong email or password")
        if two_factor_enabled(admin):
            return AdminLoginChallenge(challenge=_challenge_token(admin.id, self.settings))
        trail.record(self.session, "admin.signed_in", admin=admin, ip=ip)
        pair = await self._tokens(admin)
        await self.session.commit()
        return pair

    async def challenged_admin(self, challenge: str) -> AdminUser:
        """The admin a valid, unexpired challenge names."""
        try:
            claims = jwt.decode(
                challenge,
                self.settings.jwt_secret.get_secret_value(),
                algorithms=["HS256"],
                issuer=self.settings.jwt_issuer,
                options={"require": ["sub", "exp", "iat", "iss"]},
            )
            admin_id = uuid.UUID(claims["sub"])
        except (jwt.PyJWTError, ValueError, KeyError) as exc:
            raise Unauthorized("Sign in again") from exc
        if claims.get("type") != CHALLENGE_TOKEN_TYPE:
            raise Unauthorized("Sign in again")
        admin = await self.session.get(AdminUser, admin_id, with_for_update=True)
        if admin is None or admin.disabled_at is not None or not two_factor_enabled(admin):
            raise Unauthorized("Sign in again")
        return admin

    def _totp(self, admin: AdminUser) -> pyotp.TOTP:
        secret = self.secrets.decrypt(admin.totp_secret_encrypted) if admin.totp_secret_encrypted else None
        if secret is None:
            raise Unauthorized("That code didn't work")
        return pyotp.TOTP(secret, interval=TOTP_PERIOD)

    def _take_totp(self, admin: AdminUser, code: str) -> bool:
        """Accept a 6-digit code for the current step or one either side, once: a step at or before
        the last accepted one is refused. The caller holds the admin row locked."""
        code = code.strip()
        if not (code.isdigit() and len(code) == 6):
            return False
        totp = self._totp(admin)
        current = int(time.time()) // TOTP_PERIOD
        for step in (current - 1, current, current + 1):
            if hmac.compare_digest(totp.at(step * TOTP_PERIOD), code):
                if admin.totp_last_step is not None and step <= admin.totp_last_step:
                    return False
                admin.totp_last_step = step
                return True
        return False

    async def _take_recovery_code(self, admin: AdminUser, code: str) -> bool:
        row = await self.session.scalar(
            select(AdminRecoveryCode)
            .where(
                AdminRecoveryCode.admin_user_id == admin.id,
                AdminRecoveryCode.code_hash == hash_token(code.strip()),
                AdminRecoveryCode.used_at.is_(None),
            )
            .with_for_update()
        )
        if row is None:
            return False
        row.used_at = datetime.now(UTC)
        return True

    async def verify_second_factor(self, admin: AdminUser, code: str, ip: str | None = None) -> tuple[str, str]:
        """The second step of sign-in: a TOTP code or an unused recovery code, then a session.
        `admin` came from `challenged_admin` (its row is locked)."""
        if not self._take_totp(admin, code) and not await self._take_recovery_code(admin, code):
            # Kept like a wrong password: the row commits before the error.
            trail.record(self.session, "admin.sign_in_failed", actor_email=admin.email, ip=ip)
            await self.session.commit()
            raise Unauthorized("That code didn't work")
        trail.record(self.session, "admin.signed_in", admin=admin, ip=ip)
        pair = await self._tokens(admin)
        await self.session.commit()
        return pair

    async def start_two_factor(self, admin: AdminUser) -> AdminTwoFactorStart:
        """A fresh secret, stored encrypted and not yet in force until a code confirms it."""
        if two_factor_enabled(admin):
            raise Conflict("Two-factor sign-in is already set up")
        secret = pyotp.random_base32()
        admin.totp_secret_encrypted = self.secrets.encrypt(secret)  # EncryptionNotConfigured without a key
        admin.totp_last_step = None
        await self.session.commit()
        uri = pyotp.TOTP(secret, interval=TOTP_PERIOD).provisioning_uri(name=admin.email, issuer_name=ISSUER_NAME)
        return AdminTwoFactorStart(secret=secret, otpauth_uri=uri)

    async def confirm_two_factor(self, admin: AdminUser, code: str, ip: str | None = None) -> AdminRecoveryCodes:
        admin = await self.session.get(AdminUser, admin.id, with_for_update=True) or admin
        if two_factor_enabled(admin):
            raise Conflict("Two-factor sign-in is already set up")
        if not admin.totp_secret_encrypted:
            raise Unprocessable("Start the set-up first")
        if not self._take_totp(admin, code):
            raise Unauthorized("That code didn't work")
        admin.totp_enabled_at = datetime.now(UTC)
        codes = await self._new_recovery_codes(admin)
        trail.record(self.session, "admin.two_factor_enabled", admin=admin, ip=ip)
        await self.session.commit()
        return codes

    async def replace_recovery_codes(self, admin: AdminUser, code: str, ip: str | None = None) -> AdminRecoveryCodes:
        admin = await self.session.get(AdminUser, admin.id, with_for_update=True) or admin
        if not self._take_totp(admin, code):
            raise Unauthorized("That code didn't work")
        codes = await self._new_recovery_codes(admin)
        trail.record(self.session, "admin.recovery_codes_replaced", admin=admin, ip=ip)
        await self.session.commit()
        return codes

    async def _new_recovery_codes(self, admin: AdminUser) -> AdminRecoveryCodes:
        await self.session.execute(delete(AdminRecoveryCode).where(AdminRecoveryCode.admin_user_id == admin.id))
        codes = [generate_token() for _ in range(RECOVERY_CODE_COUNT)]
        self.session.add_all(AdminRecoveryCode(admin_user_id=admin.id, code_hash=hash_token(c)) for c in codes)
        return AdminRecoveryCodes(recovery_codes=codes)

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

    async def logout(self, admin: AdminUser, access_token: str, ip: str | None = None) -> None:
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
            trail.record(self.session, "admin.signed_out", admin=admin, ip=ip)
            await self.session.commit()

    async def read(self, admin: AdminUser) -> AdminRead:
        return AdminRead(
            id=admin.id, email=admin.email, name=admin.name, role=admin.role, created_at=admin.created_at,
            two_factor=two_factor_enabled(admin), must_enrol=must_enrol(admin, self.secrets),
        )


async def get_admin_enrolling(
    session: SessionDep, settings: SettingsDep, dtx_admin_access: Annotated[str | None, Cookie()] = None
) -> AdminUser:
    """Cookie-bound admin session -> admin account, even one that still has to set up its second
    factor; app bearer tokens are never accepted. Only `/me`, sign-out and the set-up routes use it."""
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


async def get_admin(admin: Annotated[AdminUser, Depends(get_admin_enrolling)], request: Request) -> AdminUser:
    """A full admin session: the second factor is set up (or the server can't store one)."""
    if must_enrol(admin, request.app.state.secrets):
        raise Forbidden("Set up two-factor sign-in first")
    return admin


AdminDep = Annotated[AdminUser, Depends(get_admin)]
EnrollingAdminDep = Annotated[AdminUser, Depends(get_admin_enrolling)]


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


