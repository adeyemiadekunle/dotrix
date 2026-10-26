"""What's each person's in a shared workspace (decided 2026-10-09): their conversations, their own
model keys and default model, their touches to the agents, and continuing a run that stopped at
its model's limit."""
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from cryptography.fernet import Fernet
from httpx import AsyncClient
from sqlalchemy import update

from dotrix_backend.core.crypto import Secrets
from dotrix_backend.modules.agents.models import AgentRun, RunStatus
from dotrix_backend.modules.workspaces.models import Role
from dotrix_engine.testing import ScriptedChatModel, tool_call

ANTHROPIC = "sk-ant-team-" + "t" * 30 + "TEAM"
BOBS = "sk-ant-bob-" + "b" * 30 + "BOB1"


class RateLimitError(Exception):
    status_code = 429


class RateLimited(ScriptedChatModel):
    def _generate(self, *args: Any, **kwargs: Any) -> Any:
        raise RateLimitError("429 rate_limit_error: too many tokens per minute. Please try again in 30s.")


@pytest.fixture
def world(db_client: AsyncClient, create_team, signup, add_member):
    """Ada owns an organisation with project KUN; Bob is a member."""

    async def _make():
        app = db_client._transport.app  # type: ignore[attr-defined]
        app.state.secrets = app.state.runner.secrets = Secrets(Fernet.generate_key().decode())
        ada = await signup()
        bob = await signup(email="bob@example.com", name="Bob")
        team = await create_team(ada.headers)
        await add_member(team["id"], bob.id, Role.MEMBER)
        ws = f"/v1/workspaces/{team['id']}"
        project = (await db_client.post(f"{ws}/projects", json={"key": "KUN", "name": "Kunemi"}, headers=ada.headers)).json()
        await db_client.patch(f"{ws}/projects/{project['id']}", json={"model": "anthropic:claude-sonnet-5"}, headers=ada.headers)
        return ada, bob, ws, f"{ws}/projects/{project['id']}"

    return _make


async def _ask(client: AsyncClient, base: str, headers, message: str, **extra) -> dict:
    res = await client.post(f"{base}/agent/runs", json={"message": message, **extra}, headers=headers)
    assert res.status_code == 202, res.text
    return res.json()


async def test_approval_queues_follow_conversation_privacy(
    world, db_client: AsyncClient, db_session, agent_script
) -> None:
    ada, bob, ws, base = await world()
    agent_script.say(tool_call("write_file", file_path="/dotrix/roadmap.md", content="Ada's private proposal"))
    private = await _ask(db_client, base, ada.headers, "Ada's private instruction")
    agent_script.say(tool_call("write_file", file_path="/dotrix/vision.md", content="Bob's proposal"))
    own = await _ask(db_client, base, bob.headers, "Bob's instruction")
    urls = [f"{base}/agent/approvals", f"{ws}/approvals"]
    private_id, own_id = private["approvals"][0]["id"], own["approvals"][0]["id"]

    for url in urls:
        response = await db_client.get(url, headers=bob.headers)
        assert response.status_code == 200, response.text
        assert [item["id"] for item in response.json()] == [own_id]
        assert "Ada's private" not in response.text
        # Owners can decide both pending runs, even when they did not request them.
        assert {item["id"] for item in (await db_client.get(url, headers=ada.headers)).json()} == {private_id, own_id}

    granted = await db_client.patch(ws, json={"member_permissions": ["agents:approve"]}, headers=ada.headers)
    assert granted.status_code == 200, granted.text
    for url in urls:
        assert {item["id"] for item in (await db_client.get(url, headers=bob.headers)).json()} == {private_id, own_id}

    # A stale pending approval must not extend an approver's access after the run stops waiting.
    await db_session.execute(update(AgentRun).where(AgentRun.id == uuid.UUID(private["id"])).values(status=RunStatus.COMPLETED))
    await db_session.commit()
    for url in urls:
        assert [item["id"] for item in (await db_client.get(url, headers=bob.headers)).json()] == [own_id]

    # Approval authority does not grant access to a restricted project.
    assert (await db_client.patch(base, json={"access": "restricted"}, headers=ada.headers)).status_code == 200
    assert (await db_client.get(urls[0], headers=bob.headers)).status_code == 404
    assert (await db_client.get(urls[1], headers=bob.headers)).json() == []


