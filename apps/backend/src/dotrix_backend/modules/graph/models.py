"""The project graph (agents v2 step 3): how a project's requirements, issues, decisions,
documents, and modules relate. Postgres tables walked with recursive queries, no graph database.

Nodes are the project's documents (by path), issues (by key), and the modules ADRs name.
Edges come from three places: `derived` ones from what we store (issue parents and
dependencies, and references found in documents and issues by `dotrix_engine.graph`), kept
current on every change; and links people and agents add (an agent's only with approval, or
an owner's standing rule). An edge keeps the reference it points at (`target_ref`), so a link
to something not there yet, or deleted, comes back when it is.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from dotrix_backend.db.base import Base, UUIDPrimaryKeyMixin, WorkspaceScopedMixin, str_enum


class NodeKind(enum.StrEnum):
    DOCUMENT = "document"
    ISSUE = "issue"
    MODULE = "module"


class EdgeKind(enum.StrEnum):
    IMPLEMENTS = "implements"  # an issue implements a requirement
    DEPENDS_ON = "depends_on"  # an issue waits for another
    PART_OF = "part_of"  # an issue sits under an epic (or a sub-task under its issue)
    DECIDED_BY = "decided_by"  # work follows a decision (ADR)
    AFFECTS = "affects"  # a decision affects a module
    SUPERSEDES = "supersedes"  # a decision replaces an older one
    MENTIONS = "mentions"  # anything that names something else
    RELATES_TO = "relates_to"  # a link someone added without a stronger kind


class EdgeOrigin(enum.StrEnum):
    DERIVED = "derived"
    PERSON = "person"
    AGENT = "agent"


class GraphNode(UUIDPrimaryKeyMixin, WorkspaceScopedMixin, Base):
    __tablename__ = "graph_nodes"
    __table_args__ = (UniqueConstraint("project_id", "ref"),)

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    kind: Mapped[NodeKind] = mapped_column(str_enum(NodeKind, 16))
    ref: Mapped[str] = mapped_column(String(300))  # the path, the issue key, or "module:<name>"
    subtype: Mapped[str | None] = mapped_column(String(32))  # a document's folder, an issue's type
    title: Mapped[str] = mapped_column(String(300))
    status: Mapped[str | None] = mapped_column(String(16))  # an issue's
    file_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("knowledge_files.id", ondelete="CASCADE"), index=True)
    issue_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("issues.id", ondelete="CASCADE"), index=True)
    # What was read: a document's version, an issue's last change.
    synced_version: Mapped[int | None]
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # When it last changed in a way that can make what relies on it stale: a document's
    # latest version, an issue's creation, or when it was done.
    changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GraphEdge(UUIDPrimaryKeyMixin, WorkspaceScopedMixin, Base):
    __tablename__ = "graph_edges"
    __table_args__ = (
        UniqueConstraint("source_id", "target_ref", "kind"),
        Index("ix_graph_edges_project_id_target_ref", "project_id", "target_ref"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("graph_nodes.id", ondelete="CASCADE"), index=True)
    target_ref: Mapped[str] = mapped_column(String(300))
    # Null while what it points at doesn't exist (yet, or any more).
    target_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("graph_nodes.id", ondelete="SET NULL"), index=True)
    kind: Mapped[EdgeKind] = mapped_column(str_enum(EdgeKind, 16))
    origin: Mapped[EdgeOrigin] = mapped_column(str_enum(EdgeOrigin, 16))
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    agent: Mapped[str | None] = mapped_column(String(32))
    reason: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
