"""Chat with Nova, ask for specialists, and keep the model fixed per conversation."""
import pytest
from cryptography.fernet import Fernet
from httpx import AsyncClient
from pydantic import SecretStr

from dotrix_backend.core.crypto import Secrets
from dotrix_backend.modules.workspaces.models import Role
from dotrix_engine.testing import tool_call

GEMINI = "google_genai:gemini-3.8-flash"
CLAUDE = "anthropic:claude-sonnet-5"  # the tests' default model (make_settings)


@pytest.fixture
def connected(db_client: AsyncClient):
    """Connect an individual user's provider; legacy server credentials must have no effect."""
    app = db_client._transport.app  # type: ignore[attr-defined]
    app.state.settings = app.state.settings.model_copy(
        update={
            "models": [GEMINI, "openai:gpt-test", CLAUDE],
            "google_api_key": SecretStr("test-key"),
            "openai_api_key": None,
            "anthropic_api_key": None,
        }
    )
    app.state.secrets = app.state.runner.secrets = Secrets(Fernet.generate_key().decode())

    async def connect(person, provider: str = "google_genai") -> str:
        key = f"personal-test-provider-key-{person.id}"
        response = await db_client.put(f"/v1/me/model-keys/{provider}", json={"api_key": key}, headers=person.headers)
        assert response.status_code == 200, response.text
        return key

    return connect


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


async def test_a_specialist_mention_keeps_nova_as_coordinator(project, db_client: AsyncClient, agent_script) -> None:
    ada, team, base = await project()
    model = agent_script.say("Three competitors ship multi-zone already.")
    done = (await send(db_client, base, ada.headers, "Who else does multi-zone?", agent="research")).json()
    assert done["status"] == "completed" and done["agent"] == "auto"
    assert done["reply"] == "Three competitors ship multi-zone already."
    system = str(model.received[0][0].content)
    assert "You are Nova" in system and "You're in the project's chat" in system
    assert "involve research" in str(model.received[0][-1].content)
    assert [a["agent"] for a in done["breakdown"]["by_agent"]] == ["project-manager"]
    events = (await db_client.get(f"/v1/workspaces/{team['id']}/audit", headers=ada.headers)).json()
    assert next(e for e in events if e["action"] == "agent_run.completed")["agent"] == "project-manager"
    # Auto is the Project Manager, as before.
    agent_script.say("On track.")
    auto = (await send(db_client, base, ada.headers, "Status?")).json()
    assert auto["agent"] == "auto"


async def test_a_specialists_writes_are_its_own(project, db_client: AsyncClient, agent_script) -> None:
    ada, _, base = await project()
    agent_script.say(
        tool_call("delegate_tasks", tasks=[{"key": "zones", "agent": "product", "brief": "Write up zones",
                                          "expected_result": "Requirements", "changes_project": True}]),
        tool_call("write_file", file_path="/dotrix/requirements/zones.md", content="# Zones\n"),
        "Drafted the zones requirements.",
        "Product drafted the requirements.",
    )
    paused = (await send(db_client, base, ada.headers, "Write up zones", agent="product")).json()
    assert paused["status"] == "waiting_children"
    tasks = (await db_client.get(f"{base}/agent/runs/{paused['id']}/tasks", headers=ada.headers)).json()
    child = (await db_client.get(f"{base}/agent/runs/{tasks[0]['id']}", headers=ada.headers)).json()
    pending = child["approvals"][0]
    decided = await db_client.post(
        f"{base}/agent/runs/{child['id']}/decisions",
        json={"decisions": [{"approval_id": pending["id"], "decision": "approve"}]},
        headers=ada.headers,
    )
    assert decided.json()["status"] == "completed"
    versions = (await db_client.get(f"{base}/knowledge/files/requirements/zones.md/versions", headers=ada.headers)).json()
    assert versions[0]["agent"] == "product" and versions[0]["approved_by_id"] == ada.id


async def test_a_specialist_stays_in_its_folders(project, db_client: AsyncClient, agent_script) -> None:
    ada, _, base = await project()
    agent_script.say(
        tool_call("delegate_tasks", tasks=[{"key": "architecture", "agent": "research", "brief": "Change the architecture",
                                          "expected_result": "Report", "changes_project": True}]),
        tool_call("write_file", file_path="/dotrix/architecture/overview.md", content="# Changed"),
        "Couldn't change architecture.",
        "Research could not change architecture.",
    )
    paused = (await send(db_client, base, ada.headers, "Change the architecture", agent="research")).json()
    tasks = (await db_client.get(f"{base}/agent/runs/{paused['id']}/tasks", headers=ada.headers)).json()
    child = (await db_client.get(f"{base}/agent/runs/{tasks[0]['id']}", headers=ada.headers)).json()
    done = (
        await db_client.post(
            f"{base}/agent/runs/{child['id']}/decisions",
            json={"decisions": [{"approval_id": child["approvals"][0]["id"], "decision": "approve"}]},
            headers=ada.headers,
        )
    ).json()
    assert done["status"] == "completed"
    overview = (await db_client.get(f"{base}/knowledge/files/architecture/overview.md", headers=ada.headers)).json()
    assert overview["content"] != "# Changed"  # research doesn't own architecture/, approved or not


