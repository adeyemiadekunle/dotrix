"""Durable private input ordering, safe-point steering, and normal queued turns."""
import asyncio
import shutil
import threading
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from deepagents import create_deep_agent
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import select, update
from uuid_utils.compat import uuid7

from apps.backend.tests.integration.test_runtime_tools import model_server
from dotrix_backend.core.errors import Conflict, Forbidden
from dotrix_backend.modules.agents import chat_inputs, fx_pilot
from dotrix_backend.modules.agents.chat_inputs import ChatSteering
from dotrix_backend.modules.agents.models import AgentRun, ChatInput, ChatRuntime, RunStatus
from dotrix_backend.modules.agents.runner import _GRAPH, AgentRunner, _continue_from_checkpoint
from dotrix_backend.modules.agents.schemas import ChatInputCreate
from dotrix_backend.modules.projects.deps import ProjectAccess
from dotrix_backend.modules.projects.models import Project
from dotrix_backend.modules.workspaces.models import Membership, Role
from dotrix_engine.testing import ScriptedChatModel, tool_call

pytest_plugins = ["apps.backend.tests.integration.test_runtime_tools"]


def require_fx():
    from dotrix_engine.runtimes.fx import _HOST
    if not shutil.which("node") or not (_HOST / "node_modules" / "libfx").is_dir():
        pytest.skip("Install the optional fx host to exercise native steering")


async def access_for(session, run):
    project = await session.get(Project, run.project_id)
    member = await session.scalar(select(Membership).where(Membership.workspace_id == run.workspace_id,
        Membership.user_id == run.requested_by_id))
    return ProjectAccess(project, member)


async def submit(sessions, run, message="Use self-hosted options only", kind="steer", client_id=None):
    async with sessions() as session:
        return await chat_inputs.submit(session, await access_for(session, run), run.thread_id,
            ChatInputCreate(client_id=client_id or uuid7(), kind=kind, message=message))


async def test_chat_input_api_is_private_idempotent_and_cancellable(runtime_world, db_client, signup):
    person, _, base, run, _, sessions = runtime_world
    url = f"{base}/agent/threads/{run.thread_id}/inputs"
    body = {"kind": "queue", "message": "Compare the choices afterward", "client_id": str(uuid7())}
    first = await db_client.post(url, json=body, headers=person.headers)
    assert first.status_code == 202, first.text
    assert (await db_client.post(url, json=body, headers=person.headers)).json()["id"] == first.json()["id"]
    assert (await db_client.post(url, json={**body, "message": "Changed"}, headers=person.headers)).status_code == 409
    colleague = await signup(email="colleague@example.com")
    async with sessions() as session:
        session.add(Membership(workspace_id=run.workspace_id, user_id=uuid.UUID(colleague.id), role=Role.MEMBER))
        await session.commit()
    assert (await db_client.get(url, headers=colleague.headers)).status_code == 404
    cancelled = await db_client.delete(f"{url}/{first.json()['id']}", headers=person.headers)
    assert cancelled.json()["status"] == "cancelled"
    assert (await db_client.get(url, headers=person.headers)).json()[0]["status"] == "cancelled"


async def test_deepagents_steering_reaches_next_model_and_checkpoint_without_duplicate(nova_pilot_world):
    run, sessions, _ = nova_pilot_world
    started, gate = asyncio.Event(), asyncio.Event()

    async def pause() -> str:
        """Wait for the project's evidence."""
        started.set()
        await gate.wait()
        return "Evidence available"

    model = ScriptedChatModel.of(tool_call("pause"), "Self-hosted only")
    agent = create_deep_agent(model=model, tools=[pause], checkpointer=InMemorySaver(),
        middleware=[ChatSteering(sessions, run.workspace_id, run.id, 1)])
    config = {"configurable": {"thread_id": str(run.thread_id)}}
    task = asyncio.create_task(agent.ainvoke({"messages": [{"role": "user", "content": run.message}]}, config))
    try:
        await asyncio.wait_for(started.wait(), 15)
        item = await submit(sessions, run)
        gate.set()
        result = await asyncio.wait_for(task, 15)
        assert sum(message.content == item.message for message in model.received[-1]) == 1
        assert await chat_inputs.steering(sessions, run.workspace_id, run.id, 1, result["messages"]) == []
        assert await chat_inputs.steering(sessions, run.workspace_id, run.id, 1, result["messages"]) == []
        async with sessions() as session:
            assert (await session.get(ChatInput, item.id)).status == "accepted"
            snapshot = await agent.aget_state(config)
            assert sum(message.id == str(item.id) for message in snapshot.values["messages"]) == 1
        replay_input, replayed = await _continue_from_checkpoint(agent, config,
            {"kind": "start", "message": run.message}, {"messages": [{"role": "user", "content": run.message}]})
        assert replay_input is None and replayed is not None
        assert len(model.received) == 2  # Recover recording, without starting the original request again.
    finally:
        gate.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("change", ["membership", "lease"])
