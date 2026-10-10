from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from .models import CodingAgent, CodingOrigin, CodingRunStatus, PrState


class CodingAvailability(BaseModel):
    available: bool
    agent: CodingAgent | None = Field(description="Who would code: Claude Code with an Anthropic key, else Codex")
    sandbox: str | None = Field(description="`docker`, `openshell`, or `local` (development, no isolation)")
    reason: str | None = Field(description="Why not, when it isn't available")


class CodingRunCreate(BaseModel):
    note: str | None = Field(default=None, max_length=5_000, description="Anything to add to the issue for the agent")


class CodingFollowUp(BaseModel):
    message: str = Field(min_length=1, max_length=5_000, description="What to do in this turn")


class CodingDecision(BaseModel):
    decision: Literal["approve", "reject"]
    reason: str | None = Field(default=None, max_length=1_000)


class CodingEvent(BaseModel):
    at: datetime
    kind: str = Field(description="`step`, `text` (the agent's words), `tool` (what it did), `error`")
    text: str


class CodingEventRead(BaseModel):
    seq: int = Field(description="Its place in the run, from 0")
    at: datetime
    kind: str = Field(description="`step`, `text` (the agent's words), `tool` (what it did), `error`")
    text: str


class CodingEventPage(BaseModel):
    events: list[CodingEventRead]
    next: int | None = Field(description="Pass as `after` for the next page; null when there's no more yet")


class CodingScreenshot(BaseModel):
    index: int = Field(description="Its place in the run's list; GET .../screenshots/{index} returns the image")
    name: str
    size: int
    content_type: str


class CodingRunRead(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    issue_key: str
    agent: CodingAgent
    model: str | None
    session_id: uuid.UUID = Field(description="The session this run is a turn of (its first turn's id)")
    turn: int
    origin: CodingOrigin = Field(description="`start`, `assigned` (the issue was assigned to a coding tool), or `follow_up`")
    status: CodingRunStatus
    brief: str = Field(description="Exactly what the agent is told")
    note: str | None
    repo_full_name: str
    base_branch: str
    base_sha: str | None
    branch: str | None
    commit_sha: str | None
    pr_number: int | None
    pr_url: str | None
    pr_state: PrState | None = Field(description="`open`, `merged`, or `closed`, from GitHub")
    files_changed: list[dict[str, Any]]
    screenshots: list[CodingScreenshot] = Field(default_factory=list, description="What the agent's browser captured in this turn")
    events: list[CodingEvent] = Field(description="The latest events (up to 300); every one is at GET .../events")
    event_count: int = Field(default=0, description="How many events the run has in all")
    summary: str | None = Field(description="The agent's last message")
    error: str | None
    input_tokens: int | None = Field(description="Owners and admins (usage:view) only")
    output_tokens: int | None
    cost_usd: float | None
    requested_by_id: uuid.UUID | None
    decided_by_id: uuid.UUID | None
    decision_reason: str | None
    review_run_id: uuid.UUID | None = Field(description="The Reviewer's run on the PR")
    review_thread_id: uuid.UUID | None = Field(description="Its conversation, to open in Chat")
    created_at: datetime
    decided_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    can_decide: bool = Field(description="Whether you may approve or reject it now")
    can_stop: bool = Field(description="Whether you may stop it now")


class CodingSessionRead(BaseModel):
    """A coding session: a run and its follow-ups, on one branch and one PR. Its status is its latest turn's."""

    session_id: uuid.UUID
    project_id: uuid.UUID
    project_key: str
    project_name: str
    issue_key: str
    issue_title: str
    agent: CodingAgent
    status: CodingRunStatus
    turns: int
    branch: str | None
    pr_number: int | None
    pr_url: str | None
    pr_state: PrState | None
    started_at: datetime
    updated_at: datetime
