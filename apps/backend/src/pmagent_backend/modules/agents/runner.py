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
from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage, SystemMessage
from sqlalchemy import select

from pmagent_backend.modules.agent_definitions.repository import AgentDefinitionRepository
from pmagent_backend.modules.audit.service import AuditLog
from pmagent_backend.modules.knowledge.models import AuthorType
from pmagent_backend.modules.knowledge.repository import KnowledgeRepository
from pmagent_backend.modules.projects.repository import ProjectRepository
from pmagent_engine import approvals as hitl
from pmagent_engine.agent import PM_ROLE, briefing_system_prompt, build_team, role_for_agent_name
from pmagent_engine.contracts import AgentPolicy
from pmagent_engine.layout import AGENTS

from .activity import activity_label
from .board_tools import BoardContext, board_instructions, build_board_tools
from .context import build_context_pack
from .findings import dedupe_findings
from .knowledge_tools import KNOWLEDGE_TOOLS_GUIDE, build_knowledge_tools
from .llm import ModelFactory
from .models import AgentApproval, AgentRun, AgentRunOutput, ApprovalStatus, RunKind, RunStatus
from .queue import RunQueue
from .storage_backend import PlatformKnowledgeBackend, SessionFactory
from .streams import RunStreams, Stream, Streams, text_of
from .usage import TokenBudgetExceeded, TokenUsage, merge_breakdown

logger = logging.getLogger(__name__)

