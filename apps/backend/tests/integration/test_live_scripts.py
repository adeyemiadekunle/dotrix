"""Code mode on real models (agents/scripts.py): the same question asked with run_script and without, on each chat
runtime, so what scripts save in model calls and tokens can be measured rather than assumed. Runs only when a
provider's key is given (DOTRIX_LIVE_ANTHROPIC_API_KEY, DOTRIX_LIVE_OPENAI_API_KEY, DOTRIX_LIVE_NVIDIA_API_KEY).

What a model does with the tool is its choice, so this asserts the answer and records the rest (`LIVE SCRIPTS …`
lines with `-s`): whether Nova scripted, its model calls, tokens and steps."""
import hashlib
from datetime import UTC, datetime

import pytest

from apps.backend.tests.integration.test_live_chat import CASES, _live
from apps.backend.tests.integration.test_runtime_tools import (
    nova_pilot_world,  # noqa: F401  (a fixture)
)
from dotrix_backend.modules.knowledge.models import KnowledgeFile

FACTS = {  # one fact a file, so the answer shows every file was read
    "research/costs.md": "Each turn costs about 4 cents.",
    "research/latency.md": "A reply takes about 900 milliseconds.",
    "decisions/0007-runtime.md": "We picked the queue-backed runtime.",
    "requirements/limits.md": "A workspace may run 3 turns at once.",
}
CHAINED = ("Search the project's knowledge for every document that mentions 'turn' or 'turns', read each one you find, "
           "and give me the one fact each states, a line per file.")
QUESTION = ("Read research/runtime.md, research/costs.md, research/latency.md, decisions/0007-runtime.md and "
            "requirements/limits.md in the project's knowledge, then give me the one fact each states, a line per file.")


async def _add_files(sessions, run) -> None:
    now = datetime.now(UTC)
    async with sessions() as session:
        for path, fact in FACTS.items():
            content = f"# {path.rsplit('/', 1)[-1]}\n\n{fact}\n"
            session.add(KnowledgeFile(workspace_id=run.workspace_id, project_id=run.project_id, path=path, version=1,
                                      revision=1, content=content, content_hash=hashlib.sha256(content.encode()).hexdigest(),
                                      size=len(content.encode()), created_at=now, updated_at=now))
        await session.commit()


@pytest.mark.parametrize(("question", "expected"), [
    pytest.param(QUESTION, ("4 cents", "900 milliseconds", "queue-backed", "3 turns", "private project evidence"), id="five-files"),
    pytest.param(CHAINED, ("4 cents", "3 turns"), id="search-then-read"),
])
@pytest.mark.parametrize(("runtime", "provider", "model"), CASES)
async def test_live_nova_reads_with_and_without_scripts(
    nova_pilot_world, db_client, agent_script, outbox, storage, checkouts, runtime, provider, model, question, expected,  # noqa: F811
):
    await _add_files(nova_pilot_world[1], nova_pilot_world[0])
    chat, fx = await _live(nova_pilot_world, db_client, outbox, storage, checkouts, agent_script, provider)
    settings = fx.runner.settings
    measured = {}
    try:
        for scripts in (True, False):
            fx.runner.settings = settings.model_copy(update={"agent_scripts": scripts})
            asked = await fx.client.post(f"{fx.base}/runs", headers=fx.headers, json={
                "message": question, "chat_runtime": runtime, "work_mode": "discuss", "model": model,
            })
            assert asked.status_code == 202, asked.text
            run = asked.json()
            assert run["status"] == "completed", (scripts, run["status"], run.get("error"), run.get("reply"))
            reply = run["reply"].lower()
            missing = [f for f in expected if f not in reply.replace("four", "4").replace("three", "3")]
            events = (await fx.client.get(f"{fx.base}/runs/{run['id']}/events", headers=fx.headers)).json()["events"]
            steps = [e["data"].get("label") for e in events if e["kind"] == "activity"]
            tools = {t["tool"]: t["calls"] for t in (run.get("breakdown") or {}).get("tools", [])}
            measured[scripts] = {
                "scripted": "Working through the project in one step" in steps,
                "model_calls": run.get("model_calls"), "tools": tools,
                "input": run.get("input_tokens"), "output": run.get("output_tokens"),
                "cached": run.get("cached_input_tokens"), "complete": run.get("usage_complete"),
                "steps": len(steps), "missing": missing,
            }
            print(f"LIVE SCRIPTS {runtime}/{model} scripts={scripts}: {measured[scripts]}\n  steps={steps}\n  reply={run['reply']!r}")
            assert not missing, (scripts, missing, run["reply"])
    finally:
        fx.runner.settings = settings
        await chat.__aexit__(None, None, None)
    on, off = measured[True], measured[False]
    if on["input"] and off["input"]:
        print(f"LIVE SCRIPTS {runtime}/{model} input tokens with scripts {on['input']} vs without {off['input']} "
              f"({(on['input'] - off['input']) / off['input']:+.0%}); scripted={on['scripted']}")
