from __future__ import annotations

import uuid

from pydantic import BaseModel, Field

from .models import ChunkSource


class SearchHit(BaseModel):
    source: ChunkSource
    ref: str = Field(description="The document's path in `.pmagent/`, or the issue's key")
    heading: str | None = Field(description="The document section (its heading trail), or the issue's title")
    snippet: str = Field(description="The matching text (up to about 500 characters)")
    version: int = Field(description="The document version the text is from (0 for issues)")
    score: float = Field(description="Relevance (higher is better; only comparable within one search)")


class WorkspaceSearchHit(SearchHit):
    """A hit from any project you can see, with the project it's in."""

    project_id: uuid.UUID
    project_key: str
    project_name: str
