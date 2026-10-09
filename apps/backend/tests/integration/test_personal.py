"""What's each person's in a shared workspace (decided 2026-10-09): their conversations, their own
model keys and default model, their touches to the agents, and continuing a run that stopped at
its model's limit."""
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from cryptography.fernet import Fernet
from httpx import AsyncClient
from sqlalchemy import update

from pmagent_backend.core.crypto import Secrets
from pmagent_backend.modules.agents.models import AgentRun
from pmagent_backend.modules.workspaces.models import Role
from pmagent_engine.testing import ScriptedChatModel, tool_call

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
    agent_script.say(tool_call("write_file", file_path="/pmagent/roadmap.md", content="# R\n"), "Done.")
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


async def test_a_persons_own_key_and_default_model(world, db_client: AsyncClient, agent_script) -> None:
    ada, bob, ws, base = await world()
    await db_client.put(f"{ws}/model-keys/anthropic", json={"api_key": ANTHROPIC}, headers=ada.headers)

    # Bob's default model isn't his to choose on the team's key (members don't choose models).
    mine = await db_client.put("/v1/me/models", json={"default_model": "anthropic:claude-haiku-5-5"}, headers=bob.headers)
    assert mine.status_code == 200 and mine.json()["default_model"] == "anthropic:claude-haiku-5-5"
    assert (await db_client.put("/v1/me/models", json={"default_model": "acme:x"}, headers=bob.headers)).status_code == 422
    agent_script.say("On the team's key.")
    run = await _ask(db_client, base, bob.headers, "hi")
    assert agent_script.models_used[-1] == "anthropic:claude-sonnet-5" and agent_script.keys_used[-1]["anthropic"] == ANTHROPIC
    assert run["status"] == "completed"

    # With his own key, his runs use it, and his default model with it.
    saved = await db_client.put("/v1/me/model-keys/anthropic", json={"api_key": BOBS}, headers=bob.headers)
    assert saved.status_code == 200 and BOBS not in saved.text
    assert next(k for k in saved.json()["keys"] if k["provider"] == "anthropic")["last4"] == "BOB1"
    models = (await db_client.get(f"{ws}/models", headers=bob.headers)).json()
    assert {m["source"] for m in models if m["provider"] == "anthropic"} == {"personal"}
    agent_script.say("On Bob's key.")
    await _ask(db_client, base, bob.headers, "hi again")
    assert agent_script.models_used[-1] == "anthropic:claude-haiku-5-5" and agent_script.keys_used[-1]["anthropic"] == BOBS
    # Ada's runs still use the team's.
    agent_script.say("Ada.")
    await _ask(db_client, base, ada.headers, "hello")
    assert agent_script.keys_used[-1]["anthropic"] == ANTHROPIC

    # The organisation can turn personal keys off: then the team's key runs everything.
    off = await db_client.patch(ws, json={"personal_keys": False}, headers=ada.headers)
    assert off.status_code == 200 and off.json()["personal_keys"] is False
    assert (await db_client.patch(ws, json={"personal_keys": True}, headers=bob.headers)).status_code == 403
    agent_script.say("Team again.")
    await _ask(db_client, base, bob.headers, "and now")
    assert agent_script.keys_used[-1]["anthropic"] == ANTHROPIC and agent_script.models_used[-1] == "anthropic:claude-sonnet-5"

    assert (await db_client.delete("/v1/me/model-keys/anthropic", headers=bob.headers)).status_code == 200
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
    await db_client.put(f"{ws}/model-keys/anthropic", json={"api_key": ANTHROPIC}, headers=ada.headers)
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
