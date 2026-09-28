from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from .models import DocumentStatus


class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    content_type: str
    size: int = Field(description="Bytes of the original")
    sha256: str
    knowledge_path: str = Field(
        description="Where the converted markdown lives in the project's knowledge, "
        "e.g. docs/normalized/spec.md"
    )
    knowledge_version: int = Field(description="The knowledge file version this upload produced; 0 until ready")
    status: DocumentStatus = Field(
        description="`converting` right after upload (a background job makes the markdown), then `ready`, "
        "or `failed` with `error`"
    )
    error: str | None = Field(default=None, description="Why the conversion failed")
    uploaded_by_id: uuid.UUID | None
    created_at: datetime
