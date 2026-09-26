"""Executes agent runs: builds the team for a project, runs or resumes it, and
records the outcome (reply, pending approvals, or failure).

Runs execute as background tasks in the API process (or inline, for tests).
State lives in the LangGraph checkpointer (Postgres), keyed by thread, so a
paused run resumes from exactly where it stopped.
"""
from __future__ import annotations

import asyncio
import difflib
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from deepagents.backends import CompositeBackend, StateBackend
from sqlalchemy import select

from pmagent_backend.modules.audit.service import AuditLog
from pmagent_backend.modules.knowledge.models import AuthorType
from pmagent_backend.modules.knowledge.repository import KnowledgeRepository
from pmagent_backend.modules.projects.repository import ProjectRepository
from pmagent_engine import approvals as hitl
from pmagent_engine.agent import build_team
from pmagent_engine.layout import AGENTS

from .llm import ModelFactory
from .models import AgentApproval, AgentRun, ApprovalStatus, RunKind, RunStatus
from .storage_backend import PlatformKnowledgeBackend, SessionFactory

logger = logging.getLogger(__name__)

BRIEFING_PROMPT = (
    "Give me my briefing: phase and health, today's priorities, recent decisions, "
    "open questions, blockers, recent research, and documentation status. Read only."
)
READ_ONLY_REJECTION = "This is a read-only briefing; no changes were made. Don't retry the write."
MAX_AUTO_REJECTIONS = 5
RECURSION_LIMIT = 150


def _now() -> datetime:
    return datetime.now(UTC)


