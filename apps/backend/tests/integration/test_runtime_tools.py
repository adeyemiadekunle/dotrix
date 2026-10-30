"""Experimental runtime tools recheck project access and the run lease at each call."""
import asyncio
import hashlib
import json
import os
import shutil
import threading
import uuid
from contextlib import asynccontextmanager, contextmanager, suppress
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from httpx import ASGITransport, AsyncClient
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker
from uuid_utils.compat import uuid7

from dotrix_backend.core.crypto import Secrets
from dotrix_backend.core.email import get_email_sender
from dotrix_backend.core.errors import Conflict, Forbidden, Unprocessable
from dotrix_backend.core.jobs import InlineJobs, JobContext
from dotrix_backend.core.security import create_access_token
from dotrix_backend.core.storage import get_storage, optional_storage
from dotrix_backend.jobs import JOBS
from dotrix_backend.main import create_app
from dotrix_backend.modules.agent_definitions.models import AgentPreference
from dotrix_backend.modules.agents import fx_pilot, runtime_journal, runtime_tools
from dotrix_backend.modules.agents.delegation import DelegationService
from dotrix_backend.modules.agents.llm import ModelUnavailable
from dotrix_backend.modules.agents.models import (
    AgentRun,
    AgentRuntimeBinding,
    AgentRuntimeCheckpoint,
    AgentRuntimeJournal,
    ChatRuntime,
    RunKind,
    RunStatus,
    WorkMode,
)
from dotrix_backend.modules.agents.runner import AgentRunner
from dotrix_backend.modules.agents.runtime_journal import JournalFenced, RuntimeJournal
from dotrix_backend.modules.agents.runtime_sessions import (
    RuntimeIdentity,
    bind_runtime_session,
    get_runtime_session,
)
from dotrix_backend.modules.agents.runtime_tools import RuntimeRunScope, scoped_knowledge_tools
from dotrix_backend.modules.auth.models import User
from dotrix_backend.modules.knowledge.models import KnowledgeFile
from dotrix_backend.modules.model_keys.models import UserModelKey
from dotrix_backend.modules.projects.models import Project, ProjectSource
from dotrix_backend.modules.workspaces.models import Membership, Role, Workspace, WorkspaceKind
from dotrix_engine.builtins import builtin
from dotrix_engine.delegation import SpecialistBatch, SpecialistResult
from dotrix_engine.runtimes import (
    AgentRuntimeConfig,
    DeepAgentsRuntime,
    FxRuntime,
    RuntimeHandoff,
    RuntimeTool,
    RuntimeToolContext,
    fx_configuration_digest,
)
from dotrix_engine.testing import tool_call


@pytest.fixture
async def runtime_world(signup, create_team, db_client, db_session):
    person = await signup()
    workspace = await create_team(person.headers)
    ws = f"/v1/workspaces/{workspace['id']}"
    project = (await db_client.post(f"{ws}/projects", json={"key": "FXT", "name": "Runtime"}, headers=person.headers)).json()
    base = f"{ws}/projects/{project['id']}"
    response = await db_client.put(f"{base}/knowledge/files/research/runtime.md", headers=person.headers,
                                   json={"content": "# Evidence\n\nPrivate project evidence.\n", "base_version": 0})
    assert response.status_code == 200, response.text
    now = datetime.now(UTC)
    run = AgentRun(id=uuid7(), workspace_id=uuid.UUID(workspace["id"]), project_id=uuid.UUID(project["id"]),
                   thread_id=uuid7(), kind=RunKind.CHAT, status=RunStatus.RUNNING, agent="research",
                   requested_by_id=uuid.UUID(person.id), message="Investigate", lease_token=1,
                   lease_expires_at=now + timedelta(minutes=5), created_at=now, updated_at=now)
    db_session.add(run)
    await db_session.commit()
    scope = RuntimeRunScope(run.workspace_id, run.project_id, run.id, run.requested_by_id,
                            "research", 1, "runtime-session")
    sessions = db_client._transport.app.state.runner.session_factory
    return person, ws, base, run, scope, sessions


def tool_for(sessions, scope, name="read_section"):
    spec = builtin("research")
    return next(tool for tool in scoped_knowledge_tools(sessions, scope=scope, spec=spec, embedder=None)
                if tool.name == name)


async def bind_scope(sessions, scope, runtime="fx"):
    return await bind_runtime_session(
        sessions, workspace_id=scope.workspace_id, run_id=scope.run_id, token=scope.lease_token,
        identity=RuntimeIdentity(runtime, "test-1", "a" * 64), session_id=scope.session_id,
    )


async def invoke(tool, session_id="runtime-session"):
    return await tool.execute_scoped({"file_path": "/dotrix/research/runtime.md", "heading": "Evidence"},
                                     RuntimeToolContext(session_id, "call-1"))


async def test_read_tools_use_the_real_project_and_expose_no_write_tools(runtime_world):
    _, _, _, _, scope, sessions = runtime_world
    scope = await bind_scope(sessions, scope)
    tools = scoped_knowledge_tools(sessions, scope=scope, spec=builtin("research"), embedder=None)
    assert {tool.name for tool in tools} == {"read_section", "read_skill", "document_outline", "search_knowledge"}
    assert all(tool.idempotent and not tool.writes for tool in tools)
    assert "Private project evidence" in await invoke(tool_for(sessions, scope))
    restricted = builtin("research").model_copy(update={"tools": ["knowledge.search"]})
    assert {tool.name for tool in scoped_knowledge_tools(sessions, scope=scope, spec=restricted, embedder=None)} == {
        "search_knowledge"
    }


async def test_nova_run_uses_its_builtin_identity_for_scoped_reads(runtime_world, db_session):
    _, _, _, run, scope, sessions = runtime_world
    run.agent = None  # The platform stores the default coordinator with no explicit handle.
    await db_session.commit()
    scope = replace(scope, agent="project-manager")
    scope = await bind_scope(sessions, scope)
    tools = scoped_knowledge_tools(sessions, scope=scope, spec=builtin("project-manager"), embedder=None)
    read = next(tool for tool in tools if tool.name == "read_section")
    assert "Private project evidence" in await invoke(read)


async def test_runtime_binding_pins_configuration_and_follows_a_new_lease(runtime_world, db_session):
    _, _, _, run, scope, sessions = runtime_world
    identity = RuntimeIdentity("fx", "test-1", "a" * 64)
    with pytest.raises(Conflict):
        await get_runtime_session(sessions, workspace_id=scope.workspace_id, run_id=scope.run_id,
                                  token=1, identity=identity)
    assert await bind_scope(sessions, scope) == scope
    assert await bind_scope(sessions, scope) == scope  # Retrying the identical binding is safe.
    assert await get_runtime_session(sessions, workspace_id=scope.workspace_id, run_id=scope.run_id,
                                     token=1, identity=identity) == scope
    for different in (RuntimeIdentity("deepagents", "test-1", "a" * 64),
                      RuntimeIdentity("fx", "test-2", "a" * 64),
                      RuntimeIdentity("fx", "test-1", "b" * 64)):
        with pytest.raises(Conflict):
            await get_runtime_session(sessions, workspace_id=scope.workspace_id, run_id=scope.run_id,
                                      token=1, identity=different)
        with pytest.raises(Conflict):
            await bind_runtime_session(sessions, workspace_id=scope.workspace_id, run_id=scope.run_id,
                                       token=1, identity=different, session_id=scope.session_id)
    with pytest.raises(Conflict):
        await bind_runtime_session(sessions, workspace_id=scope.workspace_id, run_id=scope.run_id,
                                   token=1, identity=identity, session_id="other-session")
    with pytest.raises(Conflict):
        await get_runtime_session(sessions, workspace_id=uuid7(), run_id=scope.run_id, token=1, identity=identity)
    run.lease_token = 2
    await db_session.commit()
    with pytest.raises(Conflict):
        await get_runtime_session(sessions, workspace_id=scope.workspace_id, run_id=scope.run_id,
                                  token=1, identity=identity)
    recovered = await get_runtime_session(sessions, workspace_id=scope.workspace_id, run_id=scope.run_id,
                                           token=2, identity=identity)
    assert recovered == replace(scope, lease_token=2)
    assert len(list(await db_session.scalars(select(AgentRuntimeBinding)))) == 1
    with pytest.raises(Conflict):
        await invoke(tool_for(sessions, scope))
    assert "Private project evidence" in await invoke(tool_for(sessions, recovered))


async def test_unbound_or_forged_session_cannot_read(runtime_world):
    _, _, _, _, scope, sessions = runtime_world
    with pytest.raises(Forbidden):
        await invoke(tool_for(sessions, scope))
    await bind_scope(sessions, scope)
    forged = replace(scope, session_id="another-session")
    with pytest.raises(Forbidden):
        await invoke(tool_for(sessions, forged), forged.session_id)


async def test_retrieving_a_binding_rechecks_project_membership(runtime_world, db_session):
    _, _, _, _, scope, sessions = runtime_world
    await bind_scope(sessions, scope)
    member = await db_session.scalar(select(Membership).where(Membership.workspace_id == scope.workspace_id,
                                                               Membership.user_id == scope.requested_by_id))
    member.role = Role.GUEST
    await db_session.commit()
    with pytest.raises(Forbidden):
        await get_runtime_session(sessions, workspace_id=scope.workspace_id, run_id=scope.run_id, token=1,
                                  identity=RuntimeIdentity("fx", "test-1", "a" * 64))


