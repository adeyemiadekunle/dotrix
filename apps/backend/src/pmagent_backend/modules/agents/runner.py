"""Executes agent runs: builds the team for a project, runs or resumes it, and
records the outcome (reply, pending approvals, or failure).

Runs execute in the worker process (enqueued by the API), as background tasks in the API
process ("local" mode), or inline (tests).
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
from langchain_core.messages import HumanMessage, RemoveMessage
from sqlalchemy import select

from pmagent_backend.modules.audit.service import AuditLog
from pmagent_backend.modules.knowledge.models import AuthorType
from pmagent_backend.modules.knowledge.repository import KnowledgeRepository
from pmagent_backend.modules.projects.repository import ProjectRepository
from pmagent_engine import approvals as hitl
from pmagent_engine.agent import PM_ROLE, build_team, role_for_agent_name
from pmagent_engine.layout import AGENTS

from .board_tools import BoardContext, board_instructions, build_board_tools
from .llm import ModelFactory
from .models import AgentApproval, AgentRun, ApprovalStatus, RunKind, RunStatus
from .queue import RunQueue
from .storage_backend import PlatformKnowledgeBackend, SessionFactory
from .streams import RunStreams, Stream, Streams, text_of
from .usage import TokenUsage

logger = logging.getLogger(__name__)

BRIEFING_PROMPT = (
    "Give me my briefing: phase and health, today's priorities, recent decisions, "
    "open questions, blockers, recent research, and documentation status. Read only."
)
READ_ONLY_REJECTION = "This is a read-only briefing; no changes were made. Don't retry the write."
MAX_AUTO_REJECTIONS = 5
RECURSION_LIMIT = 150
# Models occasionally end their turn with nothing at all (seen with Gemini after several tool
# calls: no text, no tool calls, zero output tokens). The runner asks once more with this;
# people never see it, since conversations show runs, not the checkpoint.
NO_REPLY_FOLLOW_UP = (
    "Your last turn ended without a reply. Answer my previous message now, in plain text, "
    "using what you've already found."
)
FOLLOW_UP_MARK = "pmagent_follow_up"
NO_REPLY_ERROR = "The PM finished without writing a reply, even when asked again. Send your message again."
NO_REPLY_AFTER_DECISIONS_ERROR = (
    "The PM finished without writing a reply, even when asked again. "
    "The approved actions above were applied."
)


def _now() -> datetime:
    return datetime.now(UTC)


def _text(content: Any) -> str:
    """A message's text, whether a plain string or a list of content blocks (thinking and
    other non-text blocks are left out)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(_block_text(block) for block in content)
    return str(content)


def _block_text(block: Any) -> str:
    if not isinstance(block, dict):
        return str(block)
    return str(block.get("text", "")) if block.get("type", "text") == "text" else ""


def _reply(result: dict) -> str:
    """The PM's answer in a finished step: its last message's text or, when that is empty,
    the last text it wrote since the person's message (some models write the answer and then
    end with an empty turn)."""
    for message in reversed(result.get("messages") or []):
        if getattr(message, "type", None) == "human" and not _is_follow_up(message):
            break
        if getattr(message, "type", None) == "ai" and (text := _text(message.content).strip()):
            return text
    return ""


def _is_follow_up(message: Any) -> bool:
    return bool((getattr(message, "additional_kwargs", None) or {}).get(FOLLOW_UP_MARK))


def _follow_up(result: dict) -> dict:
    """Graph input asking for the missing reply, dropping the empty turn: an empty model turn
    in the history can itself be refused by the provider."""
    messages: list[Any] = []
    last = (result.get("messages") or [None])[-1]
    if getattr(last, "type", None) == "ai" and getattr(last, "id", None) and not _text(last.content).strip():
        messages.append(RemoveMessage(id=last.id))
    messages.append(HumanMessage(NO_REPLY_FOLLOW_UP, additional_kwargs={FOLLOW_UP_MARK: True}))
    return {"messages": messages}


