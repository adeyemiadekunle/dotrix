"""A connected repository's inventory and coverage (the Repository Knowledge skill's first step)."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status

from dotrix_backend.api.deps import SessionDep
from dotrix_backend.core.openapi import errors
from dotrix_backend.modules.agents.router import Agents
from dotrix_backend.modules.agents.schemas import AgentRunRead
from dotrix_backend.modules.code.checkouts import CodeCheckouts
from dotrix_backend.modules.projects.deps import KnowledgeEditor, ProjectViewer

from .models import PathStatus
from .schemas import (
    RepoCoverageRead,
    RepoExplainRequest,
    RepoPagesRead,
    RepoPathPage,
    RepoSnapshotRead,
)
from .service import PAGE_MAX, RepoKnowledgeService

router = APIRouter(
    prefix="/workspaces/{workspace_id}/projects/{project_id}/repository/knowledge",
    tags=["repository knowledge"],
    responses=errors(401, 404),
)


def get_checkouts(request: Request) -> CodeCheckouts | None:
    return getattr(request.app.state, "checkouts", None)


Checkouts = Annotated[CodeCheckouts | None, Depends(get_checkouts)]


@router.get("")
async def repository_coverage(access: ProjectViewer, session: SessionDep, checkouts: Checkouts) -> RepoCoverageRead:
    """What the connected repository's knowledge covers at its latest inventory: paths by status,
    and each required domain (evidence, pending, or a named gap). Anyone who sees the project."""
    return await RepoKnowledgeService(session, checkouts).coverage(access.project)


@router.post("/inventory", status_code=status.HTTP_201_CREATED, responses=errors(403, 409, 422))
async def take_repository_inventory(access: KnowledgeEditor, session: SessionDep, checkouts: Checkouts) -> RepoSnapshotRead:
    """List every tracked path at the repository's current commit, classified (nothing in it is
    run). Taken once per commit; it's also taken after each push. People who edit documents."""
    return await RepoKnowledgeService(session, checkouts).snapshot(access.project)


@router.post("/explain", status_code=status.HTTP_202_ACCEPTED, responses=errors(403, 409, 422, 503))
async def explain_repository(
    data: RepoExplainRequest, access: KnowledgeEditor, session: SessionDep, checkouts: Checkouts, agents: Agents,
) -> AgentRunRead:
    """Have the documentation agent explain the repository in the project's wiki (docs/wiki/), domain
    by domain: it reads what the inventory has left (taken first if the commit is new), records what
    it read, and proposes pages that cite their sources and name their gaps, each waiting for approval
    like any document. A new conversation; another run continues where this one stopped. People who
    edit documents."""
    service = RepoKnowledgeService(session, checkouts)
    await service.snapshot(access.project)
    stale = [p.path for p in (await service.pages(access.project)).pages if p.stale] if data.refresh else []
    return await agents.explain_repository(access, data.domains, stale=stale)


@router.get("/pages")
async def list_repository_pages(access: ProjectViewer, session: SessionDep, checkouts: Checkouts) -> RepoPagesRead:
    """The repository wiki's pages (docs/wiki/) and whether each is stale: a path it cites changed
    since it was read, left the repository, or was never read. Anyone who sees the project."""
    return await RepoKnowledgeService(session, checkouts).pages(access.project)


@router.get("/paths", responses=errors(422))
async def list_repository_paths(
    access: ProjectViewer, session: SessionDep, checkouts: Checkouts,
    status: PathStatus | None = None,
    domain: Annotated[str | None, Query(max_length=24, description="One of the coverage's domains")] = None,
    prefix: Annotated[str | None, Query(max_length=500, description="Only paths under this one")] = None,
    after: Annotated[str | None, Query(max_length=2000, description="The `next` of the page before")] = None,
    limit: Annotated[int, Query(ge=1, le=PAGE_MAX)] = 200,
) -> RepoPathPage:
    """The latest inventory's paths, in path order: what each is, its domains, and its status
    (with why, when it isn't read). Anyone who sees the project."""
    return await RepoKnowledgeService(session, checkouts).paths(
        access.project, status=status, domain=domain, prefix=prefix, after=after, limit=limit,
    )