async def test_a_runtime_session_cannot_be_bound_to_a_second_run(runtime_world, db_session):
    _, _, _, first, scope, sessions = runtime_world
    await bind_scope(sessions, scope)
    now = datetime.now(UTC)
    second = AgentRun(id=uuid7(), workspace_id=first.workspace_id, project_id=first.project_id,
                      thread_id=uuid7(), kind=RunKind.CHAT, status=RunStatus.RUNNING, agent="research",
                      requested_by_id=first.requested_by_id, message="Another investigation", lease_token=1,
                      lease_expires_at=now + timedelta(minutes=5), created_at=now, updated_at=now)
    db_session.add(second)
    await db_session.commit()
    with pytest.raises(Conflict):
        await bind_runtime_session(sessions, workspace_id=scope.workspace_id, run_id=second.id, token=1,
                                   identity=RuntimeIdentity("fx", "test-1", "a" * 64), session_id=scope.session_id)
    assert "Private project evidence" in await invoke(tool_for(sessions, scope))


async def test_runtime_binding_is_deleted_with_its_run(runtime_world, db_session):
    _, _, _, _, scope, sessions = runtime_world
    await bind_scope(sessions, scope)
    await db_session.execute(delete(AgentRun).where(AgentRun.workspace_id == scope.workspace_id, AgentRun.id == scope.run_id))
    await db_session.commit()
    assert await db_session.scalar(select(AgentRuntimeBinding.id).where(
        AgentRuntimeBinding.workspace_id == scope.workspace_id, AgentRuntimeBinding.run_id == scope.run_id)) is None


@pytest.fixture
async def journal_world(nova_pilot_world):
    run, sessions, secrets = nova_pilot_world
    identity = RuntimeIdentity("fx", "test-1", "b" * 64)
    await bind_runtime_session(sessions, workspace_id=run.workspace_id, run_id=run.id, token=1,
                               identity=identity, session_id="journal-session")
    return run, sessions, secrets, identity, RuntimeJournal(
        sessions, secrets, workspace_id=run.workspace_id, run_id=run.id, token=1,
        identity=identity, session_id="journal-session",
    )


async def test_runtime_journal_persists_encrypted_records_and_checkpoints(journal_world):
    run, sessions, _, _, journal = journal_world
    assert (await journal.load()).records == ()
    assert await journal.append(expected=None, idempotency_key="one", data=b"private prompt") == "1"
    assert await journal.append(expected=None, idempotency_key="one", data=b"private prompt") == "1"
    with pytest.raises(Conflict):
        await journal.append(expected=None, idempotency_key="one", data=b"different prompt")
    with pytest.raises(JournalFenced):
        await journal.append(expected=None, idempotency_key="other", data=b"stale write")
    assert await journal.append(expected="1", idempotency_key="two", data=b"private result") == "2"
    await journal.save_checkpoint(through="1", data=b"private checkpoint")
    snapshot = await journal.load()
    assert snapshot.checkpoint == ("1", b"private checkpoint")
    assert snapshot.records == (("2", b"private result"),)
    await journal.save_checkpoint(through="1", data=b"private checkpoint")
    with pytest.raises(JournalFenced):
        await journal.save_checkpoint(through="1", data=b"another checkpoint")
    async with sessions() as session:
        records = list(await session.scalars(select(AgentRuntimeJournal).where(AgentRuntimeJournal.workspace_id == run.workspace_id)))
        checkpoint = await session.scalar(select(AgentRuntimeCheckpoint).where(AgentRuntimeCheckpoint.workspace_id == run.workspace_id))
        assert len(records) == 2
        assert all("private" not in row.encrypted for row in records) and "private" not in checkpoint.encrypted
        await session.execute(delete(AgentRun).where(AgentRun.workspace_id == run.workspace_id, AgentRun.id == run.id))
        await session.commit()
        assert not list(await session.scalars(select(AgentRuntimeJournal).where(AgentRuntimeJournal.workspace_id == run.workspace_id)))
        assert await session.scalar(select(AgentRuntimeCheckpoint.id).where(AgentRuntimeCheckpoint.workspace_id == run.workspace_id)) is None


async def test_runtime_journal_serializes_competing_and_duplicate_writers(journal_world):
    _, _, _, _, journal = journal_world
    concurrent = await asyncio.gather(
        journal.append(expected=None, idempotency_key="first", data=b"one"),
        journal.append(expected=None, idempotency_key="second", data=b"two"),
        return_exceptions=True,
    )
    assert concurrent.count("1") == 1 and sum(isinstance(item, JournalFenced) for item in concurrent) == 1
    repeated = await asyncio.gather(
        journal.append(expected="1", idempotency_key="repeat", data=b"same"),
        journal.append(expected="1", idempotency_key="repeat", data=b"same"),
    )
    assert repeated == ["2", "2"]
    assert len((await journal.load()).records) == 2


async def test_runtime_journal_rechecks_access_and_fences_expired_or_old_workers(journal_world):
    run, sessions, secrets, identity, journal = journal_world
    await journal.append(expected=None, idempotency_key="one", data=b"private")
    async with sessions() as session:
        await session.execute(update(AgentRun).where(AgentRun.id == run.id).values(
            lease_token=2, lease_expires_at=datetime.now(UTC) + timedelta(minutes=5)))
        await session.commit()
    with pytest.raises(Conflict):
        await journal.load()
    recovered = RuntimeJournal(sessions, secrets, workspace_id=run.workspace_id, run_id=run.id, token=2,
                               identity=identity, session_id="journal-session")
    assert (await recovered.load()).records == (("1", b"private"),)
    async with sessions() as session:
        await session.execute(update(Membership).where(Membership.workspace_id == run.workspace_id,
                                                        Membership.user_id == run.requested_by_id).values(role=Role.GUEST))
        await session.commit()
    with pytest.raises(Forbidden):
        await recovered.load()


async def test_runtime_journal_rejects_unreadable_data_and_oversize_writes(journal_world, monkeypatch):
    run, sessions, _, identity, journal = journal_world
    monkeypatch.setattr(runtime_journal, "MAX_JOURNAL_BYTES", 6)
    assert await journal.append(expected=None, idempotency_key="one", data=b"1234") == "1"
    with pytest.raises(Unprocessable, match="size limit"):
        await journal.append(expected="1", idempotency_key="two", data=b"567")
    wrong_key = RuntimeJournal(sessions, Secrets(Fernet.generate_key().decode()), workspace_id=run.workspace_id,
                               run_id=run.id, token=1, identity=identity, session_id="journal-session")
    with pytest.raises(Conflict, match="cannot be decrypted"):
        await wrong_key.load()
    assert (await journal.load()).records == (("1", b"1234"),)


@pytest.mark.parametrize("settlement", ["completion", "sweep", "expired"])
async def test_failed_fx_parent_cancels_its_unstarted_specialists(journal_world, settlement):
    from dotrix_backend.modules.agents.coding_outcomes import sweep_team
    from dotrix_backend.modules.execution.service import expire_agent_leases

    run, sessions, secrets, _, _ = journal_world
    stopped = []

    async def stop(run_id, reason):
        stopped.append((run_id, reason))

    runner = SimpleNamespace(session_factory=sessions, queue=None, stop_reasons=None, secrets=secrets, stop=stop)
    scheduler = DelegationService(runner)
    async with sessions() as session:
        await session.execute(update(AgentRun).where(AgentRun.id == run.id).values(
            orchestration=True, chat_runtime=ChatRuntime.FX))
        await session.commit()
    batch = SpecialistBatch(tasks=[{"key": "research", "agent": "research", "brief": "Review",
                                   "expected_result": "Evidence"}])
    await scheduler.submit(run.workspace_id, run.id, 1, "tool-call", batch, verify_runtime_batch=True)
    async with sessions() as session:
        values = ({"lease_expires_at": datetime.now(UTC) - timedelta(seconds=1)} if settlement == "expired"
                  else {"status": RunStatus.FAILED})
        await session.execute(update(AgentRun).where(AgentRun.id == run.id).values(**values))
        await session.commit()
    if settlement == "completion":
        await scheduler.completed(run.workspace_id, run.id)
    else:
        if settlement == "expired":
            assert await expire_agent_leases(sessions, queue_name="test-fx") == 1
        await sweep_team(runner)
    async with sessions() as session:
        child = await session.scalar(select(AgentRun).where(AgentRun.workspace_id == run.workspace_id,
                                                             AgentRun.parent_run_id == run.id))
        assert child.status is RunStatus.CANCELLED and stopped[0][0] == child.id


async def test_fx_delegation_cannot_commit_after_its_lease_expires(journal_world, monkeypatch):
    from dotrix_backend.modules.agents import delegation

    run, sessions, secrets, _, _ = journal_world
    async with sessions() as session:
        await session.execute(update(AgentRun).where(AgentRun.id == run.id).values(
            orchestration=True, lease_expires_at=datetime.now(UTC) + timedelta(seconds=2)))
        await session.commit()
    resolve = delegation.AgentDefinitionRepository.resolve

    async def slow_resolve(self, *args, **kwargs):
        await asyncio.sleep(2.1)
        return await resolve(self, *args, **kwargs)

    monkeypatch.setattr(delegation.AgentDefinitionRepository, "resolve", slow_resolve)
    scheduler = DelegationService(SimpleNamespace(session_factory=sessions, secrets=secrets))
    batch = SpecialistBatch(tasks=[{"key": "research", "agent": "research", "brief": "Review",
                                   "expected_result": "Evidence"}])
    with pytest.raises(Conflict):
        await scheduler.submit(run.workspace_id, run.id, 1, "tool-call", batch, verify_runtime_batch=True)
    async with sessions() as session:
        assert await session.scalar(select(AgentRun.id).where(AgentRun.workspace_id == run.workspace_id,
                                                             AgentRun.parent_run_id == run.id)) is None