async def test_steering_rechecks_access_and_lease_before_delivery(nova_pilot_world, change):
    run, sessions, _ = nova_pilot_world
    await submit(sessions, run)
    async with sessions() as session:
        if change == "membership":
            await session.execute(update(Membership).where(Membership.workspace_id == run.workspace_id,
                Membership.user_id == run.requested_by_id).values(role=Role.GUEST))
        else:
            await session.execute(update(AgentRun).where(AgentRun.id == run.id).values(lease_token=2))
        await session.commit()
    with pytest.raises((Forbidden, Conflict)):
        await chat_inputs.steering(sessions, run.workspace_id, run.id, 1)


@pytest.mark.parametrize("durable", [False, True])
async def test_fx_native_steering_reaches_the_model(nova_pilot_world, monkeypatch, durable):
    require_fx()
    run, sessions, secrets = nova_pilot_world
    from dotrix_backend.modules.agents.delegation import DelegationService

    started, gate, requests = threading.Event(), threading.Event(), []
    if durable:
        async with sessions() as session:
            await session.execute(update(AgentRun).where(AgentRun.id == run.id).values(orchestration=True))
            await session.commit()
    scheduler = DelegationService(AgentRunner(session_factory=sessions, checkpointer=InMemorySaver(), secrets=secrets,
        model_factory=lambda *args, **kwargs: SimpleNamespace(model=ScriptedChatModel.of("Done")))) if durable else None
    with model_server(started=started, gate=gate, requests=requests) as url:
        monkeypatch.setitem(fx_pilot._FX_ENDPOINTS, "openai", url)
        task = asyncio.create_task(fx_pilot.run_fx_nova_pilot(sessions, workspace_id=run.workspace_id,
            run_id=run.id, token=1, secrets=secrets, delegation=scheduler))
        try:
            if not await asyncio.wait_for(asyncio.to_thread(started.wait, 15), 16):
                await task
                pytest.fail("The fx model request did not start")
            item = await submit(sessions, run)
            async with asyncio.timeout(15):
                while True:
                    async with sessions() as session:
                        if (await session.get(ChatInput, item.id)).status == "accepted":
                            break
                    await asyncio.sleep(0.05)
            gate.set()
            result = await asyncio.wait_for(task, 20)
            assert result.stop_reason == "end_turn"
            assert any(item.message in str(request["request"]["messages"]) for request in requests[1:])
        finally:
            gate.set()
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("runtime", [ChatRuntime.DEEPAGENTS, ChatRuntime.FX])
async def test_queue_is_ordered_and_dispatch_is_atomic(nova_pilot_world, monkeypatch, runtime):
    run, sessions, secrets = nova_pilot_world
    run.chat_runtime = runtime
    async with sessions() as session:
        await session.execute(update(AgentRun).where(AgentRun.id == run.id).values(chat_runtime=runtime))
        await session.commit()
    first = await submit(sessions, run, "First follow-up", "queue")
    second = await submit(sessions, run, "Second follow-up", "queue")
    runner = AgentRunner(session_factory=sessions, checkpointer=InMemorySaver(), secrets=secrets,
        model_factory=lambda *args, **kwargs: SimpleNamespace(model=ScriptedChatModel.of("Done")))
    runner.settings = SimpleNamespace()
    dispatched = []

    async def start(run_id, message, **kwargs):
        dispatched.append(run_id)

    monkeypatch.setattr(runner, "start", start)
    assert await chat_inputs.deliver_queued(sessions, runner) == 0
    async with sessions() as session:
        await session.execute(update(AgentRun).where(AgentRun.id == run.id).values(status=RunStatus.COMPLETED))
        await session.commit()
    results = await asyncio.gather(chat_inputs.deliver_queued(sessions, runner), chat_inputs.deliver_queued(sessions, runner))
    assert sum(results) == 1 and len(dispatched) == 1
    async with sessions() as session:
        one, two = await session.get(ChatInput, first.id), await session.get(ChatInput, second.id)
        assert one.status == "delivered" and one.delivered_run_id == dispatched[0]
        assert two.status == "pending"
        child = await session.get(AgentRun, dispatched[0])
        assert child.message == first.message and child.requested_by_id == run.requested_by_id
        assert child.chat_runtime == run.chat_runtime
        child.status, child.finished_at = RunStatus.COMPLETED, datetime.now(UTC)
        await session.commit()
    assert await chat_inputs.deliver_queued(sessions, runner) == 1
    assert len(dispatched) == 2


