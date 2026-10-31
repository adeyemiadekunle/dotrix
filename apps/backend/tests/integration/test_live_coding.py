"""Live coding on real models: one of Kai's turns on each engine (Claude Code, Codex, OpenCode, fx) and
provider (Anthropic, OpenAI), in the Docker sandbox through its egress proxy, from the issue to the PR.
Each runs only when its provider's key is given (DOTRIX_LIVE_ANTHROPIC_API_KEY, DOTRIX_LIVE_OPENAI_API_KEY)
and the coding image is built (docker build -t dotrix-coding:latest infra/coding); each makes paid calls."""
import dataclasses
import os
import re
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


@pytest.mark.parametrize(("agent", "model"), list(_cases()))
async def test_live_skills_follow_what_kai_changed(
    db_client: AsyncClient, coding, github, origin: Path, agent_script, agent, model,  # noqa: F811
) -> None:
    """An issue that names no skill's area gets none, the rest listed; Juno's review and the next turn pick
    them from what Kai changed (a .py file in the payments code)."""
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
        "type": "task", "title": "Give the provider class a refund method",
        "description": "Add refund(self, amount) to the provider class; it returns the amount it refunded.",
    })).json()
    asked = (await db_client.post(f"{base}/coding/issues/{task['key']}/runs", headers=ada.headers,
                                  json={"agent": agent, "model": model})).json()
    assert "## Skills for this work" not in asked["brief"], "the issue names no skill's area"
    assert "## Other skills (not included)" in asked["brief"] and "- security-review:" in asked["brief"]
    first = await _approve(db_client, base, asked, ada.headers)
    assert first["status"] == "pr_opened", (first["status"], first["error"], first["summary"])
    assert "src/payments.py" in {f["path"] for f in first["files_changed"]}
    review = (await db_client.get(f"{base}/agent/runs/{first['review_run_id']}", headers=ada.headers)).json()
    told = [line for line in review["message"].splitlines() if "review skills" in line]
    assert told and "review-a-backend-change" in told[0] and "security-review" in told[0], told

    follow = await db_client.post(f"{base}/coding/sessions/{first['session_id']}/turns", headers=ada.headers,
                                  json={"message": "Also add a test for it."})
    assert follow.status_code == 201, follow.text
    brief = follow.json()["brief"]
    picked = sorted(set(re.findall(r'<data source="skill ([a-z-]+)">', brief)))
    assert "review-a-backend-change" in picked and "security-review" in picked, picked
    assert not {"build-a-ui-change", "review-a-frontend-change", "plan-a-schema-change"} & set(picked), picked
    second = await _approve(db_client, base, follow.json(), ada.headers)
    assert second["status"] in ("pr_opened", "no_changes"), (second["status"], second["error"])  # a test may be there already
    print(f"LIVE {agent}/{model}: review told {told[0]!r}; follow-up picked {picked}; "
          f"turn 1 summary: {first['summary']!r}; turn 2 cost {second['cost_usd']}")


@pytest.mark.parametrize(("agent", "model"), list(_cases()))
async def test_live_an_unclear_issue_never_reaches_main_unreviewed(
    db_client: AsyncClient, coding, github, origin: Path, agent_script, agent, model,  # noqa: F811
) -> None:
    """An issue nobody could act on without guessing. Kai's brief adds no rule for it (the engine's own
    harness decides): whether it stops or builds something, nothing reaches main, and what it built
    waits on a branch with Juno's review started."""
    ada, _, ws, kun, _, _ = coding
    app = db_client._transport.app  # type: ignore[attr-defined]
    settings = app.state.settings
    settings.coding_sandbox, settings.coding_image = "docker", IMAGE
    jobs = app.state.jobs
    worker: CodingWorker = jobs.ctx.coding
    jobs.ctx = dataclasses.replace(jobs.ctx, coding=dataclasses.replace(worker, sandbox=DockerSandbox(settings)))
    provider = model.partition(":")[0]
    await _save_key(db_client, ada.headers, provider, os.environ[KEYS[provider]])
    agent_script.say("This builds a checkout the issue never described; send it back with questions.")
    base = f"{ws}/projects/{kun['id']}"
    main = _git(origin, "rev-parse", "main")
    task = (await db_client.post(f"{base}/issues", headers=ada.headers, json={
        "type": "bug", "title": "Fix the checkout bug", "description": "Customers say checkout is broken.",
    })).json()
    asked = (await db_client.post(f"{base}/coding/issues/{task['key']}/runs", headers=ada.headers,
                                  json={"agent": agent, "model": model})).json()
    run = await _approve(db_client, base, asked, ada.headers)
    print(f"LIVE {agent}/{model}: status={run['status']} files={[f['path'] for f in run['files_changed']]} "
          f"summary={(run['summary'] or '')[:300]!r}")
    assert _git(origin, "rev-parse", "main") == main  # main never moves
    if run["status"] == "no_changes":
        assert github.pulls == []
    else:
        assert run["status"] == "pr_opened" and run["branch"] != "main" and run["review_run_id"], run