async def test_expired_fx_worker_cannot_renew_or_clear_the_lease(journal_world, agent_script):
    run, sessions, secrets, _, _ = journal_world
    expired = datetime.now(UTC) - timedelta(seconds=1)
    async with sessions() as session:
        await session.execute(update(AgentRun).where(AgentRun.id == run.id).values(lease_expires_at=expired))
        await session.commit()
    runner = AgentRunner(session_factory=sessions, checkpointer=InMemorySaver(), model_factory=agent_script.factory,
                         inline=True, secrets=secrets, settings=SimpleNamespace(agent_lease_seconds=0.06))

    async def worker():
        renewal = runner._hold_lease(run.id, 1)
        try:
            await asyncio.Event().wait()
        finally:
            renewal.cancel()

    task = asyncio.create_task(worker())
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 5)
    await runner._release_lease(run.id, 1, None)
    async with sessions() as session:
        stored = await session.get(AgentRun, run.id)
        assert stored.status is RunStatus.RUNNING and stored.lease_expires_at == expired


async def test_fx_restarts_an_interrupted_read_from_the_database_journal(journal_world, monkeypatch):
    """A killed fx host resumes its open turn using the Postgres journal."""
    from dotrix_engine.runtimes.fx import _HOST

    if not shutil.which("node") or not (_HOST / "node_modules" / "libfx").is_dir():
        pytest.skip("Install the optional fx host to exercise the real libfx runtime")
    run, sessions, _, _, journal = journal_world
    scope = RuntimeRunScope(run.workspace_id, run.project_id, run.id, run.requested_by_id,
                            "project-manager", 1, "journal-session")
    read = next(tool for tool in scoped_knowledge_tools(sessions, scope=scope, spec=builtin("project-manager"),
                                                        embedder=None) if tool.name == "read_section")
    intent_saved = asyncio.Event()
    original_append = journal.append

    async def observe_append(**kwargs):
        cursor = await original_append(**kwargs)
        record = json.loads(kwargs["data"])
        if any(event["type"] == "tool_intent" and any(call["name"] == "read_section" for call in event["data"])
               for event in record["events"]):
            intent_saved.set()
        return cursor

    monkeypatch.setattr(journal, "append", observe_append)
    started = asyncio.Event()
    recovered = False
    executions = []

    async def interrupted_read(arguments, context):
        executions.append(context.execution_id)
        if not recovered:
            started.set()
            await asyncio.Event().wait()
        return await read.execute_scoped(arguments, context)

    config = AgentRuntimeConfig("project-manager", "Use the project knowledge tool.",
                                (replace(read, execute_scoped=interrupted_read),))
    requests = []
    with model_server(requests=requests, report_usage=True) as url:
        first = await FxRuntime.create(config, model="test-model", base_url=url, api_key="test-key",
                                       journal=journal, engine_session="journal-session")
        task = asyncio.create_task(first.prompt("journal-session", "Read the evidence", message_id="turn-1"))
        # Idempotent reads can start before libfx persists their intent. Crash
        # only after that commit so this tests replay of a saved call, rather
        # than a new model request racing an unpersisted speculative read.
        try:
            await asyncio.wait_for(started.wait(), 20)
            await asyncio.wait_for(intent_saved.wait(), 20)
        except BaseException:
            await first.close()
            with suppress(asyncio.CancelledError, RuntimeError):
                await task
            raise
        first.process.kill()
        with pytest.raises(RuntimeError):
            await task
        await first.close()
        assert (await journal.load()).records
        recovered = True
        second = await FxRuntime.create(config, model="test-model", base_url=url, api_key="test-key",
                                        journal=journal, engine_session="journal-session")
        try:
            result = await asyncio.wait_for(second.resume("journal-session", rerun_tools=("read_section",)), 20)
            assert result.stop_reason == "end_turn" and "Private project evidence" in result.text
            assert result.usage is None  # Recovery cannot promise usage from before the crash.
            assert len(requests) >= 2
            assert len(executions) == 2 and executions[0] == executions[1]
        finally:
            await second.close()


async def test_fx_handoff_survives_process_restart_with_the_real_scheduler(journal_world):
    """Persist the handoff, release the parent, and read one saved child result on resume."""
    from dotrix_engine.runtimes.fx import _HOST

    if not shutil.which("node") or not (_HOST / "node_modules" / "libfx").is_dir():
        pytest.skip("Install the optional fx host to exercise the real libfx runtime")
    run, sessions, secrets, identity, journal = journal_world
    async with sessions() as session:
        await session.execute(update(AgentRun).where(AgentRun.id == run.id).values(orchestration=True))
        await session.commit()
    dispatched, executions = [], []
    submitted = asyncio.Event()
    interrupted = True

    async def dispatch(run_id, payload):
        dispatched.append((run_id, payload))

    scheduler = DelegationService(SimpleNamespace(session_factory=sessions, queue=None, stop_reasons=None, secrets=secrets,
                                                   _dispatch=dispatch))
    token = 1

    async def delegate(arguments, context):
        executions.append(context.execution_id)
        batch = SpecialistBatch.model_validate(arguments)
        result = await scheduler.submit(run.workspace_id, run.id, token, context.execution_id, batch,
                                        verify_runtime_batch=True)
        if result is None and interrupted:
            submitted.set()
            await asyncio.Event().wait()
        return RuntimeHandoff() if result is None else {"tasks": result}

    tool = RuntimeTool("delegate_tasks", "Delegate a read-only specialist task",
                       SpecialistBatch.model_json_schema(), execute_scoped=delegate, writes=True)
    config = AgentRuntimeConfig("project-manager", "Ask a specialist for a review.", (tool,))
    args = {"tasks": [{"key": "research", "agent": "research", "brief": "Review the evidence",
                       "expected_result": "Evidence"}]}
    with model_server(tool_name="delegate_tasks", tool_args=args) as url:
        first = await FxRuntime.create(config, model="test-model", base_url=url, api_key="test-key",
                                       journal=journal, engine_session="journal-session")
        try:
            task = asyncio.create_task(first.prompt("journal-session", "Ask for a review", message_id="turn-1"))
            await asyncio.wait_for(submitted.wait(), 20)
            first.process.kill()  # Crash after child creation, before acknowledging the handoff.
            with pytest.raises(RuntimeError):
                await task
        finally:
            await first.close()
        interrupted, token = False, 2
        async with sessions() as session:
            await session.execute(update(AgentRun).where(AgentRun.id == run.id).values(
                lease_token=token, lease_expires_at=datetime.now(UTC) + timedelta(minutes=5)))
            await session.commit()
        recovered_journal = RuntimeJournal(sessions, secrets, workspace_id=run.workspace_id, run_id=run.id, token=token,
                                           identity=identity, session_id="journal-session")
        second = await FxRuntime.create(config, model="test-model", base_url=url, api_key="test-key",
                                        journal=recovered_journal, engine_session="journal-session")
        try:
            handoff = await asyncio.wait_for(second.prompt("journal-session", "Ask for a review", message_id="turn-1",
                                                           rerun_tools=("delegate_tasks",)), 20)
            assert handoff.stop_reason == "handoff" and handoff.handoff
        finally:
            await second.close()
        with pytest.raises(Conflict, match="different batch"):
            changed = SpecialistBatch(tasks=[{"key": "research", "agent": "research", "brief": "Different brief",
                                              "expected_result": "Evidence"}])
            await scheduler.submit(run.workspace_id, run.id, token, handoff.handoff, changed, verify_runtime_batch=True)
        with pytest.raises(Forbidden, match="read-only"):
            writes = SpecialistBatch(tasks=[{"key": "write", "agent": "documentation", "brief": "Change a file",
                                             "expected_result": "Updated", "changes_project": True}])
            await scheduler.submit(run.workspace_id, run.id, token, "write-call", writes, verify_runtime_batch=True)
        await scheduler.wait(run.workspace_id, run.id, token, {"fx-handoff": handoff.handoff}, require_live_lease=True)
        async with sessions() as session:
            parent = await session.get(AgentRun, run.id)
            children = list(await session.scalars(select(AgentRun).where(AgentRun.workspace_id == run.workspace_id,
                                                                          AgentRun.parent_run_id == run.id)))
            assert parent.status is RunStatus.WAITING_CHILDREN
            assert len(children) == 1 and children[0].status is RunStatus.QUEUED
            assert dispatched[0][0] == children[0].id
            children[0].status = RunStatus.COMPLETED
            children[0].task_result = SpecialistResult(summary="Saved specialist evidence").model_dump(mode="json")
            await session.commit()
        await scheduler.advance(run.workspace_id, run.id)
        assert dispatched[-1][0] == run.id and dispatched[-1][1]["kind"] == "delegation_ready"
        token = 3
        async with sessions() as session:
            await session.execute(update(AgentRun).where(AgentRun.id == run.id).values(
                status=RunStatus.RUNNING, lease_token=token, lease_expires_at=datetime.now(UTC) + timedelta(minutes=5)))
            await session.commit()
        resumed_journal = RuntimeJournal(sessions, secrets, workspace_id=run.workspace_id, run_id=run.id, token=token,
                                         identity=identity, session_id="journal-session")
        third = await FxRuntime.create(config, model="test-model", base_url=url, api_key="test-key",
                                       journal=resumed_journal, engine_session="journal-session")
        try:
            result = await asyncio.wait_for(third.prompt("journal-session", "Ask for a review", message_id="turn-1",
                                                         rerun_tools=("delegate_tasks",)), 20)
            assert result.stop_reason == "end_turn" and "Saved specialist evidence" in result.text
            assert len(executions) >= 3 and set(executions) == {handoff.handoff}
        finally:
            await third.close()
        async with sessions() as session:
            children = list(await session.scalars(select(AgentRun.id).where(AgentRun.workspace_id == run.workspace_id,
                                                                             AgentRun.parent_run_id == run.id)))
            assert len(children) == 1


