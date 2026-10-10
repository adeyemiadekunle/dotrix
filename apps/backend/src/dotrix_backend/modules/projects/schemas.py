from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
)

from dotrix_backend.modules.workspaces.models import Role

from .models import (
    PROJECT_ICONS,
    ProjectAccessLevel,
    ProjectColor,
    ProjectHealth,
    ProjectSource,
    ProjectStatus,
)
from .repo_urls import normalize_repo_url

ProjectKey = Annotated[
    str,
    # Upper-case first: the pattern is checked before StringConstraints' own to_upper.
    BeforeValidator(lambda v: v.strip().upper() if isinstance(v, str) else v),
    StringConstraints(pattern=r"^[A-Z][A-Z0-9]{1,9}$"),
    Field(description="2-10 letters or digits, starting with a letter, e.g. KUN. Can't be changed."),
]
ProjectName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Description = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]

MODEL_PROVIDERS = ("anthropic", "openai", "google_genai")


def _model(value: str) -> str:
    provider, _, name = value.partition(":")
    if provider not in MODEL_PROVIDERS or not name.strip():
        raise ValueError(f"Use provider:model with provider one of {', '.join(MODEL_PROVIDERS)}")
    return f"{provider}:{name.strip()}"


ModelName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, max_length=100),
    AfterValidator(_model),
    Field(description="Chat model for the project's agents, e.g. google_genai:gemini-3.8-flash"),
]


def _icon(value: str) -> str:
    if value not in PROJECT_ICONS:
        raise ValueError(f"Use one of: {', '.join(sorted(PROJECT_ICONS))}")
    return value


ProjectIcon = Annotated[
    str,
    AfterValidator(_icon),
    Field(description="A Lucide icon name from the set the web app offers (globe, rocket, code, ...)"),
]


# A repo remote in any form, stored canonical (https, no .git, no credentials).
RepoUrl = Annotated[str, StringConstraints(max_length=500), AfterValidator(normalize_repo_url)]

class ProjectCreate(BaseModel):
    key: ProjectKey
    name: ProjectName
    description: Description = ""
    source: ProjectSource = ProjectSource.DOCS_ONLY
    model: ModelName | None = Field(default=None, description="Defaults to the server's default model")
    repo_url: RepoUrl | None = Field(
        default=None,
        description="The repo's remote, e.g. https://github.com/acme/kunemi or git@github.com:acme/kunemi.git. "
        "Stored in canonical form (https, no .git, credentials removed) so the same repo always matches.",
    )
    readme: str | None = Field(
        default=None,
        max_length=100_000,
        description="An existing README to import into project.md (connect flow).",
    )
    access: ProjectAccessLevel = Field(
        default=ProjectAccessLevel.WORKSPACE,
        description="workspace (every member sees it) or restricted (owners, admins, and the people added to it)",
    )
    icon: ProjectIcon | None = Field(default=None, description="Its icon; none shows its key's first letter")
    color: ProjectColor | None = Field(default=None, description="Its colour; none follows its key")


TokenBudget = Annotated[
    int,
    Field(
        ge=10_000,
        le=10_000_000,
        description="The most tokens (input + output, over all its steps) one agent run may use; "
        "a run that reaches it stops and says so",
    ),
]


class ProjectUpdate(BaseModel):
    access: ProjectAccessLevel | None = Field(
        default=None,
        description="workspace (every member) or restricted (owners, admins, and the people added to it)",
    )
    name: ProjectName | None = None
    description: Description | None = None
    model: ModelName | None = None
    specialist_model: ModelName | None = Field(
        default=None,
        description="A cheaper model for the specialists and for summarising long conversations. "
        "Send null to use the project's model; leave it out to keep the current one.",
    )
    token_budget: TokenBudget | None = Field(
        default=None, description="Send null for the server's default; leave it out to keep the current one."
    )
    repo_url: RepoUrl | None = Field(
        default=None,
        description="Link the project to its repo (any remote form; stored canonical). Send null to unlink; "
        "leave it out to keep the current link.",
    )
    health: ProjectHealth | None = Field(
        default=None, description="on_track, at_risk, or off_track; send null to clear, leave it out to keep it"
    )
    target_date: date | None = Field(
        default=None, description="When it should be done; send null to clear, leave it out to keep it"
    )
    status: ProjectStatus | None = Field(
        default=None, description="planning, active, on_hold, or completed; leave it out to keep it"
    )
    icon: ProjectIcon | None = Field(default=None, description="Send null for its key's letter; leave it out to keep it")
    color: ProjectColor | None = Field(default=None, description="Send null to follow its key; leave it out to keep it")
    archived: bool | None = Field(
        default=None, description="true archives it (out of the sidebar and Projects, kept as it is), false restores it"
    )


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    key: str
    name: str
    description: str
    source: ProjectSource
    repo_url: str | None
    access: ProjectAccessLevel = Field(
        description="workspace (every member sees it) or restricted (owners, admins, and the people added to it)"
    )
    model: str
    specialist_model: str | None = Field(
        description="The specialists' and summaries' model; null means the project's model"
    )
    token_budget: int | None = Field(description="Per-run token budget; null means the server's default")
    health: ProjectHealth | None = Field(description="How it's going, as its owners and admins say; null: not said")
    target_date: date | None = Field(description="When it should be done; null: no date")
    status: ProjectStatus = Field(description="planning, active, on_hold, or completed")
    icon: str | None = Field(description="A Lucide icon name; null: show its key's first letter")
    color: ProjectColor | None = Field(description="Its colour; null: the colour follows its key")
    archived_at: datetime | None = Field(default=None, description="When it was archived; null while in use")
    knowledge_revision: int
    created_at: datetime
    updated_at: datetime


class ProjectMove(BaseModel):
    workspace_id: uuid.UUID = Field(description="The workspace to move the project into")


class ProjectMemberRead(BaseModel):
    user_id: uuid.UUID
    email: str
    display_name: str
    role: Role = Field(description="Their role in the workspace")
    via: Literal["role", "workspace", "added"] = Field(
        description="Why they see it: their role (owners and admins see every project), the workspace "
        "(an open project), or being added to it (a restricted project)"
    )
    added: bool = Field(description="On the project's list (what counts once it's restricted)")
