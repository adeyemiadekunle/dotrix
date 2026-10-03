"""Keeping the project graph current, and walking it.

- `sync(project)` re-reads the documents and issues that changed since they were read (a
  document by version, an issue by its last change), replaces the links derived from them,
  and drops what's gone. Only database work, so every read runs it first.
- `neighbors`, `impact` (what relies on something, a recursive query), `path` (how two things
  connect), and `stale` (documents whose neighbours changed after them).
- `link` / `unlink`: links people and agents add by hand.

Every query is scoped by project (and so by workspace).
"""
from __future__ import annotations

import re
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, delete, exists, func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from pmagent_backend.core.errors import Conflict, NotFound
from pmagent_backend.modules.audit.service import AuditLog
from pmagent_backend.modules.issues.models import Issue, IssueDependency, IssueStatus
from pmagent_backend.modules.knowledge.models import AuthorType, KnowledgeFile
from pmagent_backend.modules.projects.models import Project
from pmagent_engine.graph import find_references, folder

from .models import EdgeKind, EdgeOrigin, GraphEdge, GraphNode, NodeKind
from .schemas import (
    ImpactItem,
    ImpactRead,
    LinkCreate,
    LinkRead,
    NeighborsRead,
    NodeRead,
    PathRead,
    PathStep,
    StaleRead,
    SubgraphRead,
    ViewEdge,
    ViewNode,
)

NOT_IN_GRAPH = ("agent-rules/",)  # instructions for the agents, not the project
MAX_IMPACT_DEPTH = 3
MAX_PATH_HOPS = 4
MAX_RESULTS = 200
MAX_REASONS = 5
MAX_VIEW_DEPTH = 2
MAX_VIEW_NODES = 60
_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9]*-\d+$")


def _now() -> datetime:
    return datetime.now(UTC)


def node_read(node: GraphNode) -> NodeRead:
    return NodeRead(ref=node.ref, kind=node.kind, subtype=node.subtype, title=node.title, status=node.status)


@dataclass(frozen=True)
class Linker:
    """Who adds a link by hand: a person, or an agent (instructed and approved)."""

    user_id: uuid.UUID | None
    agent: str | None = None
    approved_by_id: uuid.UUID | None = None


