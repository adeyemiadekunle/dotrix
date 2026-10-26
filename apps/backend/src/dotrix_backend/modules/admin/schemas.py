"""Admin app payloads: sign-up (proving workspace ownership once), sign-in, the account."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class AdminSignup(BaseModel):
    """Create an admin account by proving you own the workspace: your app account's email and
    password. The admin gets its own credentials from then on — separate from your sign-in."""

    owner_email: str = Field(max_length=320)
    owner_password: str = Field(max_length=200)
    email: str = Field(min_length=3, max_length=320)
    name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=8, max_length=200)


class AdminLogin(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=200)


class AdminWorkspace(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    kind: str


class AdminRead(BaseModel):
    id: uuid.UUID
    email: str
    name: str
    workspace: AdminWorkspace
    created_at: datetime


class AdminTokens(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class AdminRefresh(BaseModel):
    """Trade the refresh token for a new pair (the refresh token rotates with it)."""

    refresh_token: str
