"""Conversations across projects (UI redesign Phase 3): a chat about several of the workspace's
projects at once, or none.

Such a run belongs to the workspace (`AgentRun.project_id` is null) and lists its projects in
`project_ids`, fixed when the conversation starts. It's read-only: agents read each project's
documents (under /dotrix/<KEY>/), boards, and search, but never change anything. A change is
made in that project's own conversation, where it waits for approval as always. A conversation
is private to whoever started it, and only while they still see every project in it.
"""
from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from uuid_utils.compat import uuid7

from dotrix_backend.core.errors import Conflict, Forbidden, NotFound
from dotrix_backend.modules.agent_definitions.repository import AgentDefinitionRepository
from dotrix_backend.modules.audit.service import AuditLog
from dotrix_backend.modules.auth.models import User
from dotrix_backend.modules.issues.models import Issue, IssueStatus
from dotrix_backend.modules.knowledge.models import AuthorType
from dotrix_backend.modules.knowledge.repository import KnowledgeRepository
from dotrix_backend.modules.model_keys.service import run_keys
from dotrix_backend.modules.projects.models import Project
from dotrix_backend.modules.projects.repository import visible_to
from dotrix_backend.modules.search.embeddings import Embedder
from dotrix_backend.modules.search.models import ChunkSource
from dotrix_backend.modules.search.service import KnowledgeIndex
from dotrix_backend.modules.workspaces.models import Membership
from dotrix_backend.modules.workspaces.permissions import Permission, can
from dotrix_engine.contracts import PM_HANDLE, AgentSpec

from .board_tools import BoardContext, build_board_tools
from .models import ACTIVE_STATUSES, AgentRun, RunKind, RunStatus
from .schemas import AgentRunRead, WorkspaceConversation, WorkspaceRunCreate
from .storage_backend import SessionFactory
from .titles import title_from_message

MAX_PROJECTS = 10
EXCERPT_CHARS = 700
# What a read-only conversation never gets, whatever the agents' contracts say.
WRITE_TOOLS = ("knowledge.write", "issues.create", "issues.update", "issues.comment", "graph.link", "code.read",
               "graph.read")

WORKSPACE_GUIDE = """
## A conversation across projects
This conversation is about the projects listed in the context, not one project. Each project's
documents are under /dotrix/<KEY>/ (for example /dotrix/KUN/requirements/). Read its board
with list_issues(project="KUN") and get_issue("KUN-12"), and search them all with
search_knowledge(query) (or one, with project="KUN").

It's read-only: you can't change documents or boards here. When the person wants a change, say
what you'd change and in which project, and suggest they ask in that project's conversation,
where it waits for their approval. Compare and summarise across projects freely; say which
project each fact comes from.
"""


def _now() -> datetime:
    return datetime.now(UTC)


def read_only(spec: AgentSpec) -> AgentSpec:
    """The contract without anything that writes (or works on one project only)."""
    return spec.model_copy(update={"tools": [t for t in spec.tools if t not in WRITE_TOOLS], "pipeline": None})


# -- context ---------------------------------------------------------------------------


def _excerpt(text: str, limit: int = EXCERPT_CHARS) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[:limit].rsplit("\n", 1)[0] + "\n…(trimmed)"


async def build_workspace_pack(session: AsyncSession, projects: list[Project], visible: list[Project]) -> str:
    """Each project in the conversation: what it is, its current state, and its board in
    numbers. With none, the workspace's projects by name, so agents can say where to ask."""
    if not projects:
        lines = [
            "# Context: the workspace",
            "This conversation isn't about any one project. The projects you could be asked about (the person "
            "can open a conversation about any of them):",
            *(f"- {p.key}: {p.name}" + (f": {p.description}" if p.description else "") for p in visible),
        ]
        return "\n".join(lines)
    parts = [f"# Context: {len(projects)} projects", "Built by the platform for this run. Read a file before relying on it."]
    for project in projects:
        files = {f.path: f for f in await KnowledgeRepository(session).list_files(project.id) if not f.deleted}
        counts = dict((await session.execute(
            select(Issue.status, func.count()).where(Issue.project_id == project.id).group_by(Issue.status)
        )).all())
        overdue = await session.scalar(select(func.count()).where(
            Issue.project_id == project.id, Issue.status != IssueStatus.DONE, Issue.due < _now().date()
        )) or 0
        board = ", ".join(f"{counts.get(s, 0)} {s.value.replace('_', ' ')}" for s in IssueStatus) + f"; {overdue} overdue"
        parts += [
            f"## {project.key}: {project.name}",
            *([project.description] if project.description else []),
            f"Documents: {len(files)} under /dotrix/{project.key}/. Board: {board}.",
            *(
                [f"Current state (/dotrix/{project.key}/current-state.md):", _excerpt(f.content)]
                if (f := files.get("current-state.md")) is not None and f.content.strip() else []
            ),
        ]
    return "\n\n".join(parts)


