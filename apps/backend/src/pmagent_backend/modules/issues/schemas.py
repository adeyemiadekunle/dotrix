from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from .models import AgentAssignee, IssueEventKind, IssueStatus, IssueType, Priority


def _labels(values: list[str]) -> list[str]:
    seen: dict[str, None] = {}
    for value in values:
        cleaned = value.strip()
        if cleaned:
            seen.setdefault(cleaned, None)
    return list(seen)


Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
IssueKey = Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True, max_length=24)]
Labels = Annotated[list[Annotated[str, StringConstraints(max_length=64)]], Field(max_length=30), AfterValidator(_labels)]

AS_AGENT = Field(
    default=None,
    description="Set when a coding tool (Claude Code, Codex, the coding agent) is acting. It can only "
    "work on issues assigned to it: comment, add sub-tasks, and move its issue up to `review`.",
)


class Link(BaseModel):
    kind: Literal["pr", "commit", "doc", "adr", "other"] = "other"
    url: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
    title: str | None = Field(default=None, max_length=200)


class _AssigneeFields(BaseModel):
    assignee_user_id: uuid.UUID | None = None
    assignee_agent: AgentAssignee | None = None

    @model_validator(mode="after")
    def _one_assignee(self) -> _AssigneeFields:
        if self.assignee_user_id is not None and self.assignee_agent is not None:
            raise ValueError("Assign to a person or an agent, not both")
        return self


class IssueCreate(_AssigneeFields):
    type: IssueType = IssueType.TASK
    title: Title
    description: str = Field(default="", max_length=100_000)
    status: IssueStatus = IssueStatus.TODO
    priority: Priority = Priority.MEDIUM
    parent: IssueKey | None = Field(default=None, description="Parent issue key, e.g. KUN-1")
    estimate: float | None = Field(default=None, ge=0, le=10_000)
    due: date | None = None
    scheduled: datetime | None = None
    depends_on: list[IssueKey] = Field(default_factory=list, max_length=100)
    labels: Labels = Field(default_factory=list)
    components: Labels = Field(default_factory=list)
    links: list[Link] = Field(default_factory=list, max_length=100)
    as_agent: AgentAssignee | None = AS_AGENT


class IssueUpdate(_AssigneeFields):
    """Only the fields you send change. Send `null` to clear a field."""

    type: IssueType | None = None
    title: Title | None = None
    description: str | None = Field(default=None, max_length=100_000)
    status: IssueStatus | None = None
    priority: Priority | None = None
    parent: IssueKey | None = None
    estimate: float | None = Field(default=None, ge=0, le=10_000)
    due: date | None = None
    scheduled: datetime | None = None
    depends_on: list[IssueKey] | None = Field(default=None, max_length=100)
    labels: Labels | None = None
    components: Labels | None = None
    links: list[Link] | None = Field(default=None, max_length=100)
    note: str | None = Field(default=None, max_length=5_000, description="Added to the issue's log")
    as_agent: AgentAssignee | None = AS_AGENT


class CommentCreate(BaseModel):
    body: str = Field(min_length=1, max_length=20_000)
    as_agent: AgentAssignee | None = AS_AGENT


class RankRequest(BaseModel):
    before: IssueKey | None = Field(default=None, description="Put this issue just before that one")
    after: IssueKey | None = Field(default=None, description="…or just after that one")

    @model_validator(mode="after")
    def _exactly_one(self) -> RankRequest:
        if (self.before is None) == (self.after is None):
            raise ValueError("Give exactly one of `before` or `after`")
        return self


class ClaimRequest(BaseModel):
    key: IssueKey | None = Field(
        default=None, description="Claim this issue; omit to claim the next ready one"
    )
    as_agent: AgentAssignee | None = Field(
        default=None, description="Claim for this agent (e.g. claude-code) instead of yourself"
    )


class IssueSummary(BaseModel):
    """Board and list rows: everything except the description and log."""

    model_config = ConfigDict(from_attributes=True)

    key: str
    type: IssueType
    title: str
    status: IssueStatus
    priority: Priority
    assignee_user_id: uuid.UUID | None
    assignee_agent: AgentAssignee | None
    parent_key: str | None = None
    labels: list[str]
    estimate: float | None
    due: date | None
    rank: float
    updated_at: datetime


class WorkspaceIssue(IssueSummary):
    """An issue in a list across projects (My issues, Tasks): the row plus which project it's in."""

    project_id: uuid.UUID
    project_key: str
    project_name: str


class IssueEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    kind: IssueEventKind
    author_user_id: uuid.UUID | None
    author_agent: str | None
    body: str | None
    changes: dict[str, Any]
    created_at: datetime


class IssueRead(IssueSummary):
    id: uuid.UUID
    description: str
    reporter_user_id: uuid.UUID | None
    reporter_agent: str | None
    scheduled: datetime | None
    components: list[str]
    links: list[dict[str, Any]]
    created_at: datetime
    resolved_at: datetime | None
    depends_on: list[str] = Field(default_factory=list, description="Keys this issue is blocked by")
    blocks: list[str] = Field(default_factory=list, description="Keys blocked by this issue")
    children: list[str] = Field(default_factory=list)
    watchers: list[uuid.UUID] = Field(default_factory=list)
    ready: bool = Field(
        default=False,
        description="todo, and everything it depends on is done (assignment aside)",
    )
    log: list[IssueEventRead] = Field(default_factory=list)


class BoardColumn(BaseModel):
    status: IssueStatus
    issues: list[IssueSummary]


class Board(BaseModel):
    columns: list[BoardColumn]


class EpicProgress(BaseModel):
    key: str
    title: str
    status: IssueStatus
    total: int
    done: int
    percent: int = Field(description="Children done, 0-100")
