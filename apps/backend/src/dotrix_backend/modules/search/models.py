"""The search index over a project's documents and issues (plan Phase 2: hybrid search).

Each document is split by heading section and each issue is one chunk (key, title, fields,
description, recent comments). A chunk carries its text, a full-text vector (Postgres
`tsvector`, kept by the database), and a meaning vector (pgvector) made by an embedding model
in the background. Search merges both rankings, so exact terms (issue keys, names, error
text) and paraphrases both match.

The index is derived data: it can be dropped and rebuilt from knowledge and issues at any time.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import Computed, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from dotrix_backend.db.base import Base, UUIDPrimaryKeyMixin, WorkspaceScopedMixin, str_enum

# Every embedding model is asked for vectors of this size (Gemini and OpenAI models can
# shorten theirs), so switching models needs a re-embed, not a migration.
EMBEDDING_DIMENSIONS = 768


class ChunkSource(enum.StrEnum):
    DOCUMENT = "document"
    ISSUE = "issue"


class KnowledgeChunk(UUIDPrimaryKeyMixin, WorkspaceScopedMixin, Base):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        Index("ix_knowledge_chunks_project_id_source", "project_id", "source"),
        Index("ix_knowledge_chunks_tsv", "tsv", postgresql_using="gin"),
        Index(
            "ix_knowledge_chunks_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    source: Mapped[ChunkSource] = mapped_column(str_enum(ChunkSource, 16))
    file_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("knowledge_files.id", ondelete="CASCADE"), index=True
    )
    issue_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("issues.id", ondelete="CASCADE"), index=True)
    # The document's path or the issue's key, as people and agents refer to it.
    ref: Mapped[str] = mapped_column(String(300))
    # The section's heading trail ("Requirements > Goals"), if any.
    heading: Mapped[str | None] = mapped_column(String(300))
    position: Mapped[int]  # order within the document
    content: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    # What was indexed: the document's version, or the issue's last change.
    version: Mapped[int]
    source_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    tsv: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed(
            "setweight(to_tsvector('english', coalesce(ref, '') || ' ' || coalesce(heading, '')), 'A') "
            "|| to_tsvector('english', content)",
            persisted=True,
        ),
    )
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIMENSIONS))
    embedding_model: Mapped[str | None] = mapped_column(String(100))
