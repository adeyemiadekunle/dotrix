from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

from dotrix_backend.modules.coding.models import CodingRunStatus
from dotrix_backend.modules.workspaces.approval_modes import ApprovalMode
from dotrix_engine.catalog import action_for

from .models import ApprovalStatus, ChatRuntime, RunEventKind, RunKind, RunStatus, WorkMode

# A built-in specialist hint. Nova remains the coordinator for interactive conversations.
AgentChoice = Annotated[str, Field(pattern=r"^(auto|[a-z][a-z0-9-]{1,30})$")]


class RunCreate(BaseModel):
    message: str = Field(min_length=1, max_length=20_000)
    thread_id: uuid.UUID | None = Field(
        default=None,
        description="Continue a conversation. Omit to start a new thread.",
    )
    agent: AgentChoice = Field(
        default="auto",
        description="`auto` lets Nova advise and coordinate, or name a built-in specialist to involve. "
        "Nova remains the coordinator. `coding-agent` requests Kai's involvement in Build mode. "
        "Unsupported handles return 422 `unknown_agent`",
    )
    model: str | None = Field(
        default=None,
        max_length=100,
        description="For a new conversation only: the model it runs on (one of `GET /v1/workspaces/{id}/models`; "
        "needs agents:choose_model unless it's the project's). Fixed for the whole conversation; omit to use "
        "the project's model.",
    )
    chat_runtime: ChatRuntime | None = Field(
        default=None,
        description="For a new project conversation: `deepagents` (default) or the opt-in read-only `fx` preview. "
        "A conversation keeps its runtime; omit on follow-up.",
    )
    work_mode: WorkMode | None = Field(
        default=None,
        description="How you're working: `discuss` (advice), `plan` (a versioned plan for the conversation, "
        "`.../threads/{id}/plans`), `build` (what you asked for: code goes to Kai), `review` (what changed, with "
        "its evidence). Changes wait for approval in every mode; only `build` engages Kai. Omit for no mode "
        "(as before work modes: no plans or evidence tools)",
    )
    approval_mode: ApprovalMode | None = Field(
        default=None,
        description="How much goes through without waiting: `manual` (every change waits for a yes; the "
        "default), `accept_edits` (what you ask for goes through, recorded as approved by you, and coding starts "
        "at once), `auto` (the same, and checkpoints don't pause). Never above the workspace's cap, and Manual for "
        "people who may not approve agent changes",
    )
    mentions: list[uuid.UUID] = Field(
        default_factory=list, max_length=20,
        description="People @mentioned (user ids). Each is told if \"@Their Name\" is in the text and they "
        "can see the project; others are ignored",
    )


class ChatRuntimeOptions(BaseModel):
    fx_available: bool = Field(description="Whether the read-only fx preview is enabled")
    fx_providers: list[str] = Field(description="Compatible providers; the requesting person must connect their own key")
    fx_delegation_available: bool = Field(default=False, description="Whether the fx preview may delegate read-only work")


class ModelOption(BaseModel):
    id: str = Field(description="provider:model, e.g. google_genai:gemini-3.8-flash")
    provider: str
    name: str = Field(description="The model's name without the provider")
    source: Literal["personal", "test"] = Field(
        default="personal", description="Your own key; test is reserved for the isolated test model"
    )


class TriageRequest(BaseModel):
    report: str = Field(
        min_length=1, max_length=10_000,
        description="The bug report or feature request, as it came in (an email, a support ticket, a note)",
    )


class ArchitectureDraftRequest(BaseModel):
    repo_summary: str | None = Field(
        default=None,
        max_length=60_000,
        description="Optional summary of the repository (file tree, manifests, README) made on the "
        "owner's machine. Never the source code itself.",
    )


class ApprovalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    run_id: uuid.UUID
    position: int
    tool: str = Field(description="e.g. write_file, edit_file")
    agent: str | None = Field(default=None, description="The handle of the agent whose change it is")
    action: str | None = Field(
        default=None,
        description="The autonomy action it takes (e.g. knowledge.write); with `agent`, what "
        "`.../always-allow` would let that agent do without asking",
    )
    target: str | None = Field(description="What the action changes, e.g. /dotrix/vision.md")
    args: dict[str, Any]
    diff: str | None = Field(description="For file writes: unified diff of what would change")
    status: ApprovalStatus
    reason: str | None
    decided_by_id: uuid.UUID | None
    decided_at: datetime | None
    created_at: datetime


    @model_validator(mode="after")
    def _action(self) -> ApprovalRead:
        if self.action is None:
            self.action = action_for(self.tool)
        return self


