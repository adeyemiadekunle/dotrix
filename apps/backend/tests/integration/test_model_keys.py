"""Organisations' own model provider keys: stored encrypted, used for their runs, and a provider
refusing for its limits shown on the key (Settings → Models)."""
import uuid
from typing import Any

import pytest
from cryptography.fernet import Fernet
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy import select

from dotrix_backend.core.crypto import Secrets
from dotrix_backend.modules.agents.llm import PROVIDERS, available_models, key_for, limit_error
from dotrix_backend.modules.model_keys.models import UserModelKey, WorkspaceModelKey
from dotrix_backend.modules.model_keys.service import run_keys
from dotrix_backend.modules.workspaces.models import Role, Workspace
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


async def test_readiness_is_personal_readable_and_workspace_scoped(world, db_client, signup) -> None:
    app, ada, cat, ws, _ = await world()
    path = f"{ws}/model-access"
    assert not (await db_client.get(path, headers=cat.headers)).json()["ready"]
    outsider = await signup(email="outside@example.com")
    assert (await db_client.get(path, headers=outsider.headers)).status_code == 404
    await db_client.put("/v1/me/model-keys/xai", json={"api_key": KEY}, headers=cat.headers)
    own = await db_client.get(path, headers=cat.headers)
    assert own.json()["ready"] and own.json()["providers"] == ["xai"]
    assert KEY not in own.text and "WXYZ" not in own.text
    assert not (await db_client.get(path, headers=ada.headers)).json()["ready"]
    app.state.secrets = app.state.runner.secrets = Secrets(Fernet.generate_key().decode())
    assert not (await db_client.get(path, headers=cat.headers)).json()["ready"]


async def test_shared_endpoints_and_server_credentials_cannot_unlock_a_user(world, db_client, db_session) -> None:
    app, ada, cat, ws, _ = await world()
    app.state.settings.openai_api_key = SecretStr(KEY)
    app.state.settings.server_model_keys = True  # A legacy deployment setting must have no effect.
    workspace_id = uuid.UUID(ws.rsplit("/", 1)[1])
    workspace = await db_session.get(Workspace, workspace_id)
    workspace.personal_keys = False  # Retired policy cannot block the user's own credentials.
    db_session.add(WorkspaceModelKey(workspace_id=workspace_id, provider="openai",
                                    encrypted=app.state.secrets.encrypt(KEY), last4="WXYZ", added_by_id=ada.id))
    await db_session.commit()
    for person in (ada, cat):
        assert not (await db_client.get(f"{ws}/model-access", headers=person.headers)).json()["ready"]
        assert (await db_client.get(f"{ws}/model-keys", headers=person.headers)).status_code == 404
        assert (await db_client.put(f"{ws}/model-keys/openai", json={"api_key": KEY}, headers=person.headers)).status_code == 404
        assert (await db_client.delete(f"{ws}/model-keys/openai", headers=person.headers)).status_code == 404
    assert (await run_keys(db_session, app.state.secrets, workspace_id, None)).keys == {}
    await db_client.put("/v1/me/model-keys/openai", json={"api_key": KEY}, headers=cat.headers)
    assert (await db_client.get(f"{ws}/model-access", headers=cat.headers)).json()["ready"]
    assert not (await db_client.get(f"{ws}/model-access", headers=ada.headers)).json()["ready"]


async def test_default_coding_tool_is_private(world, db_client) -> None:
    _, ada, cat, _, _ = await world()
    saved = await db_client.put("/v1/me/coding-tool", json={"default_coding_tool": "opencode"}, headers=cat.headers)
    assert saved.status_code == 200 and saved.json()["default_coding_tool"] == "opencode"
    assert (await db_client.get("/v1/me/models", headers=ada.headers)).json()["default_coding_tool"] is None
    assert (await db_client.put("/v1/me/coding-tool", json={"default_coding_tool": "shell"}, headers=cat.headers)).status_code == 422
    assert (await db_client.put("/v1/me/coding-tool", json={"default_coding_tool": None}, headers=cat.headers)).json()["default_coding_tool"] is None