async def test_queue_rejects_revoked_access(nova_pilot_world):
    run, sessions, secrets = nova_pilot_world
    item = await submit(sessions, run, kind="queue")
    async with sessions() as session:
        await session.execute(update(AgentRun).where(AgentRun.id == run.id).values(status=RunStatus.COMPLETED))
        await session.execute(update(Membership).where(Membership.workspace_id == run.workspace_id,
            Membership.user_id == run.requested_by_id).values(role=Role.GUEST))
        await session.commit()
    runner = AgentRunner(session_factory=sessions, checkpointer=InMemorySaver(), secrets=secrets,
        model_factory=lambda *args, **kwargs: SimpleNamespace(model=ScriptedChatModel.of("Done")))
    assert await chat_inputs.deliver_queued(sessions, runner) == 0
    async with sessions() as session:
        assert (await session.get(ChatInput, item.id)).status == "rejected"


async def test_stop_cancels_pending_inputs_and_approval_does_not_deliver_them(nova_pilot_world):
    from dotrix_backend.modules.agents.service import AgentService

    run, sessions, secrets = nova_pilot_world
    runner = AgentRunner(session_factory=sessions, checkpointer=InMemorySaver(), secrets=secrets,
        model_factory=lambda *args, **kwargs: SimpleNamespace(model=ScriptedChatModel.of("Done")))
    async with sessions() as session:
        await session.execute(update(AgentRun).where(AgentRun.id == run.id).values(status=RunStatus.AWAITING_APPROVAL))
        await session.commit()
    item = await submit(sessions, run, kind="queue")
    with pytest.raises(Conflict, match="approval"):
        await submit(sessions, run, kind="steer")
    assert await chat_inputs.deliver_queued(sessions, runner) == 0
    async with sessions() as session:
        await session.execute(update(AgentRun).where(AgentRun.id == run.id).values(status=RunStatus.QUEUED))
        await session.commit()
    steer = await submit(sessions, run)
    async with sessions() as session:
        await AgentService(session, runner).stop(await access_for(session, run), run.id)
    async with sessions() as session:
        assert (await session.get(ChatInput, item.id)).status == "cancelled"
        assert (await session.get(ChatInput, steer.id)).status == "cancelled"
    assert await chat_inputs.deliver_queued(sessions, runner) == 0