# -- tools -----------------------------------------------------------------------------


def build_workspace_tools(
    session_factory: SessionFactory,
    *,
    workspace_id: uuid.UUID,
    projects: list[Project],
    instructed_by_id: uuid.UUID,
    embedder: Embedder | None,
) -> tuple[list[Callable], list[Callable]]:
    """(board reads, search) over the conversation's projects, read-only."""
    keys = {p.key: p for p in projects}
    boards = {
        p.key: build_board_tools(BoardContext(
            session_factory=session_factory, workspace_id=workspace_id, project_id=p.id,
            instructed_by_id=instructed_by_id, approved_by_id=None,
        ))[0]
        for p in projects
    }

    def _project(key: str | None) -> str | None:
        found = (key or "").strip().upper()
        return found if found in keys else None

    async def list_issues(
        project: str,
        status: str | None = None,
        type: str | None = None,  # noqa: A002 - the field's name in the issue model
        assignee: str | None = None,
        label: str | None = None,
        epic: str | None = None,
        ready_only: bool = False,
    ) -> Any:
        """List one project's issues in backlog order (up to 200).

        Args:
            project: The project's key, e.g. "KUN".
            status: todo, in_progress, blocked, review, or done.
            type: epic, story, task, bug, spike, or sub-task.
            assignee: A user ID, "claude-code", "codex", "coding-agent", or "none".
            label: Only issues with this label.
            epic: Only children of this epic key.
            ready_only: Only issues that could start now.
        """
        key = _project(project)
        if key is None:
            return {"error": f"Not a project in this conversation; use one of {', '.join(keys)}"}
        return await boards[key][0](status=status, type=type, assignee=assignee, label=label, epic=epic,
                                    ready_only=ready_only)

    async def get_issue(key: str) -> Any:
        """Get one issue in full, from any project in this conversation.

        Args:
            key: The issue key, e.g. "KUN-42".
        """
        project = _project(key.rsplit("-", 1)[0])
        if project is None:
            return {"error": f"{key} isn't in a project of this conversation ({', '.join(keys)})"}
        return await boards[project][1](key)

    async def search_knowledge(query: str, project: str | None = None, only: str | None = None, limit: int = 8) -> str:
        """Search the projects' documents (by section) and issues for a topic, in any words.

        Args:
            query: What you're looking for.
            project: One project's key to search just it; omit for all of them.
            only: "documents" or "issues".
            limit: How many results (1-10).
        """
        source = {"documents": ChunkSource.DOCUMENT, "issues": ChunkSource.ISSUE}.get((only or "").strip().lower())
        wanted = [keys[k] for k in ([_project(project)] if project else keys) if k is not None]
        if project and not wanted:
            return f"Not a project in this conversation; use one of {', '.join(keys)}"
        hits = []
        async with session_factory() as session:
            index = KnowledgeIndex(session, embedder)
            for p in wanted:
                hits += [(p, hit) for hit in await index.search(p, query, limit=max(1, min(int(limit), 10)), source=source)]
        hits.sort(key=lambda pair: pair[1].score, reverse=True)
        if not hits:
            return f"Nothing found for {query!r}."
        lines = []
        for number, (p, hit) in enumerate(hits[: max(1, min(int(limit), 10))], 1):
            where = (f"{hit.ref} (issue in {p.key}): {hit.heading}" if hit.source is ChunkSource.ISSUE
                     else f"/dotrix/{p.key}/{hit.ref}" + (f", {hit.heading}" if hit.heading else ""))
            lines.append(f"{number}. {where}\n   " + "\n   ".join(hit.snippet.splitlines()))
        return "\n".join(lines)

    return [list_issues, get_issue], [search_knowledge]


