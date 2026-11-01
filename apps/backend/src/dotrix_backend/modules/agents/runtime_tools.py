"""Read-only platform tools for the chat runtimes.

The fx pilot selects these for project Chat. A caller must first bind a runtime
session to an admitted platform run; session IDs supplied by a model are not authority.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from langchain_core.tools import StructuredTool
from sqlalchemy import select

from dotrix_backend.core.errors import Conflict, Forbidden
from dotrix_backend.modules.agent_definitions.repository import AgentDefinitionRepository
from dotrix_backend.modules.projects.repository import ProjectRepository
from dotrix_backend.modules.search.embeddings import Embedder
from dotrix_backend.modules.workspaces.permissions import Permission, can
from dotrix_backend.modules.workspaces.repository import MembershipRepository
from dotrix_engine.catalog import tool_id
from dotrix_engine.contracts import PM_HANDLE, AgentSpec
from dotrix_engine.runtimes import RuntimeTool, RuntimeToolContext

from .knowledge_tools import build_knowledge_tools
from .models import AgentRun, AgentRuntimeBinding, RunStatus
from .storage_backend import SessionFactory

_READ_TOOLS = frozenset({"document_outline", "read_section", "read_skill", "search_knowledge"})


@dataclass(frozen=True)
class RuntimeRunScope:
    """A binding assembled by the platform from a run it has already admitted."""

    workspace_id: uuid.UUID
    project_id: uuid.UUID
    run_id: uuid.UUID
    requested_by_id: uuid.UUID
    agent: str
    lease_token: int
    session_id: str


async def _authorize_read(
    sessions: SessionFactory, scope: RuntimeRunScope, context: RuntimeToolContext, capability: str,
) -> None:
    if context.session_id != scope.session_id:
        raise Forbidden("This runtime session is not bound to the run")
    async with sessions() as session:
        run = await session.scalar(select(AgentRun).where(
            AgentRun.workspace_id == scope.workspace_id, AgentRun.project_id == scope.project_id,
            AgentRun.id == scope.run_id, AgentRun.requested_by_id == scope.requested_by_id,
        ))
        now = datetime.now(UTC)
        if (run is None or run.status is not RunStatus.RUNNING or run.lease_token != scope.lease_token
                or run.lease_expires_at is None or run.lease_expires_at <= now
                or (run.agent or PM_HANDLE) != scope.agent):
            raise Conflict("The run no longer owns this work")
        binding = await session.scalar(select(AgentRuntimeBinding.id).where(
            AgentRuntimeBinding.workspace_id == scope.workspace_id, AgentRuntimeBinding.run_id == scope.run_id,
            AgentRuntimeBinding.session_id == scope.session_id,
        ))
        if binding is None:
            raise Forbidden("This runtime session is not bound to the run")
        project = await ProjectRepository(session).get(scope.workspace_id, scope.project_id)
        member = await MembershipRepository(session).get(scope.workspace_id, scope.requested_by_id)
        if (project is None or member is None or not can(member, Permission.CHAT)
                or not await ProjectRepository(session).can_see(project, scope.requested_by_id)):
            raise Forbidden("The person who asked no longer sees this project")
        resolved = await AgentDefinitionRepository(session).resolve(scope.workspace_id, scope.project_id)
        current = next((item.spec for item in resolved if item.spec.handle == scope.agent), None)
        if current is None or not current.can(capability):
            raise Forbidden("The agent no longer has this tool")


def scoped_knowledge_tools(
    sessions: SessionFactory, *, scope: RuntimeRunScope, spec: AgentSpec, embedder: Embedder | None,
) -> list[RuntimeTool]:
    """Expose only permitted knowledge reads and recheck the run before and after each call.

    The supplied `spec` is the run's initial contract; the current contract is checked
    again at execution. This is not an approval, delegation or side-effect adapter.
    """
    if spec.handle != scope.agent or not scope.session_id or scope.lease_token < 1:
        raise ValueError("The agent, session and lease must match the admitted run")
    tools = []
    for fn in build_knowledge_tools(
        sessions, workspace_id=scope.workspace_id, project_id=scope.project_id, embedder=embedder,
    ):
        tool = StructuredTool.from_function(coroutine=fn)
        capability = tool_id(tool)
        if tool.name not in _READ_TOOLS or capability not in ("knowledge.read", "knowledge.search"):
            raise ValueError(f"Unexpected runtime knowledge tool {tool.name}")
        if not spec.can(capability):
            continue

        async def execute(arguments: dict, context: RuntimeToolContext, *, _tool=tool, _capability=capability):
            await _authorize_read(sessions, scope, context, _capability)
            result = await _tool.ainvoke(arguments)
            # Do not return the result if access or the lease was revoked during the read.
            await _authorize_read(sessions, scope, context, _capability)
            return result

        tools.append(RuntimeTool(
            name=tool.name, description=tool.description, input_schema=tool.args_schema.model_json_schema(),
            idempotent=True, writes=False, execute_scoped=execute,
        ))
    return tools


def scoped_project_tools(
    sessions: SessionFactory, *, scope: RuntimeRunScope, spec: AgentSpec, embedder: Embedder | None,
    code_tools: list | None = None, web_tools: list | None = None,
) -> list[RuntimeTool]:
    """The read-only project surface, with the same builders as DeepAgents.

    Only explicit read capabilities may cross this boundary. Authorization surrounds
    every invocation, including results that finish after a lease or access change.
    """
    from dataclasses import asdict

    from .board_tools import BoardContext, build_board_tools
    from .graph_tools import build_graph_tools
    from .storage_backend import PlatformKnowledgeBackend

    backend = PlatformKnowledgeBackend(sessions, workspace_id=scope.workspace_id, project_id=scope.project_id,
                                       instructed_by_id=scope.requested_by_id)

    def path(value: str) -> str:
        return "/" + value.removeprefix("/dotrix/").lstrip("/")

    async def read_file(file_path: str, offset: int = 0, limit: int = 2000) -> dict:
        """Read a project document by /dotrix/ path, optionally a range of lines."""
        return asdict(await backend.aread(path(file_path), offset, limit))

    async def ls(path: str = "/dotrix/") -> dict:
        """List a project document folder."""
        return asdict(await backend.als("/" + path.removeprefix("/dotrix/").lstrip("/")))

    async def glob(pattern: str, path: str = "/dotrix/") -> dict:
        """Find project documents by glob pattern."""
        return asdict(await backend.aglob(pattern, "/" + path.removeprefix("/dotrix/").lstrip("/")))

    async def grep(pattern: str, path: str = "/dotrix/", glob: str | None = None) -> dict:
        """Search within project documents. Prefer sections to large full reads."""
        return asdict(await backend.agrep(pattern, "/" + path.removeprefix("/dotrix/").lstrip("/"), glob, max_count=100))

    ctx = BoardContext(sessions, scope.workspace_id, scope.project_id, scope.requested_by_id, None, coding=False)
    board, _, _ = build_board_tools(ctx)
    functions = [read_file, ls, glob, grep, *board,
                 *(fn for fn in build_graph_tools(ctx) if fn.__name__ != "link_items"), *(code_tools or []), *(web_tools or [])]
    tools = scoped_knowledge_tools(sessions, scope=scope, spec=spec, embedder=embedder)
    for fn in functions:
        tool = fn if isinstance(fn, StructuredTool) else StructuredTool.from_function(coroutine=fn)
        capability = tool_id(tool)
        if capability not in {"knowledge.read", "board.read", "graph.read", "code.read", "web.search"}:
            raise ValueError(f"Unexpected project read tool {tool.name}")
        if not spec.can(capability):
            continue

        async def execute(arguments: dict, context: RuntimeToolContext, *, _tool=tool, _capability=capability):
            await _authorize_read(sessions, scope, context, _capability)
            result = await _tool.ainvoke(arguments)
            await _authorize_read(sessions, scope, context, _capability)
            return result

        tools.append(RuntimeTool(tool.name, tool.description, tool.args_schema.model_json_schema(),
                                 idempotent=True, writes=False, execute_scoped=execute))
    return tools
