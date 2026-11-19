"""Private, per-run bindings for chat runtime sessions.

This stores an identity mapping, not the runtime's journal. The caller must derive the
identity from its trusted, effective configuration and isolate the runtime's storage.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from dotrix_backend.core.errors import Conflict, Forbidden
from dotrix_backend.modules.agent_definitions.repository import AgentDefinitionRepository
from dotrix_backend.modules.projects.repository import ProjectRepository
from dotrix_backend.modules.workspaces.permissions import Permission, can
from dotrix_backend.modules.workspaces.repository import MembershipRepository
from dotrix_engine.contracts import PM_HANDLE
from dotrix_engine.runtimes.contracts import validate_session

from .models import AgentRun, AgentRuntimeBinding, RunStatus
from .runtime_tools import RuntimeRunScope
from .storage_backend import SessionFactory

_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,79}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class RuntimeIdentity:
    """A pinned engine and SHA-256 fingerprint derived by the trusted runtime host."""

    runtime: str
    version: str
    config_digest: str

    def __post_init__(self) -> None:
        if (self.runtime not in {"deepagents", "fx"} or not _VERSION.fullmatch(self.version)
                or not _DIGEST.fullmatch(self.config_digest)):
            raise ValueError("Invalid runtime identity")


async def admit_runtime_run(session: AsyncSession, workspace_id: uuid.UUID, run_id: uuid.UUID, token: int) -> AgentRun:
    """Validate a run and hold its row lock until the caller's transaction ends."""
    # The lock serializes binding with lease changes and another attempt binding this run.
    run = await session.scalar(select(AgentRun).where(
        AgentRun.workspace_id == workspace_id, AgentRun.id == run_id,
    ).with_for_update())
    if (run is None or run.status is not RunStatus.RUNNING or token < 1 or run.lease_token != token
            or run.lease_expires_at is None or run.lease_expires_at <= datetime.now(UTC)
            or run.project_id is None or run.requested_by_id is None):
        raise Conflict("The run no longer owns this work")
    projects = ProjectRepository(session)
    project = await projects.get(workspace_id, run.project_id)
    member = await MembershipRepository(session).get(workspace_id, run.requested_by_id)
    if (project is None or member is None or not can(member, Permission.CHAT)
            or not await projects.can_see(project, run.requested_by_id)):
        raise Forbidden("The person who asked no longer sees this project")
    resolved = await AgentDefinitionRepository(session).resolve(workspace_id, run.project_id)
    if not any(item.spec.handle == (run.agent or PM_HANDLE) for item in resolved):
        raise Forbidden("The run's agent is no longer available")
    # Policy lookups may have consumed the remaining lease while the row was locked.
    if run.lease_expires_at <= datetime.now(UTC):
        raise Conflict("The run no longer owns this work")
    return run


def _scope(run: AgentRun, token: int, session_id: str) -> RuntimeRunScope:
    assert run.project_id is not None and run.requested_by_id is not None
    return RuntimeRunScope(run.workspace_id, run.project_id, run.id, run.requested_by_id,
                           run.agent or PM_HANDLE, token, session_id)


def _matches(binding: AgentRuntimeBinding, identity: RuntimeIdentity) -> bool:
    return (binding.runtime == identity.runtime and binding.runtime_version == identity.version
            and binding.config_digest == identity.config_digest)


async def bind_runtime_session(
    sessions: SessionFactory, *, workspace_id: uuid.UUID, run_id: uuid.UUID, token: int,
    identity: RuntimeIdentity, session_id: str, encrypted_context: str | None = None,
) -> RuntimeRunScope:
    """Bind once, or repeat the identical binding after verifying the live lease and access."""
    validate_session(session_id, "bind")
    async with sessions() as session:
        run = await admit_runtime_run(session, workspace_id, run_id, token)
        binding = await session.scalar(select(AgentRuntimeBinding).where(
            AgentRuntimeBinding.workspace_id == workspace_id, AgentRuntimeBinding.run_id == run_id,
        ))
        if binding is not None:
            if not _matches(binding, identity) or binding.session_id != session_id:
                raise Conflict("The run is already bound to another runtime session or configuration")
        else:
            session.add(AgentRuntimeBinding(
                workspace_id=workspace_id, run_id=run_id, runtime=identity.runtime,
                runtime_version=identity.version, config_digest=identity.config_digest,
                session_id=session_id, encrypted_context=encrypted_context, created_at=datetime.now(UTC),
            ))
        scope = _scope(run, token, session_id)
        if run.lease_expires_at <= datetime.now(UTC):
            raise Conflict("The run no longer owns this work")
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            raise Conflict("The runtime session is already bound") from None
        return scope


async def upgrade_runtime_binding(
    sessions: SessionFactory, *, workspace_id: uuid.UUID, run_id: uuid.UUID, token: int, identity: RuntimeIdentity,
    earlier: dict[str, bool], encrypted_context: str | None = None,
) -> None:
    """Move a run bound by an earlier version of the same runtime to `identity`, keeping its session.

    `earlier` names the versions that may be upgraded, each True when this version can't read its journal:
    then the journal and checkpoint are dropped and the turn starts again from its message (its changes,
    if any, are still claimed once in `agent_runtime_calls`). A binding without a pinned context gets
    `encrypted_context`. Any other binding is left alone, to fail closed as before."""
    from .models import AgentRuntimeCheckpoint, AgentRuntimeJournal

    async with sessions() as session:
        await admit_runtime_run(session, workspace_id, run_id, token)
        binding = await session.scalar(select(AgentRuntimeBinding).where(
            AgentRuntimeBinding.workspace_id == workspace_id, AgentRuntimeBinding.run_id == run_id,
        ).with_for_update())
        if binding is None or binding.runtime != identity.runtime or binding.runtime_version not in earlier:
            return
        if earlier[binding.runtime_version]:
            for table in (AgentRuntimeJournal, AgentRuntimeCheckpoint):
                await session.execute(delete(table).where(table.workspace_id == workspace_id,
                                                          table.binding_id == binding.id))
        binding.runtime_version, binding.config_digest = identity.version, identity.config_digest
        binding.encrypted_context = binding.encrypted_context or encrypted_context
        await session.commit()


async def get_runtime_session(
    sessions: SessionFactory, *, workspace_id: uuid.UUID, run_id: uuid.UUID, token: int,
    identity: RuntimeIdentity,
) -> RuntimeRunScope:
    """Find an existing binding for a new lease; this does not resume the runtime itself."""
    async with sessions() as session:
        run = await admit_runtime_run(session, workspace_id, run_id, token)
        binding = await session.scalar(select(AgentRuntimeBinding).where(
            AgentRuntimeBinding.workspace_id == workspace_id, AgentRuntimeBinding.run_id == run_id,
        ))
        if binding is None or not _matches(binding, identity):
            raise Conflict("The run has no matching runtime session and configuration")
        if run.lease_expires_at <= datetime.now(UTC):
            raise Conflict("The run no longer owns this work")
        return _scope(run, token, binding.session_id)
