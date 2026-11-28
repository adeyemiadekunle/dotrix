from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from dotrix_backend.modules.workspaces.approval_modes import ApprovalMode

from .models import (
    CodingAgent,
    CodingInputKind,
    CodingInputStatus,
    CodingLocation,
    CodingOrigin,
    CodingRunStatus,
    CodingSessionState,
    PrState,
)


class CodingToolOption(BaseModel):
    agent: CodingAgent
    available: bool
    model: str | None = None
    models: list[str] = Field(default_factory=list)
    reason: str | None = None


class CodingAvailability(BaseModel):
    available: bool
    agent: CodingAgent | None = Field(
        description="Your compatible default tool: Codex with OpenAI, Claude Code with Anthropic, "
        "or OpenCode with another connected provider"
    )
    sandbox: str | None = Field(description="`docker`, `docker-cloud`, `openshell`, or `local` (development, no isolation)")
    reason: str | None = Field(description="Why not, when it isn't available")
    local_available: bool = Field(default=False, description="Whether you can code here on your own computer")
    local_runner: str | None = Field(default=None, description="Your computer that would code (the one seen last)")
    local_reason: str | None = Field(default=None, description="Why not on your computer")
    tools: list[CodingToolOption] = Field(default_factory=list)
    local_tools: list[CodingAgent] = Field(default_factory=list)
    default_tool: CodingAgent | None = None
    models: list[str] = Field(default_factory=list, description="Every model you can code on here (a new session picks one)")
    default_model: str | None = Field(default=None, description="The model a new session starts on: your default model when you can code on it")


_APPROVAL = ("`manual` (waits for an approver; the default) or `accept_edits` / `auto` (starts at once, approved "
             "by you), never above the workspace's cap, and Manual unless you may approve agent changes")


_LOCATION = ("Where it codes: `cloud` (a sandbox on the platform) or `local` (your own computer, through "
             "`dotrix runner` in a checkout of the project). A follow-up stays where its session is unless told.")


class CodingRunCreate(BaseModel):
    work_mode: Literal["plan", "build"] = "build"
    note: str | None = Field(default=None, max_length=5_000, description="Anything to add to the issue for the agent")
    approval_mode: ApprovalMode | None = Field(default=None, description=_APPROVAL)
    location: CodingLocation = Field(default=CodingLocation.CLOUD, description=_LOCATION)
    agent: CodingAgent | None = Field(default=None, description="The engine for this session; otherwise the one for its model "
                                      "(your preferred engine when it can run it, else the model's provider's own)")
    model: str | None = Field(default=None, max_length=100, description="The provider:model to code on; otherwise your default model")


class StandaloneCodingCreate(CodingRunCreate):
    note: str = Field(min_length=1, max_length=5_000, pattern=r"\S", description="What Kai should do")
    base_branch: str | None = Field(default=None, min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_][A-Za-z0-9_./-]*$",
                                    description="Existing GitHub branch; defaults to the repository's default")

    @field_validator("base_branch")
    @classmethod
    def valid_branch_path(cls, branch: str | None) -> str | None:
        if branch is not None and (".." in branch or branch.endswith(".") or any(
            not part or part.startswith(".") or part.endswith(".lock") for part in branch.split("/")
        )):
            raise ValueError("Use a valid Git branch name")
        return branch


class CodingFollowUp(BaseModel):
    work_mode: Literal["plan", "build"] = "build"
    source_plan_id: uuid.UUID | None = None
    step_by_step: bool = Field(default=False, description="With `source_plan_id`: build the plan one task a turn. This "
                               "turn does the first task; each other is queued as a turn of its own, in dependency order")
    plan_task: int | None = Field(default=None, ge=1, le=40, description="With `source_plan_id`: build only this task "
                                  "(its number in the plan, from 1), with the whole plan as context")
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
                      "`output-error` (a command's output, and whether it failed), `error`, or `background-<state>` "
                      "(a command Kai left running or one of its workers, `ref` naming it: running, done, failed, "
                      "stopped, or ended with the turn)")
    text: str
    ref: str | None = Field(default=None, description="Pairs a command (`tool`) with its output: the tool call's id")


class CodingEventRead(BaseModel):
    seq: int = Field(description="Its place in the run, from 0")
    at: datetime
    kind: str = Field(description="`step`, `text` (the agent's words), `tool` (what it did), `output` / "
                      "`output-error` (a command's output, and whether it failed), `error`, or `background-<state>` "
                      "(a command Kai left running or one of its workers, `ref` naming it: running, done, failed, "
                      "stopped, or ended with the turn)")
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


