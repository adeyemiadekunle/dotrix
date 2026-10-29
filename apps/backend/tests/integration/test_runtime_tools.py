"""Experimental runtime tools recheck project access and the run lease at each call."""
import asyncio
import json
import shutil
import threading
import uuid
from contextlib import asynccontextmanager, contextmanager, suppress
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest
from langchain_openai import ChatOpenAI
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker
from uuid_utils.compat import uuid7

from dotrix_backend.core.errors import Conflict, Forbidden
from dotrix_backend.modules.agents import runtime_tools
from dotrix_backend.modules.agents.delegation import DelegationService
from dotrix_backend.modules.agents.models import AgentRun, AgentRuntimeBinding, RunKind, RunStatus
from dotrix_backend.modules.agents.runtime_sessions import (
    RuntimeIdentity,
    bind_runtime_session,
    get_runtime_session,
)
from dotrix_backend.modules.agents.runtime_tools import RuntimeRunScope, scoped_knowledge_tools
from dotrix_backend.modules.auth.models import User
from dotrix_backend.modules.projects.models import Project, ProjectSource
from dotrix_backend.modules.workspaces.models import Membership, Role, Workspace, WorkspaceKind
from dotrix_engine.builtins import builtin
from dotrix_engine.delegation import SpecialistBatch, SpecialistResult
from dotrix_engine.runtimes import (
    AgentRuntimeConfig,
    DeepAgentsRuntime,
    FxRuntime,
    RuntimeToolContext,
    fx_configuration_digest,
)


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
def model_server():
    """A deterministic Chat Completions endpoint that asks for one real project read."""
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            messages = request["messages"]
            if messages[-1]["role"] == "tool":
                message = {"role": "assistant", "content": messages[-1]["content"]}
                finish = "stop"
            else:
                message = {"role": "assistant", "tool_calls": [{"index": 0, "id": "read-1", "type": "function",
                    "function": {"name": "read_section", "arguments": json.dumps({
                        "file_path": "/dotrix/research/runtime.md", "heading": "Evidence"})}}]}
                finish = "tool_calls"
            if request.get("stream"):
                base = {"id": "test", "object": "chat.completion.chunk", "created": 1, "model": request["model"]}
                chunks = [{**base, "choices": [{"index": 0, "delta": message, "finish_reason": None}]},
                          {**base, "choices": [{"index": 0, "delta": {}, "finish_reason": finish}]}]
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
        server.shutdown()
        server.server_close()
        thread.join()


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
            identity = RuntimeIdentity("fx", "libfx-0.0.15", fx_configuration_digest(
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
