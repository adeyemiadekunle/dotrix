"""Experimental runtime tools recheck project access and the run lease at each call."""
import asyncio
import json
import shutil
import threading
import uuid
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from langchain_openai import ChatOpenAI
from sqlalchemy import select
from uuid_utils.compat import uuid7

from dotrix_backend.core.errors import Conflict, Forbidden
from dotrix_backend.modules.agents import runtime_tools
from dotrix_backend.modules.agents.models import AgentRun, RunKind, RunStatus
from dotrix_backend.modules.agents.runtime_tools import RuntimeRunScope, scoped_knowledge_tools
from dotrix_backend.modules.workspaces.models import Membership, Role
from dotrix_engine.builtins import builtin
from dotrix_engine.runtimes import (
    AgentRuntimeConfig,
    DeepAgentsRuntime,
    FxRuntime,
    RuntimeToolContext,
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


async def invoke(tool, session_id="runtime-session"):
    return await tool.execute_scoped({"file_path": "/dotrix/research/runtime.md", "heading": "Evidence"},
                                     RuntimeToolContext(session_id, "call-1"))


async def test_read_tools_use_the_real_project_and_expose_no_write_tools(runtime_world):
    _, _, _, _, scope, sessions = runtime_world
    tools = scoped_knowledge_tools(sessions, scope=scope, spec=builtin("research"), embedder=None)
    assert {tool.name for tool in tools} == {"read_section", "read_skill", "document_outline", "search_knowledge"}
    assert all(tool.idempotent and not tool.writes for tool in tools)
    assert "Private project evidence" in await invoke(tool_for(sessions, scope))
    restricted = builtin("research").model_copy(update={"tools": ["knowledge.search"]})
    assert {tool.name for tool in scoped_knowledge_tools(sessions, scope=scope, spec=restricted, embedder=None)} == {
        "search_knowledge"
    }


async def test_wrong_session_workspace_requester_agent_or_stale_lease_cannot_read(runtime_world, db_session):
    _, _, _, run, scope, sessions = runtime_world
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
            runtime = await FxRuntime.create(config, model="test-model", base_url=base_url)
        else:
            model = ChatOpenAI(model="test-model", base_url=base_url, api_key="test", use_responses_api=False)
            runtime = DeepAgentsRuntime(config, model)
        try:
            result = await asyncio.wait_for(runtime.prompt(scope.session_id, "Read the evidence"), 30)
            assert result.stop_reason == "end_turn"
            assert "read_section" in result.tools
            assert "Private project evidence" in result.text
        finally:
            await runtime.close()
