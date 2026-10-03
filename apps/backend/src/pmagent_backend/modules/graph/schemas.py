from __future__ import annotations

import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints, field_validator

from .models import EdgeKind, EdgeOrigin, NodeKind

# What people and agents may link by hand: the board's own structure (parents, dependencies)
# is set on the issues themselves.
LINKABLE = (
    EdgeKind.IMPLEMENTS, EdgeKind.DECIDED_BY, EdgeKind.AFFECTS, EdgeKind.SUPERSEDES, EdgeKind.MENTIONS,
    EdgeKind.RELATES_TO,
)

Ref = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]


class NodeRead(BaseModel):
    ref: str = Field(description='A document\'s path, an issue\'s key, or "module:<name>"')
    kind: NodeKind
    subtype: str | None = Field(description="A document's folder or an issue's type")
    title: str
    status: str | None = Field(description="An issue's status")


class LinkRead(BaseModel):
    id: uuid.UUID
    direction: Literal["out", "in"] = Field(description="out: this node points at the other; in: the other at this")
    kind: EdgeKind
    origin: EdgeOrigin
    agent: str | None
    reason: str | None
    node: NodeRead


class NeighborsRead(BaseModel):
    node: NodeRead
    links: list[LinkRead]


class ImpactItem(BaseModel):
    node: NodeRead
    depth: int = Field(description="Steps away (1: directly)")
    via: EdgeKind = Field(description="How it's reached on its shortest way")


class ImpactRead(BaseModel):
    node: NodeRead
    affected: list[ImpactItem]


class PathStep(BaseModel):
    node: NodeRead
    kind: EdgeKind | None = Field(description="The link from the previous step (none on the first)")
    direction: Literal["out", "in"] | None


class PathRead(BaseModel):
    found: bool
    steps: list[PathStep]


class StaleRead(BaseModel):
    node: NodeRead
    reasons: list[str]


class LinkCreate(BaseModel):
    source: Ref
    target: Ref
    kind: EdgeKind = EdgeKind.RELATES_TO
    reason: Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)] | None = None

    @field_validator("kind")
    @classmethod
    def _linkable(cls, kind: EdgeKind) -> EdgeKind:
        if kind not in LINKABLE:
            raise ValueError("Parents and dependencies are set on the issues themselves")
        return kind
