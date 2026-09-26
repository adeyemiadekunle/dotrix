"""API tokens and CLI device login (FR-6).

Device login follows RFC 8628: the CLI gets a device code and a short user
code, the user approves the user code in the web app while signed in, and the
CLI polls until it receives an API token. Only token hashes are stored.
"""
from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from urllib.parse import urlencode

from sqlalchemy.ext.asyncio import AsyncSession
from uuid_utils.compat import uuid7

from pmagent_backend.core import security
from pmagent_backend.core.errors import DomainError, NotFound, Unauthorized
from pmagent_backend.core.settings import Settings
from pmagent_backend.modules.auth.models import User

from .models import ApiToken, DeviceAuthorization, DeviceStatus, Scope
from .repository import ApiTokenRepository, DeviceAuthorizationRepository
from .schemas import (
    ApiTokenCreate,
    ApiTokenCreated,
    ApiTokenRead,
    DeviceCodeRequest,
    DeviceCodeResponse,
    DeviceLookup,
)

API_TOKEN_PREFIX = "pmat_"
DEVICE_CODE_TTL = timedelta(minutes=10)
DEVICE_TOKEN_TTL = timedelta(days=90)
POLL_INTERVAL_SECONDS = 5
# Consonants only (RFC 8628 §6.1): easy to type, can't spell words, no 0/O or 1/I mix-ups.
USER_CODE_ALPHABET = "BCDFGHJKLMNPQRSTVWXZ"
LAST_USED_RESOLUTION = timedelta(minutes=5)


def _now() -> datetime:
    return datetime.now(UTC)


def is_api_token(bearer: str) -> bool:
    return bearer.startswith(API_TOKEN_PREFIX)


def normalize_user_code(code: str) -> str:
    return "".join(c for c in code.upper() if c.isalpha())


def format_user_code(code: str) -> str:
    return f"{code[:4]}-{code[4:]}"


# RFC 8628 §3.5 token-endpoint errors. The CLI switches on `code`.
class DeviceFlowError(DomainError):
    status_code = HTTPStatus.BAD_REQUEST


class AuthorizationPending(DeviceFlowError):
    code = "authorization_pending"


class SlowDown(DeviceFlowError):
    code = "slow_down"


class AccessDenied(DeviceFlowError):
    code = "access_denied"


class ExpiredToken(DeviceFlowError):
    code = "expired_token"


class InvalidGrant(DeviceFlowError):
    code = "invalid_grant"


class ApiTokenService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.tokens = ApiTokenRepository(session)

    def mint(
        self, user_id: uuid.UUID, name: str, scopes: list[Scope], expires_at: datetime | None
    ) -> ApiTokenCreated:
        """Adds a token to the session; the caller commits."""
        raw = API_TOKEN_PREFIX + security.generate_token()
        token = ApiToken(
            id=uuid7(),
            user_id=user_id,
            name=name,
            token_hash=security.hash_token(raw),
            display_prefix=raw[:12],
            scopes=[s.value for s in scopes],
            created_at=_now(),
            expires_at=expires_at,
        )
        self.tokens.add(token)
        return ApiTokenCreated(**ApiTokenRead.model_validate(token).model_dump(), token=raw)

    async def create(self, user: User, data: ApiTokenCreate) -> ApiTokenCreated:
        expires_at = _now() + timedelta(days=data.expires_in_days) if data.expires_in_days else None
        created = self.mint(user.id, data.name, data.scopes, expires_at)
        await self.session.commit()
        return created

    async def list(self, user: User) -> list[ApiTokenRead]:
        return [ApiTokenRead.model_validate(t) for t in await self.tokens.list_for_user(user.id)]

    async def revoke(self, user: User, token_id: uuid.UUID) -> None:
        token = await self.tokens.get_for_user(user.id, token_id)
        if token is None:
            raise NotFound("Token not found")
        token.revoked_at = token.revoked_at or _now()
        await self.session.commit()

    async def authenticate(self, raw: str) -> ApiToken:
        now = _now()
        token = await self.tokens.get_by_hash(security.hash_token(raw))
        if token is None or not token.is_active(now):
            raise Unauthorized("Invalid, expired, or revoked API token")
        # Coarse last-used tracking, so authenticated reads don't all become writes.
        if token.last_used_at is None or now - token.last_used_at > LAST_USED_RESOLUTION:
            token.last_used_at = now
            await self.session.commit()
        return token


