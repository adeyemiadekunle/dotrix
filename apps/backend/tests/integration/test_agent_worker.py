"""Worker mode: the API enqueues runs in Redis (arq) and a worker executes them; the reply
streams through Redis; Stop aborts the job; a retried step continues from its checkpoint.

Needs Redis (the `redis` fixture; skipped if unreachable). Each test gets its own queue and
key prefix."""
import asyncio
import uuid
from typing import Any

import pytest
from arq import func
from arq.worker import Worker
from httpx import AsyncClient
from pydantic import Field

from pmagent_backend.modules.agents.llm import ModelChoice
from pmagent_backend.modules.agents.queue import RunQueue
from pmagent_backend.modules.agents.runner import AgentRunner
from pmagent_backend.modules.agents.streams import RedisRunStreams
from pmagent_backend.worker import run_agent
from pmagent_engine.testing import ScriptedChatModel, tool_call


@pytest.fixture
def worker_mode(db_client: AsyncClient, redis, create_team, signup, agent_script):
    """Switch the app to worker mode and build a worker; returns (ada, base url, make_worker)."""

    async def _make():
        name = f"pmagent:test:{uuid.uuid4().hex[:8]}"
        app = db_client._transport.app  # type: ignore[attr-defined]
        inline = app.state.runner
        streams = RedisRunStreams(redis, prefix=f"{name}:stream")
        app.state.runner = AgentRunner(
            session_factory=inline.session_factory,
            checkpointer=inline.checkpointer,
            model_factory=agent_script.factory,
            queue=RunQueue(redis, queue_name=name),
            streams=streams,
        )

        def make_worker(model_factory=agent_script.factory, burst: bool = True) -> Worker:
            executor = AgentRunner(
                session_factory=inline.session_factory,
                checkpointer=inline.checkpointer,
                model_factory=model_factory,
                inline=True,
                stop_reasons=RunQueue(redis, queue_name=name),
                streams=streams,
            )
            return Worker(
                functions=[func(run_agent, max_tries=3)],
                queue_name=name,
                redis_pool=redis,
                burst=burst,
                handle_signals=False,
                allow_abort_jobs=True,
                poll_delay=0.05,
                ctx={"runner": executor},
            )

        ada = await signup()
        team = await create_team(ada.headers)
        project = (
            await db_client.post(f"/v1/workspaces/{team['id']}/projects", json={"key": "KUN", "name": "K"}, headers=ada.headers)
        ).json()
        return ada, team, f"/v1/workspaces/{team['id']}/projects/{project['id']}", make_worker

    return _make


async def test_the_api_enqueues_and_the_worker_runs(worker_mode, db_client: AsyncClient, agent_script) -> None:
    ada, _, base, make_worker = await worker_mode()
    agent_script.say(
        tool_call("write_file", file_path="/pmagent/roadmap.md", content="# Roadmap\n\nPhase 1.\n"),
        "Updated the roadmap.",
    )
    queued = (await db_client.post(f"{base}/agent/runs", json={"message": "Update the roadmap"}, headers=ada.headers)).json()
    assert queued["status"] == "queued"  # the API only enqueued it

    await make_worker().main()  # burst: run what's queued, then return
    paused = (await db_client.get(f"{base}/agent/runs/{queued['id']}", headers=ada.headers)).json()
    assert paused["status"] == "awaiting_approval"

    decision = [{"approval_id": paused["approvals"][0]["id"], "decision": "approve"}]
    resumed = (
        await db_client.post(f"{base}/agent/runs/{queued['id']}/decisions", json={"decisions": decision}, headers=ada.headers)
    ).json()
    assert resumed["status"] == "queued"
    await make_worker().main()
    done = (await db_client.get(f"{base}/agent/runs/{queued['id']}", headers=ada.headers)).json()
    assert done["status"] == "completed" and done["reply"] == "Updated the roadmap."
    roadmap = (await db_client.get(f"{base}/knowledge/files/roadmap.md", headers=ada.headers)).json()
    assert "Phase 1." in roadmap["content"]


