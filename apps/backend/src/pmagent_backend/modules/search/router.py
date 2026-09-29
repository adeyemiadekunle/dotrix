"""Search a project's documents and issues by keywords and meaning."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from pmagent_backend.api.deps import SessionDep
from pmagent_backend.core.openapi import errors
from pmagent_backend.modules.projects.deps import ProjectViewer

from .embeddings import Embedder
from .models import ChunkSource
from .schemas import SearchHit
from .service import KnowledgeIndex

router = APIRouter(
    prefix="/workspaces/{workspace_id}/projects/{project_id}/search",
    tags=["search"],
    responses=errors(401, 404),
)


def get_embedder(request: Request) -> Embedder | None:
    return getattr(request.app.state, "embedder", None)


@router.get("", responses=errors(422))
async def search_project(
    access: ProjectViewer,
    session: SessionDep,
    embedder: Annotated[Embedder | None, Depends(get_embedder)],
    q: Annotated[str, Query(min_length=1, max_length=500, description="What to look for, in any words")],
    source: Annotated[ChunkSource | None, Query(description="Only documents, or only issues")] = None,
    limit: Annotated[int, Query(ge=1, le=25)] = 8,
) -> list[SearchHit]:
    """Search the project's documents (by section) and issues. Exact terms (issue keys, names,
    error text) and paraphrases both match: full-text and meaning rankings are merged. Without
    an embedding model configured, keywords only."""
    hits = await KnowledgeIndex(session, embedder).search(access.project, q, limit=limit, source=source)
    return [SearchHit(**hit.__dict__) for hit in hits]