class DeviceAuthService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.devices = DeviceAuthorizationRepository(session)

    async def start(self, data: DeviceCodeRequest) -> DeviceCodeResponse:
        now = _now()
        device_code = security.generate_token()
        user_code = await self._unused_user_code()
        self.devices.add(
            DeviceAuthorization(
                device_code_hash=security.hash_token(device_code),
                user_code=user_code,
                client_name=data.client_name,
                scopes=[s.value for s in data.scopes],
                status=DeviceStatus.PENDING,
                created_at=now,
                expires_at=now + DEVICE_CODE_TTL,
            )
        )
        await self.session.commit()
        verification_uri = f"{self.settings.app_url.rstrip('/')}/device"
        shown = format_user_code(user_code)
        return DeviceCodeResponse(
            device_code=device_code,
            user_code=shown,
            verification_uri=verification_uri,
            verification_uri_complete=f"{verification_uri}?{urlencode({'code': shown})}",
            expires_in=int(DEVICE_CODE_TTL.total_seconds()),
            interval=POLL_INTERVAL_SECONDS,
        )

    async def lookup(self, user_code: str) -> DeviceLookup:
        device = await self._pending(user_code)
        return DeviceLookup(
            client_name=device.client_name,
            scopes=[Scope(s) for s in device.scopes],
            expires_at=device.expires_at,
        )

    async def approve(self, user: User, user_code: str) -> None:
        device = await self._pending(user_code, for_update=True)
        device.status = DeviceStatus.APPROVED
        device.user_id = user.id
        await self.session.commit()

    async def deny(self, user: User, user_code: str) -> None:
        device = await self._pending(user_code, for_update=True)
        device.status = DeviceStatus.DENIED
        device.user_id = user.id
        await self.session.commit()

    async def exchange(self, device_code: str) -> ApiTokenCreated:
        """The CLI polls this until the user approves, denies, or the code expires."""
        now = _now()
        device = await self.devices.get_by_device_code_hash_for_update(
            security.hash_token(device_code)
        )
        if device is None or device.status is DeviceStatus.CONSUMED:
            raise InvalidGrant("Unknown or already used device code")
        if device.status is DeviceStatus.DENIED:
            raise AccessDenied("The sign-in request was denied")
        if device.expires_at <= now:
            raise ExpiredToken("The device code expired; start again")
        if device.status is DeviceStatus.PENDING:
            too_soon = (
                device.last_polled_at is not None
                and now - device.last_polled_at < timedelta(seconds=POLL_INTERVAL_SECONDS)
            )
            device.last_polled_at = now
            await self.session.commit()
            if too_soon:
                raise SlowDown(f"Poll at most every {POLL_INTERVAL_SECONDS} seconds")
            raise AuthorizationPending("Waiting for the user to approve the sign-in")

        assert device.user_id is not None  # approved
        created = ApiTokenService(self.session).mint(
            device.user_id,
            name=device.client_name,
            scopes=[Scope(s) for s in device.scopes],
            expires_at=now + DEVICE_TOKEN_TTL,
        )
        device.status = DeviceStatus.CONSUMED
        await self.session.commit()
        return created

    async def _pending(self, user_code: str, *, for_update: bool = False) -> DeviceAuthorization:
        device = await self.devices.get_pending_by_user_code(
            normalize_user_code(user_code), for_update=for_update
        )
        if device is None or device.expires_at <= _now():
            raise NotFound("That code is invalid or has expired")
        return device

    async def _unused_user_code(self) -> str:
        for _ in range(10):
            code = "".join(secrets.choice(USER_CODE_ALPHABET) for _ in range(8))
            if await self.devices.get_pending_by_user_code(code) is None:
                return code
        raise RuntimeError("Could not allocate a device user code")