async def test_redis_streams_give_late_followers_the_text_so_far(redis) -> None:
    streams = RedisRunStreams(redis, prefix=f"pmagent:test:{uuid.uuid4().hex[:8]}")
    run_id = uuid.uuid4()
    stream = await streams.open(run_id)
    await stream.publish("Three issues ")
    await stream.activity("Checking the board")
    events: list[tuple[str, str]] = []

    async def follow():
        async for event in streams.follow(run_id, heartbeat_seconds=1):
            events.append(event)

    follower = asyncio.create_task(follow())
    await asyncio.sleep(0.2)
    await stream.activity("Looking at KUN-5")
    await stream.publish("are open.")
    await streams.close(run_id)
    await asyncio.wait_for(follower, 5)
    assert events == [
        ("text", "Three issues "),
        ("activity", "Checking the board"),  # the current activity, for a late follower
        ("activity", "Looking at KUN-5"),
        ("delta", "are open."),
        ("end", ""),
    ]
    # After the end there's nothing to follow.
    assert [e async for e in streams.follow(run_id)] == [("end", "")]


class GatedModel(ScriptedChatModel):
    started: Any = Field(default=None, exclude=True)
    gate: Any = Field(default=None, exclude=True)

    async def _astream(self, messages, *args, **kwargs):  # type: ignore[override]
        self.started.set()
        await self.gate.wait()
        async for chunk in super()._astream(messages, *args, **kwargs):
            yield chunk


async def test_stop_aborts_the_job_in_the_worker(worker_mode, db_client: AsyncClient, agent_script) -> None:
    ada, _, base, make_worker = await worker_mode()
    agent_script.say("unused")  # the API checks a model is configured before it enqueues
    model = GatedModel.of("A long report…")
    model.started, model.gate = asyncio.Event(), asyncio.Event()
    worker = make_worker(model_factory=lambda _p: ModelChoice(model=model, web_search=None), burst=False)
    running = asyncio.create_task(worker.async_run())
    try:
        created = await db_client.post(f"{base}/agent/runs", json={"message": "Write a long report"}, headers=ada.headers)
        assert created.status_code == 202, created.text
        run = created.json()
        await asyncio.wait_for(model.started.wait(), 10)
        stopped = await db_client.post(f"{base}/agent/runs/{run['id']}/stop", headers=ada.headers)
        assert stopped.status_code == 200, stopped.text
        assert stopped.json()["status"] == "failed" and stopped.json()["error"] == "Stopped by Ada"
    finally:
        # (worker.close() sends SIGUSR1, which Windows doesn't have: cancel the loop instead.)
        running.cancel()
        await asyncio.gather(running, return_exceptions=True)


async def test_a_retried_step_does_not_resend_the_message(db_client: AsyncClient, agent_script, signup, create_team) -> None:
    """A worker cut off after the graph finished but before the outcome was saved: the retry
    reads the checkpoint instead of asking the model again (it only has one reply scripted)."""
    ada = await signup()
    team = await create_team(ada.headers)
    project = (
        await db_client.post(f"/v1/workspaces/{team['id']}/projects", json={"key": "KUN", "name": "K"}, headers=ada.headers)
    ).json()
    base = f"/v1/workspaces/{team['id']}/projects/{project['id']}"
    model = agent_script.say("Here's the plan.")
    run = (await db_client.post(f"{base}/agent/runs", json={"message": "Plan it"}, headers=ada.headers)).json()
    assert run["status"] == "completed" and len(model.received) == 1

    # Pretend the first attempt's outcome was never saved, then retry the job.
    runner: AgentRunner = db_client._transport.app.state.runner  # type: ignore[attr-defined]
    from pmagent_backend.modules.agents.models import AgentRun, RunStatus

    async with runner.session_factory() as session:
        row = await session.get(AgentRun, uuid.UUID(run["id"]))
        row.status, row.reply = RunStatus.RUNNING, None
        await session.commit()
    await runner.execute(uuid.UUID(run["id"]), {"kind": "start", "message": "Plan it"})

    again = (await db_client.get(f"{base}/agent/runs/{run['id']}", headers=ada.headers)).json()
    assert again["status"] == "completed" and again["reply"] == "Here's the plan."
    assert len(model.received) == 1  # the model wasn't asked twice
