"""Ops app payloads: sign-up (proving workspace ownership once), sign-in, the account."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class OpsSignup(BaseModel):
    """Create an ops account by proving you own the workspace: your app account's email and
    password. The ops gets its own credentials from then on — separate from your sign-in."""

    owner_email: str = Field(max_length=320)
    owner_password: str = Field(max_length=200)
    email: str = Field(min_length=3, max_length=320)
    name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=8, max_length=200)


class OpsLogin(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=200)


class OpsWorkspace(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    kind: str


class OpsRead(BaseModel):
    id: uuid.UUID
    email: str
    name: str
    workspace: OpsWorkspace
    created_at: datetime

