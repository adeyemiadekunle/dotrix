"""Admin app payloads: sign-up (with the bootstrap token), sign-in, the account."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from dotrix_backend.modules.observe.schemas import ObservedRun


class AdminSignup(BaseModel):
    """Create the first admin account. On a deployed server this needs the deployment's
    bootstrap token (DOTRIX_ADMIN_BOOTSTRAP_TOKEN). The admin has its own credentials,
    separate from any app account."""

    email: str = Field(min_length=3, max_length=320)
    name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=8, max_length=200)
    bootstrap_token: str | None = Field(default=None, max_length=200)


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
    """Whether the sign-up form is open (no admin account exists, and on a deployed server the
    bootstrap token is configured), and whether it asks for that token."""

    enabled: bool
    token_required: bool = False


# Platform administration payloads.


class StuckRun(BaseModel):
    """An active run whose lease lapsed: the worker on it is gone, and the sweep should pick it up."""

    kind: Literal["chat", "coding"]
    id: uuid.UUID
    status: str
    workspace: str = Field(description="The workspace's slug")
    label: str | None = Field(default=None, description="Coding: the issue key")
    lease_expired_at: datetime | None


class DependencyCheck(BaseModel):
    """One thing dotrix depends on, as the console shows it."""

    id: str = Field(description="redis, workers, storage, email, github")
    state: Literal["ok", "degraded", "down", "off"] = Field(description="off: not configured here, which is allowed")
    detail: str = Field(description="One short line for an operator: never a secret, never text people wrote")
    latency_ms: float | None = None


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
    dependencies: list[DependencyCheck] = []
    workers_alive: int | None = Field(
        default=None,
        description="1 when a worker has checked in (arq keeps one check-in per queue, so workers aren't counted), "
        "0 when none has; null outside worker mode",
    )
    notification_emails_waiting: int = Field(
        default=0, description="Notifications the minute job should have handled (older than 5 minutes) and hasn't"
    )
    notification_email_oldest_seconds: float | None = None
    automation_events_waiting: int = Field(
        default=0, description="Automation events written and not yet handled (they are deleted once handled)"
    )
    coding_slots: int | None = Field(default=None, description="Cloud coding turns each worker runs at once; null: no limit")
    coding_running_cloud: int = 0


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
    chat_cost_usd: float = Field(default=0.0, description="Estimated from tokens and list prices; models without a price add nothing")
    unpriced_chat_runs: int = Field(default=0, description="Chat runs on models with no listed price, so chat_cost_usd is partial")
    signups: int = 0


class ModelUsage(BaseModel):
    """One model's use in the window, chat and coding together."""

    model: str = Field(description='"provider:model", or "(default)" when a run recorded none')
    provider: str
    chat_runs: int
    coding_runs: int
    failed: int
    limit_stops: int = Field(description="Chat runs the provider stopped for its limits")
    input_tokens: int
    output_tokens: int
    cost_usd: float | None = Field(description="Estimated from tokens and list prices; None when the model has no price")
    cost_is_estimate: bool = True


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
    used_bytes: int = Field(description="Uploads stored: document originals and task attachments")
    storage_limit_mb: int | None = Field(description="This workspace's own limit; null follows the deployment's, 0 is none")
    effective_limit_bytes: int | None = Field(description="The limit that applies; null: none")


class StorageLimitUpdate(BaseModel):
    workspace_id: uuid.UUID
    storage_limit_mb: int | None = Field(
        ge=0, le=10_000_000, description="MB; 0 is unlimited, null follows the deployment's default"
    )


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
