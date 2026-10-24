from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from dotrix_backend.modules.workspaces.approval_modes import ApprovalMode

from .models import (
    CodingAgent,
    CodingLocation,
    CodingOrigin,
    CodingRunStatus,
    CodingSessionState,
    PrState,
)


class CodingAvailability(BaseModel):
    available: bool
    agent: CodingAgent | None = Field(
        description="The engine Kai, the coding agent, would code on: OpenCode when the server names it, "
        "else Claude Code with an Anthropic key, else Codex"
    )
    sandbox: str | None = Field(description="`docker`, `openshell`, or `local` (development, no isolation)")
    reason: str | None = Field(description="Why not, when it isn't available")
    local_available: bool = Field(default=False, description="Whether you can code here on your own computer")
    local_runner: str | None = Field(default=None, description="Your computer that would code (the one seen last)")
    local_reason: str | None = Field(default=None, description="Why not on your computer")


_APPROVAL = ("`manual` (waits for an approver; the default) or `accept_edits` / `auto` (starts at once, approved "
             "by you), never above the workspace's cap, and Manual unless you may approve agent changes")


_LOCATION = ("Where it codes: `cloud` (a sandbox on the platform) or `local` (your own computer, through "
             "`dotrix runner` in a checkout of the project). A follow-up stays where its session is unless told.")


class CodingRunCreate(BaseModel):
    note: str | None = Field(default=None, max_length=5_000, description="Anything to add to the issue for the agent")
    approval_mode: ApprovalMode | None = Field(default=None, description=_APPROVAL)
    location: CodingLocation = Field(default=CodingLocation.CLOUD, description=_LOCATION)


class CodingFollowUp(BaseModel):
    message: str = Field(min_length=1, max_length=5_000, description="What to do in this turn")
    approval_mode: ApprovalMode | None = Field(default=None, description=_APPROVAL)
    location: CodingLocation | None = Field(default=None, description=_LOCATION)


class CodingDecision(BaseModel):
    decision: Literal["approve", "reject"]
    reason: str | None = Field(default=None, max_length=1_000)


class CodingRevert(BaseModel):
    approval_mode: ApprovalMode | None = Field(default=None, description=_APPROVAL)


class CodingRecover(BaseModel):
    action: Literal["check", "discard"] = Field(description=(
        "`check`: look at GitHub and settle it (adopt or open its PR, or run the turn again when nothing "
        "was published); `discard`: end it as failed, having looked yourself"))


class CodingEvent(BaseModel):
    at: datetime
    kind: str = Field(description="`step`, `text` (the agent's words), `tool` (what it did), `output` / "
                      "`output-error` (a command's output, and whether it failed), `error`")
    text: str
    ref: str | None = Field(default=None, description="Pairs a command (`tool`) with its output: the tool call's id")


class CodingEventRead(BaseModel):
    seq: int = Field(description="Its place in the run, from 0")
    at: datetime
    kind: str = Field(description="`step`, `text` (the agent's words), `tool` (what it did), `output` / "
                      "`output-error` (a command's output, and whether it failed), `error`")
    text: str
    ref: str | None = Field(default=None, description="Pairs a command (`tool`) with its output: the tool call's id")


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
    thread_id: uuid.UUID | None = Field(default=None, description="The conversation it was started from (Build mode)")
    approval_mode: ApprovalMode = Field(default=ApprovalMode.MANUAL, description="The approval mode it was asked in")
    plan_id: uuid.UUID | None = Field(default=None, description="The plan version it builds from")
    can_recover: bool = Field(default=False, description="Whether you may recover it now (its outcome is uncertain)")
    can_revert: bool = Field(default=False, description="Whether you may revert it now (a pushed turn whose PR is open)")
    accepted_by_id: uuid.UUID | None = Field(default=None, description="Manual: who accepted its changes before they were pushed")
    accepted_at: datetime | None = None
    revert_of: uuid.UUID | None = Field(default=None, description="The turn this one reverts")
    location: CodingLocation = Field(default=CodingLocation.CLOUD, description="Where it codes")
    runner_name: str | None = Field(default=None, description="A local turn: the computer that claimed it")
    runner_id: uuid.UUID | None = Field(default=None, description="A local turn: the runner that claimed it")
    worktree: str | None = Field(default=None, description="A local turn: its worktree on that computer (only to whoever asked for it)")


class CodingSessionUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=200, description="A name of its own; empty: back to the issue's title")
    pinned: bool | None = None
    archived: bool | None = None


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
    state: CodingSessionState = Field(
        default=CodingSessionState.IDLE,
        description="`warm`: its sandbox is up between turns; `idle`: the next turn starts one and resumes; `closed`: closed by hand",
    )
    title: str = Field(default="", description="Its own name when renamed, else its issue's title")
    pinned: bool = False
    archived: bool = False
    thread_id: uuid.UUID | None = Field(
        default=None,
        description="The conversation it was started from (Build mode), when that conversation is yours: "
        "its turns show there, inline. Null: a session of its own.",
    )
    location: CodingLocation = Field(default=CodingLocation.CLOUD, description="Where its latest turn codes")
    started_at: datetime
    updated_at: datetime


class CodingRunnerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100, description="This computer's name; registering it again updates it")
    platform: str | None = Field(default=None, max_length=40)
    tools: list[CodingAgent] = Field(default_factory=list, max_length=5, description="Coding tools found, preferred first")
    isolation: Literal["srt", "none"] = Field(description="`srt` (the sandbox runtime) or `none` (a worktree only)")
    project_ids: list[uuid.UUID] = Field(default_factory=list, max_length=200, description="Projects it has checkouts of")


class CodingRunnerRead(BaseModel):
    id: uuid.UUID
    name: str
    platform: str | None
    tools: list[str]
    isolation: str
    project_ids: list[uuid.UUID]
    created_at: datetime
    last_seen_at: datetime
    online: bool = Field(description="Seen in the last couple of minutes")


class RunnerEvent(BaseModel):
    kind: Literal["step", "text", "tool", "output", "output-error", "error"]
    text: str = Field(max_length=10_000)
    ref: str | None = Field(default=None, max_length=64)


class CodingClaim(BaseModel):
    """A local turn this runner now holds: code it in a worktree, then report the result."""

    run_id: uuid.UUID
    project_id: uuid.UUID
    session_id: uuid.UUID
    lease_token: int = Field(description="Send it with every heartbeat and the result; a newer one fences this off")
    lease_seconds: int = Field(description="Heartbeat well within this, or the turn needs recovery")
    issue_key: str
    title: str
    turn: int
    brief: str = Field(description="Exactly what the agent is told")
    tool: CodingAgent = Field(description="The tool to code with")
    repo_full_name: str
    base_branch: str
    branch: str | None = Field(description="The session's branch to build on (a follow-up), else the base branch")


class CodingClaimed(BaseModel):
    run: CodingClaim | None = Field(description="None: nothing waits for this runner")


class RunnerHeartbeat(BaseModel):
    lease_token: int
    events: list[RunnerEvent] = Field(default_factory=list, max_length=200)
    base_sha: str | None = Field(default=None, min_length=40, max_length=40)
    worktree: str | None = Field(default=None, max_length=1024, description="The turn's worktree on this computer")


class RunnerHeartbeatRead(BaseModel):
    stop: bool = Field(description="Stop the agent and report `stopped`")


class RunnerResult(BaseModel):
    lease_token: int
    outcome: Literal["changes", "no_changes", "failed", "stopped"]
    patch: str | None = Field(default=None, max_length=20_000_000, description="`git diff --cached --binary` against base_sha")
    base_sha: str | None = Field(default=None, min_length=40, max_length=40)
    summary: str | None = Field(default=None, max_length=20_000)
    error: str | None = Field(default=None, max_length=2_000)
    events: list[RunnerEvent] = Field(default_factory=list, max_length=200)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    cost_usd: float | None = Field(default=None, ge=0)


FileStatus = Literal["added", "modified", "deleted", "unchanged"]


class CodingDiff(BaseModel):
    base_sha: str | None = Field(description="The commit the turn started from")
    diff: str = Field(description="Its changes as a unified diff against base_sha (empty until it has any)")
    files: list[dict[str, Any]] = Field(description="Each changed file, with lines added and removed")


class CodingTreeEntry(BaseModel):
    path: str
    status: FileStatus
    size: int | None = Field(description="In bytes, as the turn leaves it (none for a deleted file)")


class CodingTree(BaseModel):
    base_sha: str
    entries: list[CodingTreeEntry] = Field(description="Every file as the turn leaves the repository, and those it deleted")
    truncated: bool = Field(description="More files than are listed (the first 20,000 are)")


class CodingFile(BaseModel):
    path: str
    status: FileStatus
    before: str | None = Field(description="Its text before the turn (none: it didn't exist, or isn't shown)")
    after: str | None = Field(description="Its text after the turn (none: deleted, or isn't shown)")
    binary: bool
    too_large: bool = Field(description="Over 1 MB: not shown")