@pytest.mark.parametrize("error", [RuntimeError, Forbidden])
async def test_queue_recovery_does_not_duplicate_a_committed_dispatch(nova_pilot_world, monkeypatch, error):
    from dotrix_backend.modules.execution.models import RunDispatch

    run, sessions, secrets = nova_pilot_world
    item = await submit(sessions, run, kind="queue")
    async with sessions() as session:
        await session.execute(update(AgentRun).where(AgentRun.id == run.id).values(status=RunStatus.COMPLETED))
        await session.commit()
    runner = AgentRunner(session_factory=sessions, checkpointer=InMemorySaver(), secrets=secrets,
        queue=SimpleNamespace(queue_name="test-chat"),
        model_factory=lambda *args, **kwargs: SimpleNamespace(model=ScriptedChatModel.of("Done")))

    async def stopped_after_commit(*args, **kwargs):
        raise error("publisher interrupted")

    monkeypatch.setattr(runner, "start", stopped_after_commit)
    with pytest.raises(error, match="publisher interrupted"):
        await chat_inputs.deliver_queued(sessions, runner)
    assert await chat_inputs.deliver_queued(sessions, runner) == 0
    async with sessions() as session:
        saved = await session.get(ChatInput, item.id)
        dispatches = list(await session.scalars(select(RunDispatch).where(
            RunDispatch.workspace_id == run.workspace_id, RunDispatch.agent_run_id == saved.delivered_run_id)))
        assert saved.status == "delivered" and len(dispatches) == 1
        assert dispatches[0].accepted_at is None


async def test_fx_steering_survives_restart_before_host_acknowledgement(nova_pilot_world, monkeypatch):
    require_fx()
    from dotrix_backend.modules.agents.delegation import DelegationService
    from dotrix_engine.runtimes import FxRuntime

    run, sessions, secrets = nova_pilot_world
    async with sessions() as session:
        await session.execute(update(AgentRun).where(AgentRun.id == run.id).values(orchestration=True))
        await session.commit()
    scheduler = DelegationService(AgentRunner(session_factory=sessions, checkpointer=InMemorySaver(), secrets=secrets,
        model_factory=lambda *args, **kwargs: SimpleNamespace(model=ScriptedChatModel.of("Done"))))
    created, requests = [], []
    create, acknowledge = FxRuntime.create, fx_pilot.accepted
    native_accepted = asyncio.Event()

    async def capture_runtime(*args, **kwargs):
        runtime = await create(*args, **kwargs)
        created.append(runtime)
        return runtime

    async def lost_acknowledgement(*args, **kwargs):
        native_accepted.set()

    monkeypatch.setattr(FxRuntime, "create", staticmethod(capture_runtime))
    monkeypatch.setattr(fx_pilot, "accepted", lost_acknowledgement)
    started, gate = threading.Event(), threading.Event()
    with model_server(started=started, gate=gate, requests=requests) as url:
        monkeypatch.setitem(fx_pilot._FX_ENDPOINTS, "openai", url)

        def turn():
            return asyncio.create_task(fx_pilot.run_fx_nova_pilot(sessions, workspace_id=run.workspace_id,
                run_id=run.id, token=1, secrets=secrets, delegation=scheduler))

        first = turn()
        second = None
        try:
            if not await asyncio.to_thread(started.wait, 15):
                await first
                pytest.fail("The model request did not start")
            item = await submit(sessions, run)
            await asyncio.wait_for(native_accepted.wait(), 15)
            created[0].process.kill()
            with pytest.raises(RuntimeError):
                await asyncio.wait_for(first, 10)
            async with sessions() as session:
                assert (await session.get(ChatInput, item.id)).status == "sending"
            monkeypatch.setattr(fx_pilot, "accepted", acknowledge)
            second = turn()
            async with asyncio.timeout(15):
                while True:
                    async with sessions() as session:
                        if (await session.get(ChatInput, item.id)).status == "accepted":
                            break
                    await asyncio.sleep(0.05)
            gate.set()
            result = await asyncio.wait_for(second, 20)
            assert result.stop_reason == "end_turn"
            assert sum(str(message).count(item.message) for message in requests[-1]["request"]["messages"]) == 1
        finally:
            gate.set()
            for task in (first, second):
                if task is not None and not task.done():
                    task.cancel()
            await asyncio.gather(*(task for task in (first, second) if task is not None), return_exceptions=True)


