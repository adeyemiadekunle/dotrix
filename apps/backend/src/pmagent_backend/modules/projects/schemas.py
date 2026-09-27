from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
)

from .models import ProjectSource
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


class ProjectCreate(BaseModel):
    key: ProjectKey
    name: ProjectName
    description: Description = ""
    source: ProjectSource = ProjectSource.DOCS_ONLY
    model: ModelName | None = Field(default=None, description="Defaults to the server's default model")
    repo_url: Annotated[str, StringConstraints(max_length=500), AfterValidator(normalize_repo_url)] | None = Field(
        default=None,
        description="The repo's remote, e.g. https://github.com/acme/kunemi or git@github.com:acme/kunemi.git. "
        "Stored in canonical form (https, no .git, credentials removed) so the same repo always matches.",
    )
    readme: str | None = Field(
        default=None,
        max_length=100_000,
        description="An existing README to import into project.md (connect flow).",
    )


class ProjectUpdate(BaseModel):
    name: ProjectName | None = None
    description: Description | None = None
    model: ModelName | None = None


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    key: str
    name: str
    description: str
    source: ProjectSource
    repo_url: str | None
    model: str
    knowledge_revision: int
    created_at: datetime
    updated_at: datetime