async def test_fx_repeats_a_completed_turn_after_losing_the_host_response(journal_world):
    """The saved result must be recoverable without charging for a second model turn."""
    from dotrix_engine.runtimes.fx import _HOST

    if not shutil.which("node") or not (_HOST / "node_modules" / "libfx").is_dir():
        pytest.skip("Install the optional fx host to exercise the real libfx runtime")
    run, sessions, _, _, journal = journal_world
    scope = RuntimeRunScope(run.workspace_id, run.project_id, run.id, run.requested_by_id,
                            "project-manager", 1, "journal-session")
    read = next(tool for tool in scoped_knowledge_tools(sessions, scope=scope, spec=builtin("project-manager"),
                                                        embedder=None) if tool.name == "read_section")
    config = AgentRuntimeConfig("project-manager", "Use the project knowledge tool.", (read,))
    requests = []
    with model_server(requests=requests, report_usage=True) as url:
        first = await FxRuntime.create(config, model="test-model", base_url=url, api_key="test-key",
                                       journal=journal, engine_session="journal-session")
        try:
            answer = await first.prompt("journal-session", "Read the evidence", message_id="turn-1")
            assert "Private project evidence" in answer.text
            assert answer.usage and answer.usage["input_tokens"] > 0
        finally:
            await first.close()
        calls = len(requests)
        second = await FxRuntime.create(config, model="test-model", base_url=url, api_key="test-key",
                                        journal=journal, engine_session="journal-session")
        try:
            repeated = await second.prompt("journal-session", "Read the evidence", message_id="turn-1")
            assert repeated.text == answer.text and repeated.repeated and repeated.usage is None
            resumed = await second.resume("journal-session", message_id="turn-1")
            assert resumed.text == answer.text and resumed.repeated
            assert len(requests) == calls
        finally:
            await second.close()


@pytest.mark.parametrize("record", [b"not json", b'{"format":"libfx-journal-v2","events":[]}'])
async def test_fx_refuses_an_unknown_or_invalid_journal_format(journal_world, record):
    from dotrix_engine.runtimes.fx import _HOST

    if not shutil.which("node") or not (_HOST / "node_modules" / "libfx").is_dir():
        pytest.skip("Install the optional fx host to exercise the real libfx runtime")
    *_, journal = journal_world
    await journal.append(expected=None, idempotency_key="unsupported", data=record)
    config = AgentRuntimeConfig("project-manager", "Answer questions.")
    requests = []
    with model_server(requests=requests) as url:
        with pytest.raises(RuntimeError):
            await FxRuntime.create(config, model="test-model", base_url=url, api_key="test-key",
                                   journal=journal, engine_session="journal-session")
    assert requests == []


@pytest.mark.parametrize("final_finish", ["length", "content_filter"])
async def test_fx_replay_does_not_treat_a_truncated_or_refused_answer_as_complete(journal_world, final_finish):
    from dotrix_engine.runtimes.fx import _HOST

    if not shutil.which("node") or not (_HOST / "node_modules" / "libfx").is_dir():
        pytest.skip("Install the optional fx host to exercise the real libfx runtime")
    run, sessions, _, _, journal = journal_world
    scope = RuntimeRunScope(run.workspace_id, run.project_id, run.id, run.requested_by_id,
                            "project-manager", 1, "journal-session")
    read = next(tool for tool in scoped_knowledge_tools(sessions, scope=scope, spec=builtin("project-manager"),
                                                        embedder=None) if tool.name == "read_section")
    config = AgentRuntimeConfig("project-manager", "Use the project knowledge tool.", (read,))
    requests = []
    with model_server(requests=requests, final_finish=final_finish) as url:
        first = await FxRuntime.create(config, model="test-model", base_url=url, api_key="test-key",
                                       journal=journal, engine_session="journal-session")
        try:
            try:
                truncated = await first.prompt("journal-session", "Read the evidence", message_id="turn-1")
            except RuntimeError:
                truncated = None
            assert truncated is None or truncated.stop_reason != "end_turn"
        finally:
            await first.close()
        calls = len(requests)
        second = await FxRuntime.create(config, model="test-model", base_url=url, api_key="test-key",
                                        journal=journal, engine_session="journal-session")
        try:
            with pytest.raises(RuntimeError):
                await second.prompt("journal-session", "Read the evidence", message_id="turn-1")
            assert len(requests) == calls
        finally:
            await second.close()


async def test_binding_requires_current_membership_and_an_unexpired_lease(runtime_world, db_session):
    _, _, _, run, scope, sessions = runtime_world
    member = await db_session.scalar(select(Membership).where(Membership.workspace_id == scope.workspace_id,
                                                               Membership.user_id == scope.requested_by_id))
    member.role = Role.GUEST
    await db_session.commit()
    with pytest.raises(Forbidden):
        await bind_scope(sessions, scope)
    member.role = Role.OWNER
    run.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.commit()
    with pytest.raises(Conflict):
        await bind_scope(sessions, scope)


async def test_binding_does_not_commit_if_the_lease_expires_during_policy_lookup(runtime_world, db_session, monkeypatch):
    from dotrix_backend.modules.agents import runtime_sessions

    _, _, _, run, scope, sessions = runtime_world
    run.lease_expires_at = datetime.now(UTC) + timedelta(seconds=2)
    await db_session.commit()
    resolve = runtime_sessions.AgentDefinitionRepository.resolve
    reached = False

    async def slow_resolve(self, *args, **kwargs):
        nonlocal reached
        reached = True
        await asyncio.sleep(2.1)
        return await resolve(self, *args, **kwargs)

    monkeypatch.setattr(runtime_sessions.AgentDefinitionRepository, "resolve", slow_resolve)
    with pytest.raises(Conflict):
        await bind_scope(sessions, scope)
    assert reached
    assert await db_session.scalar(select(AgentRuntimeBinding.id).where(AgentRuntimeBinding.run_id == scope.run_id)) is None


@pytest.mark.parametrize("race", ["same-run", "same-session"])
async def test_concurrent_runtime_bindings_have_one_winner(engine, race):
    """Two independent database connections cannot bind competing sessions or runs."""
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    user_id, workspace_id, project_id, first_id, second_id = (uuid7() for _ in range(5))
    now = datetime.now(UTC)
    async with sessions() as session:
        session.add(User(id=user_id, email=f"{user_id}@example.com", display_name="Runtime test"))
        await session.flush()
        session.add(Workspace(id=workspace_id, name="Runtime test", slug=f"runtime-{workspace_id}",
                              kind=WorkspaceKind.ORGANIZATION, created_by_id=user_id))
        await session.flush()
        session.add_all([
            Membership(workspace_id=workspace_id, user_id=user_id, role=Role.OWNER),
            Project(id=project_id, workspace_id=workspace_id, key="RNT", name="Runtime",
                    source=ProjectSource.DOCS_ONLY, model="test:model", created_by_id=user_id),
        ])
        await session.flush()
        for run_id in (first_id, second_id):
            session.add(AgentRun(id=run_id, workspace_id=workspace_id, project_id=project_id, thread_id=uuid7(),
                                 kind=RunKind.CHAT, status=RunStatus.RUNNING, agent="research",
                                 requested_by_id=user_id, message="Investigate", lease_token=1,
                                 lease_expires_at=now + timedelta(minutes=5), created_at=now, updated_at=now))
        await session.commit()
    identity = RuntimeIdentity("fx", "test-1", "a" * 64)
    try:
        attempts = [(first_id, "race-session-1"),
                    (first_id if race == "same-run" else second_id,
                     "race-session-2" if race == "same-run" else "race-session-1")]
        results = await asyncio.gather(*(bind_runtime_session(
            sessions, workspace_id=workspace_id, run_id=run_id, token=1, identity=identity, session_id=session_id,
        ) for run_id, session_id in attempts), return_exceptions=True)
        assert sum(isinstance(result, RuntimeRunScope) for result in results) == 1
        assert sum(isinstance(result, Conflict) for result in results) == 1
        async with sessions() as session:
            rows = list(await session.scalars(select(AgentRuntimeBinding).where(
                AgentRuntimeBinding.workspace_id == workspace_id)))
            assert len(rows) == 1
    finally:
        async with sessions() as session:
            await session.execute(delete(Workspace).where(Workspace.id == workspace_id))
            await session.execute(delete(User).where(User.id == user_id))
            await session.commit()


async def test_wrong_session_workspace_requester_agent_or_stale_lease_cannot_read(runtime_world, db_session):
    _, _, _, run, scope, sessions = runtime_world
    scope = await bind_scope(sessions, scope)
    with pytest.raises(Forbidden):
        await invoke(tool_for(sessions, scope), "another-session")
    for changed in (
        replace(scope, workspace_id=uuid7()), replace(scope, project_id=uuid7()),
        replace(scope, requested_by_id=uuid7()), replace(scope, lease_token=2),
    ):
        with pytest.raises(Conflict):
            await invoke(tool_for(sessions, changed))
    with pytest.raises(ValueError):
        tool_for(sessions, replace(scope, agent="product"))
    run.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.commit()
    with pytest.raises(Conflict):
        await invoke(tool_for(sessions, scope))


async def test_revoked_project_access_and_agent_tool_are_rechecked(runtime_world, db_session, db_client):
    person, ws, base, _, scope, sessions = runtime_world
    scope = await bind_scope(sessions, scope)
    tool = tool_for(sessions, scope)
    member = await db_session.scalar(select(Membership).where(Membership.workspace_id == scope.workspace_id,
                                                               Membership.user_id == scope.requested_by_id))
    member.role = Role.GUEST
    await db_session.commit()
    with pytest.raises(Forbidden):
        await invoke(tool)
    member.role = Role.OWNER
    await db_session.commit()
    agent = (await db_client.get(f"{base}/agents/research", headers=person.headers)).json()
    fields = {key: agent[key] for key in ("name", "description", "instructions", "tools", "access", "issue_types", "can_call")}
    fields["tools"] = [item for item in fields["tools"] if item != "knowledge.read"]
    response = await db_client.put(f"{ws}/agents/research", headers=person.headers, json={"agent": fields})
    assert response.status_code == 200, response.text
    with pytest.raises(Forbidden):
        await invoke(tool)


