from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from .models import AutomationEvent

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Instructions = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
Hour = Annotated[int, Field(ge=0, le=23, description="Hour of the day, UTC")]
Weekday = Annotated[int, Field(ge=0, le=6, description="0 Monday … 6 Sunday")]
RunsPerDay = Annotated[int, Field(ge=1, le=1000, description="At most this many runs a day (UTC); null: no limit")]


class AutomationCreate(BaseModel):
    name: Name
    agent: str = Field(default="auto", max_length=32, description="`auto` (the Project Manager) or an agent's handle")
    instructions: Instructions = Field(description="What the agent should do each time, as you'd ask it in Chat")
    events: list[AutomationEvent] = Field(default_factory=list, max_length=5, description="What sets it off")
    schedule_hour: Hour | None = Field(default=None, description="Run every day (or `schedule_weekday`) at this hour, UTC")
    schedule_weekday: Weekday | None = None
    enabled: bool = True
    max_runs_per_day: RunsPerDay | None = None
    unattended: bool = Field(default=False, description="Its runs may make the changes the agent's contract allows without approval (owners turn it on); off: every change beyond comments and links asks")

    @model_validator(mode="after")
    def _when(self) -> AutomationCreate:
        if not self.events and self.schedule_hour is None:
            raise ValueError("Give it events to react to, a schedule, or both")
        if self.schedule_weekday is not None and self.schedule_hour is None:
            raise ValueError("A weekday needs an hour")
        return self


class AutomationUpdate(BaseModel):
    """Fields left out stay as they are; send null to clear the schedule or the daily cap."""

    name: Name | None = None
    agent: str | None = Field(default=None, max_length=32)
    instructions: Instructions | None = None
    events: list[AutomationEvent] | None = Field(default=None, max_length=5)
    schedule_hour: Hour | None = None
    schedule_weekday: Weekday | None = None
    enabled: bool | None = None
    max_runs_per_day: RunsPerDay | None = None
    unattended: bool | None = None


class AutomationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    agent: str = Field(description="`auto` or an agent's handle")
    instructions: str
    events: list[AutomationEvent]
    schedule_hour: int | None
    schedule_weekday: int | None
    enabled: bool
    max_runs_per_day: int | None = Field(description="Its own daily cap, if any (null: none)")
    unattended: bool = Field(description="Its runs may make the changes the agent's contract allows without approval (owners turn it on); off: every change beyond comments and links asks")
    created_by_id: uuid.UUID | None = Field(description="Whose instruction its runs carry")
    thread_id: uuid.UUID | None = Field(description="Its conversation in Chat (null until it first runs)")
    next_run_at: datetime | None
    last_run_at: datetime | None
    last_run_id: uuid.UUID | None
    last_error: str | None = Field(description="Why it last didn't run (null when it did)")
    runs_today: int = 0
    created_at: datetime
