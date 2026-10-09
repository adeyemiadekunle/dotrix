"""Chat with the team: pick who answers (Auto or one specialist), and the model per conversation."""
import pytest
from httpx import AsyncClient
from pydantic import SecretStr

from pmagent_backend.modules.workspaces.models import Role
from pmagent_engine.testing import tool_call

GEMINI = "google_genai:gemini-3.8-flash"
CLAUDE = "anthropic:claude-sonnet-5"  # the tests' default model (make_settings)


@pytest.fixture
def connected(db_client: AsyncClient):
    """Providers with a key, as far as the model list is concerned: Google here (Anthropic is
    the project's model, always allowed)."""
    app = db_client._transport.app  # type: ignore[attr-defined]
    app.state.settings = app.state.settings.model_copy(
        update={
            "models": [GEMINI, "openai:gpt-test", CLAUDE],
            "google_api_key": SecretStr("test-key"),
            "openai_api_key": None,
            "anthropic_api_key": None,
        }
    )


@pytest.fixture
def project(db_client: AsyncClient, create_team, signup):
    async def _make():
        ada = await signup()
        team = await create_team(ada.headers)
        created = (
            await db_client.post(
                f"/v1/workspaces/{team['id']}/projects", json={"key": "KUN", "name": "Kunemi"}, headers=ada.headers
            )
        ).json()
        return ada, team, f"/v1/workspaces/{team['id']}/projects/{created['id']}"

    return _make


async def send(client: AsyncClient, base: str, headers, message: str = "hello", **extra):
    return await client.post(f"{base}/agent/runs", json={"message": message, **extra}, headers=headers)


async def test_a_specialist_answers_directly(project, db_client: AsyncClient, agent_script) -> None:
    ada, team, base = await project()
    model = agent_script.say("Three competitors ship multi-zone already.")
    done = (await send(db_client, base, ada.headers, "Who else does multi-zone?", agent="research")).json()
    assert done["status"] == "completed" and done["agent"] == "research"
    assert done["reply"] == "Three competitors ship multi-zone already."
    system = str(model.received[0][0].content)
    assert "You are Vega, the research agent" in system and "You're in the project's chat" in system
    assert [a["agent"] for a in done["breakdown"]["by_agent"]] == ["research"]  # no PM hop
    events = (await db_client.get(f"/v1/workspaces/{team['id']}/audit", headers=ada.headers)).json()
    assert next(e for e in events if e["action"] == "agent_run.completed")["agent"] == "research"
    # Auto is the Project Manager, as before.
    agent_script.say("On track.")
    auto = (await send(db_client, base, ada.headers, "Status?")).json()
    assert auto["agent"] == "auto"


async def test_a_specialists_writes_are_its_own(project, db_client: AsyncClient, agent_script) -> None:
    ada, _, base = await project()
    agent_script.say(
        tool_call("write_file", file_path="/pmagent/requirements/zones.md", content="# Zones\n"),
        "Drafted the zones requirements.",
    )
    paused = (await send(db_client, base, ada.headers, "Write up zones", agent="product")).json()
    assert paused["status"] == "awaiting_approval"
    pending = paused["approvals"][0]
    decided = await db_client.post(
        f"{base}/agent/runs/{paused['id']}/decisions",
        json={"decisions": [{"approval_id": pending["id"], "decision": "approve"}]},
        headers=ada.headers,
    )
    assert decided.json()["status"] == "completed"
    versions = (await db_client.get(f"{base}/knowledge/files/requirements/zones.md/versions", headers=ada.headers)).json()
    assert versions[0]["agent"] == "product" and versions[0]["approved_by_id"] == ada.id