@pytest.mark.parametrize("revoked", ["lease", "membership"])
async def test_a_read_is_not_returned_after_access_revocation(runtime_world, db_session, monkeypatch, revoked):
    _, _, _, run, scope, sessions = runtime_world
    scope = await bind_scope(sessions, scope)
    member = await db_session.scalar(select(Membership).where(Membership.workspace_id == scope.workspace_id,
                                                               Membership.user_id == scope.requested_by_id))

    async def read_section(file_path: str, heading: str) -> str:
        """Read one section of a project document."""
        if revoked == "lease":
            run.lease_token += 1
        else:
            member.role = Role.GUEST
        await db_session.commit()
        return "must not escape"

    monkeypatch.setattr(runtime_tools, "build_knowledge_tools", lambda *a, **k: [read_section])
    with pytest.raises(Conflict if revoked == "lease" else Forbidden):
        await invoke(tool_for(sessions, scope))


@contextmanager
def model_server(requests=None, started=None, gate=None, tool_name="read_section", tool_args=None, final_finish="stop",
                 report_usage=False):
    """A deterministic Chat Completions endpoint that asks for one real project read."""
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if requests is not None:
                requests.append({"request": request, "authorization": self.headers.get("Authorization")})
            if started is not None:
                started.set()
            if gate is not None:
                gate.wait(timeout=15)
            messages = request["messages"]
            # Recovery may append a steering message after the saved tool
            # result. This single-tool model must still answer from that result
            # instead of issuing a second, unrelated call with the same ID.
            result = next((message for message in reversed(messages) if message["role"] == "tool"), None)
            if result is not None:
                message = {"role": "assistant", "content": result["content"]}
                finish = final_finish
            else:
                message = {"role": "assistant", "tool_calls": [{"index": 0, "id": "read-1", "type": "function",
                    "function": {"name": tool_name, "arguments": json.dumps(tool_args or {
                        "file_path": "/dotrix/research/runtime.md", "heading": "Evidence"})}}]}
                finish = "tool_calls"
            if request.get("stream"):
                base = {"id": "test", "object": "chat.completion.chunk", "created": 1, "model": request["model"]}
                chunks = [{**base, "choices": [{"index": 0, "delta": message, "finish_reason": None}]},
                          {**base, "choices": [{"index": 0, "delta": {}, "finish_reason": finish}]}]
                if report_usage:
                    chunks.append({**base, "choices": [], "usage": {"prompt_tokens": 12, "completion_tokens": 6}})
                payload = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n"
                content_type = "text/event-stream"
            else:
                payload = json.dumps({"id": "test", "object": "chat.completion", "created": 1, "model": request["model"],
                                      "choices": [{"index": 0, "message": message, "finish_reason": finish}]})
                content_type = "application/json"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.end_headers()
            self.wfile.write(payload.encode())

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1"
    finally:
        if gate is not None:
            gate.set()
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.fixture
async def nova_pilot_world(engine):
    """Committed test rows so runtime callbacks can use separate real connections."""
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    user_id, colleague_id, workspace_id, project_id, run_id = (uuid7() for _ in range(5))
    now = datetime.now(UTC)
    secrets = Secrets(Fernet.generate_key().decode())
    content = "# Evidence\n\nPrivate project evidence.\n"
    async with sessions() as session:
        session.add_all([User(id=user_id, email=f"{user_id}@example.com", display_name="Ada"),
                         User(id=colleague_id, email=f"{colleague_id}@example.com", display_name="Colleague")])
        await session.flush()
        session.add(Workspace(id=workspace_id, name="Pilot", slug=f"pilot-{workspace_id}",
                              kind=WorkspaceKind.ORGANIZATION, created_by_id=user_id))
        await session.flush()
        session.add_all([
            Membership(workspace_id=workspace_id, user_id=user_id, role=Role.OWNER),
            Membership(workspace_id=workspace_id, user_id=colleague_id, role=Role.MEMBER),
            Project(id=project_id, workspace_id=workspace_id, key="FXT", name="Runtime",
                    source=ProjectSource.DOCS_ONLY, model="openai:test-model", created_by_id=user_id),
            AgentPreference(workspace_id=workspace_id, user_id=user_id, handle="project-manager",
                            instructions="Use concise numbered answers."),
            AgentPreference(workspace_id=workspace_id, user_id=colleague_id, handle="project-manager",
                            instructions="A colleague's private preference."),
            UserModelKey(user_id=user_id, provider="openai", encrypted=secrets.encrypt("personal-pilot-key"), last4="-key"),
            UserModelKey(user_id=colleague_id, provider="openai", encrypted=secrets.encrypt("colleague-key"), last4="-key"),
        ])
        await session.flush()
        session.add(KnowledgeFile(workspace_id=workspace_id, project_id=project_id, path="research/runtime.md",
                                  version=1, revision=1, content=content, content_hash=hashlib.sha256(content.encode()).hexdigest(),
                                  size=len(content.encode()), created_at=now, updated_at=now))
        run = AgentRun(id=run_id, workspace_id=workspace_id, project_id=project_id, thread_id=uuid7(),
                       kind=RunKind.CHAT, status=RunStatus.RUNNING, agent=None, work_mode=WorkMode.DISCUSS,
                       requested_by_id=user_id, message="Investigate", model="openai:test-model", lease_token=1,
                       lease_expires_at=now + timedelta(minutes=5), created_at=now, updated_at=now)
        session.add(run)
        await session.commit()
    try:
        yield run, sessions, secrets
    finally:
        async with sessions() as session:
            await session.execute(delete(Workspace).where(Workspace.id == workspace_id))
            await session.execute(delete(User).where(User.id.in_([user_id, colleague_id])))
            await session.commit()


async def test_fx_nova_pilot_uses_admitted_run_and_personal_credentials(nova_pilot_world, monkeypatch):
    from dotrix_engine.runtimes.fx import _HOST

    if not shutil.which("node") or not (_HOST / "node_modules" / "libfx").is_dir():
        pytest.skip("Install the optional fx host to exercise the real libfx runtime")
    run, sessions, secrets = nova_pilot_world
    requests, events = [], []

    async def observe(event):
        events.append(event)

    with model_server(requests) as base_url:
        monkeypatch.setitem(fx_pilot._FX_ENDPOINTS, "openai", base_url)
        turn = await asyncio.wait_for(fx_pilot.run_fx_nova_pilot(
            sessions, workspace_id=run.workspace_id, run_id=run.id, token=1, secrets=secrets, on_event=observe,
        ), 30)
        assert turn.stop_reason == "end_turn" and "Private project evidence" in turn.text
        assert "read_section" in turn.tools
        assert requests and all(item["authorization"] == "Bearer personal-pilot-key" for item in requests)
        first = requests[0]["request"]
        assert first["model"] == "test-model"
        assert "You are Nova" in str(first["messages"])
        assert "Use concise numbered answers" in str(first["messages"])
        assert "A colleague's private preference" not in str(first["messages"])
        assert any(message.get("role") == "user" and message.get("content") == "Investigate"
                   for message in first["messages"])
        exposed = {tool["function"]["name"] for tool in first["tools"]}
        assert exposed == {"read_section", "read_skill", "document_outline", "search_knowledge",
                           "read_file", "ls", "glob", "grep", "list_issues", "get_issue",
                           "graph_neighbors", "graph_impact", "graph_path"}
        assert "Project context: Runtime (FXT)" in str(first["messages"])
        assert any(event.type == "text_delta" for event in events)
        async with sessions() as session:
            binding = await session.scalar(select(AgentRuntimeBinding).where(AgentRuntimeBinding.run_id == run.id))
            assert binding.runtime == "fx" and binding.session_id.startswith("fx-pilot-")
        with pytest.raises(Conflict, match="cannot resume"):
            await fx_pilot.run_fx_nova_pilot(
                sessions, workspace_id=run.workspace_id, run_id=run.id, token=1, secrets=secrets,
            )
        assert len(requests) == 2  # The blocked retry did not send another prompt.


async def test_fx_nova_pilot_requires_a_personal_key_and_supported_run(nova_pilot_world):
    run, sessions, secrets = nova_pilot_world
    async with sessions() as session:
        await session.execute(delete(UserModelKey).where(UserModelKey.user_id == run.requested_by_id))
        await session.commit()
    with pytest.raises(ModelUnavailable, match="personal key"):
        await fx_pilot.run_fx_nova_pilot(sessions, workspace_id=run.workspace_id, run_id=run.id, token=1, secrets=secrets)
    async with sessions() as session:
        await session.execute(update(AgentRun).where(AgentRun.id == run.id).values(work_mode=WorkMode.BUILD))
        await session.commit()
    with pytest.raises(Conflict, match="read-only"):
        await fx_pilot.run_fx_nova_pilot(sessions, workspace_id=run.workspace_id, run_id=run.id, token=1, secrets=secrets)

    async with sessions() as session:
        await session.execute(update(AgentRun).where(AgentRun.id == run.id).values(work_mode=WorkMode.DISCUSS, token_budget=100))
        await session.commit()
    with pytest.raises(Conflict, match="token budget"):
        await fx_pilot.run_fx_nova_pilot(sessions, workspace_id=run.workspace_id, run_id=run.id, token=1, secrets=secrets)
    async with sessions() as session:
        assert await session.scalar(select(AgentRuntimeBinding.id).where(AgentRuntimeBinding.run_id == run.id)) is None


async def test_fx_nova_pilot_rejects_budgets_and_stale_owners(nova_pilot_world):
    run, sessions, secrets = nova_pilot_world
    for workspace_id, token in ((uuid7(), 1), (run.workspace_id, 2)):
        with pytest.raises(Conflict):
            await fx_pilot.run_fx_nova_pilot(
                sessions, workspace_id=workspace_id, run_id=run.id, token=token, secrets=secrets,
            )
    async with sessions() as session:
        await session.execute(update(Project).where(Project.id == run.project_id).values(token_budget=100))
        await session.commit()
    with pytest.raises(Conflict, match="token budget"):
        await fx_pilot.run_fx_nova_pilot(
            sessions, workspace_id=run.workspace_id, run_id=run.id, token=1, secrets=secrets,
        )
    async with sessions() as session:
        assert await session.scalar(select(AgentRuntimeBinding.id).where(AgentRuntimeBinding.run_id == run.id)) is None


