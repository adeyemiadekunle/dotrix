"""The discovery run's tools (the `docs.repository` mode): what's left to read, marking it read,
and checking a page's citations against the inventory, so coverage counts what the agent really
read and every `path:line` it cites is in the repository at that commit.

The leading agent's alone, in that mode only. Marking read is bookkeeping on the inventory (no
document or board change), so it needs no approval; the pages themselves go through `write_file`
and its approval, like every document.
"""
from __future__ import annotations

import uuid
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from dotrix_backend.modules.projects.repository import ProjectRepository
from dotrix_engine.inventory import DOMAINS

from .models import PathStatus, RepoPath, RepoSnapshot
from .service import CITATION, RepoKnowledgeService

MODE = "docs.repository"
PAGE = 100  # paths per `repo_paths` call
MARK_MAX = 200


@dataclass(frozen=True)
class RepoContext:
    session_factory: Callable[[], AbstractAsyncContextManager[AsyncSession]]
    workspace_id: uuid.UUID
    project_id: uuid.UUID
    run_id: uuid.UUID
    root: Path | None  # the checkout, to count a cited file's lines (None: not checked)


class RepoPaths(BaseModel):
    domain: str = Field(description=f"One of: {', '.join(DOMAINS)}")
    after: str | None = Field(default=None, description="The `next` of the previous call, for the next page")


class MarkRead(BaseModel):
    paths: list[str] = Field(min_length=1, max_length=MARK_MAX, description="Paths you read, as `repo_paths` lists them")


class CheckPage(BaseModel):
    content: str = Field(max_length=200_000, description="The page you're about to write, in full")


def repo_tools(ctx: RepoContext) -> list[Any]:
    async def repo_coverage() -> dict[str, Any]:
        """The inventory's commit, and each knowledge domain: how many paths, how many read, or the gap."""
        return await _coverage(ctx)

    async def repo_stale_pages() -> dict[str, Any]:
        """The wiki's pages that cite paths changed since they were read, removed, or never read."""
        return await _stale(ctx)

    return [
        StructuredTool.from_function(coroutine=repo_coverage, name="repo_coverage"),
        StructuredTool.from_function(coroutine=repo_stale_pages, name="repo_stale_pages"),
        StructuredTool.from_function(
            coroutine=lambda **kw: _paths(ctx, RepoPaths(**kw)), name="repo_paths", args_schema=RepoPaths,
            description="A domain's paths still to read (pending), a page at a time, with their size and kind.",
        ),
        StructuredTool.from_function(
            coroutine=lambda **kw: _mark(ctx, MarkRead(**kw)), name="repo_mark_read", args_schema=MarkRead,
            description="Record that you read these paths, so coverage counts them and the next run skips them.",
        ),
        StructuredTool.from_function(
            coroutine=lambda **kw: _check(ctx, CheckPage(**kw)), name="repo_check_page", args_schema=CheckPage,
            description="Check a page's `path:line` citations against the repository before you write it.",
        ),
    ]


async def _coverage(ctx: RepoContext) -> dict[str, Any]:
    async with ctx.session_factory() as session:
        project = await ProjectRepository(session).get(ctx.workspace_id, ctx.project_id)
        if project is None:
            return {"error": "The project is gone"}
        coverage = await RepoKnowledgeService(session, None).coverage(project)
    if coverage.snapshot is None:
        return {"error": "There's no inventory yet: the project's repository isn't connected, or hasn't synced"}
    return {
        "commit": coverage.snapshot.commit_sha, "repository": coverage.snapshot.repo_full_name,
        "domains": [{"domain": d.domain, "title": d.title, "status": d.status, "paths": d.paths,
                     "read": d.analyzed, **({"gap": d.gap} if d.gap else {})} for d in coverage.domains],
    }