BRIEFING_PROMPT = (
    "Give me my briefing: phase and health, what changed, today's priorities, recent decisions, "
    "open questions, blockers, and documentation status. Write it from the project context, in one "
    "reply: it already has the board (with what's next) and what changed since the last briefing. "
    "Use a tool only if something the briefing must explain isn't in the context, and don't ask the "
    "specialists. Read only."
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
BUDGET_ERROR = (
    "Stopped: this run reached its token budget ({used:,} of {budget:,} tokens). Changes already "
    "approved were kept. Ask a narrower question, or an owner or admin can raise the budget in the "
    "project's settings."
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
        token_budget: int | None = None,
        summarize_after_tokens: int | None = None,
        embedder: Any = None,
    ) -> None:
        self.session_factory = session_factory
        # Defaults for every project (a project may set its own budget); None: no limit / the
        # engine's own summarisation.
        self.token_budget = token_budget or None
        self.summarize_after_tokens = summarize_after_tokens
        # The search index's embedding model (None: agents search by keywords only).
        self.embedder = embedder
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
        approved_by_id: uuid.UUID | None,
    ) -> None:
        await self._dispatch(
            run_id,
            {
                "kind": "resume",
                "interrupt_ids": interrupt_ids,
                "decisions": [list(d) for d in decisions],
                # None when only checkpoints were answered: nothing was approved.
                "approved_by_id": str(approved_by_id) if approved_by_id else None,
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
        approved_by_id = uuid.UUID(payload["approved_by_id"]) if resuming and payload.get("approved_by_id") else None
        # Every model call of this step, subagents' included; recorded on the run when the step
        # ends (finished, paused, failed, or stopped). Known gap: in worker mode, a cut-off
        # attempt's tokens are lost when its job is retried.
        usage = TokenUsage()
        results: list[tuple[str, list[dict[str, Any]]]] = []  # what the leading agent submitted
        try:
            async with self.session_factory() as session:
                run = await session.get(AgentRun, run_id)
                if run is None or run.status not in (RunStatus.QUEUED, RunStatus.RUNNING):
                    logger.info("agent run %s: nothing to do (%s)", run_id, run and run.status)
                    return
                retry = run.status is RunStatus.RUNNING  # a previous attempt was cut off
                project = await ProjectRepository(session).get(run.workspace_id, run.project_id)
                assert project is not None
                # The agents in effect for this project: its overrides, the workspace's, the built-ins.
                resolved = {a.spec.handle: a for a in await AgentDefinitionRepository(session).resolve(
                    run.workspace_id, run.project_id
                )}
                lead_agent = resolved.get(run.agent or PM_ROLE)
                if lead_agent is None:
                    gone = f"The @{run.agent} agent no longer exists; pick another agent"
                    await session.rollback()
                    await self._fail(run_id, gone, usage)
                    return
                specs = [a.spec for a in resolved.values()]
                run.status, run.updated_at = RunStatus.RUNNING, _now()
                run.model = run.conversation_model or project.model
                run.agent_version = lead_agent.version
                # The budget covers every step of the run: what earlier steps used counts. The
                # leading agent's own budget wins over the project's.
                run.token_budget = lead_agent.spec.budget_tokens or project.token_budget or self.token_budget
                usage = TokenUsage(
                    budget=run.token_budget,
                    used=(run.input_tokens or 0) + (run.output_tokens or 0),
                    stages=(run.usage or {}).get("stages"),
                )
                await session.commit()
                rules = await self._rules(session, project.id, list(resolved))
                context = await build_context_pack(session, project, run)
                kind, thread_id = run.kind, run.thread_id
                workspace_id, project_id, instructed_by = run.workspace_id, run.project_id, run.requested_by_id
                name, description, project_key = project.name, project.description, project.key
                choice = self.model_factory(project, run.model)
                lead = run.agent  # None: Auto (the Project Manager)
                mode = run.mode
                policy = AgentPolicy(specs)
                versions = {handle: agent.version for handle, agent in resolved.items()}

            backend = CompositeBackend(
                default=StateBackend(),
                routes={
                    "/pmagent/": PlatformKnowledgeBackend(
                        self.session_factory,
                        workspace_id=workspace_id,
                        project_id=project_id,
                        instructed_by_id=instructed_by,
                        approved_by_id=approved_by_id,
                        policy=policy,
                    )
                },
            )
            read_tools, pm_write_tools, _ = build_board_tools(
                BoardContext(
                    session_factory=self.session_factory,
                    workspace_id=workspace_id,
                    project_id=project_id,
                    instructed_by_id=instructed_by,
                    approved_by_id=approved_by_id,
                    policy=policy,
                    versions=versions,
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
                # Every agent's board changes come from the same tools; each gets the ones its
                # contract lists, and the issue service checks the contract again on every change.
                subagent_task_tools=pm_write_tools,
                agents=specs,
                models=lambda name: self.model_factory(project, name).model,
                board_instructions=board_instructions(project_key) + KNOWLEDGE_TOOLS_GUIDE,
                context=context,
                knowledge_tools=build_knowledge_tools(
                    self.session_factory,
                    workspace_id=workspace_id,
                    project_id=project_id,
                    embedder=self.embedder,
                ),
                specialist_model=choice.specialist_model,
                summarize_after_tokens=self.summarize_after_tokens,
                lead=lead,
                mode=mode,
                result_sink=lambda schema, items: results.append((schema, items)),
                # Stages show as live activity from the `stage` calls themselves (activity.py);
                # here they split the run's tokens by stage.
                stage_sink=usage.enter_stage,
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
            speaker = lead or PM_ROLE  # whose words are streamed to the person
            if result is None and kind is RunKind.BRIEFING and not resuming:
                # One model call with no tools: the context pack already says what happened.
                system = briefing_system_prompt(name, description, rules=rules, context=context)
                result = await _brief(agent, choice.model, system, payload["message"], config, stream)
            if result is None:
                result = await _run_graph(agent, graph_input, config, stream, speaker)
            result = await self._settle(agent, kind, config, stream, result)
            if not hitl.has_pending(result) and not _reply(result):
                logger.warning("agent run %s: no reply; asking once more", run_id)
                result = await _run_graph(agent, _follow_up(result), config, stream, speaker)
                result = await self._settle(agent, kind, config, stream, result)
                if not hitl.has_pending(result) and not _reply(result):
                    await self._fail(
                        run_id, NO_REPLY_AFTER_DECISIONS_ERROR if resuming else NO_REPLY_ERROR, usage
                    )
                    return
            if results:
                await self._save_outputs(run_id, speaker, results)
            await self._finish(run_id, result, usage, speaker)
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
        except TokenBudgetExceeded as exc:
            logger.info("agent run %s: %s", run_id, exc)
            await self._fail(run_id, BUDGET_ERROR.format(used=exc.used, budget=exc.budget), usage)
        except Exception as exc:
            if (budget := _budget_error(exc)) is not None:  # raised inside a tool (a subagent)
                logger.info("agent run %s: %s", run_id, budget)
                await self._fail(run_id, BUDGET_ERROR.format(used=budget.used, budget=budget.budget), usage)
                return
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

    async def _finish(self, run_id: uuid.UUID, result: dict, usage: TokenUsage, speaker: str = PM_ROLE) -> None:
        async with self.session_factory() as session:
            run = await session.get(AgentRun, run_id)
            assert run is not None
            now = _now()
            tokens = _add_tokens(run, usage)
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
                agent=speaker,
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
            tokens = _add_tokens(run, usage)
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

    async def _save_outputs(
        self, run_id: uuid.UUID, agent: str, results: list[tuple[str, list[dict[str, Any]]]]
    ) -> None:
        """The structured results the leading agent recorded, one row per submit; findings that
        repeat an open finding or issue are settled as such (findings.py)."""
        async with self.session_factory() as session:
            run = await session.get(AgentRun, run_id)
            if run is None:
                return
            for schema, items in results:
                entries = (
                    await dedupe_findings(session, run.project_id, items)
                    if schema == "finding"
                    else [{"data": item, "state": "open"} for item in items]
                )
                session.add(AgentRunOutput(
                    workspace_id=run.workspace_id, run_id=run.id, project_id=run.project_id, agent=agent,
                    schema_name=schema, items=entries, created_at=_now(),
                ))
            await session.commit()

    async def _rules(self, session: Any, project_id: uuid.UUID, handles: list[str] | None = None) -> dict[str, str]:
        """The project's agent-rules/*.md, keyed by handle ("base", "product", a custom agent's)."""
        files = await KnowledgeRepository(session).list_files(project_id)
        wanted = {f"agent-rules/{name}.md": name for name in ("base", *AGENTS, *(handles or []))}
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


def _add_tokens(run: AgentRun, usage: TokenUsage) -> dict[str, int]:
    """Record the step's usage on the run; returns the step's totals (for the audit log)."""
    tokens, breakdown = usage.take()
    run.input_tokens = (run.input_tokens or 0) + tokens["input_tokens"]
    run.output_tokens = (run.output_tokens or 0) + tokens["output_tokens"]
    run.cached_input_tokens = (run.cached_input_tokens or 0) + tokens["cached_input_tokens"]
    run.model_calls = (run.model_calls or 0) + tokens["model_calls"]
    run.usage = merge_breakdown(run.usage, breakdown)
    return tokens


def _budget_error(exc: BaseException) -> TokenBudgetExceeded | None:
    """The budget error behind an exception (a subagent's model call raises it inside the
    `task` tool, which may wrap it)."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        if isinstance(current, TokenBudgetExceeded):
            return current
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return None


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


async def _run_graph(agent: Any, graph_input: Any, config: dict, stream: Stream, speaker: str = PM_ROLE) -> dict:
    """What `agent.ainvoke` returns (the final state, plus `__interrupt__` when actions wait for
    approval), collected from the graph's stream so the Project Manager's words can be
    published as they're written. Subagents' words aren't streamed: only the PM speaks to you."""
    latest: Any = None
    interrupts: list[Any] = []
    async for mode, payload in agent.astream(graph_input, config, stream_mode=["updates", "values", "messages"]):
        if mode == "updates" and isinstance(payload, dict):
            if (found := payload.get("__interrupt__")) is not None:
                interrupts.extend(found)
            for label in _activities(payload):
                await stream.activity(label)
        elif mode == "values":
            latest = payload
        elif mode == "messages":
            chunk, metadata = payload
            if getattr(chunk, "type", "") == "AIMessageChunk" and role_for_agent_name(
                (metadata or {}).get("lc_agent_name")
            ) == speaker:
                await stream.publish(text_of(chunk.content))
    if interrupts:
        return {**latest, "__interrupt__": interrupts} if isinstance(latest, dict) else {"__interrupt__": interrupts}
    return latest if isinstance(latest, dict) else {}


async def _brief(agent: Any, model: Any, system: str, message: str, config: dict, stream: Stream) -> dict:
    """A briefing: the PM's reply from one streamed model call, then saved into the
    conversation (as the PM's turn), so a follow-up in the same thread goes to the whole team
    with the briefing in its history."""
    reply = ""
    async for chunk in model.astream(
        [SystemMessage(system), HumanMessage(message)], config={"callbacks": config["callbacks"]}
    ):
        if delta := text_of(chunk.content):
            reply += delta
            await stream.publish(delta)
    messages = [HumanMessage(message), AIMessage(reply)]
    await agent.aupdate_state(config, {"messages": messages}, as_node="model")
    return {"messages": messages}


def _activities(update: dict) -> list[str]:
    """Labels for the tool calls the PM just decided to make (graph updates are the PM's own
    steps; subagents run inside the `task` tool, which gets one label: "Asking …")."""
    labels = []
    for name, output in update.items():
        # Only the model's own steps. Middleware hooks ("HumanInTheLoopMiddleware.after_model")
        # re-send tool calls on resume, including ones a person just rejected.
        if name == "__interrupt__" or "." in name or not isinstance(output, dict):
            continue
        messages = output.get("messages")
        messages = getattr(messages, "value", messages)  # (an Overwrite wraps the list)
        for message in messages if isinstance(messages, list) else []:
            for call in getattr(message, "tool_calls", None) or []:
                if label := activity_label(call.get("name", ""), call.get("args")):
                    labels.append(label)
    return labels


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