@pytest.mark.parametrize("run_status", [RunStatus.QUEUED, RunStatus.RUNNING])
@pytest.mark.parametrize("manager_role", [Role.OWNER, Role.ADMIN])
async def test_managers_can_stop_private_runs_without_reading_them(
    world, db_client: AsyncClient, db_session, agent_script, signup, add_member, monkeypatch,
    run_status: RunStatus, manager_role: Role,
) -> None:
    ada, bob, ws, base = await world()
    manager = ada
    if manager_role is Role.ADMIN:
        manager = await signup(email="admin@example.com", name="Admin")
        await add_member(ws.rsplit("/", 1)[-1], manager.id, Role.ADMIN)
    agent_script.say("Bob's private reply")
    run = await _ask(db_client, base, bob.headers, "Bob's private instruction")
    await db_session.execute(update(AgentRun).where(AgentRun.id == uuid.UUID(run["id"])).values(status=run_status))
    await db_session.commit()

    async def no_worker(run_id, reason):
        return False  # the service also handles a queued run or a worker that has already stopped

    monkeypatch.setattr(db_client._transport.app.state.runner, "stop", no_worker)  # type: ignore[attr-defined]
    run_url = f"{base}/agent/runs/{run['id']}"
    assert (await db_client.get(run_url, headers=manager.headers)).status_code == 404
    response = await db_client.post(f"{run_url}/stop", headers=manager.headers)
    assert response.status_code == 200, response.text
    assert response.json() == {"id": run["id"], "status": "failed"}
    assert (await db_client.get(run_url, headers=manager.headers)).status_code == 404
    own = (await db_client.get(run_url, headers=bob.headers)).json()
    assert own["message"] == "Bob's private instruction" and own["reply"] == "Bob's private reply"
    assert own["error"] == f"Stopped by {manager.user['display_name']}"


async def test_conversations_are_private_to_whoever_started_them(world, db_client: AsyncClient, agent_script) -> None:
    ada, bob, ws, base = await world()
    agent_script.say("Bob's answer.")
    bobs = await _ask(db_client, base, bob.headers, "What should I pick up next?")
    assert bobs["status"] == "completed"

    # Ada, an owner, doesn't see Bob's conversation anywhere.
    assert (await db_client.get(f"{base}/agent/runs/{bobs['id']}", headers=ada.headers)).status_code == 404
    assert (await db_client.get(f"{base}/agent/runs", headers=ada.headers)).json() == []
    assert (await db_client.get(f"{ws}/threads", headers=ada.headers)).json() == []
    feed = (await db_client.get(f"{base}/activity", headers=ada.headers)).json()
    assert bobs["id"] not in str(feed)
    assert (await db_client.patch(f"{base}/agent/threads/{bobs['thread_id']}", json={"title": "Mine"},
                                  headers=ada.headers)).status_code == 404
    # Nor can she continue it.
    agent_script.say("x")
    hijack = await db_client.post(f"{base}/agent/runs", json={"message": "and?", "thread_id": bobs["thread_id"]},
                                  headers=ada.headers)
    assert hijack.status_code == 404

    # A change Bob asks for waits for Ada: she opens the run while it waits, and decides it.
    agent_script.say(tool_call("write_file", file_path="/dotrix/roadmap.md", content="# R\n"), "Done.")
    paused = await _ask(db_client, base, bob.headers, "Write the roadmap")
    assert paused["status"] == "awaiting_approval"
    seen = await db_client.get(f"{base}/agent/runs/{paused['id']}", headers=ada.headers)
    assert seen.status_code == 200 and seen.json()["approvals"][0]["tool"] == "write_file"
    decided = await db_client.post(f"{base}/agent/runs/{paused['id']}/decisions", headers=ada.headers,
                                   json={"decisions": [{"approval_id": paused["approvals"][0]["id"], "decision": "approve"}]})
    assert decided.status_code == 200 and decided.json()["status"] == "completed"
    # Decided, it's Bob's again.
    assert (await db_client.get(f"{base}/agent/runs/{paused['id']}", headers=ada.headers)).status_code == 404
    assert {r["id"] for r in (await db_client.get(f"{base}/agent/runs", headers=bob.headers)).json()} == {bobs["id"], paused["id"]}


async def test_a_persons_key_and_default_are_independent_in_every_workspace(world, db_client: AsyncClient, agent_script) -> None:
    ada, bob, ws, base = await world()
    assert (await db_client.put("/v1/me/model-keys/anthropic", json={"api_key": ANTHROPIC}, headers=ada.headers)).status_code == 200
    mine = await db_client.put("/v1/me/models", json={"default_model": "anthropic:claude-haiku-5-5"}, headers=bob.headers)
    assert mine.status_code == 200 and mine.json()["default_model"] == "anthropic:claude-haiku-5-5"
    assert (await db_client.get(f"{ws}/models", headers=bob.headers)).json() == []
    saved = await db_client.put("/v1/me/model-keys/anthropic", json={"api_key": BOBS}, headers=bob.headers)
    assert saved.status_code == 200 and BOBS not in saved.text
    assert next(k for k in saved.json()["keys"] if k["provider"] == "anthropic")["last4"] == "BOB1"
    models = (await db_client.get(f"{ws}/models", headers=bob.headers)).json()
    assert models and all(m["source"] == "personal" for m in models)
    agent_script.say("On Bob's key.")
    await _ask(db_client, base, bob.headers, "hi again")
    assert agent_script.models_used[-1] == "anthropic:claude-haiku-5-5" and agent_script.keys_used[-1]["anthropic"] == BOBS
    agent_script.say("Ada.")
    await _ask(db_client, base, ada.headers, "hello")
    assert agent_script.keys_used[-1]["anthropic"] == ANTHROPIC
    assert (await db_client.delete("/v1/me/model-keys/anthropic", headers=bob.headers)).status_code == 200
    assert (await db_client.get(f"{ws}/models", headers=bob.headers)).json() == []
    assert (await db_client.delete("/v1/me/model-keys/anthropic", headers=bob.headers)).status_code == 404