class WorkspaceApprovalRead(ApprovalRead):
    """A pending action with where it's from, for the workspace's approvals queue."""

    project_id: uuid.UUID
    project_key: str
    project_name: str
    run_message: str = Field(description="The instruction the run was given")
    requested_by_id: uuid.UUID | None = Field(description="Who instructed the run")


class WorkspaceThread(BaseModel):
    """A conversation, for the workspace's Chat list: which project it's in and how it stands."""

    thread_id: uuid.UUID
    project_id: uuid.UUID
    project_key: str
    project_name: str
    title: str = Field(description="The conversation's title (its first message if it has none)")
    kind: str = Field(description="`chat`, or `briefing` for a summary the platform wrote")
    updated_at: datetime
    waiting: bool = Field(description="A run in it waits for a decision")


class AgentRunCount(BaseModel):
    agent: str = Field(description="The agent the person picked (`auto` for the project manager's choice)")
    runs: int


class WorkspaceAgentUsage(BaseModel):
    """What the agents did across the workspace's projects in a period (owners and admins)."""

    days: int
    runs: int
    input_tokens: int
    output_tokens: int
    model_calls: int
    incomplete_usage_runs: int = Field(default=0, description="Runs whose model call or token usage is incomplete")
    approved: int = Field(description="Changes people approved")
    rejected: int = Field(description="Changes people rejected")
    by_agent: list[AgentRunCount] = Field(description="Runs per agent, most first")


class AgentUsage(BaseModel):
    agent: str = Field(description="project-manager, or the specialist's role (product, research, ...)")
    input_tokens: int
    output_tokens: int
    model_calls: int


class ToolUsage(BaseModel):
    tool: str
    calls: int
    result_tokens: int = Field(
        description="About how many tokens the tool's results added (re-sent with every later model call)"
    )


class RunFileRead(BaseModel):
    path: str
    times: int


class StageUsage(BaseModel):
    agent: str
    stage: str = Field(description="A pipeline stage the agent reported (dotrix_engine.pipelines)")
    input_tokens: int
    output_tokens: int
    model_calls: int


class WebUsageRead(BaseModel):
    searches: int = Field(description="Web searches the run made")
    fetches: int = Field(description="Web pages it read (pages from the workspace's cache aren't counted)")
    credits: int = Field(description="Tavily credits it used")
    flagged: list[str] = Field(description="Source ids of pages that addressed AI agents (their text was ignored)")


class RunBreakdown(BaseModel):
    """Where a run's tokens went."""

    by_agent: list[AgentUsage] = Field(description="Largest first")
    by_stage: list[StageUsage] = Field(
        default_factory=list, description="Tokens per pipeline stage, in the order the stages came"
    )
    tools: list[ToolUsage] = Field(description="Largest results first")
    files_read: list[RunFileRead] = Field(description="Most read first")
    token_budget: int | None = Field(description="The run's token budget (null: no limit)")
    web: WebUsageRead | None = Field(default=None, description="Its web searches and page reads (null: none)")


class QuoteCheck(BaseModel):
    source: str = Field(description="The source id the quote cites, e.g. S3")
    found: Literal["page", "snippet"] | None = Field(
        description="Where the quote was found: the page as read, only the search snippet, or nowhere"
    )


class ClaimCheck(BaseModel):
    """A report item checked against its sources (docs/agents-v2.md §6.3)."""

    status: Literal["supported", "weak", "unsupported"] = Field(
        description="supported: quoted from a primary or reputable page read in full; weak: only from snippets, "
        "`other` sources, or with low confidence; unsupported: no quote found (an assumption, not a finding)"
    )
    quotes: list[QuoteCheck]


class RunOutputItem(BaseModel):
    index: int
    data: dict[str, Any] = Field(description="The item, in its schema (e.g. a finding's severity, title, detail)")
    state: Literal["open", "done", "dismissed"]
    reason: str | None = Field(default=None, description="Why it was dismissed")
    link: str | None = Field(default=None, description="What it became, e.g. the issue key it was turned into")
    acted_by_id: uuid.UUID | None = None
    acted_at: datetime | None = None
    check: ClaimCheck | None = Field(default=None, description="For report items: the claim checked against its sources")


class RunOutputRead(BaseModel):
    """What the leading agent recorded as its result (its contract's output schema)."""

    id: uuid.UUID
    agent: str
    kind: str = Field(description="The output schema: finding, plan, spec, impact, report, doc_update, or brief")
    actions: list[str] = Field(description="What its items can become in the app, e.g. create_issue, dismiss")
    items: list[RunOutputItem]
    note: str | None = Field(default=None, description="For a report saved as a research note: the note's path")
    created_at: datetime