async def test_input_racing_turn_completion_cannot_remain_pending(nova_pilot_world):
    run, sessions, _ = nova_pilot_world
    async with sessions() as finishing:
        stored = await finishing.get(AgentRun, run.id, with_for_update=True)
        stored.status = RunStatus.COMPLETED
        task = asyncio.create_task(submit(sessions, run))
        try:
            await asyncio.sleep(0.05)
            await finishing.commit()
            with pytest.raises(Conflict, match="idle"):
                await asyncio.wait_for(task, 5)
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    async with sessions() as session:
        assert await session.scalar(select(ChatInput.id).where(ChatInput.run_id == run.id)) is None


async def test_new_message_retires_unconfirmed_steering_of_abandoned_limit_turn(nova_pilot_world, monkeypatch):
    from dotrix_backend.modules.agents.schemas import RunCreate
    from dotrix_backend.modules.agents.service import AgentService

    run, sessions, secrets = nova_pilot_world
    item = await submit(sessions, run)
    await chat_inputs.steering(sessions, run.workspace_id, run.id, 1)
    async with sessions() as session:
        await session.execute(update(AgentRun).where(AgentRun.id == run.id).values(
            status=RunStatus.FAILED, error_kind="model_limit"))
        await session.commit()
    runner = AgentRunner(session_factory=sessions, checkpointer=InMemorySaver(), secrets=secrets,
        model_factory=lambda *args, **kwargs: SimpleNamespace(model=ScriptedChatModel.of("Done")))

    async def start(*args, **kwargs):
        pass

    monkeypatch.setattr(runner, "start", start)
    async with sessions() as session:
        await AgentService(session, runner).create_run(await access_for(session, run),
            RunCreate(message="Try a different question", thread_id=run.thread_id))
    async with sessions() as session:
        saved = await session.get(ChatInput, item.id)
        assert saved.status == "rejected" and "before delivery could be confirmed" in saved.error


@pytest.mark.parametrize("runtime", [ChatRuntime.DEEPAGENTS, ChatRuntime.FX])
@pytest.mark.parametrize("error_kind", ["model_limit", "interrupted"])
async def test_only_resumable_failures_keep_follow_ups_waiting(nova_pilot_world, monkeypatch, runtime, error_kind):
    from dotrix_backend.modules.agents.schemas import RunCreate
    from dotrix_backend.modules.agents.service import AgentService, ThreadBusy

    run, sessions, secrets = nova_pilot_world
    first = await submit(sessions, run, "First follow-up", "queue")
    second = await submit(sessions, run, "Second follow-up", "queue")
    async with sessions() as session:
        await session.execute(update(AgentRun).where(AgentRun.id == run.id).values(
            chat_runtime=runtime, status=RunStatus.FAILED, error_kind=error_kind))
        await session.commit()
    runner = AgentRunner(session_factory=sessions, checkpointer=InMemorySaver(), secrets=secrets,
        model_factory=lambda *args, **kwargs: SimpleNamespace(model=ScriptedChatModel.of("Done")),
        settings=SimpleNamespace())
    dispatched = []

    async def start(*args, **kwargs):
        dispatched.append(args)

    monkeypatch.setattr(runner, "start", start)
    assert await chat_inputs.deliver_queued(sessions, runner) == 0
    assert not dispatched
    async with sessions() as session:
        rows = [await session.get(ChatInput, item.id) for item in (first, second)]
        # Both runtimes resume such a turn (DeepAgents from its checkpoint, fx from its journal).
        assert {item.status for item in rows} == {"pending"}
    async with sessions() as session:
        service, access = AgentService(session, runner), await access_for(session, run)
        with pytest.raises(ThreadBusy, match="Queued messages"):
            await service.create_run(access, RunCreate(message="A new question", thread_id=run.thread_id))


