"""The project graph: how requirements, issues, decisions, documents, and modules relate."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from pmagent_backend.api.deps import SessionDep
from pmagent_backend.core.openapi import errors
from pmagent_backend.modules.projects.deps import KnowledgeEditor, ProjectViewer

from .schemas import ImpactRead, LinkCreate, NeighborsRead, PathRead, StaleRead, SubgraphRead
from .service import MAX_IMPACT_DEPTH, MAX_VIEW_DEPTH, GraphService, Linker

router = APIRouter(
    prefix="/workspaces/{workspace_id}/projects/{project_id}/graph", tags=["graph"], responses=errors(401, 403, 404)
)

RefQuery = Annotated[str, Query(min_length=1, max_length=300, description="A document's path, an issue's key, or module:<name>")]


@router.get("/neighbors")
async def graph_neighbors(ref: RefQuery, access: ProjectViewer, session: SessionDep) -> NeighborsRead:
    """What something links to and what links to it: requirements an issue implements, its
    epic and dependencies, the decisions it follows, documents that name it, and links people
    and agents added."""
    return await GraphService(session).neighbors(access.project, ref)


@router.get("/impact")
async def graph_impact(
    ref: RefQuery, access: ProjectViewer, session: SessionDep,
    depth: Annotated[int, Query(ge=1, le=MAX_IMPACT_DEPTH)] = 2,
) -> ImpactRead:
    """What a change to something affects: what implements it, depends on it, follows it, sits
    under it, or names it, up to `depth` steps away; and the modules a decision affects."""
    return await GraphService(session).impact(access.project, ref, depth)


@router.get("/path")
async def graph_path(
    access: ProjectViewer, session: SessionDep,
    source: Annotated[str, Query(alias="from", min_length=1, max_length=300)],
    target: Annotated[str, Query(alias="to", min_length=1, max_length=300)],
) -> PathRead:
    """How two things connect: the shortest chain of links between them, either way, up to
    four links."""
    return await GraphService(session).path(access.project, source, target)


@router.get("/view")
async def graph_view(
    ref: RefQuery, access: ProjectViewer, session: SessionDep,
    depth: Annotated[int, Query(ge=1, le=MAX_VIEW_DEPTH)] = 2,
) -> SubgraphRead:
    """What's near something, to draw: nodes up to `depth` links away either way (nearest first,
    at most 60), each with the node it was reached from, and the links among them."""
    return await GraphService(session).subgraph(access.project, ref, depth)


@router.get("/stale")
async def graph_stale(access: ProjectViewer, session: SessionDep) -> list[StaleRead]:
    """Documents that may be out of date, with why: a document they build on changed after
    them, an issue they name or that builds on them was finished since, or a newer decision
    supersedes them."""
    return await GraphService(session).stale(access.project)


@router.post("/links", status_code=status.HTTP_201_CREATED, responses=errors(409, 422))
async def create_graph_link(data: LinkCreate, access: KnowledgeEditor, session: SessionDep) -> NeighborsRead:
    """Link two things the text doesn't link (people who may edit documents; audited
    `graph.linked`). Returns the source's links."""
    return await GraphService(session).link(access.project, data, Linker(access.member.user_id))


@router.delete("/links/{link_id}", status_code=status.HTTP_204_NO_CONTENT, responses=errors(409))
async def delete_graph_link(link_id: uuid.UUID, access: KnowledgeEditor, session: SessionDep) -> None:
    """Remove a link a person or an agent added (one derived from a document or an issue goes
    when its text changes: 409). Audited `graph.unlinked`."""
    await GraphService(session).unlink(access.project, link_id, Linker(access.member.user_id))
