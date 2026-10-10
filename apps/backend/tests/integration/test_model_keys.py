"""Organisations' own model provider keys: stored encrypted, used for their runs, and a provider
refusing for its limits shown on the key (Settings → Models)."""
from typing import Any

import pytest
from cryptography.fernet import Fernet
from httpx import AsyncClient
from sqlalchemy import select

from dotrix_backend.core.crypto import Secrets
from dotrix_backend.modules.agents.llm import available_models, key_for, limit_error
from dotrix_backend.modules.model_keys.models import WorkspaceModelKey
from dotrix_backend.modules.workspaces.models import Role
from dotrix_engine.testing import ScriptedChatModel

KEY = "sk-ant-test-" + "x" * 30 + "WXYZ"


class RateLimitError(Exception):
    """What a provider's SDK raises at its rate limit (HTTP 429)."""

    status_code = 429


class RateLimited(ScriptedChatModel):
    def _generate(self, *args: Any, **kwargs: Any) -> Any:
        raise RateLimitError("Error code: 429 - rate_limit_error: Number of request tokens has exceeded your per-minute rate limit")


@pytest.fixture
def world(db_client: AsyncClient, create_team, signup, add_member):
    async def _make(secure: bool = True):
        app = db_client._transport.app  # type: ignore[attr-defined]
        if secure:
            app.state.secrets = app.state.runner.secrets = Secrets(Fernet.generate_key().decode())
        ada = await signup()
        cat = await signup(email="cat@example.com", name="Cat")
        team = await create_team(ada.headers)
        await add_member(team["id"], cat.id, Role.MEMBER)
        ws = f"/v1/workspaces/{team['id']}"
        project = (await db_client.post(f"{ws}/projects", json={"key": "KUN", "name": "K"}, headers=ada.headers)).json()
        return app, ada, cat, ws, f"{ws}/projects/{project['id']}"

    return _make


async def test_connect_a_key_it_is_encrypted_and_runs_use_it(world, db_client: AsyncClient, agent_script, db_session) -> None:
    _, ada, cat, ws, base = await world()
    assert (await db_client.put(f"{ws}/model-keys/anthropic", json={"api_key": KEY}, headers=cat.headers)).status_code == 403
    saved = await db_client.put(f"{ws}/model-keys/anthropic", json={"api_key": KEY}, headers=ada.headers)
    assert saved.status_code == 200, saved.text
    assert saved.json()["connected"] and saved.json()["last4"] == "WXYZ" and KEY not in saved.text
    row = await db_session.scalar(select(WorkspaceModelKey))
    assert row is not None and KEY not in row.encrypted

    listed = {k["provider"]: k for k in (await db_client.get(f"{ws}/model-keys", headers=ada.headers)).json()}
    assert set(listed) == {"anthropic", "openai", "google_genai"}
    assert listed["anthropic"]["label"] == "Anthropic" and not listed["openai"]["connected"]
    assert "anthropic:claude-haiku-5-5" in listed["anthropic"]["models"]

    agent_script.say("Hello.")
    run = (await db_client.post(f"{base}/agent/runs", json={"message": "hi"}, headers=ada.headers)).json()
    assert run["status"] == "completed"
    assert agent_script.keys_used[-1] == {"anthropic": KEY}

    audit = [e for e in (await db_client.get(f"{ws}/audit", headers=ada.headers)).json() if e["action"].startswith("model_key.")]
    assert audit[0]["action"] == "model_key.saved" and audit[0]["details"] == {"provider": "anthropic", "last4": "WXYZ"}
    assert KEY not in str(audit)

    assert (await db_client.delete(f"{ws}/model-keys/anthropic", headers=ada.headers)).status_code == 204
    assert (await db_client.delete(f"{ws}/model-keys/anthropic", headers=ada.headers)).status_code == 404
    assert (await db_client.put(f"{ws}/model-keys/mistral", json={"api_key": KEY}, headers=ada.headers)).status_code == 404


async def test_without_an_encryption_key_the_server_says_so(world, db_client: AsyncClient) -> None:
    _, ada, _, ws, _ = await world(secure=False)
    refused = await db_client.put(f"{ws}/model-keys/openai", json={"api_key": KEY}, headers=ada.headers)
    assert refused.status_code == 503 and refused.json()["type"].endswith("/encryption_not_configured")


