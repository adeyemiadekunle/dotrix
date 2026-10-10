"""Research on the web (docs/agents-v2.md §6.2): the sources a run's agents found or read, and
the pages read, cached per workspace."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from dotrix_backend.db.base import Base, UUIDPrimaryKeyMixin, WorkspaceScopedMixin


class ResearchSource(UUIDPrimaryKeyMixin, WorkspaceScopedMixin, Base):
    """A page an agent saw in search results or read in full, under its id for the run
    (`S{number}`), which the report's claims cite."""

    __tablename__ = "research_sources"
    __table_args__ = (UniqueConstraint("run_id", "number"),)

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True)
    number: Mapped[int] = mapped_column(Integer)  # S3 -> 3
    url: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(String(300), default="")
    host: Mapped[str] = mapped_column(String(255), default="")
    tier: Mapped[str] = mapped_column(String(16))  # primary, reputable, other
    kind: Mapped[str] = mapped_column(String(8))  # search (seen in results) or page (read in full)
    snippet: Mapped[str] = mapped_column(Text, default="")
    published: Mapped[str | None] = mapped_column(String(40))
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    content_hash: Mapped[str | None] = mapped_column(String(64))
    via: Mapped[str | None] = mapped_column(String(8))  # direct, or tavily (their extract)
    # Why it looks like it addresses AI agents (empty: it doesn't).
    flagged: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    @property
    def label(self) -> str:
        return f"S{self.number}"


class WebPage(UUIDPrimaryKeyMixin, WorkspaceScopedMixin, Base):
    """A page as read, so research in the same workspace doesn't fetch it again for a day,
    and claims can be checked against it. Never shared across workspaces."""

    __tablename__ = "web_pages"
    __table_args__ = (UniqueConstraint("workspace_id", "url_key"),)

    url_key: Mapped[str] = mapped_column(String(64))  # sha256 of the normalised URL
    url: Mapped[str] = mapped_column(Text)
    final_url: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(String(300), default="")
    markdown: Mapped[str] = mapped_column(Text)
    content_type: Mapped[str] = mapped_column(String(64))
    published: Mapped[str | None] = mapped_column(String(40))
    content_hash: Mapped[str] = mapped_column(String(64))
    via: Mapped[str] = mapped_column(String(8))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
