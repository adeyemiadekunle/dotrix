from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from dotrix_engine.inventory import DOMAINS

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


class RepoExplainRequest(BaseModel):
    domains: list[str] = Field(default_factory=list, max_length=12,
                               description="Domains to start with (the coverage's `domain`s); none: the agent picks")
    refresh: bool = Field(default=False, description="Update the stale pages first (`GET .../pages`)")

    @field_validator("domains")
    @classmethod
    def _known(cls, domains: list[str]) -> list[str]:
        unknown = [d for d in domains if d not in DOMAINS]
        if unknown:
            raise ValueError(f"Unknown domain {unknown[0]!r}; use one of {', '.join(DOMAINS)}")
        return list(dict.fromkeys(domains))


class StaleSource(BaseModel):
    path: str
    why: Literal["changed", "removed", "unread"] = Field(
        description="`changed`: its content changed since it was read; `removed`: no longer in the repository; "
        "`unread`: cited but never read")


class RepoPageRead(BaseModel):
    path: str = Field(description="The wiki page, e.g. docs/wiki/architecture.md")
    version: int
    updated_at: datetime
    citations: int = Field(description="`path:line` citations on the page")
    stale: list[StaleSource] = Field(description="Cited paths that make it stale (empty: fresh)")


class RepoPagesRead(BaseModel):
    """The repository wiki's pages and whether each still matches the code at the latest inventory."""

    commit_sha: str | None
    pages: list[RepoPageRead]


class DependencyRead(BaseModel):
    ecosystem: Literal["npm", "pypi", "cargo", "go"]
    name: str
    declared: str | None = Field(description="What the manifest asks for: a range, a pin, a path")
    locked: str | None = Field(description="What the lockfile resolved it to (null: no lockfile, or not in it)")
    scope: Literal["runtime", "dev", "optional", "peer"]
    manifest: str
    lockfile: str | None


class UnreadFile(BaseModel):
    path: str
    reason: str


class RepoDependenciesRead(BaseModel):
    """Each manifest's direct dependencies with the versions its lockfile pins, read from the
    checkout without running anything; manifests and lockfiles that couldn't be read, with why."""

    commit_sha: str | None
    dependencies: list[DependencyRead]
    unread: list[UnreadFile]
