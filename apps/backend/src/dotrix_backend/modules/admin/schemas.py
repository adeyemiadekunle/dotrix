"""Admin app payloads: sign-up (proving workspace ownership once), sign-in, the account."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from dotrix_backend.modules.observe.schemas import ObservedRun


class AdminSignup(BaseModel):
    """Create an admin account by proving you own the workspace: your app account's email and
    password. The admin gets its own credentials from then on — separate from your sign-in."""

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
    workspace: AdminWorkspace | None = None
    created_at: datetime


class AdminBootstrap(BaseModel):
    """Whether the sign-up form is open: true only while no admin account exists."""

    enabled: bool


# Platform administration payloads.


class StuckRun(BaseModel):
    """An active run whose lease lapsed: the worker on it is gone, and the sweep should pick it up."""

    kind: Literal["chat", "coding"]
    id: uuid.UUID
    status: str
    workspace: str = Field(description="The workspace's slug")
    label: str | None = Field(default=None, description="Coding: the issue key")
    lease_expired_at: datetime | None


class PlatformHealth(BaseModel):
    """Is the deployment working, in one read: the database, the run queue, workers, leases and sandboxes."""

    generated_at: datetime
    version: str
    environment: str
    jobs: str = Field(description="Where background work runs: local, worker, or inline")
    sandbox: str = Field(description="Where cloud coding turns run: docker, docker-cloud, openshell, local, or off")
    database_ms: float
    queue_pending: int = Field(description="Dispatches published but not yet taken by a worker")
    queue_oldest_seconds: float | None
    queue_discarded_24h: int
    worker_last_took_at: datetime | None = Field(description="When a worker last took a run off the queue")
    runs_running: int
    runs_queued: int
    stuck: list[StuckRun]
    recovery_required: int = Field(description="Coding turns waiting for someone to check and recover them")
    interrupted: int = Field(description="Chat runs that ran out of attempts after their worker stopped")
    sandboxes_warm: int
    sandboxes_asleep: int
    runners_online: int = Field(description="People's computers that checked in during the last 2 minutes")
    runners: int
    failed_24h: int
    finished_24h: int


class PlatformCounts(BaseModel):
    days: int
    workspaces: int
    workspaces_new: int
    workspaces_active: int = Field(description="Workspaces with a run in the window")
    people: int
    people_new: int
    people_active: int = Field(description="People who started a run in the window")
    projects: int
    documents: int
    document_bytes: int


class DayStats(BaseModel):
    """One UTC day: runs started and how many of them failed, tokens, coding cost, sign-ups."""

    day: date
    chat_runs: int = 0
    chat_failed: int = 0
    coding_runs: int = 0
    coding_failed: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    coding_cost_usd: float = 0.0
    signups: int = 0


class FailureGroup(BaseModel):
    key: str = Field(description="The error kind, the model, or the error's first line")
    kind: Literal["chat", "coding"] | None = None
    detail: str | None = Field(default=None, description="Messages: the chat error kind or the coding status")
    count: int
    last_at: datetime | None


class FailureReport(BaseModel):
    days: int
    chat_kinds: list[FailureGroup]
    chat_models: list[FailureGroup]
    messages: list[FailureGroup] = Field(description="Failures grouped by their error's first line, most frequent first")


class CodingBreakdown(BaseModel):
    """Coding turns for one engine in one place (cloud or local)."""

    engine: str
    location: str
    turns: int
    finished: int = Field(description="Ended with a PR, changes ready, or no changes")
    failed: int = Field(description="Failed, or waiting to be recovered")
    prs: int
    p50_seconds: float | None
    p95_seconds: float | None
    tokens: int
    cost_usd: float


class WorkspaceUsage(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    kind: str
    members: int
    projects: int
    created_at: datetime
    chat_runs: int
    coding_runs: int
    failed: int
    tokens: int
    cost_usd: float
    last_run_at: datetime | None
    paused: bool = Field(description="An owner paused the workspace's agents")


class PlatformAuditEvent(BaseModel):
    """An audit event on the admin console: what happened, by whom and where, without its details
    (which can carry titles, paths and other words people wrote)."""

    id: uuid.UUID
    action: str
    workspace: str | None = Field(description="The workspace's slug")
    actor_type: str = Field(description="user, agent, or system")
    actor_user_id: uuid.UUID | None
    agent: str | None
    created_at: datetime


class RunPage(BaseModel):
    """A page of the admin console's run history, and how many runs match in all."""

    items: list[ObservedRun]
    total: int


class AuditPage(BaseModel):
    items: list[PlatformAuditEvent]
    total: int