async def test_a_limit_reached_is_shown_on_the_key_and_cleared_by_the_next_run(
    world, db_client: AsyncClient, agent_script
) -> None:
    _, ada, _, ws, base = await world()
    await db_client.patch(base, json={"model": "anthropic:claude-sonnet-5"}, headers=ada.headers)
    await db_client.put(f"{ws}/model-keys/anthropic", json={"api_key": KEY}, headers=ada.headers)
    agent_script.model = RateLimited.of("never")
    failed = (await db_client.post(f"{base}/agent/runs", json={"message": "hi"}, headers=ada.headers)).json()
    assert failed["status"] == "failed"
    assert failed["error"].startswith("Stopped: Anthropic refused this run") and "per-minute rate limit" in failed["error"]
    key = next(k for k in (await db_client.get(f"{ws}/model-keys", headers=ada.headers)).json() if k["provider"] == "anthropic")
    assert key["limit_reached_at"] and "rate limit" in key["limit_message"]

    agent_script.say("Back again.")
    assert (await db_client.post(f"{base}/agent/runs", json={"message": "hi"}, headers=ada.headers)).json()["status"] == "completed"
    key = next(k for k in (await db_client.get(f"{ws}/model-keys", headers=ada.headers)).json() if k["provider"] == "anthropic")
    assert key["limit_reached_at"] is None


async def test_models_offered_follow_the_workspace_s_keys(world, db_client: AsyncClient) -> None:
    app, ada, _, ws, _ = await world()
    app.state.settings.server_model_keys = False  # a hosted service: everyone brings their own
    try:
        assert not [m for m in (await db_client.get(f"{ws}/models", headers=ada.headers)).json() if not m["id"].startswith("e2e:")]
        await db_client.put(f"{ws}/model-keys/openai", json={"api_key": "sk-proj-" + "y" * 30}, headers=ada.headers)
        models = (await db_client.get(f"{ws}/models", headers=ada.headers)).json()
        assert {m["id"] for m in models} >= {"openai:gpt-5.5", "openai:gpt-5.5-mini"}
        assert all(m["provider"] == "openai" and m["source"] == "workspace" for m in models if not m["id"].startswith("e2e:"))
    finally:
        app.state.settings.server_model_keys = True


async def test_automations_have_no_daily_cap_unless_one_is_set(world, db_client: AsyncClient, agent_script) -> None:
    _, ada, _, _, base = await world()
    made = (await db_client.post(f"{base}/automations", json={
        "name": "Summary", "instructions": "Summarise.", "schedule_hour": 6,
    }, headers=ada.headers)).json()
    assert made["max_runs_per_day"] is None
    url = f"{base}/automations/{made['id']}"
    agent_script.say(*[f"Summary {i}." for i in range(8)])
    for _ in range(7):
        ran = (await db_client.post(f"{url}/run", headers=ada.headers)).json()
    assert ran["runs_today"] == 7 and ran["last_error"] is None
    capped = (await db_client.patch(url, json={"max_runs_per_day": 7}, headers=ada.headers)).json()
    assert capped["max_runs_per_day"] == 7
    assert "limit of 7 runs today" in (await db_client.post(f"{url}/run", headers=ada.headers)).json()["last_error"]
    assert (await db_client.patch(url, json={"max_runs_per_day": None}, headers=ada.headers)).json()["max_runs_per_day"] is None


async def test_which_key_a_model_runs_with(db_client: AsyncClient) -> None:
    settings = db_client._transport.app.state.settings.model_copy(update={"server_model_keys": True})  # type: ignore[attr-defined]
    own = {"anthropic": "mine"}
    assert key_for(settings, "anthropic:claude-sonnet-5", own) == "mine"
    hosted = settings.model_copy(update={"server_model_keys": False})
    assert key_for(hosted, "openai:gpt-5.5", own) is None
    assert available_models(hosted, connected={"anthropic"}) == [
        m for m in dict.fromkeys([*hosted.models, hosted.default_model]) if m.startswith("anthropic:")
    ]


def test_limit_errors_are_told_apart() -> None:
    assert limit_error(RateLimitError("slow down")) == "slow down"
    assert "credit balance" in (limit_error(ValueError("Your credit balance is too low to access the API")) or "")
    try:
        try:
            raise RuntimeError("429 RESOURCE_EXHAUSTED: quota exceeded")
        except RuntimeError as inner:
            raise ValueError("model call failed") from inner
    except ValueError as outer:
        assert "RESOURCE_EXHAUSTED" in (limit_error(outer) or "")
    assert limit_error(ValueError("bad request: missing field")) is None
