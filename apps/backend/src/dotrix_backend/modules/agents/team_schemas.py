"""Public contracts for the fixed team and its private activity."""
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from dotrix_backend.modules.coding.models import CodingRunStatus
from dotrix_engine.delegation import SpecialistResult

from .models import RunStatus
from .schemas import ReviewRevision


class TeamMemberRead(BaseModel):
    handle: str
    name: str
    role: str
    kind: Literal["coordinator", "specialist", "coding"]
    built_in: bool = True
    customised: bool = False


class SpecialistTaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    parent_run_id: uuid.UUID | None
    project_id: uuid.UUID | None
    agent: str | None
    task_key: str | None
    message: str
    status: RunStatus
    depends_on: list[str] | None
    task_result: SpecialistResult | None
    error: str | None
    review_context: ReviewRevision | None
    updated_at: datetime


class AgentActivityRead(BaseModel):
    run_id: uuid.UUID
    parent_run_id: uuid.UUID | None
    thread_id: uuid.UUID | None
    session_id: uuid.UUID | None = None
    project_id: uuid.UUID
    project_key: str
    agent: str
    status: RunStatus | CodingRunStatus
    title: str
    source: str
    updated_at: datetime