async def _stale(ctx: RepoContext) -> dict[str, Any]:
    async with ctx.session_factory() as session:
        project = await ProjectRepository(session).get(ctx.workspace_id, ctx.project_id)
        if project is None:
            return {"error": "The project is gone"}
        pages = await RepoKnowledgeService(session, None).pages(project)
    stale = [{"page": p.path, "sources": [s.model_dump() for s in p.stale]} for p in pages.pages if p.stale]
    return {"stale": stale, "fresh": [p.path for p in pages.pages if not p.stale]}


async def _paths(ctx: RepoContext, ask: RepoPaths) -> dict[str, Any]:
    if ask.domain not in DOMAINS:
        return {"error": f"Unknown domain {ask.domain!r}; use one of {', '.join(DOMAINS)}"}
    async with ctx.session_factory() as session:
        project = await ProjectRepository(session).get(ctx.workspace_id, ctx.project_id)
        if project is None:
            return {"error": "The project is gone"}
        page = await RepoKnowledgeService(session, None).paths(
            project, status=PathStatus.PENDING, domain=ask.domain, prefix=None, after=ask.after, limit=PAGE)
    return {"paths": [{"path": p.path, "size": p.size, "kinds": p.kinds, **({"language": p.language}
                                                                           if p.language else {})}
                      for p in page.paths], "next": page.next}


async def _mark(ctx: RepoContext, ask: MarkRead) -> dict[str, Any]:
    async with ctx.session_factory() as session:
        snapshot = await _latest(session, ctx)
        if snapshot is None:
            return {"error": "There's no inventory yet"}
        marked = (await session.execute(
            update(RepoPath).where(
                RepoPath.workspace_id == ctx.workspace_id, RepoPath.snapshot_id == snapshot,
                RepoPath.path.in_(ask.paths), RepoPath.status == PathStatus.PENDING,
            ).values(status=PathStatus.ANALYZED, analyzed_at=datetime.now(UTC), analyzed_run_id=ctx.run_id)
            .returning(RepoPath.path)
        )).scalars().all()
        await session.commit()
    unknown = sorted(set(ask.paths) - set(marked))
    return {"marked": len(marked), **({"not_marked": unknown[:50], "why": "not in the inventory, already read, or "
                                       "excluded"} if unknown else {})}


async def _check(ctx: RepoContext, ask: CheckPage) -> dict[str, Any]:
    cited = [(m.group(1), int(m.group(2)), int(m.group(3) or m.group(2))) for m in CITATION.finditer(ask.content)]
    if not cited:
        return {"error": "No citations found: cite each claim as `path:line` or `path:start-end`, in backticks"}
    async with ctx.session_factory() as session:
        snapshot = await _latest(session, ctx)
        if snapshot is None:
            return {"error": "There's no inventory yet"}
        known = set(await session.scalars(select(RepoPath.path).where(
            RepoPath.workspace_id == ctx.workspace_id, RepoPath.snapshot_id == snapshot,
            RepoPath.path.in_({p for p, _, _ in cited}),
        )))
    problems = []
    lines: dict[str, int | None] = {}
    for path, start, end in cited:
        if path not in known:
            problems.append(f"`{path}:{start}`: no such path in the repository")
            continue
        if start < 1 or end < start:
            problems.append(f"`{path}:{start}-{end}`: not a line range")
            continue
        if path not in lines:
            lines[path] = _line_count(ctx.root, path)
        count = lines[path]
        if count is not None and end > count:
            problems.append(f"`{path}:{start}-{end}`: the file has {count} lines")
    return {"citations": len(cited), "ok": not problems, **({"problems": problems[:50]} if problems else {})}


def _line_count(root: Path | None, path: str) -> int | None:
    if root is None:
        return None
    file = (root / path).resolve()
    if not file.is_relative_to(root.resolve()) or not file.is_file():
        return None
    with file.open("rb") as handle:
        return sum(1 for _ in handle)


async def _latest(session: AsyncSession, ctx: RepoContext) -> uuid.UUID | None:
    return await session.scalar(select(RepoSnapshot.id).where(
        RepoSnapshot.workspace_id == ctx.workspace_id, RepoSnapshot.project_id == ctx.project_id,
    ).order_by(RepoSnapshot.created_at.desc()).limit(1))
