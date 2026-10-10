from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from dotrix_backend.modules.knowledge.models import AuthorType


class AuditEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID | None
    action: str
    target: str | None
    actor_type: AuthorType
    actor_user_id: uuid.UUID | None
    agent: str | None
    instructed_by_id: uuid.UUID | None
    approved_by_id: uuid.UUID | None
    details: dict[str, Any]
    created_at: datetime
