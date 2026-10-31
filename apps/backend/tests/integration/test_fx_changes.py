"""fx chat changes the project through the platform's approvals, once, and recovers a cut-off turn.

These use the real libfx host, real Postgres on separate connections, and a local fake model.
"""
import asyncio
import json
import os
import shutil
import threading
import uuid
from contextlib import asynccontextmanager, contextmanager
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import select, update

from apps.backend.tests.integration.test_runtime_tools import (
    nova_pilot_world,  # noqa: F401  (a fixture)
)
from dotrix_backend.core.email import get_email_sender
from dotrix_backend.core.jobs import InlineJobs, JobContext
from dotrix_backend.core.security import create_access_token
from dotrix_backend.core.storage import get_storage, optional_storage
from dotrix_backend.jobs import JOBS
from dotrix_backend.main import create_app
from dotrix_backend.modules.agents import fx_pilot
from dotrix_backend.modules.agents.fx_tools import CUT_OFF, approval_key, call_key, fx_change_tools
from dotrix_backend.modules.agents.models import (
    AgentApproval,
    AgentRun,
    AgentRuntimeCall,
    ConversationPlan,
    RunStatus,
)
from dotrix_backend.modules.agents.runner import AgentRunner
from dotrix_backend.modules.agents.runtime_tools import RuntimeRunScope
from dotrix_backend.modules.agents.unattended import Unattended
from dotrix_backend.modules.audit.models import AuditEvent
from dotrix_backend.modules.knowledge.models import KnowledgeFile
from dotrix_backend.modules.knowledge.service import KnowledgeService
from dotrix_backend.modules.model_keys.models import UserModelKey
from dotrix_backend.modules.workspaces.models import Workspace
from dotrix_engine.builtins import builtin
from dotrix_engine.contracts import AgentPolicy
from dotrix_engine.runtimes import FxRuntime, RuntimeHandoff, RuntimeToolContext

PLAN = {"file_path": "/dotrix/progress/plan.md", "content": "# Plan\n\nShip it.\n"}


def _has_fx() -> bool:
    from dotrix_engine.runtimes.fx import _HOST

    return bool(shutil.which("node")) and (_HOST / "node_modules" / "libfx").is_dir()


pytestmark = pytest.mark.skipif(not _has_fx(), reason="Install the optional fx host to exercise the real libfx runtime")


