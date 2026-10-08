from __future__ import annotations

import uuid
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
Icon = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]
Color = Annotated[str, StringConstraints(pattern=r"^#[0-9A-Fa-f]{6}$")]


class TeamCreate(BaseModel):
    name: Name
    description: str = Field(default="", max_length=500)
    icon: Icon = "users"
    color: Color = "#8A867E"


class TeamUpdate(BaseModel):
    """Only the fields you send change."""

    name: Name | None = None
    description: str | None = Field(default=None, max_length=500)
    icon: Icon | None = None
    color: Color | None = None


class TeamRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str
    icon: str
    color: str
    member_ids: list[uuid.UUID] = Field(default_factory=list, description="The people in the team, in the order they joined")
    project_ids: list[uuid.UUID] = Field(
        default_factory=list, description="The projects it looks after, among those you can see"
    )
