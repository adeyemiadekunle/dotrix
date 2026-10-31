"""Live coding on real models: one of Kai's turns on each engine (Claude Code, Codex, OpenCode, fx) and
provider (Anthropic, OpenAI), in the Docker sandbox through its egress proxy, from the issue to the PR.
Each runs only when its provider's key is given (DOTRIX_LIVE_ANTHROPIC_API_KEY, DOTRIX_LIVE_OPENAI_API_KEY)
and the coding image is built (docker build -t dotrix-coding:latest infra/coding); each makes paid calls."""
import dataclasses
import os
import subprocess
from pathlib import Path

import pytest
from httpx import AsyncClient

from apps.backend.tests.integration.test_coding import (  # noqa: F401  (fixtures)
    _approve,
    _git,
    _save_key,
    claude,
    coding,
    origin,
)
from dotrix_backend.modules.coding.runner import CodingWorker
from dotrix_backend.modules.coding.sandbox import DockerSandbox

IMAGE = "dotrix-coding:latest"
KEYS = {"anthropic": "DOTRIX_LIVE_ANTHROPIC_API_KEY", "openai": "DOTRIX_LIVE_OPENAI_API_KEY"}
ENGINES = [
    ("claude-code", "anthropic:claude-haiku-5-5"),
    ("codex", "openai:gpt-5.5"),
    ("opencode", "anthropic:claude-haiku-5-5"),
    ("opencode", "openai:gpt-5.5"),
    ("fx", "anthropic:claude-haiku-5-5"),
    ("fx", "openai:gpt-5.5"),
]


def _image() -> bool:
    try:
        return subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True, check=False).returncode == 0
    except OSError:
        return False


def _cases():
    for agent, model in ENGINES:
        variable = KEYS[model.partition(":")[0]]
        yield pytest.param(agent, model, id=f"{agent}-{model.partition(':')[0]}", marks=[
            pytest.mark.skipif(not os.environ.get(variable), reason=f"Live model test: set {variable}"),
            pytest.mark.skipif(not _image(), reason=f"needs Docker and {IMAGE}"),
        ])


@pytest.mark.parametrize(("agent", "model"), list(_cases()))
async def test_live_kai_turn_in_docker_opens_a_pr(
    db_client: AsyncClient, coding, github, origin: Path, agent_script, agent, model,  # noqa: F811
) -> None:
    ada, _, ws, kun, _, _ = coding
    app = db_client._transport.app  # type: ignore[attr-defined]
    settings = app.state.settings
    settings.coding_sandbox, settings.coding_image = "docker", IMAGE
    jobs = app.state.jobs
    worker: CodingWorker = jobs.ctx.coding
    jobs.ctx = dataclasses.replace(jobs.ctx, coding=dataclasses.replace(worker, sandbox=DockerSandbox(settings)))
    provider = model.partition(":")[0]
    await _save_key(db_client, ada.headers, provider, os.environ[KEYS[provider]])
    agent_script.say("Looks right.")
    base = f"{ws}/projects/{kun['id']}"
    task = (await db_client.post(f"{base}/issues", headers=ada.headers, json={
        "type": "task", "title": "Add refund()",
        "description": "In src/payments.py, add a module-level function `refund(amount)` that returns `amount`. "
                       "Change nothing else.",
    })).json()
    asked = await db_client.post(f"{base}/coding/issues/{task['key']}/runs", headers=ada.headers,
                                 json={"agent": agent, "model": model})
    assert asked.status_code == 201, asked.text
    run = await _approve(db_client, base, asked.json(), ada.headers)
    steps = [e["text"] for e in run["events"]]
    assert run["status"] == "pr_opened", (run["status"], run["error"], steps[-15:])
    assert (run["agent"], run["model"]) == (agent, model)
    assert "src/payments.py" in {f["path"] for f in run["files_changed"]}, run["files_changed"]
    assert "def refund(" in _git(origin, "show", f"{run['branch']}:src/payments.py")
    assert run["input_tokens"] > 0 and run["cost_usd"], run  # every engine shows a cost (Codex and fx priced from tokens)
    print(f"LIVE {agent}/{model}: {run['summary']!r} tokens={run['input_tokens']}+{run['output_tokens']} "
          f"cost={run['cost_usd']} steps={steps[:8]}")