async def test_people_touch_up_agents_for_themselves_within_limits(world, db_client: AsyncClient, agent_script) -> None:
    ada, bob, ws, base = await world()
    url = f"{ws}/my-agents"
    saved = await db_client.put(f"{url}/product", json={"instructions": "Write stories in British English, short."},
                                headers=bob.headers)
    assert saved.status_code == 200 and saved.json()["handle"] == "product"
    # A model needs the workspace's say-so unless his own key runs it.
    no = await db_client.put(f"{url}/product", json={"instructions": "x", "model": "anthropic:claude-haiku-5-5"},
                             headers=bob.headers)
    assert no.status_code in (403, 422)
    assert (await db_client.put(f"{url}/nobody", json={"instructions": "x"}, headers=bob.headers)).status_code == 404
    long = await db_client.put(f"{url}/product", json={"instructions": "x" * 2001}, headers=bob.headers)
    assert long.status_code == 422

    # His runs with Lyra carry them; the contract itself is unchanged, and Ada's runs don't.
    model = agent_script.say("Stories.")
    await _ask(db_client, base, bob.headers, "stories please", agent="product")
    prompt = str(model.received[0][0].content)
    assert "How Bob likes you to work" in prompt and "British English" in prompt
    model = agent_script.say("Stories.")
    await _ask(db_client, base, ada.headers, "stories please", agent="product")
    assert "British English" not in str(model.received[0][0].content)
    assert (await db_client.get(f"{ws}/agents/product", headers=ada.headers)).json()["source"] == "built_in"

    # They're his alone.
    assert [p["handle"] for p in (await db_client.get(url, headers=bob.headers)).json()] == ["product"]
    assert (await db_client.get(url, headers=ada.headers)).json() == []
    assert (await db_client.delete(f"{url}/product", headers=bob.headers)).status_code == 204


async def test_a_run_stopped_at_its_limit_continues_now_or_when_it_resets(
    world, db_client: AsyncClient, agent_script, db_session
) -> None:
    ada, _, ws, base = await world()
    await db_client.put("/v1/me/model-keys/anthropic", json={"api_key": ANTHROPIC}, headers=ada.headers)
    agent_script.model = RateLimited.of("never")
    stopped = await _ask(db_client, base, ada.headers, "Summarise the project")
    assert stopped["status"] == "failed" and stopped["error_kind"] == "model_limit"
    resumes = datetime.fromisoformat(stopped["resumes_at"])
    assert timedelta(seconds=20) < resumes - datetime.now(UTC) <= timedelta(seconds=31)
    notes = (await db_client.get(f"{ws}/notifications", headers=ada.headers)).json()
    limit = next(n for n in notes if n["kind"] == "limit")
    assert limit["run_id"] == stopped["id"] and "Anthropic" in limit["excerpt"]

    # Continue now: it picks up from where it stopped.
    url = f"{base}/agent/runs/{stopped['id']}/continue"
    agent_script.say("Here's the summary.")
    went_on = await db_client.post(url, json={}, headers=ada.headers)
    assert went_on.status_code == 200, went_on.text
    assert went_on.json()["status"] == "completed" and went_on.json()["reply"] == "Here's the summary."
    assert (await db_client.post(url, json={}, headers=ada.headers)).status_code == 409

    # Or once the limit resets, by itself.
    agent_script.model = RateLimited.of("never")
    again = await _ask(db_client, base, ada.headers, "And the risks?")
    later = await db_client.post(f"{base}/agent/runs/{again['id']}/continue", json={"when_reset": True}, headers=ada.headers)
    assert later.json()["status"] == "failed" and later.json()["continue_at_reset"] is True
    await db_session.execute(update(AgentRun).where(AgentRun.id == again["id"]).values(
        resumes_at=datetime.now(UTC) - timedelta(seconds=1)))
    await db_session.commit()
    agent_script.say("Two risks.")
    await db_client._transport.app.state.jobs.enqueue("run_automations")  # type: ignore[attr-defined]
    done = (await db_client.get(f"{base}/agent/runs/{again['id']}", headers=ada.headers)).json()
    assert done["status"] == "completed" and done["reply"] == "Two risks."
