import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class GitHubImportPreviewCreate(BaseModel):
    page: int = Field(default=1, ge=1, le=10000)
    state: Literal["open", "closed", "all"] = "all"
    open_status: Literal["backlog", "todo"] = "backlog"


class GitHubImportItem(BaseModel):
    source_id: int
    number: int
    source_url: str
    title: str
    description: str
    status: Literal["backlog", "todo", "done"]
    labels: list[str]
    assignee_user_id: uuid.UUID | None
    assignee_name: str | None
    github_assignees: list[str]
    warnings: list[str]
    existing_key: str | None = None
    blocked: bool = False


class GitHubImportPreviewRead(BaseModel):
    id: uuid.UUID
    repository: str
    page: int
    has_more: bool
    skipped_pull_requests: int
    expires_at: datetime
    items: list[GitHubImportItem]


class GitHubImportConfirm(BaseModel):
    preview_id: uuid.UUID
    issue_ids: list[int] = Field(min_length=1, max_length=50)
    acknowledge_shared: Literal[True]


class GitHubImportResultItem(BaseModel):
    source_id: int
    issue_key: str
    outcome: Literal["created", "already_imported", "already_linked", "deleted_task"]


class GitHubImportResult(BaseModel):
    items: list[GitHubImportResultItem]
