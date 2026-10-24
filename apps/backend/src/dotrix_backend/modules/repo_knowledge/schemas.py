from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .models import PathStatus


class RepoSnapshotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    repo_full_name: str
    commit_sha: str
    policy_version: str = Field(description="The classification rules it was taken with")
    path_count: int
    created_at: datetime


class DomainCoverage(BaseModel):
    domain: str
    title: str
    status: Literal["gap", "pending", "partial", "covered"] = Field(
        description="`gap`: nothing in the repository is evidence for it (see `gap`); `pending`: its paths "
        "are listed, none read yet; `partial`: some read; `covered`: every readable one read")
    paths: int = Field(description="Paths that are evidence for it (excluded ones aside)")
    analyzed: int
    excluded: int = Field(description="Paths for it that are listed but not read (with why)")
    gap: str | None = Field(default=None, description="What's missing, and what to ask for, when it's a gap")


class RepoCoverageRead(BaseModel):
    """What the repository's knowledge covers at its latest snapshot: path coverage and domain
    coverage, separately. Reading a file isn't proof its meaning was understood."""

    snapshot: RepoSnapshotRead | None = Field(description="Null until the repository's first inventory")
    statuses: dict[PathStatus, int] = Field(default_factory=dict, description="Paths by status")
    inventory_complete: bool = Field(description="Every tracked path at the commit is listed")
    discovery_complete: bool = Field(
        description="Nothing in scope is still pending, unsupported, or inaccessible (gaps can remain)")
    domains: list[DomainCoverage] = Field(default_factory=list)


class RepoPathRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    path: str
    size: int
    language: str | None
    kinds: list[str]
    domains: list[str]
    status: PathStatus
    reason: str | None
    analyzed_at: datetime | None


class RepoPathPage(BaseModel):
    paths: list[RepoPathRead]
    next: str | None = Field(description="Pass as `after` for the next page; null on the last")
