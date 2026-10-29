"""Read-only platform tools for experimental chat runtimes.

The production runner does not select these yet. A caller must first bind a runtime
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
