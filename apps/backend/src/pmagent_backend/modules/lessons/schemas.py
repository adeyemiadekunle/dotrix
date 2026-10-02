from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from .models import LessonSource, LessonStatus


class LessonRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agent: str = Field(description="The agent it's for (its handle; project-manager is Auto)")
    text: str = Field(description="The lesson as the agent will read it")
    source: LessonSource
    reason: str = Field(description="What the person said when rejecting or dismissing")
    run_id: uuid.UUID | None
    status: LessonStatus
    proposed_by_id: uuid.UUID | None = Field(description="Whose rejection or dismissal it came from")
    decided_by_id: uuid.UUID | None
    decided_at: datetime | None
    created_at: datetime


class LessonAccept(BaseModel):
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=600)] | None = Field(
        default=None, description="The lesson in your words (default: as proposed)"
    )