class CodingTaskRead(BaseModel):
    key: str
    status: str
    attempt: int = 0
    owned_paths: list[str] = Field(default_factory=list)
    checks: list[dict[str, Any]] = Field(default_factory=list)
    usage: dict[str, Any] = Field(default_factory=dict)


class CodingCapabilityRead(BaseModel):
    id: str
    label: str
    available: bool
    reason: str | None = None


class CodingSkillRead(BaseModel):
    name: str
    description: str
    sha256: str
    resources: list[str]
    missing_resources: list[str]
    unavailable_tools: list[str]


class CodingRunRead(BaseModel):
    environment_image_id: str | None = None
    capabilities: list[CodingCapabilityRead] = Field(default_factory=list)
    skills: list[CodingSkillRead] = Field(default_factory=list)
    tasks: list[CodingTaskRead] = Field(default_factory=list)
    work_mode: Literal["plan", "build"] = "build"
    plan_result: dict[str, Any] | None = None
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
    ci_sensitive: list[str] = Field(default_factory=list, description="Changed files CI runs (build scripts, "
                                    "test setup): a turn that changes any waits for a person to accept it, in every mode")
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
    review_posted_url: str | None = Field(default=None, description="Juno's review on GitHub, once posted on the PR")
    ci_state: Literal["passed", "failed"] | None = Field(
        default=None, description="CI on the turn's commit, from GitHub's check suites (null: none seen)")
    ci_review_run_id: uuid.UUID | None = Field(default=None, description="Juno's look at the failed CI, a run of its own")
    ci_review_posted_url: str | None = Field(default=None, description="That look on the PR's conversation, once posted")
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
    questions: list[str] = Field(default_factory=list, description="What Kai asked at the end of the turn (its final "
                                 "message's `questions` block); answer in the next turn. Queued messages wait until then")
    accepts_steering: bool = Field(default=False, description="Whether you may steer it now (POST .../sessions/{id}/inputs "
                                   "with `steer`): a cloud turn that's working, on an engine that takes a message mid-turn")


class CodingInputCreate(BaseModel):
    """A message to a session while Kai works: `steer` the working turn (it takes it at its next step; only when
    the turn's `accepts_steering`), or `queue` it for the next turn."""

    client_id: uuid.UUID = Field(description="Your own id for this message: sending it again returns the same one")
    kind: CodingInputKind
    message: str = Field(min_length=1, max_length=5_000)
    work_mode: Literal["plan", "build"] | None = Field(default=None, description="A queued message's turn (default: the last turn's)")
    approval_mode: ApprovalMode | None = Field(default=None, description=_APPROVAL)


class CodingInputRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    session_id: uuid.UUID
    run_id: uuid.UUID = Field(description="The turn working when it was sent")
    delivered_run_id: uuid.UUID | None = Field(description="The turn that took it")
    kind: CodingInputKind = Field(description="`steer` or `queue`; a steer the turn didn't take is queued instead")
    status: CodingInputStatus = Field(description="pending, sending, accepted, delivered, cancelled or rejected")
    message: str
    note: str | None = Field(description="Why it was queued instead, cancelled or refused")
    created_at: datetime
    updated_at: datetime


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
    sandbox: Literal["warm", "asleep"] | None = Field(
        default=None,
        description="Its cloud sandbox between turns: `warm` (running), `asleep` (stopped, files kept; deleted after "
        "the sleep days), or none (the next turn starts one). Whoever started it, or owners and admins, can delete it.",
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
    isolation: Literal["sbx", "srt", "none"] = Field(
        description="`sbx` (a Docker Sandboxes microVM on that computer), `srt` (the sandbox runtime), or `none` (a worktree only)"
    )
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
    # `background-<state>`: one of Kai's helpers (subagents), `ref` `worker:<id>`, at its latest state; Codes lists it
    # with the turn's background tasks, as a cloud turn's.
    kind: Literal["step", "text", "tool", "output", "output-error", "error", "background-running", "background-done",
                  "background-failed", "background-stopped", "background-ended"]
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
    source_sha: str | None = Field(default=None, description="Admitted starting commit for a standalone turn")
    managed_worktree: bool = Field(default=False, description="Reuse the worktree assigned to this session and runner")
    network: list[str] = Field(default_factory=list, description=(
        "Hosts the turn's sandboxed commands may reach (the session's pinned network policy, within the workspace's "
        "limit now). The runner's own DOTRIX_CODING_NETWORK_ALLOW may only narrow it"))
    helper_events: bool = Field(default=True, description=(
        "The platform takes `background-<state>` events for Kai's helpers (an older one doesn't say so, and a runner "
        "then reports them as steps)"))
    branch: str | None = Field(description="The session's branch to build on (a follow-up), else the base branch")


class CodingClaimed(BaseModel):
    run: CodingClaim | None = Field(description="None: nothing waits for this runner")


COMMIT_SHA = r"^[0-9a-f]{40}$"  # a full commit ID, as `git rev-parse` prints it


class RunnerSteerReport(BaseModel):
    """What the local driver said about a person's message to the working turn."""

    id: uuid.UUID
    state: Literal["pending", "sent", "accepted", "delivered", "cancelled", "rejected"] = Field(
        description="`pending`: the runner couldn't put it in the turn's inbox (it goes to the next turn)")
    message: str | None = Field(default=None, max_length=200)


class RunnerSteer(BaseModel):
    id: uuid.UUID
    message: str


class RunnerHeartbeat(BaseModel):
    lease_token: int
    events: list[RunnerEvent] = Field(default_factory=list, max_length=200)
    base_sha: str | None = Field(default=None, pattern=COMMIT_SHA)
    worktree: str | None = Field(default=None, max_length=1024, description="The turn's worktree on this computer")
    steering_open: bool = Field(default=False, description="The turn's inbox takes a person's messages (a runner that steers)")
    steering: list[RunnerSteerReport] = Field(default_factory=list, max_length=100)


class RunnerHeartbeatRead(BaseModel):
    stop: bool = Field(description="Stop the agent and report `stopped`")
    steers: list[RunnerSteer] = Field(default_factory=list, description="A person's messages for the working turn: "
                                      "put each in its inbox, and report its state on the next heartbeat")


class RunnerResult(BaseModel):
    lease_token: int
    steering: list[RunnerSteerReport] = Field(default_factory=list, max_length=100)
    outcome: Literal["changes", "no_changes", "failed", "stopped"]
    patch: str | None = Field(default=None, max_length=20_000_000, description="`git diff --cached --binary` against base_sha")
    patch_b64: str | None = Field(
        default=None, max_length=14_000_000,
        description="The same patch, base64-encoded: exact for files that aren't UTF-8 text. Wins over `patch`")
    base_sha: str | None = Field(default=None, pattern=COMMIT_SHA)
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


class SandboxNetworkUpdate(BaseModel):
    """A project's network policy: the hosts its coding sessions may reach besides the model API, within the
    workspace's limit. A new session pins it; follow-ups keep what their session pinned."""

    presets: list[str] = Field(default_factory=list, max_length=20,
                               description="Named presets (package registries), e.g. npm, pypi")
    hosts: list[str] = Field(default_factory=list, max_length=50, description=(
        "Exact host names, *.domain for one domain's hosts, either with :port (443 if none)"))


class SandboxNetworkLimitUpdate(SandboxNetworkUpdate):
    """The workspace's limit: the most any project's network policy may allow."""

    limited: bool = Field(default=False, description=(
        "Whether projects are limited to these presets and hosts. False: no limit (send no presets or hosts)"))


class SandboxNetworkRead(BaseModel):
    presets: list[str] = Field(description="The presets chosen here (a workspace: its limit's)")
    hosts: list[str] = Field(description="The hosts chosen here (a workspace: its limit's)")
    effective: list[str] = Field(description=(
        "A project: what its new sessions get, within the workspace's limit. A workspace: its limit's hosts"))
    limited: bool = Field(default=False, description="Whether the workspace limits what projects may allow")
    limit: list[str] | None = Field(default=None, description="The workspace's limit, expanded; None: no limit")
    outside_limit: list[str] = Field(default_factory=list, description=(
        "A project's chosen hosts that the workspace's limit leaves out (they aren't reached)"))
    available_presets: dict[str, dict[str, Any]] = Field(description="Each preset's name and its hosts")


class SharedCodingOutcomeRead(BaseModel):
    """Published PR evidence; no private brief, summary, events, keys or Chat references."""

    pr_number: int
    pr_url: str
    pr_state: PrState | None
    commit_sha: str | None
    turn: int
    finished_at: datetime | None
    ci_state: Literal["passed", "failed"] | None
    review_url: str | None
    ci_review_url: str | None
    session_id: uuid.UUID | None = Field(description="Only present for the coding session's owner")