def _text(content: Any) -> str:
    """A message's text, whether a plain string or a list of content blocks."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "") if isinstance(block, dict) else str(block) for block in content
        )
    return str(content)


class AgentRunner:
    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        checkpointer: Any,
        model_factory: ModelFactory,
        inline: bool = False,
    ) -> None:
        self.session_factory = session_factory
        self.checkpointer = checkpointer
        self.model_factory = model_factory
        self.inline = inline
        self._tasks: set[asyncio.Task[None]] = set()

    # -- scheduling ------------------------------------------------------------------

    async def start(self, run_id: uuid.UUID, message: str) -> None:
        await self._schedule(run_id, {"messages": [{"role": "user", "content": message}]}, None)

    async def resume(self, run_id: uuid.UUID, command: Any, approved_by_id: uuid.UUID) -> None:
        await self._schedule(run_id, command, approved_by_id)

    async def _schedule(self, run_id: uuid.UUID, graph_input: Any, approved_by_id: uuid.UUID | None) -> None:
        if self.inline:
            await self._execute(run_id, graph_input, approved_by_id)
            return
        task = asyncio.create_task(self._execute(run_id, graph_input, approved_by_id))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def shutdown(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    # -- execution -------------------------------------------------------------------

    async def _execute(self, run_id: uuid.UUID, graph_input: Any, approved_by_id: uuid.UUID | None) -> None:
        try:
            async with self.session_factory() as session:
                run = await session.get(AgentRun, run_id)
                assert run is not None
                project = await ProjectRepository(session).get(run.workspace_id, run.project_id)
                assert project is not None
                run.status, run.updated_at = RunStatus.RUNNING, _now()
                await session.commit()
                rules = await self._rules(session, project.id)
                kind, thread_id = run.kind, run.thread_id
                workspace_id, project_id, instructed_by = run.workspace_id, run.project_id, run.requested_by_id
                name, description = project.name, project.description
                choice = self.model_factory(project)

            backend = CompositeBackend(
                default=StateBackend(),
                routes={
                    "/pmagent/": PlatformKnowledgeBackend(
                        self.session_factory,
                        workspace_id=workspace_id,
                        project_id=project_id,
                        instructed_by_id=instructed_by,
                        approved_by_id=approved_by_id,
                    )
                },
            )
            agent = build_team(
                name,
                description,
                choice.model,
                backend,
                checkpointer=self.checkpointer,
                web_search=choice.web_search,
                rules=rules,
            )
            config = {"configurable": {"thread_id": str(thread_id)}, "recursion_limit": RECURSION_LIMIT}
            result = await agent.ainvoke(graph_input, config)
            if kind is RunKind.BRIEFING:
                for _ in range(MAX_AUTO_REJECTIONS):
                    if not hitl.has_pending(result):
                        break
                    command = hitl.resume_command(result, "reject", READ_ONLY_REJECTION)
                    result = await agent.ainvoke(command, config)
            await self._finish(run_id, result)
        except asyncio.CancelledError:
            await self._fail(run_id, "Stopped because the server shut down; send the message again")
            raise
        except Exception as exc:
            logger.exception("agent run %s failed", run_id)
            await self._fail(run_id, getattr(exc, "detail", None) or f"{exc.__class__.__name__}: {exc}")

    async def _finish(self, run_id: uuid.UUID, result: dict) -> None:
        async with self.session_factory() as session:
            run = await session.get(AgentRun, run_id)
            assert run is not None
            now = _now()
            pending = hitl.pending_actions(result)
            if pending:
                files = {
                    f"/pmagent/{f.path}": f.content
                    for f in await KnowledgeRepository(session).list_files(run.project_id)
                }
                for position, action in enumerate(pending):
                    target, diff = _preview(action, files)
                    session.add(
                        AgentApproval(
                            workspace_id=run.workspace_id,
                            run_id=run.id,
                            project_id=run.project_id,
                            position=position,
                            interrupt_id=action["interrupt_id"],
                            tool=action["tool"] or "?",
                            args=_jsonable(action["args"]),
                            target=target,
                            diff=diff,
                            status=ApprovalStatus.PENDING,
                            created_at=now,
                        )
                    )
                run.status = RunStatus.AWAITING_APPROVAL
                action_name = "agent_run.awaiting_approval"
            else:
                messages = result.get("messages") or []
                run.reply = _text(messages[-1].content) if messages else ""
                run.status, run.finished_at = RunStatus.COMPLETED, now
                action_name = "agent_run.completed"
            run.updated_at = now
            AuditLog(session).record(
                workspace_id=run.workspace_id,
                project_id=run.project_id,
                action=action_name,
                target=str(run.id),
                actor_type=AuthorType.AGENT,
                agent="project-manager",
                instructed_by_id=run.requested_by_id,
                details={"pending_actions": len(pending)} if pending else {},
            )
            await session.commit()

    async def _fail(self, run_id: uuid.UUID, error: str) -> None:
        async with self.session_factory() as session:
            run = await session.get(AgentRun, run_id)
            if run is None:
                return
            run.status, run.error = RunStatus.FAILED, error[:2000]
            run.updated_at = run.finished_at = _now()
            AuditLog(session).record(
                workspace_id=run.workspace_id,
                project_id=run.project_id,
                action="agent_run.failed",
                target=str(run.id),
                actor_type=AuthorType.SYSTEM,
                instructed_by_id=run.requested_by_id,
                details={"error": run.error},
            )
            await session.commit()

    async def _rules(self, session: Any, project_id: uuid.UUID) -> dict[str, str]:
        """The project's agent-rules/*.md, keyed by role ("base", "product", ...)."""
        files = await KnowledgeRepository(session).list_files(project_id)
        wanted = {f"agent-rules/{name}.md": name for name in ("base", *AGENTS)}
        return {wanted[f.path]: f.content for f in files if f.path in wanted}


async def mark_interrupted_runs(session_factory: SessionFactory) -> None:
    """At startup: runs that were mid-flight when the process stopped can't continue."""
    async with session_factory() as session:
        result = await session.scalars(
            select(AgentRun).where(AgentRun.status.in_([RunStatus.QUEUED, RunStatus.RUNNING]))
        )
        for run in result:
            run.status, run.error = RunStatus.FAILED, "Interrupted by a server restart; send it again"
            run.updated_at = run.finished_at = _now()
        await session.commit()


def _preview(action: dict, files: dict[str, str]) -> tuple[str | None, str | None]:
    """(target, unified diff) for file writes; (None, None) for other tools."""
    args = action.get("args") or {}
    path = args.get("file_path") if isinstance(args, dict) else None
    if action.get("tool") not in ("write_file", "edit_file") or not isinstance(path, str):
        return None, None
    before = files.get(path, "")
    if action["tool"] == "write_file":
        after = str(args.get("content", ""))
    else:
        old, new = str(args.get("old_string", "")), str(args.get("new_string", ""))
        after = before.replace(old, new) if args.get("replace_all") else before.replace(old, new, 1)
    diff = "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a{path}" if path in files else "/dev/null",
            tofile=f"b{path}",
        )
    )
    return path, diff


def _jsonable(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return {str(k): v if isinstance(v, (str, int, float, bool, type(None), list, dict)) else str(v) for k, v in value.items()}
    return {"value": str(value)}
