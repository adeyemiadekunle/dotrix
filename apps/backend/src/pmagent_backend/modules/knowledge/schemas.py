from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from .models import AuthorType


class FileEntry(BaseModel):
    """A file in the manifest: metadata, no content."""

    model_config = ConfigDict(from_attributes=True)

    path: str
    version: int
    revision: int
    content_hash: str = Field(description="SHA-256 of the UTF-8 content")
    size: int = Field(description="Bytes, UTF-8")
    deleted: bool
    updated_at: datetime


class Manifest(BaseModel):
    revision: int = Field(description="The project's current knowledge revision")
    files: list[FileEntry]


class FileRead(FileEntry):
    content: str


class FileWrite(BaseModel):
    content: str
    base_version: int | None = Field(
        default=None,
        description="The version you edited (0 for a new file). If the file has changed since, "
        "the write fails with 409 instead of overwriting someone else's change.",
    )
    message: str | None = Field(default=None, max_length=500)


class VersionEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    version: int
    revision: int
    content_hash: str
    deleted: bool
    author_type: AuthorType
    author_id: uuid.UUID | None
    agent: str | None
    instructed_by_id: uuid.UUID | None
    approved_by_id: uuid.UUID | None
    message: str | None
    created_at: datetime


class VersionRead(VersionEntry):
    content: str


class VersionDiff(BaseModel):
    path: str
    from_version: int = Field(description="0 when the file didn't exist before")
    to_version: int
    diff: str = Field(description="Unified diff")


class RestoreRequest(BaseModel):
    version: int = Field(ge=1)
    base_version: int | None = None
