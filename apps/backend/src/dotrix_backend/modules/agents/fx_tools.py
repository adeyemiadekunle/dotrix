"""Project-changing tools for an fx Nova turn: the same builders and approval rules as DeepAgents.

Documents (`write_file`, `edit_file`), the board (`create_issue`, `update_issue`, `comment_issue`), graph
links (`link_items`) and the work mode's own tools (`save_plan`, `start_coding`) reach the project only
through these. A change the run's effective contract doesn't allow without asking (the person's approval
mode, an owner's standing rule) waits for a person: the call saves a pending approval and hands the turn
off; once someone decides, the turn resumes from its journal and the same call (same execution ID) runs
with that person as approver, or hears it was rejected.

Every call is claimed in `agent_runtime_calls` in its own commit before it changes anything, and its
result saved after, so a resumed or recovered turn gets the saved result rather than changing the
project twice. A claimed call without a result was cut off: it is never run again unasked.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from langchain_core.tools import StructuredTool
from sqlalchemy import func, select

from dotrix_backend.core.crypto import Secrets
from dotrix_backend.core.errors import Forbidden
from dotrix_engine.catalog import group, tool_id
from dotrix_engine.contracts import PM_HANDLE, AgentPolicy, AgentSpec
from dotrix_engine.runtimes import RuntimeHandoff, RuntimeTool, RuntimeToolContext

from .models import AgentApproval, AgentRuntimeCall, ApprovalStatus, WorkMode
from .runtime_sessions import admit_runtime_run
from .runtime_tools import RuntimeRunScope
from .storage_backend import SessionFactory
from .unattended import Unattended

CUT_OFF = ("Cut off: this change was interrupted before its result was saved, so it may or may not have gone "
           "through. Check the project before trying again, and tell the person.")
_KNOWLEDGE_TOOLS = ("write_file", "edit_file")
_MODE_TOOLS = {"save_plan", "start_coding"}


def call_key(execution_id: str, tool: str, args: dict) -> str:
    """One call's key: libfx's execution ID (the provider's tool call ID, which some providers reuse
    within a turn) with a digest of it, the tool and its arguments."""
    digest = hashlib.sha256(json.dumps([execution_id, tool, args], sort_keys=True, default=str).encode()).hexdigest()
    return f"{execution_id[:64]}:{digest[:24]}"


def approval_key(key: str) -> str:
    """The approval's interrupt_id for an fx call: distinct from LangGraph's interrupt IDs."""
    return f"fx:{key}"


@dataclass(frozen=True)
class _Change:
    name: str
    description: str
    schema: dict
    gated: bool
    make: Callable[[uuid.UUID | None], Callable[[dict], Awaitable[Any]]]


def _dotrix_path(value: Any) -> Any:
    return "/dotrix/" + value.removeprefix("/dotrix/").lstrip("/") if isinstance(value, str) else value


def _schema(fn: Any) -> tuple[str, str, dict]:
    tool = fn if isinstance(fn, StructuredTool) else StructuredTool.from_function(coroutine=fn)
    return tool.name, tool.description, tool.args_schema.model_json_schema()


def _invoke(fn: Any) -> Callable[[dict], Awaitable[Any]]:
    tool = fn if isinstance(fn, StructuredTool) else StructuredTool.from_function(coroutine=fn)
    return tool.ainvoke


def _changes(sessions: SessionFactory, scope: RuntimeRunScope, spec: AgentSpec, policy: AgentPolicy,
             unattended: Unattended, work_mode: WorkMode | None, mode_context: Any) -> list[_Change]:
    """Every change Nova may make in this run, with whether it asks a person first."""
    from .board_tools import BoardContext, build_board_tools
    from .graph_tools import build_graph_tools
    from .storage_backend import PlatformKnowledgeBackend
    from .work_modes import codes, lead_tools

    def asks(group_id: str) -> bool:
        return not all(spec.allowed(action) for action in group(group_id).actions)

    def board(approved_by_id: uuid.UUID | None) -> BoardContext:
        return BoardContext(sessions, scope.workspace_id, scope.project_id, scope.requested_by_id, approved_by_id,
                            policy=policy, unattended=unattended, coding=codes(work_mode))

    changes: list[_Change] = []
    if spec.can("knowledge.write"):
        def backend(approved_by_id: uuid.UUID | None) -> PlatformKnowledgeBackend:
            return PlatformKnowledgeBackend(sessions, workspace_id=scope.workspace_id, project_id=scope.project_id,
                                            instructed_by_id=scope.requested_by_id, approved_by_id=approved_by_id,
                                            policy=policy, unattended=unattended)

        def path(value: str) -> str:
            return "/" + value.removeprefix("/dotrix/").lstrip("/")

        def write(approved_by_id):
            async def call(args: dict) -> dict:
                return asdict(await backend(approved_by_id).awrite(path(args["file_path"]), args["content"]))
            return call

        def edit(approved_by_id):
            async def call(args: dict) -> dict:
                return asdict(await backend(approved_by_id).aedit(
                    path(args["file_path"]), args["old_string"], args["new_string"], bool(args.get("replace_all")),
                ))
            return call

        gated = asks("knowledge.write")
        changes += [
            _Change("write_file", "Write a project document under /dotrix/ (a new file, or all of an existing one).",
                    {"type": "object", "properties": {"file_path": {"type": "string"}, "content": {"type": "string"}},
                     "required": ["file_path", "content"]}, gated, write),
            _Change("edit_file", "Replace text in a project document under /dotrix/.",
                    {"type": "object", "properties": {
                        "file_path": {"type": "string"}, "old_string": {"type": "string"},
                        "new_string": {"type": "string"}, "replace_all": {"type": "boolean", "default": False}},
                     "required": ["file_path", "old_string", "new_string"]}, gated, edit),
        ]
    _, writes, _ = build_board_tools(board(None))
    links = [fn for fn in build_graph_tools(board(None)) if fn.__name__ == "link_items"]
    for index, fn in enumerate([*writes, *links]):
        group_id = tool_id(StructuredTool.from_function(coroutine=fn))
        if group_id is None or not spec.can(group_id):
            continue
        name, description, schema = _schema(fn)
        is_link = index >= len(writes)

        def make(approved_by_id, *, _index=index, _link=is_link):
            ctx = board(approved_by_id)
            built = [fn for fn in build_graph_tools(ctx) if fn.__name__ == "link_items"] if _link else build_board_tools(ctx)[1]
            return _invoke(built[_index - len(writes) if _link else _index])

        changes.append(_Change(name, description, schema, asks(group_id), make))
    for fn in lead_tools(work_mode, mode_context) if mode_context is not None else []:
        name, description, schema = _schema(fn)
        if name in _MODE_TOOLS:
            changes.append(_Change(name, description, schema, False, lambda _approver, _fn=fn: _invoke(_fn)))
    return changes


def fx_change_tools(
    sessions: SessionFactory, secrets: Secrets, *, scope: RuntimeRunScope, spec: AgentSpec, policy: AgentPolicy,
    unattended: Unattended, work_mode: WorkMode | None, mode_context: Any, authorize: Callable[[], Awaitable[None]],
) -> list[RuntimeTool]:
    """The run's project-changing tools, each going through at most once (see the module docstring).

    `spec` is the run's effective contract (standing rules and the approval mode already applied, Manual
    for a recovered attempt); `authorize` rechecks the runtime binding before every call."""
    if spec.handle != PM_HANDLE or spec.handle != scope.agent:
        raise ValueError("fx changes are Nova's, for the admitted run")

    def execute_for(change: _Change):
        async def execute(arguments: dict, context: RuntimeToolContext) -> Any:
            if context.session_id != scope.session_id or not context.execution_id:
                raise Forbidden("This change has no bound runtime call")
            await authorize()
            args = {**arguments, "file_path": _dotrix_path(arguments["file_path"])} if (
                change.name in _KNOWLEDGE_TOOLS and "file_path" in arguments) else dict(arguments)
            if change.name in _KNOWLEDGE_TOOLS and not policy.can_write(PM_HANDLE, args["file_path"].removeprefix("/dotrix/")):
                # Its folder access refuses it whoever approves: say so now, rather than ask a person first.
                return {"error": f"Permission denied: Nova can't write {args['file_path']}; propose the change instead"}
            key = call_key(context.execution_id, change.name, args)
            async with sessions() as session:
                await admit_runtime_run(session, scope.workspace_id, scope.run_id, scope.lease_token)
                call = await session.scalar(select(AgentRuntimeCall).where(
                    AgentRuntimeCall.workspace_id == scope.workspace_id, AgentRuntimeCall.run_id == scope.run_id,
                    AgentRuntimeCall.execution_id == key,
                ))
                if call is not None:
                    if call.tool != change.name:
                        raise Forbidden("This runtime call was a different change")
                    return json.loads(secrets.decrypt(call.encrypted_result)) if call.encrypted_result else {"error": CUT_OFF}
                approver: uuid.UUID | None = None
                approval_id: uuid.UUID | None = None
                if change.gated:
                    approval = await session.scalar(select(AgentApproval).where(
                        AgentApproval.workspace_id == scope.workspace_id, AgentApproval.run_id == scope.run_id,
                        AgentApproval.interrupt_id == approval_key(key),
                    ))
                    if approval is None:
                        await _ask(session, scope, key, change.name, args)
                        await session.commit()
                        return RuntimeHandoff()
                    if approval.tool != change.name or approval.args != _jsonable(args):
                        raise Forbidden("This runtime call doesn't match the change that was decided")
                    if approval.status is ApprovalStatus.PENDING:
                        return RuntimeHandoff()
                    if approval.status is ApprovalStatus.REJECTED:
                        reason = f": {approval.reason}" if approval.reason else ""
                        return {"error": f"A person rejected this change{reason}. Don't make it; say what you'd do instead."}
                    approver, approval_id = approval.decided_by_id, approval.id
                    if approver is None:
                        return {"error": "The person who approved this change is gone; ask again"}
                session.add(AgentRuntimeCall(
                    workspace_id=scope.workspace_id, run_id=scope.run_id, execution_id=key, tool=change.name,
                    approval_id=approval_id, started_at=datetime.now(UTC),
                ))
                await session.commit()
            result = await change.make(approver)(args)
            async with sessions() as session:
                call = await session.scalar(select(AgentRuntimeCall).where(
                    AgentRuntimeCall.workspace_id == scope.workspace_id, AgentRuntimeCall.run_id == scope.run_id,
                    AgentRuntimeCall.execution_id == key,
                ).with_for_update())
                assert call is not None
                call.encrypted_result = secrets.encrypt(json.dumps(result, default=str))
                call.finished_at = datetime.now(UTC)
                await session.commit()
            return json.loads(json.dumps(result, default=str))
        return execute

    return [RuntimeTool(change.name, change.description, change.schema, writes=True, hands_off=True,
                        execute_scoped=execute_for(change))
            for change in _changes(sessions, scope, spec, policy, unattended, work_mode, mode_context)]


async def _ask(session: Any, scope: RuntimeRunScope, key: str, tool: str, args: dict) -> None:
    """A pending approval for this call, shown and decided like any other (AgentService.decide)."""
    from dotrix_backend.modules.knowledge.repository import KnowledgeRepository

    from .runner import _preview

    files = {}
    if tool in _KNOWLEDGE_TOOLS:
        files = {f"/dotrix/{f.path}": f.content for f in await KnowledgeRepository(session).list_files(scope.project_id)}
    target, diff = _preview({"tool": tool, "args": args}, files)
    position = await session.scalar(select(func.coalesce(func.max(AgentApproval.position) + 1, 0)).where(
        AgentApproval.run_id == scope.run_id))
    session.add(AgentApproval(
        workspace_id=scope.workspace_id, run_id=scope.run_id, project_id=scope.project_id, position=position,
        interrupt_id=approval_key(key), tool=tool, agent=PM_HANDLE, args=_jsonable(args), target=target, diff=diff,
        status=ApprovalStatus.PENDING, created_at=datetime.now(UTC),
    ))


def _jsonable(args: dict) -> dict:
    from .runner import _jsonable as jsonable

    return jsonable(args)