async def test_personal_keys_are_encrypted_private_and_used_for_runs(world, db_client, agent_script, db_session) -> None:
    _, ada, cat, _, base = await world()
    saved = await db_client.put("/v1/me/model-keys/anthropic", json={"api_key": KEY}, headers=ada.headers)
    assert saved.status_code == 200 and KEY not in saved.text
    listed = {k["provider"]: k for k in saved.json()["keys"]}
    assert set(listed) == set(PROVIDERS) and listed["anthropic"]["last4"] == "WXYZ"
    assert all("server_key" not in k for k in listed.values())
    row = await db_session.scalar(select(UserModelKey).where(UserModelKey.user_id == ada.id))
    assert row is not None and KEY not in row.encrypted
    other = (await db_client.get("/v1/me/models", headers=cat.headers)).json()
    assert all(not k["connected"] and k["last4"] is None for k in other["keys"])
    agent_script.say("Hello.")
    run = await db_client.post(f"{base}/agent/runs", json={"message": "hi"}, headers=ada.headers)
    assert run.json()["status"] == "completed" and agent_script.keys_used[-1] == {"anthropic": KEY}
    assert (await db_client.delete("/v1/me/model-keys/anthropic", headers=ada.headers)).status_code == 200
    assert (await db_client.delete("/v1/me/model-keys/anthropic", headers=ada.headers)).status_code == 404
    assert (await db_client.put("/v1/me/model-keys/unsupported", json={"api_key": KEY}, headers=ada.headers)).status_code == 404


async def test_personal_keys_require_encryption(world, db_client) -> None:
    _, ada, _, _, _ = await world(secure=False)
    refused = await db_client.put("/v1/me/model-keys/openai", json={"api_key": KEY}, headers=ada.headers)
    assert refused.status_code == 503 and refused.json()["type"].endswith("/encryption_not_configured")
    assert (await db_client.put("/v1/me/model-keys/openai", json={"api_key": " " * 30}, headers=ada.headers)).status_code == 422


async def test_provider_limits_are_recorded_only_on_the_requesters_key(world, db_client, agent_script) -> None:
    _, ada, cat, _, base = await world()
    for person in (ada, cat):
        await db_client.put("/v1/me/model-keys/anthropic", json={"api_key": KEY}, headers=person.headers)
    agent_script.model = RateLimited.of("never")
    failed = (await db_client.post(f"{base}/agent/runs", json={"message": "hi"}, headers=ada.headers)).json()
    assert failed["status"] == "failed" and "per-minute rate limit" in failed["error"]
    async def key(person):
        return next(k for k in (await db_client.get("/v1/me/models", headers=person.headers)).json()["keys"] if k["provider"] == "anthropic")
    assert (await key(ada))["limit_reached_at"] and (await key(cat))["limit_reached_at"] is None
    agent_script.say("Back again.")
    await db_client.post(f"{base}/agent/runs", json={"message": "hi"}, headers=ada.headers)
    assert (await key(ada))["limit_reached_at"] is None


async def test_model_choices_and_automations_use_the_creators_own_key(world, db_client, agent_script) -> None:
    _, ada, cat, ws, base = await world()
    await db_client.put("/v1/me/model-keys/openai", json={"api_key": KEY}, headers=ada.headers)
    models = (await db_client.get(f"{ws}/models", headers=ada.headers)).json()
    assert models and all(m["provider"] == "openai" and m["source"] == "personal" for m in models)
    assert (await db_client.get(f"{ws}/models", headers=cat.headers)).json() == []
    await db_client.put("/v1/me/model-keys/anthropic", json={"api_key": KEY}, headers=ada.headers)
    made = (await db_client.post(f"{base}/automations", json={
        "name": "Summary", "instructions": "Summarise.", "schedule_hour": 6,
    }, headers=ada.headers)).json()
    assert made["max_runs_per_day"] is None
    agent_script.say("Summary.")
    await db_client.post(f"{base}/automations/{made['id']}/run", headers=ada.headers)
    assert agent_script.keys_used[-1]["anthropic"] == KEY


async def test_models_never_fall_back_to_server_keys(db_client) -> None:
    settings = db_client._transport.app.state.settings
    settings.anthropic_api_key = SecretStr(KEY)
    settings.server_model_keys = True
    assert key_for(settings, "anthropic:claude-sonnet-5") is None
    assert available_models(settings) == []
    assert key_for(settings, "anthropic:claude-sonnet-5", {"anthropic": "mine"}) == "mine"


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
