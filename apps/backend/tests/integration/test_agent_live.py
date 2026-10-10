"""Live runs: streaming the PM's reply, stopping a run, and renaming a conversation.

These need a run that is still working when the test acts, so they swap in a background
(non-inline) runner whose model waits on a gate the test opens."""
import asyncio
from typing import Any

import pytest
from httpx import AsyncClient
from pydantic import Field

from dotrix_backend.modules.agents.llm import ModelChoice
from dotrix_backend.modules.agents.runner import AgentRunner
from dotrix_backend.modules.workspaces.models import Role
from dotrix_engine.testing import ScriptedChatModel, tool_call


class GatedModel(ScriptedChatModel):
    """Signals `started`, then waits for `gate` before replying (word by word)."""

    started: Any = Field(default=None, exclude=True)
    gate: Any = Field(default=None, exclude=True)

    async def _astream(self, messages, *args, **kwargs):  # type: ignore[override]
        self.started.set()
        await self.gate.wait()
        async for chunk in super()._astream(messages, *args, **kwargs):
            yield chunk


@pytest.fixture
def live(db_client: AsyncClient, create_team, signup):
    """(ada, base url, gated model): a project whose runs execute in the background."""

    async def _make(*replies: Any):
        ada = await signup()
        team = await create_team(ada.headers)
        project = (
            await db_client.post(f"/v1/workspaces/{team['id']}/projects", json={"key": "KUN", "name": "K"}, headers=ada.headers)
        ).json()
        model = GatedModel.of(*(replies or ("Three issues are open and one is blocked.",)))
        model.started, model.gate = asyncio.Event(), asyncio.Event()
        app = db_client._transport.app  # type: ignore[attr-defined]
        inline = app.state.runner
        app.state.runner = AgentRunner(
            session_factory=inline.session_factory,
            checkpointer=inline.checkpointer,
            model_factory=lambda _project, _model=None, **_: ModelChoice(model=model, web_search=None),
            inline=False,
        )
        return ada, team, f"/v1/workspaces/{team['id']}/projects/{project['id']}", model

    return _make


async def wait_for(client: AsyncClient, url: str, headers, done) -> dict:
    for _ in range(100):
        run = (await client.get(url, headers=headers)).json()
        if done(run):
            return run
        await asyncio.sleep(0.05)
    raise AssertionError(f"run never reached the expected state: {run}")


async def test_the_reply_streams_as_it_is_written(live, db_client: AsyncClient) -> None:
    ada, _, base, model = await live()
    run = (await db_client.post(f"{base}/agent/runs", json={"message": "What's open?"}, headers=ada.headers)).json()
    await asyncio.wait_for(model.started.wait(), 5)

    async def open_gate_soon():
        await asyncio.sleep(0.2)
        model.gate.set()

    # The whole event stream (the test client collects it), while the model writes.
    response, _ = await asyncio.gather(
        db_client.get(f"{base}/agent/runs/{run['id']}/stream", headers=ada.headers), open_gate_soon()
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    body = response.text
    assert body.startswith('event: text\ndata: {"text": ""}')
    deltas = [line for line in body.splitlines() if line.startswith("data:")][1:-1]
    assert len(deltas) > 3  # word by word
    assert body.rstrip().endswith('event: end\ndata: {"text": ""}')

    done = await wait_for(db_client, f"{base}/agent/runs/{run['id']}", ada.headers, lambda r: r["status"] == "completed")
    assert done["reply"] == "Three issues are open and one is blocked."
    # Once it's finished there's nothing to stream: just the end.
    after = await db_client.get(f"{base}/agent/runs/{run['id']}/stream", headers=ada.headers)
    assert after.text.startswith("event: end")


async def test_the_stream_says_what_the_pm_is_doing(live, db_client: AsyncClient) -> None:
    ada, _, base, model = await live(
        tool_call("read_file", file_path="/dotrix/roadmap.md"), "The roadmap has three phases."
    )
    run = (await db_client.post(f"{base}/agent/runs", json={"message": "Summarise the roadmap"}, headers=ada.headers)).json()
    await asyncio.wait_for(model.started.wait(), 5)

    async def open_gate_soon():
        await asyncio.sleep(0.2)
        model.gate.set()

    response, _ = await asyncio.gather(
        db_client.get(f"{base}/agent/runs/{run['id']}/stream", headers=ada.headers), open_gate_soon()
    )
    body = response.text
    assert 'event: activity\ndata: {"text": "Reading roadmap.md"}' in body
    # The activity comes before the reply is written.
    assert body.index("event: activity") < body.index("phases")  # (the reply streams word by word)


async def test_stop_a_working_run(live, db_client: AsyncClient, add_member, signup) -> None:
    ada, team, base, model = await live()
    run = (await db_client.post(f"{base}/agent/runs", json={"message": "Plan the quarter"}, headers=ada.headers)).json()
    await asyncio.wait_for(model.started.wait(), 5)

    bob = await signup(email="bob@example.com", name="Bob")
    await add_member(team["id"], bob.id, Role.MEMBER)
    denied = await db_client.post(f"{base}/agent/runs/{run['id']}/stop", headers=bob.headers)
    assert denied.status_code == 403  # not his run, and not an owner or admin

    stopped = await db_client.post(f"{base}/agent/runs/{run['id']}/stop", headers=ada.headers)
    assert stopped.status_code == 200, stopped.text
    assert stopped.json()["status"] == "failed" and stopped.json()["error"] == "Stopped by Ada"
    again = await db_client.post(f"{base}/agent/runs/{run['id']}/stop", headers=ada.headers)
    assert again.status_code == 409

    audit = (await db_client.get(f"/v1/workspaces/{team['id']}/audit", headers=ada.headers)).json()
    stops = [e for e in audit if e["action"] == "agent_run.stopped"]
    assert [e["actor_user_id"] for e in stops] == [ada.id]

    # The conversation carries on.
    model.gate.set()
    follow_up = await db_client.post(
        f"{base}/agent/runs", json={"message": "Just the next sprint", "thread_id": run["thread_id"]}, headers=ada.headers
    )
    assert follow_up.status_code == 202


async def test_rename_a_conversation(db_client: AsyncClient, agent_script, signup, create_team) -> None:
    ada = await signup()
    team = await create_team(ada.headers)
    project = (
        await db_client.post(f"/v1/workspaces/{team['id']}/projects", json={"key": "KUN", "name": "K"}, headers=ada.headers)
    ).json()
    base = f"/v1/workspaces/{team['id']}/projects/{project['id']}"
    agent_script.say("Hi.", "Again.")
    first = (await db_client.post(f"{base}/agent/runs", json={"message": "hello there"}, headers=ada.headers)).json()
    await db_client.post(f"{base}/agent/runs", json={"message": "more", "thread_id": first["thread_id"]}, headers=ada.headers)

    renamed = await db_client.patch(f"{base}/agent/threads/{first['thread_id']}", json={"title": "  Kickoff notes "}, headers=ada.headers)
    assert renamed.status_code == 200
    assert renamed.json() == {"thread_id": first["thread_id"], "title": "Kickoff notes"}
    fetched = (await db_client.get(f"{base}/agent/runs/{first['id']}", headers=ada.headers)).json()
    assert fetched["title"] == "Kickoff notes"

    assert (await db_client.patch(f"{base}/agent/threads/{first['id']}", json={"title": "x"}, headers=ada.headers)).status_code == 404
    assert (await db_client.patch(f"{base}/agent/threads/{first['thread_id']}", json={"title": ""}, headers=ada.headers)).status_code == 422
