from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints

from .models import Scope


def _dedupe(scopes: list[Scope]) -> list[Scope]:
    return sorted(set(scopes))


Scopes = Annotated[list[Scope], Field(min_length=1), AfterValidator(_dedupe)]
TokenName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class ApiTokenCreate(BaseModel):
    name: TokenName
    scopes: Scopes = [Scope.READ, Scope.WRITE]
    expires_in_days: int | None = Field(default=90, ge=1, le=365)


class ApiTokenRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    display_prefix: str
    scopes: list[Scope]
    created_at: datetime
    expires_at: datetime | None
    last_used_at: datetime | None


class ApiTokenCreated(ApiTokenRead):
    """Returned once, at creation. The token can't be retrieved again."""

    token: str
    token_type: Literal["bearer"] = "bearer"


# -- device login -------------------------------------------------------------------


class DeviceCodeRequest(BaseModel):
    client_name: TokenName = "dotrix CLI"
    scopes: Scopes = [Scope.READ, Scope.WRITE]


class DeviceCodeResponse(BaseModel):
    device_code: str
    user_code: str  # shown to the user, e.g. "BCDF-GHJK"
    verification_uri: str
    verification_uri_complete: str
    expires_in: int
    interval: int  # minimum seconds between polls


class UserCodeRequest(BaseModel):
    user_code: str = Field(max_length=16)


class DeviceLookup(BaseModel):
    client_name: str
    scopes: list[Scope]
    expires_at: datetime


class DeviceTokenRequest(BaseModel):
    device_code: str = Field(max_length=256)
