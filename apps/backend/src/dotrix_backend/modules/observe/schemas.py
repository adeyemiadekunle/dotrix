"""Observability reads: a workspace's health at a glance and its recent runs in one list."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class RunGroupSummary(BaseModel):
    """One run kind's numbers on the overview: agent runs (chat) or coding runs."""

    total: int
    active: int = Field(description="Queued or running right now")
    waiting: int = Field(description="Stopped for a person's decision: approval, changes ready, or recovery")
    failed_7d: int
    input_tokens_7d: int
    output_tokens_7d: int
    model_calls_7d: int = 0
    cost_usd_7d: float | None = Field(default=None, description="Coding runs only; the tool's reported cost")


class ObserveCounts(BaseModel):
    projects: int = Field(description="Projects you can see")
    members: int
    documents: int
    document_bytes: int
    coding_runners: int = Field(description="Computers registered to code your local turns")


class ObserveQueue(BaseModel):
    pending: int = Field(description="Dispatches published but not yet taken by a worker")
    oldest_pending_seconds: float | None = Field(description="How long the oldest pending dispatch has waited")
    discarded_7d: int = Field(description="Dispatches given up on in the last 7 days")


class ProviderLimit(BaseModel):
    provider: str
    scope: Literal["workspace", "person"] = Field(description="Whose key hit the limit")
    limit_reached_at: datetime
    message: str | None


class ObserveOverview(BaseModel):
    """The workspace's health in one read (the Admin screen's cards)."""

    generated_at: datetime
    jobs: str = Field(description="Where background work runs: local, worker, or inline")
    counts: ObserveCounts
    chat: RunGroupSummary
    coding: RunGroupSummary
    queue: ObserveQueue
    stuck: int = Field(description="Active runs whose lease lapsed: the worker on them is gone")
    limits: list[ProviderLimit] = Field(
        description="Providers that last refused a run for a rate limit or quota"
    )


class ObservedRun(BaseModel):
    """One agent run or coding turn in the unified run history."""

    kind: Literal["chat", "coding"]
    id: uuid.UUID
    status: str
    label: str = Field(description="The conversation's title or first message; the coding run's issue key")
    project_id: uuid.UUID | None
    agent: str | None
    model: str | None
    work_mode: str | None = None
    location: str | None = Field(default=None, description="Coding runs: cloud (a worker) or local (your computer)")
    input_tokens: int
    output_tokens: int
    cost_usd: float | None = None
    error: str | None = None
    error_kind: str | None = None
    requested_by_id: uuid.UUID | None
    automation: bool = False
    created_at: datetime
    finished_at: datetime | None
