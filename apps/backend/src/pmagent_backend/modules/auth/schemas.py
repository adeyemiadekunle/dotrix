from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, Field, StringConstraints

# Lowercased so lookups and the unique index are case-insensitive.
Email = Annotated[EmailStr, AfterValidator(str.lower)]
# NIST 800-63B: length over composition rules; cap length to bound hashing cost.
Password = Annotated[str, Field(min_length=10, max_length=128)]
DisplayName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class SignupRequest(BaseModel):
    email: Email
    password: Password
    display_name: DisplayName


class LoginRequest(BaseModel):
    email: Email
    password: str = Field(max_length=128)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(max_length=256)


class TokenRequest(BaseModel):
    token: str = Field(max_length=256)


class PasswordResetRequest(BaseModel):
    email: Email


class MagicLinkRequest(BaseModel):
    email: Email


class PasswordResetConfirm(BaseModel):
    token: str = Field(max_length=256)
    new_password: Password


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int  # access token lifetime, seconds


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    display_name: str
    email_verified: bool
    created_at: datetime


class SignupResponse(BaseModel):
    user: UserRead
    tokens: TokenPair