@contextmanager
def scripted_model(tool: str, args: dict, *, requests: list | None = None, hold: threading.Event | None = None,
                   reached: threading.Event | None = None):
    """Asks for one `tool` call, then answers with that call's result. `hold` blocks the answer (the
    request after the tool result) until set, with `reached` set when it arrives."""
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if requests is not None:
                requests.append(request)
            result = next((m for m in reversed(request["messages"]) if m["role"] == "tool"), None)
            if result is None:
                delta = {"role": "assistant", "tool_calls": [{"index": 0, "id": "call-1", "type": "function",
                         "function": {"name": tool, "arguments": json.dumps(args)}}]}
                finish = "tool_calls"
            else:
                if reached is not None:
                    reached.set()
                if hold is not None:
                    hold.wait(timeout=30)
                delta, finish = {"role": "assistant", "content": f"Result: {result['content']}"}, "stop"
            base = {"id": "test", "object": "chat.completion.chunk", "created": 1, "model": request["model"]}
            chunks = [{**base, "choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
                      {**base, "choices": [{"index": 0, "delta": {}, "finish_reason": finish}]}]
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(("".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n").encode())

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1"
    finally:
        if hold is not None:
            hold.set()
        server.shutdown()
        server.server_close()
        thread.join()


@asynccontextmanager
async def fx_chat(world, db_client, outbox, storage, checkouts, agent_script):
    """The public API with its runner inline, and the requester's headers."""
    existing, sessions, secrets = world
    settings = db_client._transport.app.state.settings
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
    base = f"/v1/workspaces/{existing.workspace_id}/projects/{existing.project_id}/agent"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield SimpleNamespace(client=client, base=base, headers={"Authorization": f"Bearer {token}"},
                              runner=runner, sessions=sessions, existing=existing)


async def _file(sessions, project_id, path="progress/plan.md"):
    async with sessions() as session:
        return await session.scalar(select(KnowledgeFile).where(
            KnowledgeFile.project_id == project_id, KnowledgeFile.path == path))


@pytest.mark.parametrize("decision", ["approve", "reject"])
async def test_fx_change_waits_for_a_person_then_goes_through_once_or_not_at_all(
    nova_pilot_world, db_client, monkeypatch, agent_script, outbox, storage, checkouts, decision,  # noqa: F811
):
    async with fx_chat(nova_pilot_world, db_client, outbox, storage, checkouts, agent_script) as fx:
        requests = []
        with scripted_model("write_file", PLAN, requests=requests) as url:
            monkeypatch.setitem(fx_pilot._FX_ENDPOINTS, "openai", url)
            asked = await fx.client.post(f"{fx.base}/runs", headers=fx.headers, json={
                "message": "Write the plan document", "chat_runtime": "fx", "work_mode": "build",
            })
            assert asked.status_code == 202, asked.text
            run = asked.json()
            assert run["status"] == "awaiting_approval", run
            [approval] = run["approvals"]
            assert approval["tool"] == "write_file" and approval["target"] == "/dotrix/progress/plan.md"
            assert "+# Plan" in approval["diff"]
            assert await _file(fx.sessions, fx.existing.project_id) is None
            exposed = {tool["function"]["name"] for tool in requests[0]["tools"]}
            assert {"write_file", "edit_file", "create_issue", "update_issue", "comment_issue", "start_coding"} <= exposed
            assert "save_plan" not in exposed  # Plan's

            decided = await fx.client.post(f"{fx.base}/runs/{run['id']}/decisions", headers=fx.headers, json={
                "decisions": [{"approval_id": approval["id"], "decision": decision, "reason": "Not now"}],
            })
            assert decided.status_code == 200, decided.text
            done = (await fx.client.get(f"{fx.base}/runs/{run['id']}", headers=fx.headers)).json()
        assert done["status"] == "completed", done
        written = await _file(fx.sessions, fx.existing.project_id)
        async with fx.sessions() as session:
            calls = list(await session.scalars(select(AgentRuntimeCall).where(AgentRuntimeCall.run_id == run["id"])))
            approvals = list(await session.scalars(select(AgentApproval).where(AgentApproval.run_id == run["id"])))
        assert len(approvals) == 1  # the resumed call didn't ask again
        if decision == "approve":
            assert written is not None and written.content == PLAN["content"] and written.version == 1
            assert len(calls) == 1 and calls[0].approval_id is not None and calls[0].encrypted_result
            assert "plan.md" in done["reply"]
        else:
            assert written is None and not calls
            assert "rejected" in done["reply"] and "Not now" in done["reply"]


async def test_fx_change_goes_through_at_once_under_accept_edits(
    nova_pilot_world, db_client, monkeypatch, agent_script, outbox, storage, checkouts,  # noqa: F811
):
    existing, sessions, _ = nova_pilot_world
    async with sessions() as session:
        await session.execute(update(Workspace).where(Workspace.id == existing.workspace_id).values(approval_mode_cap="auto"))
        await session.commit()
    async with fx_chat(nova_pilot_world, db_client, outbox, storage, checkouts, agent_script) as fx:
        with scripted_model("write_file", PLAN) as url:
            monkeypatch.setitem(fx_pilot._FX_ENDPOINTS, "openai", url)
            asked = await fx.client.post(f"{fx.base}/runs", headers=fx.headers, json={
                "message": "Write the plan document", "chat_runtime": "fx", "work_mode": "build",
                "approval_mode": "accept_edits",
            })
        assert asked.status_code == 202 and asked.json()["status"] == "completed", asked.text
        assert asked.json()["approvals"] == []
        assert (await _file(sessions, existing.project_id)).content == PLAN["content"]
        async with sessions() as session:
            accepted = await session.scalar(select(AuditEvent).where(
                AuditEvent.workspace_id == existing.workspace_id, AuditEvent.action == "knowledge.write.accepted"))
        assert accepted is not None and accepted.approved_by_id == existing.requested_by_id


async def test_fx_plan_mode_saves_the_conversations_plan(
    nova_pilot_world, db_client, monkeypatch, agent_script, outbox, storage, checkouts,  # noqa: F811
):
    plan = {"title": "Ship", "summary": "Ship it.", "acceptance_criteria": ["It ships"],
            "tasks": [{"title": "Build", "detail": "Do it"}]}
    async with fx_chat(nova_pilot_world, db_client, outbox, storage, checkouts, agent_script) as fx:
        with scripted_model("save_plan", plan) as url:
            monkeypatch.setitem(fx_pilot._FX_ENDPOINTS, "openai", url)
            asked = await fx.client.post(f"{fx.base}/runs", headers=fx.headers, json={
                "message": "Plan it", "chat_runtime": "fx", "work_mode": "plan",
            })
        assert asked.status_code == 202 and asked.json()["status"] == "completed", asked.text
        async with fx.sessions() as session:
            saved = list(await session.scalars(select(ConversationPlan).where(
                ConversationPlan.thread_id == asked.json()["thread_id"])))
        assert [p.title for p in saved] == ["Ship"]


async def test_a_cut_off_fx_turn_recovers_from_its_journal_without_changing_the_project_twice(
    nova_pilot_world, db_client, monkeypatch, agent_script, outbox, storage, checkouts,  # noqa: F811
):
    """The worker dies while a change it made is unrecorded: the recovered attempt is told so, never redoes it."""
    existing, sessions, _ = nova_pilot_world
    async with sessions() as session:
        await session.execute(update(Workspace).where(Workspace.id == existing.workspace_id).values(approval_mode_cap="auto"))
        await session.commit()
    written, dies = asyncio.Event(), asyncio.Event()
    original = KnowledgeService.write

    async def write_then_die(self, project, path, *args, **kwargs):
        result = await original(self, project, path, *args, **kwargs)
        if path != "progress/plan.md":
            return result
        written.set()
        await dies.wait()  # the worker is cut off before the call's result is saved
        return result

    async with fx_chat(nova_pilot_world, db_client, outbox, storage, checkouts, agent_script) as fx:
        fx.runner.inline = False

        class Worker:  # in the worker, a cut-off attempt leaves the run working for the sweep
            async def stop_reason(self, run_id):
                return None

        fx.runner.stop_reasons = Worker()
        queued = []

        async def start(*args, **kwargs):  # the worker picks it up below
            queued.append(args)

        monkeypatch.setattr(fx.runner, "start", start)
        requests = []
        with scripted_model("write_file", PLAN, requests=requests) as url:
            monkeypatch.setitem(fx_pilot._FX_ENDPOINTS, "openai", url)
            monkeypatch.setattr(KnowledgeService, "write", write_then_die)
            asked = await fx.client.post(f"{fx.base}/runs", headers=fx.headers, json={
                "message": "Write the plan document", "chat_runtime": "fx", "work_mode": "build",
                "approval_mode": "accept_edits",
            })
            assert asked.status_code == 202, asked.text
            run_id = uuid.UUID(asked.json()["id"])
            payload = {"kind": "start", "message": "Write the plan document"}
            hosts = []
            create = FxRuntime.create

            async def remember(*args, **kwargs):
                hosts.append(await create(*args, **kwargs))
                return hosts[-1]

            monkeypatch.setattr(FxRuntime, "create", remember)
            attempt = asyncio.create_task(fx.runner.execute(run_id, payload))
            await asyncio.wait_for(written.wait(), 30)
            hosts[0].process.kill()  # the worker dies: no cancellation reaches libfx's journal
            attempt.cancel()
            with pytest.raises(asyncio.CancelledError):
                await attempt
            monkeypatch.setattr(KnowledgeService, "write", original)
            async with sessions() as session:
                cut = await session.get(AgentRun, run_id)
                assert cut.status is RunStatus.RUNNING
                # What the dispatch sweep does with a lapsed lease (expire_agent_leases): queue a recovered attempt.
                cut.status, cut.lease_expires_at = RunStatus.QUEUED, None
                await session.commit()
            await asyncio.wait_for(fx.runner.execute(run_id, {**payload, "recovered": True, "attempt": 2}), 60)
        done = (await fx.client.get(f"{fx.base}/runs/{run_id}", headers=fx.headers)).json()
        assert done["status"] == "completed", done
        assert "Cut off" in done["reply"]
        file = await _file(sessions, existing.project_id)
        assert file.content == PLAN["content"] and file.version == 1  # written once
        async with sessions() as session:
            calls = list(await session.scalars(select(AgentRuntimeCall).where(AgentRuntimeCall.run_id == run_id)))
        assert len(calls) == 1 and calls[0].encrypted_result is None
        # The model was asked for the change once; the recovered turn continued from the tool's result.
        assert sum(1 for r in requests if not any(m["role"] == "tool" for m in r["messages"])) == 1


async def test_a_change_is_claimed_once_and_its_saved_result_replayed(nova_pilot_world):  # noqa: F811
    run, sessions, secrets = nova_pilot_world
    scope = RuntimeRunScope(run.workspace_id, run.project_id, run.id, run.requested_by_id, "project-manager", 1, "fx-s")
    nova = builtin("project-manager").allowing(frozenset({"knowledge.write"}))
    policy = AgentPolicy([nova])
    unattended = Unattended(policy, {}, {}, 0, accepted={"project-manager": frozenset({"knowledge.write"})},
                            instructor_id=run.requested_by_id, mode="accept_edits")

    async def nothing():
        return None

    [write] = [t for t in fx_change_tools(sessions, secrets, scope=scope, spec=nova, policy=policy, unattended=unattended,
                                          work_mode=None, mode_context=None, authorize=nothing) if t.name == "write_file"]
    assert write.hands_off and not write.idempotent
    first = await write.execute_scoped(PLAN, RuntimeToolContext("fx-s", "exec-1"))
    again = await write.execute_scoped(PLAN, RuntimeToolContext("fx-s", "exec-1"))
    assert first == again and not first.get("error")
    assert (await _file(sessions, run.project_id)).version == 1
    async with sessions() as session:
        await session.execute(update(AgentRuntimeCall).where(AgentRuntimeCall.run_id == run.id).values(encrypted_result=None))
        await session.commit()
    assert await write.execute_scoped(PLAN, RuntimeToolContext("fx-s", "exec-1")) == {"error": CUT_OFF}
    with pytest.raises(Exception, match="bound runtime call"):
        await write.execute_scoped(PLAN, RuntimeToolContext("another-session", "exec-2"))

    # Without an allowance, the same change asks a person and hands the turn off.
    asking = builtin("project-manager")
    [gated] = [t for t in fx_change_tools(sessions, secrets, scope=scope, spec=asking, policy=AgentPolicy([asking]),
                                          unattended=Unattended(AgentPolicy([asking]), {}, {}, 0), work_mode=None,
                                          mode_context=None, authorize=nothing) if t.name == "write_file"]
    assert isinstance(await gated.execute_scoped(PLAN, RuntimeToolContext("fx-s", "exec-3")), RuntimeHandoff)
    assert isinstance(await gated.execute_scoped(PLAN, RuntimeToolContext("fx-s", "exec-3")), RuntimeHandoff)
    async with sessions() as session:
        pending = list(await session.scalars(select(AgentApproval).where(AgentApproval.run_id == run.id)))
    assert [(a.tool, a.interrupt_id) for a in pending] == [("write_file", approval_key(call_key("exec-3", "write_file", PLAN)))]


@pytest.mark.skipif(not os.environ.get("DOTRIX_LIVE_ANTHROPIC_API_KEY"),
                    reason="Live model test: set DOTRIX_LIVE_ANTHROPIC_API_KEY (it makes a few paid Claude Haiku calls)")
async def test_live_fx_build_change_on_anthropic_waits_for_approval(
    nova_pilot_world, db_client, agent_script, outbox, storage, checkouts,  # noqa: F811
):
    """On a real model, a Build turn's document change waits for a person, then goes through once."""
    existing, sessions, secrets = nova_pilot_world
    async with sessions() as session:
        session.add(UserModelKey(user_id=existing.requested_by_id, provider="anthropic",
                                 encrypted=secrets.encrypt(os.environ["DOTRIX_LIVE_ANTHROPIC_API_KEY"]), last4="live"))
        await session.commit()
    async with fx_chat(nova_pilot_world, db_client, outbox, storage, checkouts, agent_script) as fx:
        fx.client.timeout = 180
        asked = await fx.client.post(f"{fx.base}/runs", headers=fx.headers, json={
            "message": "Write /dotrix/progress/status.md containing exactly the line: Runtime check passed.",
            "chat_runtime": "fx", "work_mode": "build", "model": "anthropic:claude-haiku-5-5",
        })
        assert asked.status_code == 202, asked.text
        run = asked.json()
        assert run["status"] == "awaiting_approval", run
        [approval] = run["approvals"]
        assert approval["tool"] in ("write_file", "edit_file") and approval["target"] == "/dotrix/progress/status.md"
        decided = await fx.client.post(f"{fx.base}/runs/{run['id']}/decisions", headers=fx.headers, json={
            "decisions": [{"approval_id": approval["id"], "decision": "approve"}],
        })
        assert decided.status_code == 200, decided.text
        done = (await fx.client.get(f"{fx.base}/runs/{run['id']}", headers=fx.headers)).json()
        assert done["status"] == "completed", done
        written = await _file(sessions, existing.project_id, "progress/status.md")
        assert written is not None and "Runtime check passed." in written.content and written.version == 1
        print("LIVE REPLY:", done["reply"])


async def test_fx_runs_with_a_token_budget_and_stops_at_its_next_step_once_used(
    nova_pilot_world, db_client, monkeypatch, agent_script, outbox, storage, checkouts,  # noqa: F811
):
    """Nova's budget per run (its contract's `budget_tokens`) doesn't keep fx out; once a run has used it, its
    next step (here, after a decision) stops before asking the model again, and the decided change doesn't
    go through."""
    from dotrix_backend.modules.agent_definitions.schemas import AgentFields

    existing, sessions, _ = nova_pilot_world
    async with fx_chat(nova_pilot_world, db_client, outbox, storage, checkouts, agent_script) as fx:
        nova = f"/v1/workspaces/{existing.workspace_id}/agents/project-manager"
        current = (await fx.client.get(nova, headers=fx.headers)).json()
        fields = {name: current[name] for name in AgentFields.model_fields if name in current}
        saved = await fx.client.put(nova, json={"agent": {**fields, "budget_tokens": 10_000}}, headers=fx.headers)
        assert saved.status_code == 200, saved.text
        requests = []
        with scripted_model("write_file", PLAN, requests=requests) as url:
            monkeypatch.setitem(fx_pilot._FX_ENDPOINTS, "openai", url)
            asked = await fx.client.post(f"{fx.base}/runs", headers=fx.headers, json={
                "message": "Write the plan document", "chat_runtime": "fx", "work_mode": "build",
            })
            assert asked.status_code == 202 and asked.json()["status"] == "awaiting_approval", asked.text
            run = asked.json()
            async with sessions() as session:  # what the first step used, as a provider might report it
                await session.execute(update(AgentRun).where(AgentRun.id == uuid.UUID(run["id"])).values(
                    input_tokens=9_000, output_tokens=2_000))
                await session.commit()
            asked_model = len(requests)
            decided = await fx.client.post(f"{fx.base}/runs/{run['id']}/decisions", headers=fx.headers, json={
                "decisions": [{"approval_id": run["approvals"][0]["id"], "decision": "approve"}],
            })
            assert decided.status_code == 200, decided.text
        done = (await fx.client.get(f"{fx.base}/runs/{run['id']}", headers=fx.headers)).json()
        assert done["status"] == "failed" and "budget" in done["error"].lower(), done
        assert len(requests) == asked_model
        assert await _file(sessions, existing.project_id) is None


@pytest.mark.parametrize("version", ["libfx-0.0.16-pilot-2", "libfx-0.0.15-delegation-1", "libfx-9.9-unknown"])
async def test_a_run_bound_by_an_earlier_fx_version_runs_on_this_one(nova_pilot_world, monkeypatch, version):  # noqa: F811
    """A run an earlier pilot bound (no pinned context; 0.0.15's journal unreadable by 0.0.16) is moved to this
    version and answers; a version this one doesn't know still fails closed."""
    from datetime import UTC, datetime

    from apps.backend.tests.integration.test_runtime_tools import model_server
    from dotrix_backend.modules.agents.models import AgentRuntimeBinding, AgentRuntimeJournal

    run, sessions, secrets = nova_pilot_world
    async with sessions() as session:
        binding = AgentRuntimeBinding(workspace_id=run.workspace_id, run_id=run.id, runtime="fx", runtime_version=version,
                                      config_digest="0" * 64, session_id="fx-pilot-earlier", created_at=datetime.now(UTC))
        session.add(binding)
        await session.flush()
        session.add(AgentRuntimeJournal(workspace_id=run.workspace_id, binding_id=binding.id, sequence=1, expected_sequence=0,
                                        idempotency_key="old", encrypted=secrets.encrypt("not a libfx 0.0.16 record"),
                                        byte_count=26, created_at=datetime.now(UTC)))
        await session.commit()
    with model_server() as url:
        monkeypatch.setitem(fx_pilot._FX_ENDPOINTS, "openai", url)
        if version.startswith("libfx-9"):
            with pytest.raises(Exception, match="another runtime session or configuration"):
                await fx_pilot.run_fx_nova_pilot(sessions, workspace_id=run.workspace_id, run_id=run.id, token=1, secrets=secrets)
            return
        if version.startswith("libfx-0.0.16"):  # its journal is kept: here it has none an engine could read
            async with sessions() as session:
                await session.execute(AgentRuntimeJournal.__table__.delete().where(AgentRuntimeJournal.binding_id == binding.id))
                await session.commit()
        turn = await asyncio.wait_for(fx_pilot.run_fx_nova_pilot(
            sessions, workspace_id=run.workspace_id, run_id=run.id, token=1, secrets=secrets), 60)
    assert turn.stop_reason == "end_turn" and "Private project evidence" in turn.text
    async with sessions() as session:
        upgraded = await session.get(AgentRuntimeBinding, binding.id)
        assert upgraded.runtime_version == fx_pilot._VERSION and upgraded.session_id == "fx-pilot-earlier"
        assert upgraded.encrypted_context is not None
