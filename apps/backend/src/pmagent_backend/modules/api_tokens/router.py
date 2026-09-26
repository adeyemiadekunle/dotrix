"""API tokens (/v1/me/tokens) and CLI device login (/v1/auth/device/*) (FR-6)."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from pmagent_backend.api.deps import CurrentUser, SessionDep, SessionUser, SettingsDep

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

tokens_router = APIRouter(prefix="/me/tokens", tags=["api tokens"])
device_router = APIRouter(prefix="/auth/device", tags=["device login"])


@tokens_router.get("")
async def list_tokens(user: CurrentUser, tokens: Tokens) -> list[ApiTokenRead]:
    return await tokens.list(user)


@tokens_router.post("", status_code=status.HTTP_201_CREATED)
async def create_token(data: ApiTokenCreate, user: SessionUser, tokens: Tokens) -> ApiTokenCreated:
    """The token is in this response only; store it now."""
    return await tokens.create(user, data)


@tokens_router.delete("/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_token(token_id: uuid.UUID, user: CurrentUser, tokens: Tokens) -> None:
    """Any of your credentials can revoke your tokens, including the token itself (CLI logout)."""
    await tokens.revoke(user, token_id)


# -- device login: the CLI calls /code then polls /token; the web app calls the rest ----


@device_router.post("/code")
async def start_device_login(data: DeviceCodeRequest, devices: Devices) -> DeviceCodeResponse:
    return await devices.start(data)


@device_router.post("/token")
async def exchange_device_code(data: DeviceTokenRequest, devices: Devices) -> ApiTokenCreated:
    return await devices.exchange(data.device_code)


@device_router.post("/lookup")
async def lookup_device(data: UserCodeRequest, user: SessionUser, devices: Devices) -> DeviceLookup:
    return await devices.lookup(data.user_code)


@device_router.post("/approve", status_code=status.HTTP_204_NO_CONTENT)
async def approve_device(data: UserCodeRequest, user: SessionUser, devices: Devices) -> None:
    await devices.approve(user, data.user_code)


@device_router.post("/deny", status_code=status.HTTP_204_NO_CONTENT)
async def deny_device(data: UserCodeRequest, user: SessionUser, devices: Devices) -> None:
    await devices.deny(user, data.user_code)