@pytest.mark.parametrize("limited", [True, False])
async def test_failure_reconciles_checkpointed_steering_before_marking_it_rejected(nova_pilot_world, limited):
    from dotrix_backend.modules.agents.usage import TokenUsage

    class ProviderFailure(Exception):
        pass

    failure = ProviderFailure("429 rate limit exceeded" if limited else "provider connection failed")

    class FailsOnce(ScriptedChatModel):
        failures: list[bool] = [True]

        def _generate(self, *args, **kwargs):
            if self.failures:
                self.failures.pop()
                raise failure
            return super()._generate(*args, **kwargs)

    run, sessions, secrets = nova_pilot_world
    item = await submit(sessions, run)
    checkpointer = InMemorySaver()
    model = FailsOnce.of("Recovered answer")
    agent = create_deep_agent(model=model, checkpointer=checkpointer,
        middleware=[ChatSteering(sessions, run.workspace_id, run.id, 1)])
    config = {"configurable": {"thread_id": str(run.thread_id)}}
    with pytest.raises(ProviderFailure):
        await agent.ainvoke({"messages": [{"role": "user", "content": run.message}]}, config)
    async with sessions() as session:
        assert (await session.get(ChatInput, item.id)).status == "sending"
    saved = await agent.aget_state(config)
    assert sum(message.id == str(item.id) for message in saved.values["messages"]) == 1
    runner = AgentRunner(session_factory=sessions, checkpointer=checkpointer, secrets=secrets,
        model_factory=lambda *args, **kwargs: SimpleNamespace(model=model))
    graph_token = _GRAPH.set((run.id, agent))
    try:
        if limited:
            assert await runner._limited(run.id, failure, TokenUsage())
        else:
            await runner._fail(run.id, str(failure), TokenUsage())
    finally:
        _GRAPH.reset(graph_token)
    async with sessions() as session:
        stored, instruction = await session.get(AgentRun, run.id), await session.get(ChatInput, item.id)
        assert stored.status is RunStatus.FAILED
        assert stored.error_kind == ("model_limit" if limited else None)
        assert instruction.status == "accepted" and instruction.error is None
        if limited:
            stored.status = RunStatus.RUNNING
            await session.commit()
    if limited:
        result = await agent.ainvoke(None, config)
        assert sum(message.id == str(item.id) for message in result["messages"]) == 1
        assert await chat_inputs.steering(sessions, run.workspace_id, run.id, 1, result["messages"]) == []


async def test_unreadable_checkpoint_does_not_claim_steering_was_rejected(nova_pilot_world):
    from dotrix_backend.modules.agents.usage import TokenUsage

    run, sessions, secrets = nova_pilot_world
    item = await submit(sessions, run)
    await chat_inputs.steering(sessions, run.workspace_id, run.id, 1)

    async def unavailable(config):
        raise OSError("Checkpoint store unavailable")

    runner = AgentRunner(session_factory=sessions, checkpointer=SimpleNamespace(aget_tuple=unavailable), secrets=secrets,
        model_factory=lambda *args, **kwargs: SimpleNamespace(model=ScriptedChatModel.of("Done")))
    await runner._limited(run.id, RuntimeError("429 rate limit exceeded"), TokenUsage())
    async with sessions() as session:
        saved = await session.get(ChatInput, item.id)
        assert saved.status == "sending" and saved.error is None


async def test_runner_failure_uses_its_restored_graph_to_accept_checkpointed_steering(nova_pilot_world):
    from dotrix_backend.modules.agents.llm import ModelChoice

    class Limited(ScriptedChatModel):
        def _generate(self, *args, **kwargs):
            raise RuntimeError("429 rate limit exceeded")

    run, sessions, secrets = nova_pilot_world
    item = await submit(sessions, run)
    async with sessions() as session:
        await session.execute(update(AgentRun).where(AgentRun.id == run.id).values(
            status=RunStatus.QUEUED, lease_expires_at=None))
        await session.commit()
    runner = AgentRunner(session_factory=sessions, checkpointer=InMemorySaver(), secrets=secrets,
        model_factory=lambda *args, **kwargs: ModelChoice(model=Limited.of(), web_search=None))
    await runner.execute(run.id, {"kind": "start", "message": run.message})
    async with sessions() as session:
        stored, instruction = await session.get(AgentRun, run.id), await session.get(ChatInput, item.id)
        assert stored.status is RunStatus.FAILED and stored.error_kind == "model_limit"
        assert instruction.status == "accepted" and instruction.error is None
    assert _GRAPH.get() is None
