"""A run's events, kept: its steps, its reply as written, and each step's outcome, read from where a
client was (`after`); the stream falls back to them when the live one is gone and the run still works."""
import asyncio
import uuid
from datetime import UTC, datetime

from httpx import AsyncClient
from sqlalchemy import update

from dotrix_backend.modules.agents.events import RunRecorder, follow_run
from dotrix_backend.modules.agents.models import AgentRun, RunEventKind, RunStatus
from dotrix_backend.modules.agents.streams import RunStreams
from dotrix_backend.modules.workspaces.models import Role
from dotrix_engine.testing import tool_call


async def _project(db_client: AsyncClient, signup, create_team, add_member):
    ada = await signup()
    bob = await signup(email="bob@example.com", name="Bob")
    team = await create_team(ada.headers)
    await add_member(team["id"], bob.id, Role.MEMBER)
    project = (await db_client.post(f"/v1/workspaces/{team['id']}/projects", json={"key": "KUN", "name": "K"},
                                    headers=ada.headers)).json()
    return ada, bob, team, f"/v1/workspaces/{team['id']}/projects/{project['id']}"


def _factory(db_client: AsyncClient):
    return db_client._transport.app.state.jobs.ctx.session_factory  # type: ignore[attr-defined]


async def test_a_run_keeps_its_steps_and_reply_and_reads_from_a_cursor(
    db_client: AsyncClient, signup, create_team, add_member, agent_script
) -> None:
    ada, bob, _, base = await _project(db_client, signup, create_team, add_member)
    agent_script.say(tool_call("write_file", file_path="/dotrix/roadmap.md", content="# Plan"), "I wrote the roadmap.")
    run = (await db_client.post(f"{base}/agent/runs", headers=ada.headers, json={"message": "Write it"})).json()
    assert run["status"] == "awaiting_approval"
    page = (await db_client.get(f"{base}/agent/runs/{run['id']}/events", headers=ada.headers)).json()
    kinds = [e["kind"] for e in page["events"]]
    assert kinds[0] == "step" and kinds[-1] == "status" and not page["active"]
    assert page["events"][0]["data"] == {"attempt": 1, "step": "start", "recovered": False}
    assert page["events"][-1]["data"] == {"status": "awaiting_approval", "pending": 1}
    assert [e["seq"] for e in page["events"]] == list(range(1, len(kinds) + 1))

    # Approved: the resumed step's events follow, from where the client was.
    last = page["events"][-1]["seq"]
    decision = [{"approval_id": run["approvals"][0]["id"], "decision": "approve"}]
    await db_client.post(f"{base}/agent/runs/{run['id']}/decisions", json={"decisions": decision}, headers=ada.headers)
    more = (await db_client.get(f"{base}/agent/runs/{run['id']}/events?after={last}", headers=ada.headers)).json()
    assert more["events"][0]["kind"] == "step" and more["events"][0]["data"]["step"] == "resume"
    assert more["events"][0]["attempt"] == 2  # each step's attempt takes the next lease
    text = "".join(e["data"]["text"] for e in more["events"] if e["kind"] == "text")
    assert text == "I wrote the roadmap."
    assert more["events"][-1]["data"] == {"status": "completed", "pending": 0}

    # As private as the run.
    assert (await db_client.get(f"{base}/agent/runs/{run['id']}/events", headers=bob.headers)).status_code == 404


async def test_the_stream_falls_back_to_kept_events_when_the_live_one_is_gone(
    db_client: AsyncClient, signup, create_team, add_member, agent_script
) -> None:
    ada, _, team, base = await _project(db_client, signup, create_team, add_member)
    agent_script.say("Hello.")
    run = (await db_client.post(f"{base}/agent/runs", headers=ada.headers, json={"message": "Hi"})).json()
    run_id, workspace_id = uuid.UUID(run["id"]), uuid.UUID(team["id"])
    factory = _factory(db_client)
    # Its worker died mid-reply, and a new attempt is writing: no live stream here.
    async with factory() as session:
        await session.execute(update(AgentRun).where(AgentRun.id == run_id).values(status=RunStatus.RUNNING, lease_token=5))
        await session.commit()
    recorder = RunRecorder(factory, workspace_id, run_id, 5)
    await recorder.write(RunEventKind.STEP, {"attempt": 5, "step": "start", "recovered": True})
    await recorder.write(RunEventKind.TEXT, {"text": "Three issues "})
    await recorder.write(RunEventKind.ACTIVITY, {"label": "Reading the board"})

    async def finish() -> None:
        await asyncio.sleep(1.2)
        await recorder.write(RunEventKind.TEXT, {"text": "are open."})
        async with factory() as session:
            await session.execute(update(AgentRun).where(AgentRun.id == run_id).values(
                status=RunStatus.COMPLETED, finished_at=datetime.now(UTC)))
            await session.commit()

    finishing = asyncio.create_task(finish())
    seen = [e async for e in follow_run(RunStreams(), factory, workspace_id, run_id)]
    await finishing
    assert seen == [("text", "Three issues "), ("activity", "Reading the board"), ("delta", "are open."), ("end", "")]

    # A run that isn't working: just the end.
    assert [e async for e in follow_run(RunStreams(), factory, workspace_id, run_id)] == [("end", "")]


async def test_nova_s_thinking_is_kept_apart_from_its_reply(
    db_client: AsyncClient, signup, create_team, add_member, agent_script
) -> None:
    from langchain_core.messages import AIMessage

    ada, _, _, base = await _project(db_client, signup, create_team, add_member)
    thought = "This isn't about the project: no documents to read, I'll answer directly."
    agent_script.say(AIMessage(content=[{"type": "thinking", "thinking": thought, "signature": "s"},
                                        {"type": "text", "text": "Paris."}]))
    run = (await db_client.post(f"{base}/agent/runs", headers=ada.headers,
                                json={"message": "What is the capital of France?"})).json()
    assert run["status"] == "completed" and run["reply"] == "Paris.", run
    events = (await db_client.get(f"{base}/agent/runs/{run['id']}/events", headers=ada.headers)).json()["events"]
    assert "".join(e["data"]["text"] for e in events if e["kind"] == "thinking") == thought
    assert "".join(e["data"]["text"] for e in events if e["kind"] == "text") == "Paris."
    kinds = [e["kind"] for e in events]
    assert kinds.index("thinking") < kinds.index("text")  # in the order it happened