async def test_a_specialist_stays_in_its_folders(project, db_client: AsyncClient, agent_script) -> None:
    ada, _, base = await project()
    agent_script.say(
        tool_call("write_file", file_path="/pmagent/architecture/overview.md", content="# Changed"),
        "Couldn't change architecture.",
    )
    paused = (await send(db_client, base, ada.headers, "Change the architecture", agent="research")).json()
    done = (
        await db_client.post(
            f"{base}/agent/runs/{paused['id']}/decisions",
            json={"decisions": [{"approval_id": paused["approvals"][0]["id"], "decision": "approve"}]},
            headers=ada.headers,
        )
    ).json()
    assert done["status"] == "completed"
    overview = (await db_client.get(f"{base}/knowledge/files/architecture/overview.md", headers=ada.headers)).json()
    assert overview["content"] != "# Changed"  # research doesn't own architecture/, approved or not


async def test_a_conversation_keeps_its_model(project, db_client: AsyncClient, agent_script, connected) -> None:
    ada, _, base = await project()
    agent_script.say("First.", "Second.", "Third.")
    first = (await send(db_client, base, ada.headers, "one", model=GEMINI)).json()
    assert first["conversation_model"] == GEMINI and first["model"] == GEMINI
    second = (await send(db_client, base, ada.headers, "two", thread_id=first["thread_id"])).json()
    assert second["conversation_model"] == GEMINI and second["model"] == GEMINI
    assert agent_script.models_used[-1] == GEMINI  # the run itself used it
    # The same model again is fine; another one is refused.
    assert (await send(db_client, base, ada.headers, "3", thread_id=first["thread_id"], model=GEMINI)).status_code == 202
    locked = await send(db_client, base, ada.headers, "four", thread_id=first["thread_id"], model=CLAUDE)
    assert locked.status_code == 409 and locked.json()["type"].endswith("/model_locked")
    # A new conversation without a model gets the project's, fixed from the start.
    agent_script.say("Default.")
    plain = (await send(db_client, base, ada.headers, "new")).json()
    assert plain["conversation_model"] == CLAUDE


async def test_who_may_choose_a_model(project, db_client: AsyncClient, agent_script, connected, signup, add_member) -> None:
    ada, team, base = await project()
    bob = await signup(email="bob@example.com", name="Bob")
    await add_member(team["id"], bob.id, Role.MEMBER)
    agent_script.say("ok", "ok", "ok")
    assert (await send(db_client, base, bob.headers, "hi")).status_code == 202  # the project's model: anyone
    assert (await send(db_client, base, bob.headers, "hi", model=CLAUDE)).status_code == 202  # same thing
    assert (await send(db_client, base, bob.headers, "hi", model=GEMINI)).status_code == 403
    ws = f"/v1/workspaces/{team['id']}"
    res = await db_client.patch(ws, json={"member_permissions": ["agents:choose_model"]}, headers=ada.headers)
    assert res.status_code == 200
    assert (await send(db_client, base, bob.headers, "hi", model=GEMINI)).status_code == 202
    # Only models that can run here.
    unavailable = await send(db_client, base, ada.headers, "hi", model="openai:gpt-test")
    assert unavailable.status_code == 422 and unavailable.json()["type"].endswith("/model_not_available")


async def test_the_models_that_can_run(db_client: AsyncClient, create_team, signup, connected) -> None:
    ada = await signup()
    team = await create_team(ada.headers)
    models = (await db_client.get(f"/v1/workspaces/{team['id']}/models", headers=ada.headers)).json()
    assert [m["id"] for m in models] == [GEMINI]  # OpenAI and Anthropic have no key here
    assert models[0] == {"id": GEMINI, "provider": "google_genai", "name": "gemini-3.8-flash"}
    outsider = await signup(email="eve@example.com", name="Eve")
    assert (await db_client.get(f"/v1/workspaces/{team['id']}/models", headers=outsider.headers)).status_code == 404


async def test_unknown_agents_are_refused(project, db_client: AsyncClient, agent_script) -> None:
    ada, _, base = await project()
    agent_script.say("ok")
    assert (await send(db_client, base, ada.headers, "hi", agent="marketing")).status_code == 422