class AgentRunner:
    """Starts, resumes, and stops runs, and executes them.

    Where a run executes depends on how it's constructed:
    - `queue` set (API in worker mode): runs are enqueued; the worker process executes them.
    - `inline=True` (tests, the worker itself): executed right away, in the caller.
    - otherwise: a background task in this process ("local" mode).

    A run step is a JSON payload, so it can sit in a queue: {"kind": "start", "message"} or
    {"kind": "resume", "interrupt_ids", "decisions", "approved_by_id"}.
    """

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        checkpointer: Any,
        model_factory: ModelFactory,
        inline: bool = False,
        queue: RunQueue | None = None,
        stop_reasons: RunQueue | None = None,
        streams: Streams | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.checkpointer = checkpointer
        self.model_factory = model_factory
        self.inline = inline
        self.queue = queue
        # The worker: why a job was aborted (Stop). Also means a cut-off run gets retried.
        self.stop_reasons = stop_reasons
        # The PM's reply as it's written, for clients that stream it.
        self.streams: Streams = streams or RunStreams()
        self._tasks: set[asyncio.Task[None]] = set()
        # Local mode: background tasks by run, so a person can stop one; and why it was stopped.
        self._running: dict[uuid.UUID, asyncio.Task[None]] = {}
        self._stopped: dict[uuid.UUID, str] = {}

    # -- dispatching -----------------------------------------------------------------

    async def start(self, run_id: uuid.UUID, message: str) -> None:
        await self._dispatch(run_id, {"kind": "start", "message": message})

    async def resume(
        self,
        run_id: uuid.UUID,
        *,
        interrupt_ids: list[str | None],
        decisions: list[tuple[str, str | None]],
        approved_by_id: uuid.UUID,
    ) -> None:
        await self._dispatch(
            run_id,
            {
                "kind": "resume",
                "interrupt_ids": interrupt_ids,
                "decisions": [list(d) for d in decisions],
                "approved_by_id": str(approved_by_id),
            },
        )

    async def _dispatch(self, run_id: uuid.UUID, payload: dict[str, Any]) -> None:
        if self.queue is not None:
            await self.queue.enqueue(run_id, payload)
            return
        if self.inline:
            await self.execute(run_id, payload)
            return
        task = asyncio.create_task(self.execute(run_id, payload))
        self._tasks.add(task)
        self._running[run_id] = task
        task.add_done_callback(self._tasks.discard)
        task.add_done_callback(lambda _: self._running.pop(run_id, None))

    async def stop(self, run_id: uuid.UUID, reason: str) -> bool:
        """Cancel a run that's queued or working, and wait (briefly) for it to record the stop.
        False if nothing was running it (finished, or cut off by a restart)."""
        if self.queue is not None:
            return await self.queue.stop(run_id, reason)
        task = self._running.get(run_id)
        if task is None or task.done():
            return False
        self._stopped[run_id] = reason
        task.cancel()
        await asyncio.wait({task}, timeout=10)
        return True

    async def shutdown(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    # -- execution -------------------------------------------------------------------

    async def execute(self, run_id: uuid.UUID, payload: dict[str, Any]) -> None:
        """Run one step of a run to its outcome: a reply, actions waiting for approval, or a
        failure. Safe to call again for a step that was cut off (a retried queue job): it
        continues from the last checkpoint instead of starting over."""
        resuming = payload["kind"] == "resume"
        approved_by_id = uuid.UUID(payload["approved_by_id"]) if resuming else None
        # Every model call of this step, subagents' included; recorded on the run when the step
        # ends (finished, paused, failed, or stopped). Known gap: in worker mode, a cut-off
        # attempt's tokens are lost when its job is retried.
        usage = TokenUsage()
        try:
            async with self.session_factory() as session:
                run = await session.get(AgentRun, run_id)
                if run is None or run.status not in (RunStatus.QUEUED, RunStatus.RUNNING):
                    logger.info("agent run %s: nothing to do (%s)", run_id, run and run.status)
                    return
                retry = run.status is RunStatus.RUNNING  # a previous attempt was cut off
                project = await ProjectRepository(session).get(run.workspace_id, run.project_id)
                assert project is not None
                run.status, run.updated_at = RunStatus.RUNNING, _now()
                run.model = project.model
                await session.commit()
                rules = await self._rules(session, project.id)
                kind, thread_id = run.kind, run.thread_id
                workspace_id, project_id, instructed_by = run.workspace_id, run.project_id, run.requested_by_id
                name, description, project_key = project.name, project.description, project.key
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
            read_tools, pm_write_tools, specialist_write_tools = build_board_tools(
                BoardContext(
                    session_factory=self.session_factory,
                    workspace_id=workspace_id,
                    project_id=project_id,
                    instructed_by_id=instructed_by,
                    approved_by_id=approved_by_id,
                )
            )
            agent = build_team(
                name,
                description,
                choice.model,
                backend,
                checkpointer=self.checkpointer,
                web_search=choice.web_search,
                rules=rules,
                task_tools=(read_tools, pm_write_tools),
                subagent_task_tools=specialist_write_tools,
                board_instructions=board_instructions(project_key),
            )
            config = {
                "configurable": {"thread_id": str(thread_id)},
                "recursion_limit": RECURSION_LIMIT,
                "callbacks": [usage],  # inherited by tools and the subagents they start
            }
            graph_input: Any = (
                hitl.resume_command(
                    [{"interrupt_id": i} for i in payload["interrupt_ids"]],
                    [tuple(d) for d in payload["decisions"]],
                )
                if resuming
                else {"messages": [{"role": "user", "content": payload["message"]}]}
            )
            stream = await self.streams.open(run_id)
            result = None
            if retry:
                graph_input, result = await _continue_from_checkpoint(agent, config, payload, graph_input)
            if result is None:
                result = await _run_graph(agent, graph_input, config, stream)
            result = await self._settle(agent, kind, config, stream, result)
            if not hitl.has_pending(result) and not _reply(result):
                logger.warning("agent run %s: no reply; asking once more", run_id)
                result = await _run_graph(agent, _follow_up(result), config, stream)
                result = await self._settle(agent, kind, config, stream, result)
                if not hitl.has_pending(result) and not _reply(result):
                    await self._fail(
                        run_id, NO_REPLY_AFTER_DECISIONS_ERROR if resuming else NO_REPLY_ERROR, usage
                    )
                    return
            await self._finish(run_id, result, usage)
        except asyncio.CancelledError:
            reason = self._stopped.pop(run_id, None)
            if reason is None and self.stop_reasons is not None:
                reason = await self.stop_reasons.stop_reason(run_id)
            if reason is not None:
                await self._fail(run_id, reason, usage)  # a person stopped it
                return
            if self.stop_reasons is None:
                await self._fail(run_id, "Stopped because the server shut down; send the message again", usage)
            # In the worker the run stays "running": its job is retried and continues from the
            # last checkpoint.
            raise
        except Exception as exc:
            logger.exception("agent run %s failed", run_id)
            await self._fail(run_id, getattr(exc, "detail", None) or f"{exc.__class__.__name__}: {exc}", usage)
        finally:
            await self.streams.close(run_id)

    async def _settle(self, agent: Any, kind: RunKind, config: dict, stream: Stream, result: dict) -> dict:
        """A briefing is read-only: any write it attempts is rejected so it can carry on."""
        if kind is RunKind.BRIEFING:
            for _ in range(MAX_AUTO_REJECTIONS):
                if not hitl.has_pending(result):
                    break
                command = hitl.resume_command(result, "reject", READ_ONLY_REJECTION)
                result = await _run_graph(agent, command, config, stream)
        return result

    async def _finish(self, run_id: uuid.UUID, result: dict, usage: TokenUsage) -> None:
        async with self.session_factory() as session:
            run = await session.get(AgentRun, run_id)
            assert run is not None
            now = _now()
            tokens = usage.take()
            _add_tokens(run, tokens)
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
                run.reply = _reply(result)
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
                details={"pending_actions": len(pending), **tokens} if pending else tokens,
            )
            await session.commit()

    async def _fail(self, run_id: uuid.UUID, error: str, usage: TokenUsage) -> None:
        """Stopped and failed runs keep the tokens they used."""
        async with self.session_factory() as session:
            run = await session.get(AgentRun, run_id)
            if run is None:
                return
            tokens = usage.take()
            _add_tokens(run, tokens)
            run.status, run.error = RunStatus.FAILED, error[:2000]
            run.updated_at = run.finished_at = _now()
            AuditLog(session).record(
                workspace_id=run.workspace_id,
                project_id=run.project_id,
                action="agent_run.failed",
                target=str(run.id),
                actor_type=AuthorType.SYSTEM,
                instructed_by_id=run.requested_by_id,
                details={"error": run.error, **tokens},
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


def _add_tokens(run: AgentRun, tokens: dict[str, int]) -> None:
    run.input_tokens = (run.input_tokens or 0) + tokens["input_tokens"]
    run.output_tokens = (run.output_tokens or 0) + tokens["output_tokens"]


def _preview(action: dict, files: dict[str, str]) -> tuple[str | None, str | None]:
    """(target, unified diff) for file writes; a readable target for board changes."""
    args = action.get("args") or {}
    if isinstance(args, dict) and action.get("tool") == "create_issue":
        return f"new {args.get('type', 'issue')}: {args.get('title', '')}".strip(), None
    if isinstance(args, dict) and action.get("tool") in ("update_issue", "comment_issue"):
        return str(args.get("key") or "") or None, None
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


async def _run_graph(agent: Any, graph_input: Any, config: dict, stream: Stream) -> dict:
    """What `agent.ainvoke` returns (the final state, plus `__interrupt__` when actions wait for
    approval), collected from the graph's stream so the Project Manager's words can be
    published as they're written. Subagents' words aren't streamed: only the PM speaks to you."""
    latest: Any = None
    interrupts: list[Any] = []
    async for mode, payload in agent.astream(graph_input, config, stream_mode=["updates", "values", "messages"]):
        if mode == "updates" and isinstance(payload, dict) and (found := payload.get("__interrupt__")) is not None:
            interrupts.extend(found)
        elif mode == "values":
            latest = payload
        elif mode == "messages":
            chunk, metadata = payload
            if getattr(chunk, "type", "") == "AIMessageChunk" and role_for_agent_name(
                (metadata or {}).get("lc_agent_name")
            ) == PM_ROLE:
                await stream.publish(text_of(chunk.content))
    if interrupts:
        return {**latest, "__interrupt__": interrupts} if isinstance(latest, dict) else {"__interrupt__": interrupts}
    return latest if isinstance(latest, dict) else {}


def _last_user_message(values: dict) -> str | None:
    for message in reversed(values.get("messages") or []):
        if getattr(message, "type", None) == "human" and not _is_follow_up(message):
            return _text(message.content)
    return None


async def _continue_from_checkpoint(
    agent: Any, config: dict, payload: dict[str, Any], graph_input: Any
) -> tuple[Any, dict | None]:
    """A retried step whose previous attempt was cut off: (input to send, or the result if the
    step already finished). Never sends the person's message twice."""
    state = await agent.aget_state(config)
    if payload["kind"] == "resume" and state.interrupts:
        return graph_input, None  # the decisions weren't applied yet: apply them
    if state.next:
        return None, None  # continue the pending steps from the last checkpoint
    if payload["kind"] == "start" and _last_user_message(state.values) != payload["message"]:
        return graph_input, None  # the message never reached the graph: send it now
    # The step had finished; only recording its outcome was cut off.
    result = dict(state.values)
    if state.interrupts:
        result["__interrupt__"] = list(state.interrupts)
    return None, result
