"""Project-graph tools for agent runs (agents v2 step 3).

Reads (`graph_neighbors`, `graph_impact`, `graph_path`) run freely. `link_items` adds a link the
text doesn't make; it pauses for a person's approval like any write, unless an owner allowed
the agent to link without asking (a low-risk action), and is recorded with the agent, who
instructed the run, and who approved it.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import ValidationError

from pmagent_backend.core.errors import DomainError
from pmagent_backend.modules.audit.service import AuditLog
from pmagent_backend.modules.graph.schemas import LinkCreate, NodeRead
from pmagent_backend.modules.graph.service import GraphService, Linker
from pmagent_backend.modules.knowledge.models import AuthorType
from pmagent_backend.modules.projects.repository import ProjectRepository

from .board_tools import BoardContext
from .storage_backend import current_agent_role
from .unattended import REFUSED

GRAPH_TOOLS_GUIDE = """
## How things connect
The project graph links requirements, issues, decisions (ADRs), documents, and the modules
decisions affect, from what they say (issue keys, document paths, "Supersedes:", "Affected
modules:") and the board (epics, dependencies). Refer to things as "requirements/auth.md",
"KUN-12", or "module:auth".
- `graph_neighbors(ref)`: what something links to and what links to it.
- `graph_impact(ref)`: what a change to it affects (what implements, depends on, follows, or
  names it), before you propose a change.
- `graph_path(from_ref, to_ref)`: how two things connect.
- `link_items(source, target, kind, reason)`: link two things the text doesn't (ACTION MODE;
  pauses for approval).
"""


def _node(node: NodeRead) -> str:
    extra = f", {node.status}" if node.status else ""
    return f"{node.ref} ({node.subtype or node.kind}{extra}): {node.title}"


def build_graph_tools(ctx: BoardContext) -> list[Callable]:
    async def _read(fn: Callable[[GraphService, Any], Any]) -> Any:
        async with ctx.session_factory() as session:
            project = await ProjectRepository(session).get(ctx.workspace_id, ctx.project_id)
            if project is None:
                return "Error: the project is gone"
            try:
                return await fn(GraphService(session), project)
            except DomainError as exc:
                return f"Error: {exc.detail}"

    async def graph_neighbors(ref: str) -> str:
        """What something links to and what links to it.

        Args:
            ref: A document path ("requirements/auth.md"), an issue key ("KUN-12"), or "module:auth".
        """
        async def fn(graph: GraphService, project: Any) -> str:
            found = await graph.neighbors(project, ref)
            lines = [_node(found.node)]
            for link in found.links:
                arrow = f"-> {link.kind.value} ->" if link.direction == "out" else f"<- {link.kind.value} <-"
                lines.append(f"  {arrow} {_node(link.node)}")
            return "\n".join(lines) if found.links else f"{lines[0]}\n  (no links)"

        return await _read(fn)

    async def graph_impact(ref: str, depth: int = 2) -> str:
        """What a change to something affects: what implements it, depends on it, follows it,
        sits under it, or names it, and what relies on those in turn.

        Args:
            ref: A document path, an issue key, or "module:<name>".
            depth: How many steps away to look (1 to 3).
        """
        async def fn(graph: GraphService, project: Any) -> str:
            found = await graph.impact(project, ref, depth)
            if not found.affected:
                return f"Nothing in the graph relies on {found.node.ref}."
            return "\n".join([f"What relies on {_node(found.node)}:"] + [
                f"  {'  ' * (item.depth - 1)}{item.via.value}: {_node(item.node)}" for item in found.affected
            ])

        return await _read(fn)

    async def graph_path(from_ref: str, to_ref: str) -> str:
        """How two things connect: the shortest chain of links between them (up to four).

        Args:
            from_ref: A document path, an issue key, or "module:<name>".
            to_ref: The same.
        """
        async def fn(graph: GraphService, project: Any) -> str:
            found = await graph.path(project, from_ref, to_ref)
            if not found.found:
                return f"No connection between {from_ref} and {to_ref} within four links."
            parts = [found.steps[0].node.ref]
            for step in found.steps[1:]:
                kind = step.kind.value if step.kind else "?"
                parts.append(f"-{kind}->" if step.direction == "out" else f"<-{kind}-")
                parts.append(step.node.ref)
            return " ".join(parts)

        return await _read(fn)

    async def link_items(source: str, target: str, kind: str = "relates_to", reason: str = "") -> Any:
        """Link two things the text doesn't link. ACTION MODE ONLY: pauses for a person's approval unless allowed.

        Args:
            source: What the link is from (a path, an issue key, or "module:<name>").
            target: What it points at.
            kind: implements, decided_by, affects, supersedes, mentions, or relates_to.
            reason: Why, in a sentence (shown to people).
        """
        agent = current_agent_role()
        if ctx.instructed_by_id is None:
            return {"error": "Links need a person's instruction"}
        approved_by_id, rule = ctx.approved_by_id, None
        if approved_by_id is None:
            granted = ctx.unattended.grant(agent, "graph.link") if ctx.unattended else REFUSED
            if isinstance(granted, str):
                return {"error": granted}
            approved_by_id, rule = granted
        try:
            data = LinkCreate(source=source, target=target, kind=kind, reason=reason or None)
        except ValidationError as exc:
            return {"error": "; ".join(e["msg"] for e in exc.errors())}
        async with ctx.session_factory() as session:
            project = await ProjectRepository(session).get(ctx.workspace_id, ctx.project_id)
            if project is None:
                return {"error": "The project is gone"}
            try:
                await GraphService(session).link(
                    project, data, Linker(ctx.instructed_by_id, agent=agent, approved_by_id=approved_by_id)
                )
            except DomainError as exc:
                return {"error": exc.detail}
            if rule is not None:
                AuditLog(session).record(
                    workspace_id=ctx.workspace_id, project_id=ctx.project_id, action="graph.link.allowed",
                    target=f"{data.source} {data.kind.value} {data.target}"[:300], actor_type=AuthorType.AGENT,
                    agent=agent, instructed_by_id=ctx.instructed_by_id, approved_by_id=approved_by_id,
                    details={"rule": rule},
                )
                await session.commit()
        return {"linked": f"{data.source} {data.kind.value} {data.target}"}

    return [graph_neighbors, graph_impact, graph_path, link_items]