async def test_fx_nova_pilot_includes_only_the_requesters_prior_conversation(nova_pilot_world, monkeypatch):
    from dotrix_engine.runtimes.fx import _HOST

    if not shutil.which("node") or not (_HOST / "node_modules" / "libfx").is_dir():
        pytest.skip("Install the optional fx host to exercise the real libfx runtime")
    run, sessions, secrets = nova_pilot_world
    async with sessions() as session:
        colleague = await session.scalar(select(Membership.user_id).where(
            Membership.workspace_id == run.workspace_id, Membership.user_id != run.requested_by_id))
        earlier = run.created_at - timedelta(minutes=1)
        for user_id, text in ((run.requested_by_id, "My earlier question"), (colleague, "Another person's private question")):
            session.add(AgentRun(id=uuid7(), workspace_id=run.workspace_id, project_id=run.project_id,
                                 thread_id=run.thread_id, kind=RunKind.CHAT, status=RunStatus.COMPLETED,
                                 requested_by_id=user_id, message=text, reply="Earlier answer",
                                 created_at=earlier, updated_at=earlier))
        await session.commit()
    requests = []
    with model_server(requests=requests) as base_url:
        monkeypatch.setitem(fx_pilot._FX_ENDPOINTS, "openai", base_url)
        await fx_pilot.run_fx_nova_pilot(sessions, workspace_id=run.workspace_id, run_id=run.id, token=1, secrets=secrets)
        messages = str(requests[0]["request"]["messages"])
        assert "My earlier question" in messages and "Earlier answer" in messages
        assert "Another person's private question" not in messages
        assert "Latest message" in messages and "Investigate" in messages


@pytest.mark.skipif(not os.environ.get("DOTRIX_LIVE_ANTHROPIC_API_KEY"),
                    reason="Live model test: set DOTRIX_LIVE_ANTHROPIC_API_KEY (it makes a few paid Claude Haiku calls)")
async def test_live_fx_chat_on_anthropic_reads_project_knowledge(
    nova_pilot_world, db_client, agent_script, outbox, storage, checkouts,
):
    """The fx preview through the public API on a real Anthropic model (its OpenAI-compatible endpoint): Nova
    reads the project's knowledge with the platform's tools, and a follow-up keeps the conversation."""
    from dotrix_engine.runtimes.fx import _HOST

    if not shutil.which("node") or not (_HOST / "node_modules" / "libfx").is_dir():
        pytest.skip("Install the optional fx host to exercise the real libfx runtime")
    existing, sessions, secrets = nova_pilot_world
    async with sessions() as session:
        session.add(UserModelKey(user_id=existing.requested_by_id, provider="anthropic",
                                 encrypted=secrets.encrypt(os.environ["DOTRIX_LIVE_ANTHROPIC_API_KEY"]), last4="live"))
        await session.commit()
    settings = db_client._transport.app.state.settings.model_copy(update={"fx_chat_pilot": True})
    app = create_app(settings)
    app.state.sessionmaker, app.state.secrets, app.state.checkouts = sessions, secrets, checkouts
    app.dependency_overrides[get_email_sender] = lambda: outbox
    app.dependency_overrides[get_storage] = lambda: storage
    app.dependency_overrides[optional_storage] = lambda: storage
    app.state.runner = runner = AgentRunner(
        session_factory=sessions, checkpointer=InMemorySaver(), model_factory=agent_script.factory,
        inline=True, checkouts=checkouts, secrets=secrets, settings=settings,
    )
    app.state.jobs = InlineJobs(JobContext(sessions, settings, outbox, storage, checkouts=checkouts, runner=runner), JOBS)
    runner.jobs = app.state.jobs
    token = create_access_token(existing.requested_by_id, secret=settings.jwt_secret.get_secret_value(),
                                issuer=settings.jwt_issuer, ttl=timedelta(minutes=10))
    headers = {"Authorization": f"Bearer {token}"}
    base = f"/v1/workspaces/{existing.workspace_id}/projects/{existing.project_id}/agent"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", timeout=180) as client:
        assert "anthropic" in (await client.get(f"{base}/runtime-options", headers=headers)).json()["fx_providers"]
        first = await client.post(f"{base}/runs", headers=headers, json={
            "message": "Read research/runtime.md in the project's knowledge and quote its one sentence of evidence.",
            "chat_runtime": "fx", "work_mode": "discuss", "model": "anthropic:claude-haiku-5-5",
        })
        assert first.status_code == 202, first.text
        run = first.json()
        assert run["status"] == "completed", run
        assert run["chat_runtime"] == "fx" and run["model"] == "anthropic:claude-haiku-5-5"
        assert "private project evidence" in run["reply"].lower(), run["reply"]
        second = await client.post(f"{base}/runs", headers=headers, json={
            "message": "Which file did you read? Just its path.", "thread_id": run["thread_id"], "work_mode": "discuss",
        })
        assert second.status_code == 202 and second.json()["status"] == "completed", second.text
        assert "runtime.md" in second.json()["reply"], second.json()["reply"]


async def test_fx_chat_runs_through_api_and_keeps_its_runtime(
    nova_pilot_world, db_client, monkeypatch, agent_script, outbox, storage, checkouts,
):
    """Exercise public chat with real libfx, real tools, and separate database connections."""
    from dotrix_engine.runtimes.fx import _HOST

    if not shutil.which("node") or not (_HOST / "node_modules" / "libfx").is_dir():
        pytest.skip("Install the optional fx host to exercise the real libfx runtime")
    existing, sessions, secrets = nova_pilot_world
    settings = db_client._transport.app.state.settings.model_copy(update={"fx_chat_pilot": True})
    app = create_app(settings)
    app.state.sessionmaker = sessions
    app.state.secrets = secrets
    app.state.checkouts = checkouts
    app.dependency_overrides[get_email_sender] = lambda: outbox
    app.dependency_overrides[get_storage] = lambda: storage
    app.dependency_overrides[optional_storage] = lambda: storage
    app.state.runner = runner = AgentRunner(
        session_factory=sessions, checkpointer=InMemorySaver(), model_factory=agent_script.factory,
        inline=True, checkouts=checkouts, secrets=secrets, settings=settings,
    )
    app.state.jobs = InlineJobs(JobContext(sessions, settings, outbox, storage, checkouts=checkouts, runner=runner), JOBS)
    runner.jobs = app.state.jobs
    token = create_access_token(existing.requested_by_id, secret=settings.jwt_secret.get_secret_value(),
                                issuer=settings.jwt_issuer, ttl=timedelta(minutes=10))
    headers = {"Authorization": f"Bearer {token}"}
    base = f"/v1/workspaces/{existing.workspace_id}/projects/{existing.project_id}/agent"
    requests = []
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        options = await client.get(f"{base}/runtime-options", headers=headers)
        assert options.status_code == 200 and "openai" in options.json()["fx_providers"]
        with model_server(requests=requests) as url:
            monkeypatch.setitem(fx_pilot._FX_ENDPOINTS, "openai", url)
            first = await client.post(f"{base}/runs", headers=headers, json={
                "message": "What is the evidence?", "chat_runtime": "fx", "work_mode": "discuss",
            })
            assert first.status_code == 202, first.text
            first_run = first.json()
            assert first_run["status"] == "completed", first.text
            assert first_run["chat_runtime"] == "fx" and "Private project evidence" in first_run["reply"]
            assert first_run["model_calls"] is None and first_run["usage_complete"] is False
            assert first_run["input_tokens"] is None and first_run["output_tokens"] is None
            events = await client.get(f"{base}/runs/{first_run['id']}/events", headers=headers)
            assert events.status_code == 200 and "Private project evidence" in events.text
            second = await client.post(f"{base}/runs", headers=headers, json={
                "message": "And what else?", "thread_id": first_run["thread_id"], "work_mode": "discuss",
            })
            assert second.status_code == 202 and second.json()["status"] == "completed", second.text
            assert second.json()["chat_runtime"] == "fx"
            assert "What is the evidence?" in str(requests[2]["request"]["messages"])
            assert all(item["authorization"] == "Bearer personal-pilot-key" for item in requests)
        switched = await client.post(f"{base}/runs", headers=headers, json={
            "message": "Switch", "thread_id": first_run["thread_id"], "chat_runtime": "deepagents",
        })
        assert switched.status_code == 409 and switched.json()["type"].endswith("/runtime_locked")
        unsupported = await client.post(f"{base}/runs", headers=headers, json={
            "message": "Implement it", "chat_runtime": "fx", "work_mode": "build",
        })
        assert unsupported.status_code == 422
        async with sessions() as session:
            colleague = await session.scalar(select(Membership.user_id).where(
                Membership.workspace_id == existing.workspace_id, Membership.user_id != existing.requested_by_id))
            await session.execute(update(Project).where(Project.id == existing.project_id).values(token_budget=100))
            await session.commit()
        colleague_token = create_access_token(colleague, secret=settings.jwt_secret.get_secret_value(),
                                              issuer=settings.jwt_issuer, ttl=timedelta(minutes=10))
        forbidden = await client.get(f"{base}/runs/{first_run['id']}",
                                     headers={"Authorization": f"Bearer {colleague_token}"})
        assert forbidden.status_code == 404
        budgeted = await client.post(f"{base}/runs", headers=headers, json={
            "message": "Budgeted", "chat_runtime": "fx", "work_mode": "discuss",
        })
        assert budgeted.status_code == 422 and "budget" in budgeted.text
        async with sessions() as session:
            await session.execute(update(Project).where(Project.id == existing.project_id).values(token_budget=None))
            await session.commit()

        # Stop acts on the running worker and prevents its incomplete output from becoming a reply.
        runner.inline = False
        started, gate = threading.Event(), threading.Event()
        with model_server(started=started, gate=gate) as url:
            monkeypatch.setitem(fx_pilot._FX_ENDPOINTS, "openai", url)
            pending = await client.post(f"{base}/runs", headers=headers, json={
                "message": "Stop this", "chat_runtime": "fx", "work_mode": "discuss",
            })
            assert pending.status_code == 202
            assert await asyncio.to_thread(started.wait, 10)
            stopped = await client.post(f"{base}/runs/{pending.json()['id']}/stop", headers=headers)
            assert stopped.status_code == 200 and stopped.json()["status"] == "failed", stopped.text
            gate.set()
            stopped_run = await client.get(f"{base}/runs/{pending.json()['id']}", headers=headers)
            assert stopped_run.json()["reply"] is None
            continued = await client.post(f"{base}/runs/{pending.json()['id']}/continue", headers=headers, json={})
            assert continued.status_code == 409 and "send a new message" in continued.text
        runner.inline = True
        settings.fx_chat_pilot = False
        disabled = await client.post(f"{base}/runs", headers=headers, json={
            "message": "Another", "chat_runtime": "fx", "work_mode": "discuss",
        })
        assert disabled.status_code == 422
        agent_script.say("Default DeepAgents answer")
        default = await client.post(f"{base}/runs", headers=headers, json={"message": "Default?"})
        assert default.status_code == 202 and default.json()["chat_runtime"] == "deepagents", default.text
        assert default.json()["reply"] == "Default DeepAgents answer"


