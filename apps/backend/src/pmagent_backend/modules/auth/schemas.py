from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, Field, StringConstraints

from .models import SessionClient

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


class EmailSignupFinish(BaseModel):
    token: str = Field(max_length=256)
    display_name: DisplayName


class EmailSignupAddress(BaseModel):
    email: str = Field(description="The address the sign-up link is for")


class PasswordResetConfirm(BaseModel):
    token: str = Field(max_length=256)
    new_password: Password


class SessionRead(BaseModel):
    """A browser or the desktop app you're signed in on (the CLI and tools use API tokens)."""

    id: uuid.UUID
    client: SessionClient = Field(description="`web` (a browser), `desktop` (the desktop app), or `other`")
    device: str = Field(description='What it runs on, from its User-Agent: "Chrome on macOS"')
    ip: str | None = Field(description="The address it last signed in or refreshed from")
    created_at: datetime = Field(description="When it signed in")
    last_used_at: datetime = Field(description="When it last refreshed its access (within minutes of last use)")
    current: bool = Field(description="The one making this request")


class SignedOut(BaseModel):
    signed_out: int = Field(description="How many sessions were signed out")


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
    title: str | None = Field(description="What they do, e.g. Product designer")
    avatar_updated_at: datetime | None = Field(description="When their photo last changed; null without one")
    created_at: datetime


Title = Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)]


class ProfileUpdate(BaseModel):
    """Change your name or what you do; leave a field out to keep it. An empty title clears it."""

    display_name: DisplayName | None = None
    title: Title | None = None


class LinkedAccount(BaseModel):
    provider: Literal["github"]
    login: str | None = Field(description="Your username there")
    linked_at: datetime


class SignInMethods(BaseModel):
    password: bool = Field(description="You have a password (else: set one with Forgot password)")
    email_link: bool = Field(description="A sign-in link by email always works")
    accounts: list[LinkedAccount]


class SignupResponse(BaseModel):
    user: UserRead
    tokens: TokenPair


class AuthProviders(BaseModel):
    github: bool = Field(description="Sign in with GitHub is set up")


class GitHubStart(BaseModel):
    authorize_url: str = Field(description="Send the person here to approve the sign-in on GitHub")
    state: str = Field(description="Keep this (e.g. in a cookie) and check GitHub sends it back")


class GitHubFinish(BaseModel):
    code: str = Field(max_length=256, description="The `code` GitHub sent back")