async def test_a_conversation_keeps_its_model(project, db_client: AsyncClient, agent_script, connected) -> None:
    ada, _, base = await project()
    await connected(ada)
    await connected(ada, "anthropic")
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


async def test_delegated_specialists_use_their_model_override_or_project_default(
    project, db_client: AsyncClient, agent_script, connected
) -> None:
    from dotrix_backend.modules.agent_definitions.schemas import AgentFields

    ada, _, base = await project()
    await connected(ada, "google_genai")
    await connected(ada, "anthropic")
    configured = await db_client.patch(base, json={"specialist_model": GEMINI}, headers=ada.headers)
    assert configured.status_code == 200, configured.text
    research = (await db_client.get(f"{base}/agents/research", headers=ada.headers)).json()
    fields = {key: research[key] for key in AgentFields.model_fields if key in research}
    fields["model"] = CLAUDE
    saved = await db_client.put(f"{base}/agents/research", json={"agent": fields}, headers=ada.headers)
    assert saved.status_code == 200, saved.text

    agent_script.say(
        tool_call("delegate_tasks", tasks=[
            {"key": "product", "agent": "product", "brief": "Summarise the requirements", "expected_result": "Summary"},
            {"key": "research", "agent": "research", "brief": "Review the requirements", "expected_result": "Evidence",
             "depends_on": ["product"]},
        ]),
        tool_call("submit_specialist_result", summary="Requirements"), "Product done.",
        tool_call("submit_specialist_result", summary="Review evidence"), "Research done.",
        "The team completed the review.",
    )
    response = await send(db_client, base, ada.headers, "Review the requirements")
    assert response.status_code == 202, response.text
    parent = response.json()
    assert parent["status"] == "completed"
    tasks = (await db_client.get(f"{base}/agent/runs/{parent['id']}/tasks", headers=ada.headers)).json()
    children = [(await db_client.get(f"{base}/agent/runs/{task['id']}", headers=ada.headers)).json() for task in tasks]
    child_models = {child["agent"]: child["model"] for child in children}
    assert parent["model"] == CLAUDE
    assert child_models == {"product": GEMINI, "research": CLAUDE}
    assert GEMINI in agent_script.models_used and CLAUDE in agent_script.models_used


async def test_who_may_choose_a_model(project, db_client: AsyncClient, agent_script, connected, signup, add_member) -> None:
    ada, team, base = await project()
    await connected(ada)
    bob = await signup(email="bob@example.com", name="Bob")
    await add_member(team["id"], bob.id, Role.MEMBER)
    await connected(bob, "anthropic")
    agent_script.say("ok", "ok", "ok")
    assert (await send(db_client, base, bob.headers, "hi")).status_code == 202  # the project's model: anyone
    assert (await send(db_client, base, bob.headers, "hi", model=CLAUDE)).status_code == 202  # same thing
    assert (await send(db_client, base, bob.headers, "hi", model=GEMINI)).status_code == 403
    ws = f"/v1/workspaces/{team['id']}"
    res = await db_client.patch(ws, json={"member_permissions": ["agents:choose_model"]}, headers=ada.headers)
    assert res.status_code == 200
    assert (await send(db_client, base, bob.headers, "hi", model=GEMINI)).status_code == 422
    # A role grant cannot borrow Ada's key. With his own key Bob can choose its model.
    own = await connected(bob)
    await db_client.patch(ws, json={"member_permissions": []}, headers=ada.headers)
    assert (await send(db_client, base, bob.headers, "hi", model=GEMINI)).status_code == 202
    assert agent_script.keys_used[-1]["google_genai"] == own
    # Only models that can run here.
    unavailable = await send(db_client, base, ada.headers, "hi", model="openai:gpt-test")
    assert unavailable.status_code == 422 and unavailable.json()["type"].endswith("/model_not_available")


async def test_the_models_that_can_run(db_client: AsyncClient, create_team, signup, connected) -> None:
    ada = await signup()
    await connected(ada)
    team = await create_team(ada.headers)
    models = (await db_client.get(f"/v1/workspaces/{team['id']}/models", headers=ada.headers)).json()
    assert [m["id"] for m in models] == [GEMINI]  # OpenAI and Anthropic have no key here
    assert models[0] == {"id": GEMINI, "provider": "google_genai", "name": "gemini-3.8-flash", "source": "personal"}
    outsider = await signup(email="eve@example.com", name="Eve")
    assert (await db_client.get(f"/v1/workspaces/{team['id']}/models", headers=outsider.headers)).status_code == 404


async def test_unknown_agents_are_refused(project, db_client: AsyncClient, agent_script) -> None:
    ada, _, base = await project()
    agent_script.say("ok")
    assert (await send(db_client, base, ada.headers, "hi", agent="marketing")).status_code == 422