async def test_fx_queued_run_fails_if_project_access_was_removed_before_it_starts(nova_pilot_world, agent_script):
    existing, sessions, secrets = nova_pilot_world
    run_id = uuid7()
    now = datetime.now(UTC)
    async with sessions() as session:
        await session.execute(update(Membership).where(
            Membership.workspace_id == existing.workspace_id, Membership.user_id == existing.requested_by_id,
        ).values(role=Role.GUEST))
        session.add(AgentRun(id=run_id, workspace_id=existing.workspace_id, project_id=existing.project_id,
                             thread_id=uuid7(), kind=RunKind.CHAT, status=RunStatus.QUEUED,
                             chat_runtime=ChatRuntime.FX, work_mode=WorkMode.DISCUSS,
                             requested_by_id=existing.requested_by_id, message="Question", created_at=now, updated_at=now))
        await session.commit()
    runner = AgentRunner(session_factory=sessions, checkpointer=InMemorySaver(), model_factory=agent_script.factory,
                         inline=True, secrets=secrets)
    await runner.execute(run_id, {"kind": "start", "message": "Question"})
    async with sessions() as session:
        denied = await session.get(AgentRun, run_id)
        assert denied.status is RunStatus.FAILED and "no longer sees this project" in denied.error


async def test_fx_chat_delegates_through_real_child_runner_and_returns_the_saved_result(
    nova_pilot_world, db_client, monkeypatch, agent_script, outbox, storage, checkouts,
):
    """Public chat runs Nova in fx and a cheaper specialist through Dotrix's scheduler."""
    from dotrix_engine.runtimes.fx import _HOST

    if not shutil.which("node") or not (_HOST / "node_modules" / "libfx").is_dir():
        pytest.skip("Install the optional fx host to exercise the real libfx runtime")
    existing, sessions, secrets = nova_pilot_world
    settings = db_client._transport.app.state.settings.model_copy(update={
        "fx_chat_pilot": True, "fx_chat_durable_delegation": True,
    })
    async with sessions() as session:
        await session.execute(update(Project).where(Project.id == existing.project_id).values(
            specialist_model="openai:cheap-model"))
        await session.commit()
    app = create_app(settings)
    app.state.sessionmaker, app.state.secrets, app.state.checkouts = sessions, secrets, checkouts
    app.dependency_overrides[get_email_sender] = lambda: outbox
    app.dependency_overrides[get_storage] = lambda: storage
    app.dependency_overrides[optional_storage] = lambda: storage
    app.state.runner = runner = AgentRunner(
        session_factory=sessions, checkpointer=InMemorySaver(), model_factory=agent_script.factory,
        inline=True, checkouts=checkouts, secrets=secrets, settings=settings,
    )
    app.state.jobs = InlineJobs(JobContext(sessions, settings, outbox, storage, checkouts=checkouts, runner=runner), JOBS)
    runner.jobs = app.state.jobs
    agent_script.say(tool_call("submit_specialist_result", summary="Saved specialist evidence", evidence=["runtime.md"]),
                     "Research complete.")
    token = create_access_token(existing.requested_by_id, secret=settings.jwt_secret.get_secret_value(),
                                issuer=settings.jwt_issuer, ttl=timedelta(minutes=10))
    headers = {"Authorization": f"Bearer {token}"}
    base = f"/v1/workspaces/{existing.workspace_id}/projects/{existing.project_id}/agent"
    args = {"tasks": [{"key": "research", "agent": "research", "brief": "Review the evidence",
                       "expected_result": "Evidence"}]}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        options = await client.get(f"{base}/runtime-options", headers=headers)
        assert options.json()["fx_delegation_available"] is True
        with model_server(tool_name="delegate_tasks", tool_args=args) as url:
            monkeypatch.setitem(fx_pilot._FX_ENDPOINTS, "openai", url)
            response = await client.post(f"{base}/runs", headers=headers, json={
                "message": "Ask the research specialist", "chat_runtime": "fx", "work_mode": "discuss",
            })
        assert response.status_code == 202, response.text
        root = response.json()
        assert root["status"] == "completed" and "Saved specialist evidence" in root["reply"], response.text
        tasks = await client.get(f"{base}/runs/{root['id']}/tasks", headers=headers)
        assert tasks.status_code == 200 and len(tasks.json()) == 1
        assert tasks.json()[0]["task_result"]["summary"] == "Saved specialist evidence"
        assert "openai:cheap-model" in agent_script.models_used


@pytest.mark.parametrize("revoked", ["membership", "lease"])
async def test_fx_nova_pilot_stops_returning_results_after_revocation(nova_pilot_world, monkeypatch, revoked):
    from dotrix_engine.runtimes.fx import _HOST

    if not shutil.which("node") or not (_HOST / "node_modules" / "libfx").is_dir():
        pytest.skip("Install the optional fx host to exercise the real libfx runtime")
    run, sessions, secrets = nova_pilot_world
    started, gate, events = threading.Event(), threading.Event(), []

    async def observe(event):
        events.append(event)

    with model_server(started=started, gate=gate) as base_url:
        monkeypatch.setitem(fx_pilot._FX_ENDPOINTS, "openai", base_url)
        task = asyncio.create_task(fx_pilot.run_fx_nova_pilot(
            sessions, workspace_id=run.workspace_id, run_id=run.id, token=1, secrets=secrets, on_event=observe,
        ))
        try:
            assert await asyncio.wait_for(asyncio.to_thread(started.wait), 15)
            async with sessions() as session:
                if revoked == "membership":
                    await session.execute(update(Membership).where(Membership.workspace_id == run.workspace_id,
                                                                   Membership.user_id == run.requested_by_id).values(role=Role.GUEST))
                else:
                    await session.execute(update(AgentRun).where(AgentRun.workspace_id == run.workspace_id,
                                                                 AgentRun.id == run.id).values(lease_token=2))
                await session.commit()
            gate.set()
            with pytest.raises(Forbidden if revoked == "membership" else Conflict):
                await asyncio.wait_for(task, 30)
            assert not any(event.type == "text_delta" and "Private project evidence" in event.text for event in events)
        finally:
            gate.set()
            if not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task


async def test_fx_nova_pilot_cancellation_does_not_silently_replay(nova_pilot_world, monkeypatch):
    from dotrix_engine.runtimes.fx import _HOST

    if not shutil.which("node") or not (_HOST / "node_modules" / "libfx").is_dir():
        pytest.skip("Install the optional fx host to exercise the real libfx runtime")
    run, sessions, secrets = nova_pilot_world
    started, gate, requests = threading.Event(), threading.Event(), []
    with model_server(requests=requests, started=started, gate=gate) as base_url:
        monkeypatch.setitem(fx_pilot._FX_ENDPOINTS, "openai", base_url)
        task = asyncio.create_task(fx_pilot.run_fx_nova_pilot(
            sessions, workspace_id=run.workspace_id, run_id=run.id, token=1, secrets=secrets,
        ))
        try:
            assert await asyncio.wait_for(asyncio.to_thread(started.wait), 15)
            with pytest.raises(Conflict, match="cannot resume"):
                await fx_pilot.run_fx_nova_pilot(
                    sessions, workspace_id=run.workspace_id, run_id=run.id, token=1, secrets=secrets,
                )
            task.cancel()
            gate.set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 30)
            assert len(requests) == 1
        finally:
            gate.set()
            if not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task


@pytest.mark.parametrize("kind", ["deepagents", "fx"])
async def test_runtime_reads_real_project_knowledge_through_scoped_tools(runtime_world, kind):
    _, _, _, _, scope, sessions = runtime_world
    if kind == "fx":
        from dotrix_engine.runtimes.fx import _HOST

        if not shutil.which("node") or not (_HOST / "node_modules" / "libfx").is_dir():
            pytest.skip("Install the optional fx host to exercise the real libfx runtime")
    tools = scoped_knowledge_tools(sessions, scope=scope, spec=builtin("research"), embedder=None)
    config = AgentRuntimeConfig("research", "Read the requested project evidence.", tuple(tools))
    with model_server() as base_url:
        if kind == "fx":
            identity = RuntimeIdentity("fx", "libfx-0.0.16", fx_configuration_digest(
                config, model="test-model", base_url=base_url))
            await bind_runtime_session(sessions, workspace_id=scope.workspace_id, run_id=scope.run_id, token=1,
                                       identity=identity, session_id=scope.session_id)
            runtime = await FxRuntime.create(config, model="test-model", base_url=base_url)
        else:
            await bind_scope(sessions, scope, "deepagents")
            model = ChatOpenAI(model="test-model", base_url=base_url, api_key="test", use_responses_api=False)
            runtime = DeepAgentsRuntime(config, model)
        try:
            result = await asyncio.wait_for(runtime.prompt(scope.session_id, "Read the evidence"), 30)
            assert result.stop_reason == "end_turn"
            assert "read_section" in result.tools
            assert "Private project evidence" in result.text
        finally:
            await runtime.close()


