"""Live chat on real models: Nova on each chat runtime (DeepAgents, fx) and each provider (Anthropic,
OpenAI), through the public API with the requester's own key. Each test runs only when its provider's
key is given (DOTRIX_LIVE_ANTHROPIC_API_KEY, DOTRIX_LIVE_OPENAI_API_KEY); they make a few paid calls."""
import os

import pytest
from sqlalchemy import update

from apps.backend.tests.integration.test_fx_changes import _file, _has_fx, fx_chat
from apps.backend.tests.integration.test_runtime_tools import (
    nova_pilot_world,  # noqa: F401  (a fixture)
)
from dotrix_backend.modules.agents.llm import settings_model_factory
from dotrix_backend.modules.model_keys.models import UserModelKey

LIVE = {"anthropic": ("DOTRIX_LIVE_ANTHROPIC_API_KEY", "anthropic:claude-haiku-5-5"),
        "openai": ("DOTRIX_LIVE_OPENAI_API_KEY", "openai:gpt-5.5")}


def _cases():
    for provider, (variable, model) in LIVE.items():
        for runtime in ("deepagents", "fx"):
            marks = [pytest.mark.skipif(not os.environ.get(variable), reason=f"Live model test: set {variable}")]
            if runtime == "fx":
                marks.append(pytest.mark.skipif(not _has_fx(), reason="Install the optional fx host"))
            yield pytest.param(runtime, provider, model, id=f"{runtime}-{provider}", marks=marks)


CASES = list(_cases())


async def _live(world, db_client, outbox, storage, checkouts, agent_script, provider):
    """The requester's own key for `provider`, and the runner building real models from it."""
    existing, sessions, secrets = world
    key = secrets.encrypt(os.environ[LIVE[provider][0]])
    async with sessions() as session:  # the world already holds a placeholder OpenAI key
        changed = await session.execute(update(UserModelKey).where(
            UserModelKey.user_id == existing.requested_by_id, UserModelKey.provider == provider).values(encrypted=key))
        if not changed.rowcount:
            session.add(UserModelKey(user_id=existing.requested_by_id, provider=provider, encrypted=key, last4="live"))
        await session.commit()
    chat = fx_chat(world, db_client, outbox, storage, checkouts, agent_script)
    fx = await chat.__aenter__()
    fx.runner.model_factory = settings_model_factory(db_client._transport.app.state.settings)
    fx.client.timeout = 300
    return chat, fx


@pytest.mark.parametrize(("runtime", "provider", "model"), CASES)
async def test_live_chat_reads_project_knowledge_and_follows_up(
    nova_pilot_world, db_client, agent_script, outbox, storage, checkouts, runtime, provider, model,  # noqa: F811
):
    """Nova reads the project's knowledge with the platform's tools, and a follow-up keeps the conversation."""
    chat, fx = await _live(nova_pilot_world, db_client, outbox, storage, checkouts, agent_script, provider)
    try:
        first = await fx.client.post(f"{fx.base}/runs", headers=fx.headers, json={
            "message": "Read research/runtime.md in the project's knowledge and quote its one sentence of evidence.",
            "chat_runtime": runtime, "work_mode": "discuss", "model": model,
        })
        assert first.status_code == 202, first.text
        run = first.json()
        assert run["status"] == "completed", (run["status"], run.get("error"), run.get("reply"))
        assert run["chat_runtime"] == runtime and run["model"] == model
        assert "private project evidence" in run["reply"].lower(), run["reply"]
        second = await fx.client.post(f"{fx.base}/runs", headers=fx.headers, json={
            "message": "Which file did you read? Just its path.", "thread_id": run["thread_id"], "work_mode": "discuss",
        })
        assert second.status_code == 202 and second.json()["status"] == "completed", second.text
        assert second.json()["chat_runtime"] == runtime
        assert "runtime.md" in second.json()["reply"], second.json()["reply"]
        print(f"LIVE {runtime}/{model}:", run["reply"], "|", second.json()["reply"])
    finally:
        await chat.__aexit__(None, None, None)


@pytest.mark.parametrize(("runtime", "provider", "model"), CASES)
async def test_live_build_change_waits_for_approval_then_goes_through_once(
    nova_pilot_world, db_client, agent_script, outbox, storage, checkouts, runtime, provider, model,  # noqa: F811
):
    """In Build (Manual), Nova's document change waits for a person, then is written once."""
    chat, fx = await _live(nova_pilot_world, db_client, outbox, storage, checkouts, agent_script, provider)
    try:
        asked = await fx.client.post(f"{fx.base}/runs", headers=fx.headers, json={
            "message": "Write /dotrix/progress/status.md containing exactly the line: Runtime check passed.",
            "chat_runtime": runtime, "work_mode": "build", "model": model,
        })
        assert asked.status_code == 202, asked.text
        run = asked.json()
        assert run["status"] == "awaiting_approval", (run["status"], run.get("error"), run.get("reply"))
        [approval] = run["approvals"]
        assert approval["tool"] in ("write_file", "edit_file"), approval
        assert approval["target"].endswith("progress/status.md"), approval
        decided = await fx.client.post(f"{fx.base}/runs/{run['id']}/decisions", headers=fx.headers, json={
            "decisions": [{"approval_id": approval["id"], "decision": "approve"}],
        })
        assert decided.status_code == 200, decided.text
        done = (await fx.client.get(f"{fx.base}/runs/{run['id']}", headers=fx.headers)).json()
        assert done["status"] == "completed", done
        written = await _file(fx.sessions, fx.existing.project_id, "progress/status.md")
        assert written is not None and "Runtime check passed." in written.content and written.version == 1
        print(f"LIVE {runtime}/{model}:", done["reply"])
    finally:
        await chat.__aexit__(None, None, None)