class OutputItemUpdate(BaseModel):
    state: Literal["done", "dismissed", "open"]
    reason: str | None = Field(default=None, max_length=500, description="Why it's dismissed (shown to the agent later)")
    link: str | None = Field(default=None, max_length=100, description="What it became, e.g. the issue key")


class SourceRead(BaseModel):
    """A web page the run's agents found or read, under the id its report cites."""

    model_config = ConfigDict(from_attributes=True)

    label: str = Field(description="The id claims cite, e.g. S3")
    url: str
    title: str
    host: str = Field(description="The site, e.g. gov.uk")
    tier: Literal["primary", "reputable", "other"] = Field(
        description="primary: government, regulators, standards bodies; reputable: established press, journals, "
        "universities; other: everything else"
    )
    kind: Literal["search", "page"] = Field(description="search: seen in results only; page: read in full")
    published: str | None = Field(description="When the page says it was published, as it says it")
    fetched_at: datetime | None = Field(description="When it was read (null: seen in results only)")
    flagged: list[str] = Field(description="Why it looks like it addresses AI agents (its text was ignored)")


class WorkspaceRunCreate(BaseModel):
    message: str = Field(min_length=1, max_length=20_000)
    thread_id: uuid.UUID | None = Field(default=None, description="Continue a conversation. Omit to start one.")
    project_ids: list[uuid.UUID] = Field(
        default_factory=list, max_length=10,
        description="For a new conversation: the projects it's about (none: about the workspace in general). "
        "Fixed from then on; 409 `scope_locked` if a continuation sends others",
    )
    agent: AgentChoice = Field(default="auto", description="`auto` or one of the workspace's agents")
    model: str | None = Field(default=None, max_length=100, description="For a new conversation only")


class WorkspaceConversation(BaseModel):
    thread_id: uuid.UUID
    title: str
    project_ids: list[uuid.UUID]
    project_keys: list[str]
    model: str | None
    updated_at: datetime
    working: bool = Field(description="A run in it is still answering")


class RunStopRead(BaseModel):
    """Acknowledges a stop without granting access to the conversation."""

    id: uuid.UUID
    status: RunStatus


class ReviewRevision(BaseModel):
    """Recorded coding evidence for a review and its automatic conversation summary."""

    coding_run_id: uuid.UUID
    session_id: uuid.UUID
    issue_key: str
    revision: str
    status: CodingRunStatus
    pr_url: str | None = None
    reported_summary: str | None = None
    error: str | None = None
    files: list[dict[str, Any]] = Field(default_factory=list)
    diff_truncated: bool = False
    verification: str


class TaskLifecycle(BaseModel):
    task_id: uuid.UUID
    agent: str
    status: RunStatus
    key: str | None = None


class AgentRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    parent_run_id: uuid.UUID | None = None
    source: str = "user"
    review_context: ReviewRevision | None = None
    orchestration: bool = False
    thread_id: uuid.UUID
    project_ids: Annotated[list[uuid.UUID], BeforeValidator(lambda v: v or [])] = Field(
        default_factory=list, description="A conversation across projects: the projects it's about (empty otherwise)"
    )
    kind: RunKind
    status: RunStatus
    message: str
    title: str | None = Field(
        default=None, description="The conversation's title; set on the first run of a thread"
    )
    reply: str | None
    error: str | None
    error_kind: str | None = Field(
        default=None, description="`model_limit`: it stopped at its model's limit; `interrupted`: its worker stopped "
        "again and again. Either can be continued (`.../continue`)",
    )
    resumes_at: datetime | None = Field(default=None, description="When the limit resets, if the provider said")
    continue_at_reset: bool = Field(default=False, description="It continues by itself once the limit resets")
    automation_id: uuid.UUID | None = Field(default=None, description="The automation that started it, if one did")
    requested_by_id: uuid.UUID | None
    agent: Annotated[str, BeforeValidator(lambda v: v or "auto")] = Field(
        default="auto", description="Who answered: `auto` (the Project Manager) or the leading agent's handle"
    )
    mode: str | None = Field(
        default=None, description="The pipeline the leading agent followed for this run (pm.triage, reviewer.issue); "
        "null: its own"
    )
    work_mode: WorkMode | None = Field(default=None, description="How the person was working when they sent it")
    approval_mode: Annotated[ApprovalMode, BeforeValidator(lambda v: v or "manual")] = Field(
        default=ApprovalMode.MANUAL, description="The approval mode in effect when it was sent",
    )
    conversation_model: str | None = Field(
        default=None,
        description="The model the conversation runs on (fixed when it started); null on older conversations, "
        "which use the project's model",
    )
    chat_runtime: ChatRuntime = Field(default=ChatRuntime.DEEPAGENTS, description="Runtime fixed for this conversation")
    # Usage is for owners and admins (the usage:view permission); null for everyone else.
    model: str | None = Field(
        default=None,
        description="The project's model when the run last worked, e.g. `google_genai:gemini-3.8-flash`. "
        "Owners and admins only (null otherwise)",
    )
    input_tokens: int | None = Field(
        default=None,
        description="Input (prompt) tokens over every model call of the run, subagents included. "
        "Owners and admins only (null otherwise)",
    )
    output_tokens: int | None = Field(
        default=None,
        description="Output tokens over every model call of the run, subagents included. "
        "Owners and admins only (null otherwise)",
    )
    cached_input_tokens: int | None = Field(
        default=None,
        description="Of the input tokens, how many the provider served from its prompt cache (cheaper). "
        "Owners and admins only (null otherwise)",
    )
    model_calls: int | None = Field(
        default=None,
        description="Model calls the run made (each re-sends the prompt). Owners and admins only (null otherwise)",
    )
    usage_complete: bool | None = Field(default=None, description="False when runtime usage is incomplete")
    breakdown: RunBreakdown | None = Field(
        default=None,
        description="Where the tokens went: by agent, by tool, and the files read. Owners and admins only "
        "(null otherwise)",
    )
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None
    approvals: list[ApprovalRead] = []
    outputs: list[RunOutputRead] = Field(default_factory=list, description="The structured results the run recorded")
    sources: list[SourceRead] = Field(default_factory=list, description="Web pages its agents found or read, by id")


class Decision(BaseModel):
    approval_id: uuid.UUID
    decision: Literal["approve", "reject", "steer"] = Field(
        description="approve or reject a change; at a checkpoint (tool `checkpoint`): approve to "
        "continue, steer to continue with the changes in `reason`, reject to stop"
    )
    reason: str | None = Field(
        default=None, max_length=500, description="Sent back to the agent when rejecting or steering"
    )


class DecisionsRequest(BaseModel):
    decisions: list[Decision] = Field(
        min_length=1, description="One decision for every pending approval of the run"
    )


class ThreadRename(BaseModel):
    title: str = Field(min_length=1, max_length=120)


class PlanTaskRead(BaseModel):
    title: str
    detail: str
    depends_on: list[int] = Field(description="The tasks (numbers, from 1) this one needs first")


class PlanRead(BaseModel):
    """A version of a conversation's plan, saved in Plan mode."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    thread_id: uuid.UUID
    version: int
    run_id: uuid.UUID = Field(description="The run that saved it")
    title: str
    summary: str
    acceptance_criteria: list[str]
    tasks: list[PlanTaskRead]
    open_questions: list[str]
    created_at: datetime


class ThreadRead(BaseModel):
    thread_id: uuid.UUID
    title: str


class ContinueRun(BaseModel):
    when_reset: bool = Field(
        default=False,
        description="Continue it automatically once the limit resets (when the provider said when), instead of now",
    )


class RunEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    seq: int = Field(description="1, 2, … per run: pass the last one you have as `after`")
    attempt: int = Field(description="Which attempt wrote it (a resumed run's later attempts count up)")
    kind: RunEventKind = Field(description="`step`: an attempt at a step began (its text starts over); `text`: a "
                               "piece of the reply; `activity`: what the agents were doing; `status`: the step's outcome")
    data: TaskLifecycle | dict[str, Any]
    created_at: datetime


class RunEventPage(BaseModel):
    events: list[RunEventRead]
    active: bool = Field(description="The run is still working: more events will come")


class ChatInputCreate(BaseModel):
    client_id: uuid.UUID
    kind: Literal["steer", "queue"]
    message: str = Field(min_length=1, max_length=20_000)
    work_mode: WorkMode = WorkMode.DISCUSS
    approval_mode: ApprovalMode = ApprovalMode.MANUAL


class ChatInputRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    run_id: uuid.UUID
    kind: Literal["steer", "queue"]
    status: Literal["pending", "sending", "accepted", "delivered", "cancelled", "rejected"]
    message: str
    delivered_run_id: uuid.UUID | None
    error: str | None
    created_at: datetime