async def test_fx_handoff_uses_the_real_delegation_scheduler(runtime_world, db_session):
    """An in-memory fx journal hands off to the real scheduler and returns its saved result."""
    from dotrix_engine.runtimes.fx import _HOST

    if not shutil.which("node") or not (_HOST / "node_modules" / "libfx").is_dir():
        pytest.skip("Install the optional fx host to exercise the real libfx runtime")
    _, _, _, parent, _, _ = runtime_world
    parent.agent, parent.orchestration = None, True
    await db_session.commit()
    dispatches = []

    @asynccontextmanager
    async def sessions():
        yield db_session

    async def dispatch(run_id, payload):
        dispatches.append((run_id, payload))

    service = DelegationService(SimpleNamespace(session_factory=sessions, queue=None, stop_reasons=None,
                                                 _dispatch=dispatch))
    process = await asyncio.create_subprocess_exec(
        "node", str(_HOST / "platform-handoff-probe.mjs"),
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )

    async def read():
        line = await asyncio.wait_for(process.stdout.readline(), 30)
        if not line:
            raise AssertionError(f"fx probe stopped: {(await process.stderr.read()).decode()}")
        return json.loads(line)

    async def send(data):
        process.stdin.write((json.dumps(data) + "\n").encode())
        await process.stdin.drain()

    try:
        first = await read()
        assert first["kind"] == "delegate"
        batch = SpecialistBatch(tasks=[{"key": "review", "agent": "research", "brief": first["input"]["brief"],
                                       "expected_result": "Evidence"}])
        key = first["executionId"]
        assert await service.submit(parent.workspace_id, parent.id, 1, key, batch) is None
        await service.wait(parent.workspace_id, parent.id, 1, {"fx-handoff": key})
        assert parent.status is RunStatus.WAITING_CHILDREN
        children = list(await db_session.scalars(select(AgentRun).where(AgentRun.parent_run_id == parent.id)))
        assert len(children) == 1 and children[0].status is RunStatus.QUEUED
        assert dispatches[0][0] == children[0].id
        await send({"action": "suspend"})
        assert (await read())["kind"] == "suspended"

        child = children[0]
        child.status = RunStatus.COMPLETED
        child.task_result = SpecialistResult(summary="Saved specialist evidence").model_dump(mode="json")
        await db_session.commit()
        await service.advance(parent.workspace_id, parent.id)
        assert parent.status is RunStatus.QUEUED and dispatches[-1][0] == parent.id
        parent.status, parent.lease_token = RunStatus.RUNNING, 2
        await db_session.commit()
        await send({"action": "resume"})
        replay = await read()
        assert replay == first  # fx retains the same delegation execution ID and input.
        with pytest.raises(Conflict):
            await service.submit(parent.workspace_id, parent.id, 1, key, batch)
        saved = await service.submit(parent.workspace_id, parent.id, 2, key, batch)
        assert saved[0]["result"]["summary"] == "Saved specialist evidence"
        assert len(list(await db_session.scalars(select(AgentRun).where(AgentRun.parent_run_id == parent.id)))) == 1
        await send({"action": "result", "result": {"tasks": saved}})
        finished = await read()
        assert finished["kind"] == "finished" and finished["stopReason"] == "end_turn"
        assert "Saved specialist evidence" in finished["text"]
        process.stdin.close()
        assert await asyncio.wait_for(process.wait(), 10) == 0
    finally:
        if process.returncode is None:
            with suppress(ProcessLookupError):
                process.kill()
            await process.wait()


async def test_fx_context_guidance_is_private_encrypted_and_stable_on_recovery(nova_pilot_world, monkeypatch):
    from dotrix_backend.modules.rules.models import WorkspaceRule
    from dotrix_engine.runtimes import TurnResult

    run, sessions, secrets = nova_pilot_world
    configs = []

    class FakeRuntime:
        async def prompt(self, *args, **kwargs):
            if len(configs) == 1:
                return TurnResult("", "handoff", handoff="saved-specialist-batch")
            return TurnResult("Saved answer", "end_turn")

        async def close(self):
            pass

    async def create(config, **kwargs):
        configs.append(config)
        return FakeRuntime()

    monkeypatch.setattr(fx_pilot.FxRuntime, "create", create)
    async with sessions() as session:
        current = await session.get(AgentRun, run.id)
        current.orchestration = True
        session.add(WorkspaceRule(workspace_id=run.workspace_id, handle="base", content="Workspace guidance marker",
                                  version=1, updated_at=datetime.now(UTC)))
        session.add(KnowledgeFile(workspace_id=run.workspace_id, project_id=run.project_id,
                                  path="agent-rules/project-manager.md", version=1, revision=2,
                                  content="Project Nova guidance marker", content_hash="a" * 64, size=28,
                                  created_at=datetime.now(UTC), updated_at=datetime.now(UTC)))
        await session.commit()
    for revision in ("aaaa111", "bbbb222"):
        await fx_pilot.run_fx_nova_pilot(sessions, workspace_id=run.workspace_id, run_id=run.id, token=1,
                                       secrets=secrets, delegation=object(),
                                       code_context=f"Connected repository acme/repo at {revision}")
        async with sessions() as session:
            binding = await session.scalar(select(AgentRuntimeBinding).where(AgentRuntimeBinding.run_id == run.id))
            assert binding.encrypted_context and "guidance marker" not in binding.encrypted_context
            saved = json.loads(secrets.decrypt(binding.encrypted_context))
            assert saved["code_context"] == "Connected repository acme/repo at aaaa111"
            await session.execute(update(KnowledgeFile).where(KnowledgeFile.project_id == run.project_id,
                KnowledgeFile.path == "agent-rules/project-manager.md").values(content="Changed while children run"))
            await session.commit()
    assert configs[0].instructions == configs[1].instructions
    assert "aaaa111" in configs[1].instructions and "bbbb222" not in configs[1].instructions
    assert "Workspace guidance marker" in configs[0].instructions
    assert "Project Nova guidance marker" in configs[0].instructions
    assert "Project context: Runtime (FXT)" in configs[0].instructions
    assert "A colleague's private preference" not in configs[0].instructions


async def test_fx_project_reads_share_builders_and_recheck_access(runtime_world, db_session):
    from dotrix_backend.modules.agents.runtime_tools import scoped_project_tools

    _, _, _, run, scope, sessions = runtime_world
    run.agent = None
    await db_session.commit()
    scope = await bind_scope(sessions, replace(scope, agent="project-manager"))
    tools = {tool.name: tool for tool in scoped_project_tools(
        sessions, scope=scope, spec=builtin("project-manager"), embedder=None)}
    context = RuntimeToolContext(scope.session_id, "read")
    assert all(not tool.writes and tool.idempotent for tool in tools.values())
    result = await tools["read_file"].execute_scoped({"file_path": "/dotrix/research/runtime.md"}, context)
    assert "Private project evidence" in str(result)
    assert "research" in str(await tools["ls"].execute_scoped({}, context))
    assert "research/runtime.md" in str(await tools["glob"].execute_scoped({"pattern": "**/*.md"}, context))
    assert "Private project evidence" in str(await tools["grep"].execute_scoped({"pattern": "Private"}, context))
    assert isinstance(await tools["list_issues"].execute_scoped({}, context), list)
    await tools["graph_neighbors"].execute_scoped({"ref": "research/runtime.md"}, context)
    member = await db_session.scalar(select(Membership).where(Membership.workspace_id == scope.workspace_id,
                                                               Membership.user_id == scope.requested_by_id))
    member.role = Role.GUEST
    await db_session.commit()
    for name, args in (("read_file", {"file_path": "/dotrix/research/runtime.md"}),
                       ("list_issues", {}), ("graph_neighbors", {"ref": "research/runtime.md"})):
        with pytest.raises(Forbidden):
            await tools[name].execute_scoped(args, context)


async def test_fx_code_and_web_reads_are_filtered_and_cannot_return_after_revocation(runtime_world, db_session):
    from dotrix_backend.modules.agents.runtime_tools import scoped_project_tools

    _, _, _, run, scope, sessions = runtime_world
    run.agent = None
    await db_session.commit()
    scope = await bind_scope(sessions, replace(scope, agent="project-manager"))

    async def code_read(path: str) -> str:
        """Read authorized repository evidence."""
        return "repository evidence"

    async def web_search(query: str) -> str:
        """Read web evidence using the configured project service."""
        async with sessions() as session:
            await session.execute(update(Membership).where(Membership.workspace_id == scope.workspace_id,
                Membership.user_id == scope.requested_by_id).values(role=Role.GUEST))
            await session.commit()
        return "evidence that must not be returned"

    kwargs = dict(sessions=sessions, scope=scope, embedder=None, code_tools=[code_read], web_tools=[web_search])
    restricted = builtin("project-manager").model_copy(update={"tools": ["knowledge.search"]})
    assert {tool.name for tool in scoped_project_tools(spec=restricted, **kwargs)} == {"search_knowledge"}
    tools = {tool.name: tool for tool in scoped_project_tools(spec=builtin("project-manager"), **kwargs)}
    context = RuntimeToolContext(scope.session_id, "read")
    assert await tools["code_read"].execute_scoped({"path": "app.py"}, context) == "repository evidence"
    with pytest.raises(Forbidden):
        await tools["web_search"].execute_scoped({"query": "auth"}, context)