class GraphService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # -- keeping it current ------------------------------------------------------------------

    async def sync(self, project: Project) -> int:
        """Re-read what changed; returns how many documents and issues were (re)read or dropped.

        One sync per project at a time: a second waits for the first, then finds nothing to do."""
        await self.session.execute(
            select(func.pg_advisory_xact_lock(func.hashtextextended(f"graph:{project.id}", 0)))
        )
        nodes = {n.ref: n for n in await self.session.scalars(select(GraphNode).where(GraphNode.project_id == project.id))}
        files = (await self.session.execute(
            select(KnowledgeFile.id, KnowledgeFile.path, KnowledgeFile.version, KnowledgeFile.updated_at,
                   KnowledgeFile.title)
            .where(KnowledgeFile.project_id == project.id, KnowledgeFile.deleted.is_(False),
                   *(~KnowledgeFile.path.startswith(p) for p in NOT_IN_GRAPH))
        )).all()
        issues = (await self.session.execute(
            select(Issue.id, Issue.key, Issue.type, Issue.title, Issue.status, Issue.updated_at, Issue.created_at,
                   Issue.resolved_at)
            .where(Issue.project_id == project.id)
        )).all()

        live_files, live_issues = {f.id for f in files}, {i.id for i in issues}
        gone = [
            n for n in nodes.values()
            if (n.kind is NodeKind.DOCUMENT and n.file_id not in live_files)
            or (n.kind is NodeKind.ISSUE and n.issue_id not in live_issues)
        ]
        for node in gone:
            await self.session.delete(node)
            del nodes[node.ref]
        if gone:
            await self.session.flush()

        changed: list[tuple[GraphNode, Any]] = []
        for f in files:
            node = nodes.get(f.path)
            if node is not None and node.file_id == f.id and node.synced_version == f.version:
                continue
            node = node or self._node(project, f.path, NodeKind.DOCUMENT, nodes)
            node.file_id, node.synced_version = f.id, f.version
            node.subtype, node.title = folder(f.path) or None, (f.title or f.path.rsplit("/", 1)[-1])[:300]
            node.changed_at = f.updated_at
            changed.append((node, f))
        for i in issues:
            node = nodes.get(i.key)
            if node is not None and node.issue_id == i.id and node.synced_at == i.updated_at:
                continue
            node = node or self._node(project, i.key, NodeKind.ISSUE, nodes)
            node.issue_id, node.synced_at = i.id, i.updated_at
            node.subtype, node.title, node.status = i.type.value, i.title[:300], i.status.value
            node.changed_at = i.resolved_at if i.status is IssueStatus.DONE and i.resolved_at else i.created_at
            changed.append((node, i))
        if not changed and not gone:
            return 0
        await self.session.flush()

        # Links waiting for something that now exists find it.
        await self.session.execute(
            update(GraphEdge)
            .where(GraphEdge.project_id == project.id, GraphEdge.target_id.is_(None), GraphNode.project_id == project.id,
                   GraphNode.ref == GraphEdge.target_ref)
            .values(target_id=GraphNode.id)
        )
        if changed:
            await self._derive(project, changed, nodes, [f.path for f in files], {i.id: i.key for i in issues})
        # Modules exist only while a decision names them.
        await self.session.execute(
            delete(GraphNode).where(
                GraphNode.project_id == project.id, GraphNode.kind == NodeKind.MODULE,
                ~exists().where(GraphEdge.target_id == GraphNode.id),
            )
        )
        await self.session.commit()
        return len(changed) + len(gone)

    def _node(self, project: Project, ref: str, kind: NodeKind, nodes: dict[str, GraphNode]) -> GraphNode:
        node = GraphNode(workspace_id=project.workspace_id, project_id=project.id, ref=ref, kind=kind, title=ref)
        self.session.add(node)
        nodes[ref] = node
        return node

    async def _derive(
        self, project: Project, changed: list[tuple[GraphNode, Any]], nodes: dict[str, GraphNode],
        paths: list[str], keys: dict[uuid.UUID, str],
    ) -> None:
        """Replace the derived links of what changed."""
        await self.session.execute(
            delete(GraphEdge).where(GraphEdge.source_id.in_([n.id for n, _ in changed]),
                                    GraphEdge.origin == EdgeOrigin.DERIVED)
        )
        file_ids = [row.id for n, row in changed if n.kind is NodeKind.DOCUMENT]
        issue_ids = [row.id for n, row in changed if n.kind is NodeKind.ISSUE]
        contents = dict((await self.session.execute(
            select(KnowledgeFile.id, KnowledgeFile.content).where(KnowledgeFile.id.in_(file_ids))
        )).all()) if file_ids else {}
        details = {row.id: row for row in (await self.session.execute(
            select(Issue.id, Issue.description, Issue.links, Issue.parent_id).where(Issue.id.in_(issue_ids))
        )).all()} if issue_ids else {}
        blockers: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
        if issue_ids:
            for issue_id, depends_on_id in (await self.session.execute(
                select(IssueDependency.issue_id, IssueDependency.depends_on_id)
                .where(IssueDependency.issue_id.in_(issue_ids))
            )).all():
                blockers[issue_id].append(depends_on_id)

        now = _now()
        for node, row in changed:
            links: dict[str, tuple[EdgeKind, str | None]] = {}  # target -> (kind, module name)
            if node.kind is NodeKind.DOCUMENT:
                refs = find_references(contents.get(row.id, ""), source=row.path, project_key=project.key, paths=paths)
            else:
                d = details[row.id]
                link_text = "\n".join(f"{link.get('url', '')} {link.get('title', '')}" for link in d.links or [])
                refs = find_references(f"{d.description}\n{link_text}", source=row.key, project_key=project.key,
                                       paths=paths, is_issue=True)
                for blocker in blockers[row.id]:
                    if blocker in keys:
                        links[keys[blocker]] = (EdgeKind.DEPENDS_ON, None)
                if d.parent_id in keys:
                    links[keys[d.parent_id]] = (EdgeKind.PART_OF, None)
            for ref in refs:
                links.setdefault(ref.target, (EdgeKind(ref.kind), ref.title))
            for target, (kind, module) in links.items():
                if module is not None and target not in nodes:
                    self._node(project, target, NodeKind.MODULE, nodes).title = module[:300]
                    await self.session.flush()
                target_node = nodes.get(target)
                self.session.add(GraphEdge(
                    workspace_id=project.workspace_id, project_id=project.id, source_id=node.id, target_ref=target,
                    target_id=target_node.id if target_node is not None else None, kind=kind,
                    origin=EdgeOrigin.DERIVED, created_at=now,
                ))
        await self.session.flush()

    # -- reading -----------------------------------------------------------------------------

    async def _get(self, project: Project, ref: str) -> GraphNode:
        node = await self.session.scalar(
            select(GraphNode).where(GraphNode.project_id == project.id, GraphNode.ref == _clean(ref))
        )
        if node is None:
            raise NotFound(f"Nothing called {ref} in this project's graph")
        return node

    async def neighbors(self, project: Project, ref: str) -> NeighborsRead:
        await self.sync(project)
        node = await self._get(project, ref)
        rows = (await self.session.execute(
            select(GraphEdge, GraphNode)
            .join(GraphNode, or_(
                and_(GraphEdge.source_id == node.id, GraphNode.id == GraphEdge.target_id),
                and_(GraphEdge.target_id == node.id, GraphNode.id == GraphEdge.source_id),
            ))
            .where(GraphEdge.project_id == project.id)
            .order_by(GraphEdge.kind, GraphNode.ref)
            .limit(MAX_RESULTS)
        )).all()
        return NeighborsRead(node=node_read(node), links=[
            LinkRead(id=edge.id, direction="out" if edge.source_id == node.id else "in", kind=edge.kind,
                     origin=edge.origin, agent=edge.agent, reason=edge.reason, node=node_read(other))
            for edge, other in rows
        ])

    async def impact(self, project: Project, ref: str, depth: int = 2) -> ImpactRead:
        """What relies on `ref`: what implements it, depends on it, follows it, sits under it, or
        names it, and in turn what relies on those; plus the modules a decision affects."""
        await self.sync(project)
        node = await self._get(project, ref)
        depth = max(1, min(depth, MAX_IMPACT_DEPTH))
        rows = (await self.session.execute(text("""
            WITH RECURSIVE walk(node_id, depth, via) AS (
                SELECT CAST(:start AS uuid), 0, CAST(NULL AS varchar)
                UNION
                SELECT CASE WHEN e.target_id = w.node_id THEN e.source_id ELSE e.target_id END, w.depth + 1, e.kind
                FROM walk w
                JOIN graph_edges e ON e.project_id = :project AND (
                    e.target_id = w.node_id OR (e.source_id = w.node_id AND e.kind = 'affects' AND e.target_id IS NOT NULL)
                )
                WHERE w.depth < :depth
            )
            SELECT DISTINCT ON (node_id) node_id, depth, via FROM walk
            WHERE node_id <> CAST(:start AS uuid)
            ORDER BY node_id, depth, via
        """), {"start": node.id, "project": project.id, "depth": depth})).all()
        found = {r.node_id: r for r in rows}
        others = {n.id: n for n in await self.session.scalars(select(GraphNode).where(GraphNode.id.in_(found)))}
        items = sorted(
            (ImpactItem(node=node_read(others[i]), depth=r.depth, via=EdgeKind(r.via)) for i, r in found.items() if i in others),
            key=lambda item: (item.depth, item.node.kind, item.node.ref),
        )
        return ImpactRead(node=node_read(node), affected=items[:MAX_RESULTS])

    async def path(self, project: Project, source: str, target: str) -> PathRead:
        """The shortest way two things connect, in either direction, up to four links."""
        await self.sync(project)
        start, goal = await self._get(project, source), await self._get(project, target)
        previous: dict[uuid.UUID, tuple[uuid.UUID, GraphEdge] | None] = {start.id: None}
        frontier = [start.id]
        for _ in range(MAX_PATH_HOPS):
            if goal.id in previous or not frontier:
                break
            edges = await self.session.scalars(select(GraphEdge).where(
                GraphEdge.project_id == project.id, GraphEdge.target_id.is_not(None),
                or_(GraphEdge.source_id.in_(frontier), GraphEdge.target_id.in_(frontier)),
            ))
            reached = []
            for edge in edges:
                for here, there in ((edge.source_id, edge.target_id), (edge.target_id, edge.source_id)):
                    if here in frontier and there is not None and there not in previous:
                        previous[there] = (here, edge)
                        reached.append(there)
            frontier = reached
        if goal.id not in previous:
            return PathRead(found=False, steps=[])
        chain: list[tuple[uuid.UUID, GraphEdge | None]] = []
        current: uuid.UUID | None = goal.id
        while current is not None:
            step = previous[current]
            chain.append((current, step[1] if step else None))
            current = step[0] if step else None
        chain.reverse()
        found = {n.id: n for n in await self.session.scalars(select(GraphNode).where(GraphNode.id.in_([c for c, _ in chain])))}
        return PathRead(found=True, steps=[
            PathStep(node=node_read(found[node_id]), kind=edge.kind if edge else None,
                     direction=None if edge is None else ("out" if edge.target_id == node_id else "in"))
            for node_id, edge in chain
        ])

    async def subgraph(self, project: Project, ref: str, depth: int = 2) -> SubgraphRead:
        """Everything up to `depth` links from `ref`, either way, nearest first (at most
        MAX_VIEW_NODES), with the links among them: for drawing."""
        await self.sync(project)
        center = await self._get(project, ref)
        depth = max(1, min(depth, MAX_VIEW_DEPTH))
        reached: dict[uuid.UUID, tuple[int, uuid.UUID | None]] = {center.id: (0, None)}
        frontier, truncated = [center.id], False
        for level in range(1, depth + 1):
            if not frontier:
                break
            edges = await self.session.scalars(select(GraphEdge).where(
                GraphEdge.project_id == project.id, GraphEdge.target_id.is_not(None),
                or_(GraphEdge.source_id.in_(frontier), GraphEdge.target_id.in_(frontier)),
            ).order_by(GraphEdge.kind, GraphEdge.created_at))
            here = set(frontier)
            frontier = []
            for edge in edges:
                for a, b in ((edge.source_id, edge.target_id), (edge.target_id, edge.source_id)):
                    if a in here and b is not None and b not in reached:
                        if len(reached) >= MAX_VIEW_NODES:
                            truncated = True
                            continue
                        reached[b] = (level, a)
                        frontier.append(b)
        nodes = {n.id: n for n in await self.session.scalars(select(GraphNode).where(GraphNode.id.in_(reached)))}
        edges = await self.session.scalars(select(GraphEdge).where(
            GraphEdge.project_id == project.id, GraphEdge.source_id.in_(reached), GraphEdge.target_id.in_(reached),
        ))
        return SubgraphRead(
            nodes=[
                ViewNode(**node_read(nodes[i]).model_dump(), depth=d,
                         parent=nodes[p].ref if p is not None and p in nodes else None)
                for i, (d, p) in sorted(reached.items(), key=lambda item: item[1][0]) if i in nodes
            ],
            edges=[ViewEdge(source=nodes[e.source_id].ref, target=nodes[e.target_id].ref, kind=e.kind)  # type: ignore[index]
                   for e in edges],
            truncated=truncated,
        )

    async def stale(self, project: Project) -> list[StaleRead]:
        """Documents that may be out of date: a document they build on changed after them, an
        issue they name or that implements them was finished after them, or a newer decision
        supersedes them."""
        await self.sync(project)
        docs = {n.id: n for n in await self.session.scalars(
            select(GraphNode).where(GraphNode.project_id == project.id, GraphNode.kind == NodeKind.DOCUMENT)
        )}
        if not docs:
            return []
        edges = list(await self.session.scalars(select(GraphEdge).where(
            GraphEdge.project_id == project.id, GraphEdge.target_id.is_not(None),
            or_(GraphEdge.source_id.in_(docs), GraphEdge.target_id.in_(docs)),
        )))
        ends = {e.source_id for e in edges} | {e.target_id for e in edges}
        nodes = {n.id: n for n in await self.session.scalars(select(GraphNode).where(GraphNode.id.in_(ends)))}
        reasons: dict[uuid.UUID, list[str]] = defaultdict(list)

        def newer(other: GraphNode, doc: GraphNode) -> bool:
            return bool(other.changed_at and doc.changed_at and other.changed_at > doc.changed_at)

        for edge in edges:
            source, target = nodes.get(edge.source_id), nodes.get(edge.target_id)  # type: ignore[arg-type]
            if source is None or target is None:
                continue
            if edge.source_id in docs and edge.kind is EdgeKind.MENTIONS:
                if target.kind is NodeKind.DOCUMENT and newer(target, source):
                    reasons[source.id].append(f"{target.ref} changed since")
                elif target.kind is NodeKind.ISSUE and target.status == IssueStatus.DONE and newer(target, source):
                    reasons[source.id].append(f"{target.ref} ({target.title}) was finished since")
            if edge.target_id in docs:
                if edge.kind is EdgeKind.SUPERSEDES and source.kind is NodeKind.DOCUMENT:
                    reasons[target.id].append(f"superseded by {source.ref}")
                elif (edge.kind in (EdgeKind.IMPLEMENTS, EdgeKind.DECIDED_BY) and source.kind is NodeKind.ISSUE
                      and source.status == IssueStatus.DONE and newer(source, target)):
                    reasons[target.id].append(f"{source.ref} ({source.title}), which builds on it, was finished since")
        found = [StaleRead(node=node_read(docs[i]), reasons=r[:MAX_REASONS]) for i, r in reasons.items()]
        return sorted(found, key=lambda s: (-len(s.reasons), s.node.ref))[:MAX_RESULTS]

    # -- links by hand -----------------------------------------------------------------------

    async def link(self, project: Project, data: LinkCreate, by: Linker) -> NeighborsRead:
        await self.sync(project)
        source, target = await self._get(project, data.source), await self._get(project, data.target)
        if source.id == target.id:
            raise Conflict("A link needs two different things")
        if await self.session.scalar(select(GraphEdge.id).where(
            GraphEdge.source_id == source.id, GraphEdge.target_ref == target.ref, GraphEdge.kind == data.kind
        )):
            raise Conflict(f"{source.ref} already {data.kind.value.replace('_', ' ')} {target.ref}")
        self.session.add(GraphEdge(
            workspace_id=project.workspace_id, project_id=project.id, source_id=source.id, target_ref=target.ref,
            target_id=target.id, kind=data.kind, origin=EdgeOrigin.AGENT if by.agent else EdgeOrigin.PERSON,
            created_by_id=by.user_id, agent=by.agent, reason=data.reason, created_at=_now(),
        ))
        self._audit(project, "graph.linked", f"{source.ref} {data.kind.value} {target.ref}", by,
                    {"reason": data.reason})
        await self.session.commit()
        return await self.neighbors(project, source.ref)

    async def unlink(self, project: Project, edge_id: uuid.UUID, by: Linker) -> None:
        edge = await self.session.scalar(
            select(GraphEdge).where(GraphEdge.project_id == project.id, GraphEdge.id == edge_id)
        )
        if edge is None:
            raise NotFound("No such link in this project")
        if edge.origin is EdgeOrigin.DERIVED:
            raise Conflict("This link comes from what the document or issue says: change that instead")
        source = await self.session.get(GraphNode, edge.source_id)
        self._audit(project, "graph.unlinked", f"{source.ref if source else '?'} {edge.kind.value} {edge.target_ref}",
                    by, {"origin": edge.origin.value})
        await self.session.delete(edge)
        await self.session.commit()

    def _audit(self, project: Project, action: str, target: str, by: Linker, details: dict[str, Any]) -> None:
        AuditLog(self.session).record(
            workspace_id=project.workspace_id, project_id=project.id, action=action, target=target[:300],
            actor_type=AuthorType.AGENT if by.agent else AuthorType.USER,
            actor_user_id=None if by.agent else by.user_id, agent=by.agent,
            instructed_by_id=by.user_id if by.agent else None, approved_by_id=by.approved_by_id, details=details,
        )


def _clean(ref: str) -> str:
    """A reference as people and agents write it: "/pmagent/requirements/a.md", "kun-4"."""
    ref = ref.strip()
    for prefix in ("/pmagent/", "pmagent/", "/"):
        if ref.startswith(prefix):
            ref = ref[len(prefix):]
    return ref.upper() if _KEY.match(ref) else ref
