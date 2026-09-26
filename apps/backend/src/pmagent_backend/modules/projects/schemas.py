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
    HttpUrl,
    StringConstraints,
)

from .models import ProjectSource

ProjectKey = Annotated[
    str,
    # Upper-case first: the pattern is checked before StringConstraints' own to_upper.
    BeforeValidator(lambda v: v.strip().upper() if isinstance(v, str) else v),
    StringConstraints(pattern=r"^[A-Z][A-Z0-9]{1,9}$"),
    Field(description="2-10 letters or digits, starting with a letter, e.g. KUN. Can't be changed."),
]
ProjectName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Description = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]


class ProjectCreate(BaseModel):
    key: ProjectKey
    name: ProjectName
    description: Description = ""
    source: ProjectSource = ProjectSource.DOCS_ONLY
    repo_url: Annotated[HttpUrl, AfterValidator(str)] | None = None
    readme: str | None = Field(
        default=None,
        max_length=100_000,
        description="An existing README to import into project.md (connect flow).",
    )


class ProjectUpdate(BaseModel):
    name: ProjectName | None = None
    description: Description | None = None


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
