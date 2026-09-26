"""API tokens (/v1/me/tokens) and CLI device login (/v1/auth/device/*) (FR-6)."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from pmagent_backend.api.deps import CurrentUser, SessionDep, SessionUser, SettingsDep
from pmagent_backend.core.openapi import errors

from .schemas import (
    ApiTokenCreate,
    ApiTokenCreated,
    ApiTokenRead,
    DeviceCodeRequest,
    DeviceCodeResponse,
    DeviceLookup,
    DeviceTokenRequest,
    UserCodeRequest,
)
from .service import ApiTokenService, DeviceAuthService


def get_token_service(session: SessionDep) -> ApiTokenService:
    return ApiTokenService(session)


def get_device_service(session: SessionDep, settings: SettingsDep) -> DeviceAuthService:
    return DeviceAuthService(session, settings)


Tokens = Annotated[ApiTokenService, Depends(get_token_service)]
Devices = Annotated[DeviceAuthService, Depends(get_device_service)]

tokens_router = APIRouter(prefix="/me/tokens", tags=["api tokens"], responses=errors(401))
device_router = APIRouter(prefix="/auth/device", tags=["device login"])


@tokens_router.get("")
async def list_tokens(user: CurrentUser, tokens: Tokens) -> list[ApiTokenRead]:
    """Your active API tokens. The token values themselves are never shown again."""
    return await tokens.list(user)


@tokens_router.post("", status_code=status.HTTP_201_CREATED, responses=errors(403, 422))
async def create_token(data: ApiTokenCreate, user: SessionUser, tokens: Tokens) -> ApiTokenCreated:
    """Create an API token. It's in this response only; store it now. Needs a login
    session: an API token can't create another (403)."""
    return await tokens.create(user, data)


@tokens_router.delete(
    "/{token_id}", status_code=status.HTTP_204_NO_CONTENT, responses=errors(404)
)
async def revoke_token(token_id: uuid.UUID, user: CurrentUser, tokens: Tokens) -> None:
    """Any of your credentials can revoke your tokens, including the token itself (CLI logout)."""
    await tokens.revoke(user, token_id)


# -- device login: the CLI calls /code then polls /token; the web app calls the rest ----


@device_router.post("/code", responses=errors(422))
async def start_device_login(data: DeviceCodeRequest, devices: Devices) -> DeviceCodeResponse:
    """Step 1 (CLI): get a `device_code` to keep and a `user_code` to show the user, with the
    page where they approve it. Valid 10 minutes."""
    return await devices.start(data)


@device_router.post("/token", responses=errors(400, 422))
async def exchange_device_code(data: DeviceTokenRequest, devices: Devices) -> ApiTokenCreated:
    """Step 3 (CLI): poll every `interval` seconds. Until the user decides, returns 400 with
    `type` ending in `authorization_pending` (keep polling), `slow_down` (poll less often),
    `access_denied` or `expired_token` (stop). On approval, returns an API token once."""
    return await devices.exchange(data.device_code)


@device_router.post("/lookup", responses=errors(401, 403, 404, 422))
async def lookup_device(data: UserCodeRequest, user: SessionUser, devices: Devices) -> DeviceLookup:
    """Step 2 (web app): show what's asking for access before the user approves."""
    return await devices.lookup(data.user_code)


@device_router.post(
    "/approve", status_code=status.HTTP_204_NO_CONTENT, responses=errors(401, 403, 404, 422)
)
async def approve_device(data: UserCodeRequest, user: SessionUser, devices: Devices) -> None:
    """Step 2 (web app): approve. Needs a login session, not an API token."""
    await devices.approve(user, data.user_code)


@device_router.post(
    "/deny", status_code=status.HTTP_204_NO_CONTENT, responses=errors(401, 403, 404, 422)
)
async def deny_device(data: UserCodeRequest, user: SessionUser, devices: Devices) -> None:
    """Step 2 (web app): deny. The CLI's next poll gets `access_denied`."""
    await devices.deny(user, data.user_code)
