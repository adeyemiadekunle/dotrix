"""Live coding on real models: one of Kai's turns on each engine (Claude Code, Codex, OpenCode, fx) and
provider (Anthropic, OpenAI, NVIDIA), in the Docker sandbox through its egress proxy, from the issue to the PR.
Each runs only when its provider's key is given (DOTRIX_LIVE_ANTHROPIC_API_KEY, DOTRIX_LIVE_OPENAI_API_KEY, DOTRIX_LIVE_NVIDIA_API_KEY)
and the coding image is built (docker build -t dotrix-coding:latest infra/coding); each makes paid calls."""
import dataclasses
import json
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
KEYS = {"anthropic": "DOTRIX_LIVE_ANTHROPIC_API_KEY", "openai": "DOTRIX_LIVE_OPENAI_API_KEY",
        "nvidia": "DOTRIX_LIVE_NVIDIA_API_KEY"}
ENGINES = [
    ("claude-code", "anthropic:claude-haiku-5-5"),
    ("codex", "openai:gpt-5.5"),
    ("opencode", "anthropic:claude-haiku-5-5"),
    ("opencode", "openai:gpt-5.5"),
    ("fx", "anthropic:claude-haiku-5-5"),
    ("fx", "openai:gpt-5.5"),
    ("opencode", "nvidia:nvidia/nemotron-3-ultra-550b-a55b"),
    ("fx", "nvidia:nvidia/nemotron-3-ultra-550b-a55b"),
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
    assert run["input_tokens"] > 0, run
    if provider != "nvidia":
        assert run["cost_usd"], run  # NVIDIA billing is not established by engine estimates.
    print(f"LIVE {agent}/{model}: {run['summary']!r} tokens={run['input_tokens']}+{run['output_tokens']} "
          f"cost={run['cost_usd']} steps={steps[:8]}")


@pytest.mark.parametrize(("agent", "model"), list(_cases()))
async def test_live_skills_follow_what_kai_changed(
    db_client: AsyncClient, coding, github, origin: Path, agent_script, agent, model,  # noqa: F811
) -> None:
    """Cloud briefs list pinned skills for lazy loading; Juno still selects review guidance from the diff."""
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
    assert "## Pinned skills" in asked["brief"] and "- security-review:" in asked["brief"]
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
    picked = [skill["name"] for skill in follow.json()["skills"]]
    assert "review-a-backend-change" in picked and "security-review" in picked, picked
    assert "## Pinned skills" in brief and '<data source="skill ' not in brief
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


@pytest.mark.parametrize(("agent", "model"), list(_cases()))
async def test_live_kai_loads_a_pinned_skill_resource(
    db_client: AsyncClient, coding, github, origin: Path, agent_script, agent, model,  # noqa: F811
) -> None:
    """The expected marker exists only in a pinned resource, never in the task or catalog description."""
    ada, _, ws, kun, _, _ = coding
    app = db_client._transport.app  # type: ignore[attr-defined]
    settings = app.state.settings
    settings.coding_sandbox, settings.coding_image = "docker", IMAGE
    worker = app.state.jobs.ctx.coding
    app.state.jobs.ctx = dataclasses.replace(app.state.jobs.ctx,
        coding=dataclasses.replace(worker, sandbox=DockerSandbox(settings)))
    provider = model.partition(":")[0]
    await _save_key(db_client, ada.headers, provider, os.environ[KEYS[provider]])
    base = f"{ws}/projects/{kun['id']}"
    marker = "refund-policy-resource-verification-2026"
    entries = {
        "agent-rules/skills/team-refund.md": "Description: Read the team's refund policy before implementing refunds.\n"
            "Agents: coding\nResources: references/policy.md\nRequires: repository.read, repository.write\n\n"
            "Read the pinned references/policy.md resource. Its marker must be used verbatim as REFUND_POLICY in src/payments.py.",
        "agent-rules/skills/team-refund/references/policy.md": f"The refund policy marker is `{marker}`.\n",
    }
    for path, content in entries.items():
        response = await db_client.put(f"{base}/knowledge/files/{path}", headers=ada.headers, json={"content": content})
        assert response.status_code in (200, 201), response.text
    task = (await db_client.post(f"{base}/issues", headers=ada.headers, json={
        "type": "task", "title": "Apply the team refund policy",
        "description": "Read the pinned team-refund skill and its policy reference, then add REFUND_POLICY "
                       "to src/payments.py using the exact marker from that reference. Change nothing else.",
    })).json()
    agent_script.say("The policy marker matches the requested resource.")
    asked = (await db_client.post(f"{base}/coding/issues/{task['key']}/runs", headers=ada.headers,
                                  json={"agent": agent, "model": model})).json()
    assert marker not in asked["brief"]
    skill = next(item for item in asked["skills"] if item["name"] == "team-refund")
    assert skill["resources"] == ["references/policy.md"] and not skill["missing_resources"]
    run = await _approve(db_client, base, asked, ada.headers)
    assert run["status"] == "pr_opened", (run["status"], run["error"], run["summary"])
    assert marker in _git(origin, "show", f"{run['branch']}:src/payments.py")


@pytest.mark.parametrize(("agent", "model"), [case for case in _cases() if case.values[1].startswith("nvidia:")])
async def test_live_nvidia_bug_and_browser(
    db_client: AsyncClient, coding, github, origin: Path, agent_script, agent, model,  # noqa: F811
) -> None:
    """Real provider and gVisor containers; disposable git and simulated GitHub/reviewer only."""
    ada, _, ws, kun, _, _ = coding
    app = db_client._transport.app
    settings = app.state.settings
    settings.coding_sandbox, settings.coding_image = "docker", IMAGE
    settings.coding_docker_runtime = "runsc"
    settings.coding_timeout_minutes = 5
    worker = app.state.jobs.ctx.coding
    app.state.jobs.ctx = dataclasses.replace(app.state.jobs.ctx,
        coding=dataclasses.replace(worker, sandbox=DockerSandbox(settings)))
    await _save_key(db_client, ada.headers, "nvidia", os.environ[KEYS["nvidia"]])
    # The test starts after setup; no external repository or GitHub write is possible.
    (origin / ".gitignore").write_text("__pycache__/\n")
    (origin / "add.py").write_text("def add(a, b):\n    return a - b\n")
    (origin / "test_add.py").write_text("import unittest\nfrom add import add\nclass TestAdd(unittest.TestCase):\n"
        "    def test_sum(self):\n        self.assertEqual(add(2, 3), 5)\n        self.assertEqual(add(-2, 3), 1)\n"
        "        self.assertEqual(add(0, 0), 0)\n")
    (origin / "index.html").write_text('<button onclick="this.textContent=\'Clicked successfully\'">Click me</button>')
    _git(origin, "add", "-A")
    _git(origin, "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "Bug fixture")
    base = f"{ws}/projects/{kun['id']}"
    task = (await db_client.post(f"{base}/issues", headers=ada.headers, json={
        "type": "task", "title": "Fix add and verify the browser",
        "description": "Fix add.py so add returns a+b. Change only add.py. Run python3 -m unittest -v test_add "
        "and verify all assertions pass. Then start python3 -m http.server 8080 in the background, "
        "navigate with browser tools to http://localhost:8080/index.html, read browser_snapshot, "
        "click Click me using its target, read a fresh snapshot and verify Clicked successfully. "
        "Save a screenshot in /tmp/playwright and stop the web server. Report tests and browser evidence.",
    })).json()
    asked = await db_client.post(f"{base}/coding/issues/{task['key']}/runs", headers=ada.headers,
        json={"agent": agent, "model": model})
    assert asked.status_code == 201, asked.text
    assert asked.json()["status"] == "awaiting_approval"
    agent_script.say("Disposable live validation review completed.")
    decision = await db_client.post(f"{base}/coding/runs/{asked.json()['id']}/decision",
        json={"decision": "approve"}, headers=ada.headers)
    assert decision.status_code == 200, decision.text
    run = (await db_client.get(f"{base}/coding/runs/{asked.json()['id']}", headers=ada.headers)).json()
    print("NVIDIA_LIVE_RESULT " + json.dumps({key: run.get(key) for key in (
        "agent", "model", "status", "error", "summary", "input_tokens", "output_tokens", "cost_usd",
        "events", "files_changed", "screenshots")}), flush=True)
    assert run["status"] == "changes_ready", (run["status"], run.get("error"))
    assert not github.pulls, "Manual changes must wait for human acceptance"
    assert {f["path"] for f in run["files_changed"]} == {"add.py"}
    diff = (await db_client.get(f"{base}/coding/runs/{run['id']}/diff", headers=ada.headers)).json()["diff"]
    assert "+    return a + b" in diff or "+    return a+b" in diff
    assert any("test_sum" in e["text"] and "OK" in e["text"] for e in run["events"])
    assert any("Clicked successfully" in e["text"] for e in run["events"])
    assert run["input_tokens"] > 0
    assert run["screenshots"], "The real model must capture the browser"
    shot = await db_client.get(f"{base}/coding/runs/{run['id']}/screenshots/0", headers=ada.headers)
    assert shot.status_code == 200 and shot.content.startswith(b"\x89PNG")
    # Discard instead of publishing even to the fake GitHub transport.
    rejected = await db_client.post(f"{base}/coding/runs/{run['id']}/decision",
        json={"decision": "reject"}, headers=ada.headers)
    assert rejected.status_code == 200, rejected.text