# -- the API's side ----------------------------------------------------------------------


class ScopeLocked(Conflict):
    code = "scope_locked"


class ThreadBusy(Conflict):
    code = "thread_busy"


class WorkspaceRunService:
    def __init__(self, session: AsyncSession, runner: Any) -> None:
        self.session = session
        self.runner = runner

    async def _visible(self, member: Membership, ids: list[uuid.UUID]) -> list[Project]:
        found = {p.id: p for p in await self.session.scalars(
            select(Project).where(Project.workspace_id == member.workspace_id, Project.id.in_(ids),
                                  visible_to(member.user_id, member.role))
        )} if ids else {}
        if len(found) != len(set(ids)):
            raise NotFound("Project not found")
        return [found[i] for i in dict.fromkeys(ids)]

    async def create(
        self, member: Membership, data: WorkspaceRunCreate, *, default_model: str, available: list[str]
    ) -> AgentRunRead:
        if data.thread_id is not None:
            first = await self._first(member, data.thread_id)
            if any(s in ACTIVE_STATUSES for s in await self.session.scalars(
                select(AgentRun.status).where(AgentRun.workspace_id == member.workspace_id,
                                              AgentRun.thread_id == data.thread_id)
            )):
                raise ThreadBusy("This conversation is still answering; wait for it, or stop it")
            if data.project_ids and set(data.project_ids) != set(first.project_ids or []):
                raise ScopeLocked("A conversation keeps the projects it started with; start a new one for others")
            if data.model and data.model != first.conversation_model:
                raise ScopeLocked("A conversation keeps the model it started with; start a new one for another")
            project_ids, model, thread_id = list(first.project_ids or []), first.conversation_model, data.thread_id
        else:
            project_ids, thread_id = list(dict.fromkeys(data.project_ids)), uuid7()
            model = data.model or default_model
            if model != default_model:
                if not can(member, Permission.CHOOSE_MODEL):
                    raise Forbidden("Only owners and admins (or members the workspace allows) choose the model")
                if model not in available:
                    raise ScopeLocked(f"{model} can't run here; choose one of: {', '.join(available) or 'none'}")
            # Fail fast (503) if the model can't run.
            keys = (await run_keys(self.session, self.runner.secrets, member.workspace_id, member.user_id)).keys
            self.runner.model_factory(SimpleNamespace(model=model, specialist_model=None), model, keys=keys)
        projects = await self._visible(member, project_ids)
        if data.agent != "auto":
            handles = {a.spec.handle for a in await AgentDefinitionRepository(self.session).resolve(member.workspace_id)}
            if data.agent not in handles:
                raise NotFound(f"This workspace has no @{data.agent} agent")
        now = _now()
        run = AgentRun(
            workspace_id=member.workspace_id, project_id=None, project_ids=[p.id for p in projects],
            thread_id=thread_id, kind=RunKind.CHAT, status=RunStatus.QUEUED, message=data.message,
            title=title_from_message(data.message) if data.thread_id is None else None,
            agent=None if data.agent in ("auto", PM_HANDLE) else data.agent, conversation_model=model,
            requested_by_id=member.user_id, created_at=now, updated_at=now,
        )
        self.session.add(run)
        AuditLog(self.session).record(
            workspace_id=member.workspace_id, action="agent_run.started", target=str(run.id),
            actor_type=AuthorType.USER, actor_user_id=member.user_id, instructed_by_id=member.user_id,
            details={"kind": "chat", "thread_id": str(thread_id), "agent": data.agent, "model": model,
                     "projects": [p.key for p in projects]},
        )
        await self.session.commit()
        await self.runner.start(run.id, data.message)
        return await self.get(member, run.id)

    async def _first(self, member: Membership, thread_id: uuid.UUID) -> AgentRun:
        first = await self.session.scalar(
            select(AgentRun).where(
                AgentRun.workspace_id == member.workspace_id, AgentRun.project_id.is_(None),
                AgentRun.thread_id == thread_id, AgentRun.requested_by_id == member.user_id,
            ).order_by(AgentRun.created_at).limit(1)
        )
        if first is None:
            raise NotFound("Conversation not found")
        await self._visible(member, list(first.project_ids or []))  # 404 once a project is out of sight
        return first

    async def _run(self, member: Membership, run_id: uuid.UUID, *, lock: bool = False) -> AgentRun:
        stmt = select(AgentRun).where(
            AgentRun.workspace_id == member.workspace_id, AgentRun.project_id.is_(None), AgentRun.id == run_id,
            AgentRun.requested_by_id == member.user_id,
        )
        run = await self.session.scalar(stmt.with_for_update() if lock else stmt.options(
            selectinload(AgentRun.approvals), selectinload(AgentRun.output_rows), selectinload(AgentRun.source_rows)
        ).execution_options(populate_existing=True))
        if run is None:
            raise NotFound("Run not found")
        await self._visible(member, list(run.project_ids or []))
        return run

    async def get(self, member: Membership, run_id: uuid.UUID) -> AgentRunRead:
        return _read(member, await self._run(member, run_id))

    async def check_run(self, member: Membership, run_id: uuid.UUID) -> None:
        await self._run(member, run_id, lock=False)

    async def list_runs(self, member: Membership, thread_id: uuid.UUID) -> list[AgentRunRead]:
        await self._first(member, thread_id)
        runs = await self.session.scalars(
            select(AgentRun).options(
                selectinload(AgentRun.approvals), selectinload(AgentRun.output_rows), selectinload(AgentRun.source_rows)
            ).where(AgentRun.workspace_id == member.workspace_id, AgentRun.project_id.is_(None),
                    AgentRun.thread_id == thread_id).order_by(AgentRun.created_at.desc())
        )
        return [_read(member, r) for r in runs]

    async def conversations(self, member: Membership, *, limit: int = 50) -> list[WorkspaceConversation]:
        """Your conversations across projects, most recently active first; only those whose
        projects you can all still see."""
        runs = list(await self.session.scalars(
            select(AgentRun).where(
                AgentRun.workspace_id == member.workspace_id, AgentRun.project_id.is_(None),
                AgentRun.requested_by_id == member.user_id,
            ).order_by(AgentRun.created_at)
        ))
        visible = {p.id: p for p in await self.session.scalars(
            select(Project).where(Project.workspace_id == member.workspace_id, visible_to(member.user_id, member.role))
        )}
        threads: dict[uuid.UUID, dict[str, Any]] = {}
        for run in runs:
            entry = threads.setdefault(run.thread_id, {"first": run, "updated_at": run.updated_at, "working": False})
            entry["updated_at"] = max(entry["updated_at"], run.updated_at)
            entry["working"] = entry["working"] or run.status in ACTIVE_STATUSES
        found = []
        for thread_id, entry in threads.items():
            ids = list(entry["first"].project_ids or [])
            if any(i not in visible for i in ids):
                continue
            found.append(WorkspaceConversation(
                thread_id=thread_id, title=entry["first"].title or entry["first"].message[:80],
                project_keys=[visible[i].key for i in ids], project_ids=ids, updated_at=entry["updated_at"],
                working=entry["working"], model=entry["first"].conversation_model,
            ))
        return sorted(found, key=lambda c: c.updated_at, reverse=True)[:limit]

    async def stop(self, member: Membership, run_id: uuid.UUID) -> AgentRunRead:
        run = await self._run(member, run_id, lock=True)
        if run.status not in (RunStatus.QUEUED, RunStatus.RUNNING):
            raise Conflict("Only a run that's still working can be stopped")
        user = await self.session.get(User, member.user_id)
        reason = f"Stopped by {user.display_name if user else 'a member'}"
        AuditLog(self.session).record(
            workspace_id=member.workspace_id, action="agent_run.stopped", target=str(run.id),
            actor_type=AuthorType.USER, actor_user_id=member.user_id,
        )
        await self.session.commit()
        await self.runner.stop(run.id, reason)
        await self.session.refresh(run)
        if run.status in (RunStatus.QUEUED, RunStatus.RUNNING):
            run.status, run.error = RunStatus.FAILED, reason
            run.updated_at = run.finished_at = _now()
            await self.session.commit()
        return await self.get(member, run.id)


def _read(member: Membership, run: AgentRun) -> AgentRunRead:
    from .service import read_run  # (service imports this module's neighbours; import late)

    return read_run(member, run)
