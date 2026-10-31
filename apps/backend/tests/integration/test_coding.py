"""Coding runs (step 5c): asked for, approved, run in a sandbox, pushed to a new branch, and
opened as a PR. GitHub's API is faked (conftest.FakeGitHub), the repo is a local git repo, and the
"sandbox" is the local one with a scripted Claude Code (or OpenCode) in place of the real CLI."""
import asyncio
import base64
import dataclasses
import json
import re
import subprocess
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from cryptography.fernet import Fernet
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy import select, update

from dotrix_backend.core.crypto import Secrets
from dotrix_backend.modules.coding.models import CodingRun, CodingRunStatus
from dotrix_backend.modules.coding.recovery import recover_uncertain_runs
from dotrix_backend.modules.coding.runner import (
    _LEASE,
    SHOTS_LIST,
    CodingWorker,
    _ReconciliationRequired,
)
from dotrix_backend.modules.coding.sandbox import ExecResult, LocalSandbox, LocalSession
from dotrix_backend.modules.coding.warm import WarmPool
from dotrix_backend.modules.connectors.github_app import get_github_app
from dotrix_backend.modules.execution.service import expire_coding_leases
from dotrix_engine.testing import tool_call


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout.strip()


class ScriptedClaude:
    """Stands in for `claude -p`: makes `edits` in the repo and prints stream-json events."""

    def __init__(self) -> None:
        self.edits: dict[str, str] = {}
        self.result = "Added refunds to the payment provider and a test; pytest passes."
        self.briefs: list[str] = []
        self.argv: list[str] = []
        self.env: dict[str, str] = {}

    def lines(self) -> list[str]:
        events: list[dict[str, Any]] = [{"type": "system", "subtype": "init", "model": "claude-test"}]
        for path in self.edits:
            events.append({"type": "assistant", "message": {"id": f"m-{path}", "content": [
                {"type": "text", "text": f"Editing {path}"},
                {"type": "tool_use", "name": "Edit", "input": {"file_path": f"/sandbox/repo/{path}"}},
            ], "usage": {"input_tokens": 1000, "output_tokens": 200}}})
        events.append({"type": "result", "subtype": "success", "result": self.result, "total_cost_usd": 0.12,
                       "usage": {"input_tokens": 1000 * len(self.edits), "output_tokens": 200 * len(self.edits)}})
        return [json.dumps(e) + "\n" for e in events]


class ScriptedOpenCode(ScriptedClaude):
    """Stands in for `opencode run --format json`: the same edits, as OpenCode 2's events. Its last
    step has no `step_finish` (as in the real one); `session export` gives it, with the cost."""

    error: str | None = None
    input_tokens: int = 1000

    def lines(self) -> list[str]:
        def event(kind: str, **part: Any) -> dict[str, Any]:
            return {"type": kind, "sessionID": "ses_x", "part": {"sessionID": "ses_x", **part}}
        tokens = {"input": self.input_tokens, "output": 200, "reasoning": 0, "cache": {"read": 0, "write": 0}}
        events: list[dict[str, Any]] = []
        for path in self.edits:
            events += [event("step_start", messageID=f"m-{path}"), event("text", messageID=f"m-{path}", text=f"Editing {path}"),
                       event("tool_use", messageID=f"m-{path}", tool="edit",
                             state={"status": "completed", "input": {"path": f"/sandbox/repo/{path}"}}),
                       event("step_finish", messageID=f"m-{path}", reason="tool-calls", tokens=tokens)]
        events += [event("step_start", messageID="m-last"), event("text", messageID="m-last", text=self.result)]
        if self.error:  # e.g. the provider refused mid-turn
            events.append({"type": "error", "sessionID": "ses_x", "error": {"type": "provider.auth", "message": self.error}})
        return [json.dumps(e) + "\n" for e in events]

    def totals(self) -> str:
        last = {"input": 500, "output": 50, "reasoning": 0, "cache": {"read": 0, "write": 0}}
        steps = [{"id": f"m-{path}"} for path in self.edits] + [{"id": "m-last", "tokens": last}]
        return json.dumps({"cost": 0.2, "turn": steps}) + "\n"


class ScriptedSession(LocalSession):
    def __init__(self, root: Path, env: dict[str, str], agent: ScriptedClaude) -> None:
        super().__init__(root, env)
        self.agent = agent

    async def exec(self, argv, *, stdin=None, on_line=None, timeout, cancel=None) -> ExecResult:
        if isinstance(self.agent, ScriptedOpenCode) and argv[:2] == ["sh", "-c"] and "node -e" in argv[2]:
            return ExecResult(code=0, stdout=self.agent.totals(), stderr="")  # its totals after the turn
        if argv[0] != "claude" and not (argv[0] == "env" and "opencode" in argv):
            return await super().exec(argv, stdin=stdin, on_line=on_line, timeout=timeout, cancel=cancel)
        self.agent.argv, self.agent.env = argv, dict(self.env)
        self.agent.briefs.append((stdin or b"").decode())
        for path, text in self.agent.edits.items():
            target = self.root / "repo" / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)
        for line in self.agent.lines():
            assert on_line is not None
            await on_line(line)
        return ExecResult(code=0, stdout="", stderr="")


class ScriptedSandbox(LocalSandbox):
    def __init__(self, agent: ScriptedClaude) -> None:
        self.agent = agent
        self.opened = 0

    async def open(self, run_id, source, tool, model_key):
        self.opened += 1
        session = await super().open(run_id, source, tool, model_key)
        assert isinstance(session, LocalSession)
        return ScriptedSession(session.root, session.env, self.agent)


async def _approve(db_client: AsyncClient, base: str, run: dict, headers: dict) -> dict:
    """Approve a turn; in Manual its checked changes then wait (`changes_ready`), and are accepted too."""
    for _ in range(2):
        res = await db_client.post(f"{base}/coding/runs/{run['id']}/decision", json={"decision": "approve"}, headers=headers)
        assert res.status_code == 200, res.text
        read = (await db_client.get(f"{base}/coding/runs/{run['id']}", headers=headers)).json()
        if read["status"] != "changes_ready":
            break
    return read


@pytest.fixture
def origin(tmp_path: Path) -> Path:
    """kunemi/api on "GitHub"."""
    root = tmp_path / "origin"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    (root / "src").mkdir()
    (root / "src/payments.py").write_text("class PaymentProvider:\n    pass\n")
    _git(root, "add", "-A")
    _git(root, "-c", "user.email=a@b.c", "-c", "user.name=A", "commit", "-qm", "first")
    _git(root, "config", "receive.denyCurrentBranch", "refuse")
    return root


@pytest.fixture
def claude() -> ScriptedClaude:
    return ScriptedClaude()


async def _save_key(client: AsyncClient, headers, provider: str, key: str) -> None:
    response = await client.put(f"/v1/me/model-keys/{provider}", json={"api_key": key}, headers=headers)
    assert response.status_code == 200, response.text


@pytest.fixture
async def coding(db_client: AsyncClient, github, github_world, origin: Path, claude: ScriptedClaude):
    """Ada (owner) and Cat (member); KUN connected to kunemi/api; coding on, with Claude Code."""
    app = db_client._transport.app  # type: ignore[attr-defined]
    settings = app.state.settings
    client = app.dependency_overrides[get_github_app]()
    settings.coding_sandbox = "local"
    settings.encryption_key = SecretStr(Fernet.generate_key().decode())
    app.state.secrets = app.state.runner.secrets = Secrets.from_settings(settings)
    settings.github_app_id, settings.github_app_slug = "4242", "dotrix-test"
    settings.github_app_private_key = SecretStr(client.private_key)
    ada, cat, ws, kun, mob = await github_world()
    for person in (ada, cat):
        await _save_key(db_client, person.headers, "anthropic", "test-anthropic-personal-key-" + str(person.id))
    installation = (await db_client.post(f"{ws}/github/installations", json={"installation_id": 111, "code": "code-1"},
                                          headers=ada.headers)).json()
    connected = await db_client.put(f"{ws}/projects/{kun['id']}/repository",
                                    json={"installation_ref": installation["id"], "github_repo_id": 9001},
                                    headers=ada.headers)
    assert connected.status_code == 200, connected.text

    async def repo_url(ref) -> str:
        assert ref.full_name == "kunemi/api" and ref.default_branch == "main"
        return str(origin)

    sandbox = ScriptedSandbox(claude)
    jobs = app.state.jobs
    jobs.ctx = dataclasses.replace(jobs.ctx, coding=CodingWorker(
        jobs.ctx.session_factory, settings, sandbox, client, repo_url=repo_url, reviewer=app.state.runner,
        secrets=app.state.secrets, pool=WarmPool(3600, 0),  # each turn starts fresh here; the warm sandbox has a test of its own
    ))
    yield ada, cat, ws, kun, mob, sandbox


async def test_an_approved_run_opens_a_pr_on_a_new_branch(
    db_client: AsyncClient, coding, github, origin: Path, claude: ScriptedClaude, agent_script
) -> None:
    ada, cat, ws, kun, _, _ = coding
    base = f"{ws}/projects/{kun['id']}"
    await db_client.put(f"{base}/knowledge/files/requirements/refunds.md", headers=ada.headers,
                        json={"content": "# Refunds\n\nRefund within a week of purchase.\n"})
    story = (await db_client.post(f"{base}/issues", headers=ada.headers, json={
        "type": "story", "title": "Refund a payment",
        "description": "Implements requirements/refunds.md.\n\nAcceptance: refund() returns the amount.",
    })).json()

    availability = (await db_client.get(f"{base}/coding", headers=cat.headers)).json()
    expected = {"available": True, "agent": "claude-code", "sandbox": "local", "reason": None,
                "local_available": False, "local_runner": None,
                "local_reason": "Run `dotrix runner` in a checkout of KUN on your computer first"}
    assert {name: availability[name] for name in expected} == expected
    assert availability["default_tool"] == "claude-code" and availability["local_tools"] == []
    assert {tool["agent"]: tool["available"] for tool in availability["tools"]} == {
        "claude-code": True, "codex": False, "opencode": True, "fx": True,  # fx: Anthropic's OpenAI-compatible endpoint
    }
    # Members can't instruct the coding agent unless the workspace lets them.
    assert (await db_client.post(f"{base}/coding/issues/{story['key']}/runs", json={},
                                 headers=cat.headers)).status_code == 403

    started = await db_client.post(f"{base}/coding/issues/{story['key']}/runs", headers=ada.headers,
                                   json={"note": "Keep it small."})
    assert started.status_code == 201, started.text
    run = started.json()
    assert run["status"] == "awaiting_approval" and run["agent"] == "claude-code" and run["can_decide"]
    assert "Acceptance: refund() returns the amount." in run["brief"] and "Keep it small." in run["brief"]
    assert "Refund within a week of purchase." in run["brief"]  # the requirement it implements, as data
    again = await db_client.post(f"{base}/coding/issues/{story['key']}/runs", json={}, headers=ada.headers)
    assert again.status_code == 409 and again.json()["type"].endswith("/coding_busy")
    # Sessions are private like conversations: Cat (who may neither approve nor see Ada's) gets nothing.
    assert (await db_client.get(f"{base}/coding/runs/{run['id']}", headers=cat.headers)).status_code == 404
    assert (await db_client.get(f"{base}/coding/runs", headers=cat.headers)).json() == []
    assert (await db_client.get(f"{ws}/coding/sessions", headers=cat.headers)).json() == []
    assert (await db_client.post(f"{base}/coding/runs/{run['id']}/decision", json={"decision": "approve"},
                                 headers=cat.headers)).status_code == 403

    claude.edits = {
        "src/payments.py": "class PaymentProvider:\n    def refund(self, amount):\n        return amount\n",
        "tests/test_refund.py": "def test_refund():\n    assert True\n",
    }
    agent_script.say("Looks right: refund() returns the amount, and there's a test. Ready to merge.")
    done = await db_client.post(f"{base}/coding/runs/{run['id']}/decision", json={"decision": "approve"},
                                headers=ada.headers)
    assert done.status_code == 200, done.text
    # Manual: the turn's checked changes wait for a person; nothing has reached GitHub yet.
    ready = (await db_client.get(f"{base}/coding/runs/{run['id']}", headers=ada.headers)).json()
    assert ready["status"] == "changes_ready" and ready["can_decide"] and ready["branch"] is None, ready
    assert {f["path"] for f in ready["files_changed"]} == {"src/payments.py", "tests/test_refund.py"}
    assert ready["summary"].startswith("Added refunds") and github.pulls == []
    assert _git(origin, "branch", "--list", "dotrix/*") == ""
    [waiting] = (await db_client.get(f"{ws}/notifications", params={"kind": "approval"}, headers=ada.headers)).json()[:1]
    assert waiting["title"].startswith("Changes ready for") and not waiting["resolved"], waiting
    accepted = await db_client.post(f"{base}/coding/runs/{run['id']}/decision", json={"decision": "approve"},
                                    headers=ada.headers)
    assert accepted.status_code == 200, accepted.text
    run = (await db_client.get(f"{base}/coding/runs/{run['id']}", headers=ada.headers)).json()
    assert run["status"] == "pr_opened" and run["accepted_by_id"] == ada.id and run["can_revert"], run
    assert run["pr_number"] == 1 and run["pr_url"] == "https://github.com/kunemi/api/pull/1"
    assert run["branch"].startswith(f"dotrix/{story['key'].lower()}-refund-a-payment-")
    assert {f["path"] for f in run["files_changed"]} == {"src/payments.py", "tests/test_refund.py"}
    assert run["summary"].startswith("Added refunds") and run["input_tokens"] == 2000 and run["cost_usd"] == 0.12
    assert "Edited src/payments.py" in [e["text"] for e in run["events"]]

    # The branch is on the remote with the agent's change; the default branch is untouched.
    assert _git(origin, "show", f"{run['branch']}:src/payments.py").endswith("return amount")
    assert _git(origin, "rev-parse", "main") == run["base_sha"] != run["commit_sha"]
    assert _git(origin, "rev-parse", run["branch"]) == run["commit_sha"]
    [pr] = github.pulls
    assert pr["head"] == run["branch"] and pr["base"] == "main" and pr["title"] == f"{story['key']}: Refund a payment"
    # The token was for this repo only, with push and PR rights; the agent never had it.
    assert github.token_requests[-1] == {"repository_ids": [9001], "permissions": {
        "metadata": "read", "contents": "write", "pull_requests": "write"}}
    assert set(claude.env) == {"PATH", "HOME", "LANG", "ANTHROPIC_API_KEY"}
    assert claude.env["ANTHROPIC_API_KEY"] == "test-anthropic-personal-key-" + str(ada.id)
    assert claude.argv[:3] == ["claude", "-p", "--bare"] and "--dangerously-skip-permissions" not in claude.argv

    # The issue is the coding tool's, in review, with the PR linked; a person closes it.
    issue = (await db_client.get(f"{base}/issues/{story['key']}", headers=ada.headers)).json()
    assert issue["status"] == "review" and issue["assignee_agent"] == "coding-agent"  # Kai, whatever the engine
    assert {"kind": "pr", "url": run["pr_url"], "title": "PR #1: Refund a payment"} in issue["links"]

    # The Reviewer read the PR in a conversation of its own.
    review = (await db_client.get(f"{base}/agent/runs/{run['review_run_id']}", headers=ada.headers)).json()
    assert review["status"] == "completed" and review["reply"].startswith("Looks right")
    assert "src/payments.py (+2 -1)" in review["message"] and "<repo_content" in review["message"]
    assert "## Definition of done" in review["message"] and "Added refunds" in review["message"]  # Kai's report
    assert "read review-a-backend-change, security-review, threat-model-a-feature with read_skill" in review["message"]

    actions = [e["action"] for e in (await db_client.get(f"{ws}/audit", headers=ada.headers)).json()]
    assert {"coding.requested", "coding.approved", "coding.changes_ready", "coding.changes_accepted",
            "coding.pr_opened"} <= set(actions)


async def test_an_approver_who_cant_instruct_the_coding_agent_still_approves_its_run(
    db_client: AsyncClient, coding, claude: ScriptedClaude
) -> None:
    ada, cat, ws, kun, _, _ = coding
    base = f"{ws}/projects/{kun['id']}"
    # Cat may approve agents' changes, not instruct the coding agent: approving Ada's run is enough.
    assert (await db_client.patch(ws, json={"member_permissions": ["agents:approve"]}, headers=ada.headers)).status_code == 200
    story = (await db_client.post(f"{base}/issues", headers=ada.headers, json={"type": "task", "title": "Refund a payment"})).json()
    run = (await db_client.post(f"{base}/coding/issues/{story['key']}/runs", json={}, headers=ada.headers)).json()
    assert (await db_client.post(f"{base}/coding/issues/{story['key']}/runs", json={},
                                 headers=cat.headers)).status_code in (403, 409)

    claude.edits = {"src/payments.py": "class PaymentProvider:\n    def refund(self, amount):\n        return amount\n"}
    done = await db_client.post(f"{base}/coding/runs/{run['id']}/decision", json={"decision": "approve"}, headers=cat.headers)
    assert done.status_code == 200, done.text
    issue = (await db_client.get(f"{base}/issues/{story['key']}", headers=ada.headers)).json()
    assert issue["assignee_agent"] == "coding-agent"
    # Assigning Kai by hand still needs the right to instruct it.
    other = (await db_client.post(f"{base}/issues", headers=ada.headers, json={"type": "task", "title": "t"})).json()
    refused = await db_client.patch(f"{base}/issues/{other['key']}", json={"assignee_agent": "coding-agent"}, headers=cat.headers)
    assert refused.status_code == 403


async def test_changes_to_dotrix_or_workflows_are_never_pushed(
    db_client: AsyncClient, coding, github, origin: Path, claude: ScriptedClaude
) -> None:
    ada, _, ws, kun, _, _ = coding
    base = f"{ws}/projects/{kun['id']}"
    task = (await db_client.post(f"{base}/issues", json={"type": "task", "title": "Tidy"}, headers=ada.headers)).json()
    claude.edits = {"src/payments.py": "# tidy\n", ".dotrix/requirements/x.md": "# sneaky\n"}
    run = (await db_client.post(f"{base}/coding/issues/{task['key']}/runs", json={}, headers=ada.headers)).json()
    await _approve(db_client, base, run, ada.headers)
    run = (await db_client.get(f"{base}/coding/runs/{run['id']}", headers=ada.headers)).json()
    assert run["status"] == "failed" and ".dotrix/ stays on the platform" in run["error"]
    assert run["branch"] is None and github.pulls == []
    assert _git(origin, "branch", "--list", "dotrix/*") == ""

    # Workflows likewise; and a run that changes nothing ends without a PR.
    claude.edits = {".github/workflows/ci.yml": "on: push\n"}
    run = (await db_client.post(f"{base}/coding/issues/{task['key']}/runs", json={}, headers=ada.headers)).json()
    await _approve(db_client, base, run, ada.headers)
    run = (await db_client.get(f"{base}/coding/runs/{run['id']}", headers=ada.headers)).json()
    assert run["status"] == "failed" and "CI configuration" in run["error"]
    claude.edits = {}
    run = (await db_client.post(f"{base}/coding/issues/{task['key']}/runs", json={}, headers=ada.headers)).json()
    await _approve(db_client, base, run, ada.headers)
    run = (await db_client.get(f"{base}/coding/runs/{run['id']}", headers=ada.headers)).json()
    assert run["status"] == "no_changes" and github.pulls == []


async def test_rejecting_stopping_and_when_it_isnt_available(
    db_client: AsyncClient, coding, add_member
) -> None:
    ada, cat, ws, kun, mob, sandbox = coding
    base = f"{ws}/projects/{kun['id']}"
    task = (await db_client.post(f"{base}/issues", json={"type": "task", "title": "Tidy"}, headers=ada.headers)).json()
    run = (await db_client.post(f"{base}/coding/issues/{task['key']}/runs", json={}, headers=ada.headers)).json()
    rejected = await db_client.post(f"{base}/coding/runs/{run['id']}/decision",
                                    json={"decision": "reject", "reason": "Not yet"}, headers=ada.headers)
    assert rejected.json()["status"] == "rejected" and rejected.json()["decision_reason"] == "Not yet"
    assert (await db_client.post(f"{base}/coding/runs/{run['id']}/decision", json={"decision": "approve"},
                                 headers=ada.headers)).status_code == 409

    # Stopped before it starts: whoever asked (Cat, once the workspace lets members code), or an owner.
    await db_client.patch(ws, json={"member_permissions": ["agents:code"]}, headers=ada.headers)
    run = (await db_client.post(f"{base}/coding/issues/{task['key']}/runs", json={}, headers=cat.headers)).json()
    assert run["can_stop"] and not run["can_decide"]
    stopped = (await db_client.post(f"{base}/coding/runs/{run['id']}/stop", headers=cat.headers)).json()
    assert stopped["status"] == "stopped" and sandbox.opened == 0
    assert (await db_client.post(f"{base}/coding/runs/{run['id']}/stop", headers=cat.headers)).status_code == 409
    # Cat sees their own turn on the issue, not Ada's (sessions are private, like conversations).
    assert [r["status"] for r in (await db_client.get(f"{base}/coding/runs", params={"issue": task["key"]},
                                                       headers=cat.headers)).json()] == ["stopped"]

    # MOB has no connected repo; epics are too big; nothing runs without a model key.
    mob_task = (await db_client.post(f"{ws}/projects/{mob['id']}/issues", json={"type": "task", "title": "x"},
                                     headers=ada.headers)).json()
    refused = await db_client.post(f"{ws}/projects/{mob['id']}/coding/issues/{mob_task['key']}/runs", json={},
                                   headers=ada.headers)
    assert refused.status_code == 409 and refused.json()["type"].endswith("/coding_unavailable")
    epic = (await db_client.post(f"{base}/issues", json={"type": "epic", "title": "Big"}, headers=ada.headers)).json()
    assert (await db_client.post(f"{base}/coding/issues/{epic['key']}/runs", json={},
                                 headers=ada.headers)).status_code == 422
    await db_client.delete("/v1/me/model-keys/anthropic", headers=ada.headers)
    reason = (await db_client.get(f"{base}/coding", headers=ada.headers)).json()["reason"]
    assert "Connect your own model provider" in reason


async def test_a_running_agent_is_stopped_and_nothing_is_pushed(
    db_client: AsyncClient, coding, github, claude: ScriptedClaude, monkeypatch
) -> None:
    """The worker polls for Stop while the agent works, and kills it."""
    from dotrix_backend.modules.coding import runner as runner_module

    ada, _, ws, kun, _, _ = coding
    base = f"{ws}/projects/{kun['id']}"
    monkeypatch.setattr(runner_module, "STOP_POLL_SECONDS", 0.05)
    task = (await db_client.post(f"{base}/issues", json={"type": "task", "title": "Slow"}, headers=ada.headers)).json()
    run = (await db_client.post(f"{base}/coding/issues/{task['key']}/runs", json={}, headers=ada.headers)).json()
    pressed = asyncio.Event()

    async def stop_requested(self, run_id) -> bool:  # someone pressed Stop while it worked
        return pressed.is_set()

    async def slow_exec(self, argv, *, stdin=None, on_line=None, timeout, cancel=None):
        if argv[0] != "claude":
            return await LocalSession.exec(self, argv, stdin=stdin, on_line=on_line, timeout=timeout, cancel=cancel)
        pressed.set()
        assert cancel is not None
        await asyncio.wait_for(cancel.wait(), 5)
        return ExecResult(code=None, stdout="", stderr="", cancelled=True)

    monkeypatch.setattr(CodingWorker, "stop_requested", stop_requested)
    monkeypatch.setattr(ScriptedSession, "exec", slow_exec)
    await _approve(db_client, base, run, ada.headers)
    run = (await db_client.get(f"{base}/coding/runs/{run['id']}", headers=ada.headers)).json()
    assert run["status"] == "stopped" and run["error"] == "Stopped by a person" and github.pulls == []


async def test_with_a_fork_owner_branches_go_to_the_apps_fork(
    db_client: AsyncClient, coding, github, origin: Path, tmp_path: Path, claude: ScriptedClaude, agent_script
) -> None:
    ada, _, ws, kun, _, _ = coding
    base = f"{ws}/projects/{kun['id']}"
    app = db_client._transport.app  # type: ignore[attr-defined]
    app.state.settings.coding_fork_owner = "dotrix-fork"
    fork = tmp_path / "fork"
    _git(tmp_path, "clone", "-q", "--bare", str(origin), str(fork))
    folders = {"kunemi/api": origin, "dotrix-fork/kunemi-api": fork}

    async def repo_url(ref) -> str:
        return str(folders[ref.full_name])

    jobs = app.state.jobs
    jobs.ctx = dataclasses.replace(jobs.ctx, coding=dataclasses.replace(jobs.ctx.coding, repo_url=repo_url))
    task = (await db_client.post(f"{base}/issues", json={"type": "task", "title": "Refunds"}, headers=ada.headers)).json()
    claude.edits = {"src/refunds.py": "def refund(amount):\n    return amount\n"}
    agent_script.say("Fine.", "Fine again.")
    first = (await db_client.post(f"{base}/coding/issues/{task['key']}/runs", json={}, headers=ada.headers)).json()
    first = await _approve(db_client, base, first, ada.headers)
    assert first["status"] == "pr_opened", first

    # The branch is on the fork, not the repo; the PR is the repo's, from the fork's branch.
    assert _git(fork, "rev-parse", first["branch"]) == first["commit_sha"]
    assert first["branch"] not in _git(origin, "branch", "--list")
    # (found again each time the worker takes the turn: once to code, once to push what was accepted)
    assert github.forks == 2 * [{"repo": "kunemi/api", "organization": "dotrix-fork", "name": "kunemi-api",
                                 "default_branch_only": True}]
    assert github.synced == [("dotrix-fork/kunemi-api", "main")]
    [pr] = github.pulls
    assert pr["repo"] == "kunemi/api" and pr["head"] == f"dotrix-fork:{first['branch']}" and not pr["maintainer_can_modify"]
    # The repo's token reads and opens the PR, no more; only the fork's token pushes.
    assert github.token_requests[-3:] == [
        {"repository_ids": [9001], "permissions": {"metadata": "read", "contents": "read", "pull_requests": "write"}},
        {},  # the fork organisation's, to fork
        {"repository_ids": [9700], "permissions": {"metadata": "read", "contents": "write", "pull_requests": "write"}},
    ]

    # A follow-up continues on the fork's branch, with the same fork and PR.
    claude.edits = {"src/refunds.py": "def refund(amount):\n    return -amount\n"}
    second = (await db_client.post(f"{base}/coding/sessions/{first['session_id']}/turns",
                                   json={"message": "Negative"}, headers=ada.headers)).json()
    second = await _approve(db_client, base, second, ada.headers)
    assert second["status"] == "pr_opened" and second["base_sha"] == first["commit_sha"]
    assert _git(fork, "rev-parse", f"{first['branch']}~1") == first["commit_sha"]
    assert len(github.pulls) == 1 and len(github.forks) == 4 and len(github.synced) == 1


async def test_a_session_continues_on_its_branch_and_pr(
    db_client: AsyncClient, coding, github, origin: Path, claude: ScriptedClaude, agent_script
) -> None:
    ada, cat, ws, kun, _, _ = coding
    base = f"{ws}/projects/{kun['id']}"
    task = (await db_client.post(f"{base}/issues", json={"type": "task", "title": "Refunds"}, headers=ada.headers)).json()
    claude.edits = {"src/refunds.py": "def refund(amount):\n    return amount\n"}
    agent_script.say("Fine.", "Fine again.")
    first = (await db_client.post(f"{base}/coding/issues/{task['key']}/runs", json={}, headers=ada.headers)).json()
    assert first["session_id"] == first["id"] and first["turn"] == 1 and first["origin"] == "start"
    first = await _approve(db_client, base, first, ada.headers)
    assert first["status"] == "pr_opened" and first["pr_state"] == "open"

    # A follow-up: the same agent, told what was done so far, on the same branch and PR.
    claude.result = "Refunds over £500 now need a manager."
    claude.edits = {"src/refunds.py": "def refund(amount):\n    if amount > 500:\n        raise PermissionError\n    return amount\n"}
    turns = f"{base}/coding/sessions/{first['session_id']}/turns"
    assert (await db_client.post(turns, json={"message": "Large refunds"}, headers=cat.headers)).status_code == 403
    second = await db_client.post(turns, json={"message": "Refunds over £500 need a manager"}, headers=ada.headers)
    assert second.status_code == 201, second.text
    second = second.json()
    assert (second["turn"], second["origin"], second["session_id"]) == (2, "follow_up", first["session_id"])
    assert second["branch"] == first["branch"] and second["pr_number"] == first["pr_number"]
    assert "## Earlier in this session" in second["brief"] and "Added refunds" in second["brief"]
    assert "## What to do in this turn" in second["brief"] and "over £500 need a manager" in second["brief"]
    assert (await db_client.post(turns, json={"message": "more"}, headers=ada.headers)).status_code == 409  # one waits

    second = await _approve(db_client, base, second, ada.headers)
    assert second["status"] == "pr_opened" and second["pr_number"] == first["pr_number"]
    assert len(github.pulls) == 1  # no second PR: the branch moved on
    assert _git(origin, "rev-parse", f"{first['branch']}~1") == first["commit_sha"]
    assert "PermissionError" in _git(origin, "show", f"{first['branch']}:src/refunds.py")
    assert second["base_sha"] == first["commit_sha"]  # it started from the branch, not main
    issue = (await db_client.get(f"{base}/issues/{task['key']}", headers=ada.headers)).json()
    assert [link["url"] for link in issue["links"]].count(first["pr_url"]) == 1
    assert any("Pushed turn 2 to PR #1" in (e.get("body") or "") for e in issue["log"])

    # The session's turns, and the workspace's sessions (Chat's Coding tab).
    listed = (await db_client.get(f"{base}/coding/sessions/{first['session_id']}", headers=ada.headers)).json()
    assert [t["turn"] for t in listed] == [1, 2]
    assert (await db_client.get(f"{base}/coding/sessions/{first['session_id']}", headers=cat.headers)).status_code == 404
    [session] = (await db_client.get(f"{ws}/coding/sessions", headers=ada.headers)).json()
    assert session["session_id"] == first["session_id"] and session["turns"] == 2 and session["project_key"] == "KUN"
    assert session["issue_title"] == "Refunds" and session["status"] == "pr_opened" and session["pr_number"] == 1


async def test_assigning_to_a_coding_tool_starts_a_session_and_approvers_are_told(
    db_client: AsyncClient, coding
) -> None:
    ada, cat, ws, kun, _, _ = coding
    base = f"{ws}/projects/{kun['id']}"
    task = (await db_client.post(f"{base}/issues", json={"type": "task", "title": "Export"}, headers=ada.headers)).json()

    # Cat may assign Claude Code, but may not instruct the coding agent: no session.
    await db_client.patch(f"{base}/issues/{task['key']}", json={"assignee_agent": "claude-code"}, headers=cat.headers)
    assert (await db_client.get(f"{base}/coding/runs", headers=ada.headers)).json() == []

    # Once the workspace lets members code, assigning starts one in the background.
    await db_client.patch(f"{base}/issues/{task['key']}", json={"assignee_agent": None}, headers=ada.headers)
    await db_client.patch(ws, json={"member_permissions": ["agents:code"]}, headers=ada.headers)
    await db_client.patch(f"{base}/issues/{task['key']}", json={"assignee_agent": "claude-code"}, headers=cat.headers)
    [run] = (await db_client.get(f"{base}/coding/runs", headers=ada.headers)).json()
    assert run["origin"] == "assigned" and run["status"] == "awaiting_approval"
    # Creating an issue assigned to a coding tool does the same.
    other = (await db_client.post(f"{base}/issues", headers=cat.headers,
                                  json={"type": "task", "title": "Import", "assignee_agent": "codex"})).json()
    assert [r["origin"] for r in (await db_client.get(f"{base}/coding/runs", params={"issue": other["key"]},
                                                       headers=ada.headers)).json()] == ["assigned"]

    # Ada (who may approve) is told; it counts until decided, and Cat hears the decision.
    notes = (await db_client.get(f"{ws}/notifications", params={"kind": "approval"}, headers=ada.headers)).json()
    waiting = next(n for n in notes if n["coding_run_id"] == run["id"])
    assert waiting["title"] == f"Coding {task['key']}: Export" and not waiting["resolved"]
    assert waiting["coding_session_id"] == run["session_id"] and waiting["issue_key"] == task["key"]
    assert (await db_client.get(f"{ws}/notifications/counts", headers=ada.headers)).json()["by_kind"]["approval"] == 2
    await db_client.post(f"{base}/coding/runs/{run['id']}/decision", json={"decision": "reject", "reason": "Later"},
                         headers=ada.headers)
    notes = (await db_client.get(f"{ws}/notifications", params={"kind": "approval"}, headers=ada.headers)).json()
    assert next(n for n in notes if n["coding_run_id"] == run["id"])["resolved"]
    [decided] = (await db_client.get(f"{ws}/notifications", params={"kind": "decided"}, headers=cat.headers)).json()
    assert decided["title"] == f"1 rejected: Coding {task['key']}: Export" and decided["excerpt"] == "Later"


async def test_a_merged_pr_is_recorded_on_the_session_and_the_issue(
    db_client: AsyncClient, coding, github, claude: ScriptedClaude, agent_script, deliver
) -> None:
    ada, _, ws, kun, _, _ = coding
    base = f"{ws}/projects/{kun['id']}"
    task = (await db_client.post(f"{base}/issues", json={"type": "task", "title": "Ship"}, headers=ada.headers)).json()
    claude.edits = {"src/ship.py": "SHIP = True\n"}
    agent_script.say("Fine.")
    run = (await db_client.post(f"{base}/coding/issues/{task['key']}/runs", json={}, headers=ada.headers)).json()
    run = await _approve(db_client, base, run, ada.headers)
    payload = {"action": "closed", "pull_request": {"number": run["pr_number"], "merged": True},
               "repository": {"id": 9001, "full_name": "kunemi/api"}}
    assert (await deliver("pull_request", payload)).status_code == 202
    run = (await db_client.get(f"{base}/coding/runs/{run['id']}", headers=ada.headers)).json()
    assert run["pr_state"] == "merged"
    issue = (await db_client.get(f"{base}/issues/{task['key']}", headers=ada.headers)).json()
    assert issue["status"] == "review"  # a person closes it
    assert any(e.get("body") == f"PR #{run['pr_number']} was merged on GitHub" for e in issue["log"])

    # The session stays open: more work starts from the default branch, on a new branch and PR.
    [listed] = (await db_client.get(f"{ws}/coding/sessions", headers=ada.headers)).json()
    assert listed["state"] != "closed"
    agent_script.say("Fine again.")
    claude.edits = {"src/ship.py": "SHIP = True\nVERSION = 2\n"}
    turns = f"{base}/coding/sessions/{run['session_id']}/turns"
    more = (await db_client.post(turns, json={"message": "Add a version"}, headers=ada.headers)).json()
    assert more["branch"] is None and more["pr_number"] is None
    more = await _approve(db_client, base, more, ada.headers)
    assert more["status"] == "pr_opened", more.get("error")
    assert more["branch"] != run["branch"] and more["pr_number"] != run["pr_number"]
    assert len(github.pulls) == 2 and github.pulls[-1]["base"] == "main"


PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40


class ShootingSession(ScriptedSession):
    """A sandbox where the agent's browser left a screenshot, a copy of it, and a file that only looks like one."""

    async def exec(self, argv, *, stdin=None, on_line=None, timeout, cancel=None) -> ExecResult:
        if argv[:2] == ["sh", "-c"] and argv[2] == SHOTS_LIST:
            return ExecResult(code=0, stdout="/tmp/playwright/page-subtract.png\n/tmp/page-subtract.png\n/tmp/notes.png\n", stderr="")
        if argv[:2] == ["sh", "-c"] and "base64 -w0" in argv[2]:
            data = PNG if "page-subtract.png" in argv[2] else b"not an image at all"
            return ExecResult(code=0, stdout=base64.b64encode(data).decode(), stderr="")
        return await super().exec(argv, stdin=stdin, on_line=on_line, timeout=timeout, cancel=cancel)


class ShootingSandbox(ScriptedSandbox):
    kind = "docker"  # screenshots are kept from the coding image's sandboxes, never the local one

    async def open(self, run_id, source, tool, model_key):
        session = await super().open(run_id, source, tool, model_key)
        return ShootingSession(session.root, session.env, self.agent)


async def test_the_agent_s_screenshots_are_kept_and_shown(
    db_client: AsyncClient, coding, claude: ScriptedClaude, agent_script, storage
) -> None:
    ada, cat, ws, kun, _, _ = coding
    app = db_client._transport.app  # type: ignore[attr-defined]
    jobs = app.state.jobs
    jobs.ctx = dataclasses.replace(jobs.ctx, coding=dataclasses.replace(jobs.ctx.coding, sandbox=ShootingSandbox(claude), storage=storage))
    base = f"{ws}/projects/{kun['id']}"
    issue = (await db_client.post(f"{base}/issues", headers=ada.headers, json={"title": "Add a Subtract button"})).json()
    run = (await db_client.post(f"{base}/coding/issues/{issue['key']}/runs", json={}, headers=ada.headers)).json()
    claude.edits = {"src/payments.py": "class PaymentProvider:\n    def subtract(self): ...\n"}
    agent_script.say("Looks right.")
    run = await _approve(db_client, base, run, ada.headers)
    assert run["status"] == "pr_opened", run.get("error")
    # Images only, whatever the name says, and each once; listed on the run, served to whoever's session it is.
    assert run["screenshots"] == [{"index": 0, "name": "page-subtract.png", "size": len(PNG), "content_type": "image/png"}]
    assert any(e["text"] == "Kept 1 screenshot from the browser" for e in run["events"])
    shot = await db_client.get(f"{base}/coding/runs/{run['id']}/screenshots/0", headers=ada.headers)
    assert shot.status_code == 200 and shot.content == PNG and shot.headers["content-type"] == "image/png"
    assert (await db_client.get(f"{base}/coding/runs/{run['id']}/screenshots/1", headers=ada.headers)).status_code == 404
    assert (await db_client.get(f"{base}/coding/runs/{run['id']}/screenshots/0", headers=cat.headers)).status_code == 404


async def test_every_event_is_kept_and_read_a_page_at_a_time(
    db_client: AsyncClient, coding, claude: ScriptedClaude, agent_script
) -> None:
    """The run keeps its latest 300 events for quick reads; coding_events keeps every one, in order.
    The events come from the agent while it works: a finished run takes no more (#139)."""
    ada, _, ws, kun, _, _ = coding
    base = f"{ws}/projects/{kun['id']}"
    issue = (await db_client.post(f"{base}/issues", headers=ada.headers, json={"title": "Tidy payments"})).json()
    run = (await db_client.post(f"{base}/coding/issues/{issue['key']}/runs", json={}, headers=ada.headers)).json()
    claude.edits = {"src/payments.py": "# tidy\n"}
    steps = [json.dumps({"type": "assistant", "message": {"id": f"s{i}", "content": [
        {"type": "tool_use", "name": "Bash", "input": {"command": f"step {i}"}}]}}) + "\n" for i in range(350)]
    scripted = claude.lines
    claude.lines = lambda: [*scripted()[:1], *steps, *scripted()[1:]]  # type: ignore[method-assign]
    agent_script.say("Fine.")
    read = await _approve(db_client, base, run, ada.headers)
    assert read["status"] == "pr_opened", read
    total = read["event_count"]
    assert total > 350 and len(read["events"]) == 300 and "Ran step 349" in [e["text"] for e in read["events"]]
    first = (await db_client.get(f"{base}/coding/runs/{run['id']}/events", params={"limit": 100}, headers=ada.headers)).json()
    assert [e["seq"] for e in first["events"]] == list(range(100)) and first["next"] == 99
    seen, after = list(first["events"]), first["next"]
    while after is not None:
        page = (await db_client.get(f"{base}/coding/runs/{run['id']}/events", params={"after": after, "limit": 1000},
                                    headers=ada.headers)).json()
        seen += page["events"]
        after = page["next"]
    assert len(seen) == total and [e["seq"] for e in seen] == list(range(total))
    texts = [e["text"] for e in seen]
    assert [t for t in texts if t.startswith("Ran step ")] == [f"Ran step {i}" for i in range(350)]


class TranscriptSession(ScriptedSession):
    """Claude Code keeps its conversation under ~/.claude: this one writes a transcript there, and
    notes whether one was already there when a turn started (a warm sandbox, or one restored)."""

    async def exec(self, argv, *, stdin=None, on_line=None, timeout, cancel=None) -> ExecResult:
        if argv[0] == "claude":
            transcript = Path(self.env["HOME"]) / ".claude" / "projects" / "-repo" / "conversation.jsonl"
            self.agent.found_transcript.append(transcript.read_text() if transcript.exists() else None)
            transcript.parent.mkdir(parents=True, exist_ok=True)
            transcript.write_text((transcript.read_text() if transcript.exists() else "") + f"turn {len(self.agent.found_transcript)}\n")
            self.agent.argvs.append(list(argv))
        return await super().exec(argv, stdin=stdin, on_line=on_line, timeout=timeout, cancel=cancel)


class TranscriptSandbox(ScriptedSandbox):
    async def open(self, run_id, source, tool, model_key):
        session = await super().open(run_id, source, tool, model_key)
        return TranscriptSession(session.root, session.env, self.agent)


async def test_a_session_keeps_its_sandbox_and_resumes_its_conversation(
    db_client: AsyncClient, coding, github, claude: ScriptedClaude, agent_script, storage
) -> None:
    """Phase B: a follow-up runs in the sandbox the last turn left (warm), resuming Claude Code's
    conversation; after a restart a fresh sandbox gets the saved transcript and still resumes; closing
    the session drops the sandbox and the transcript."""


    ada, _, ws, kun, _, _ = coding
    app = db_client._transport.app  # type: ignore[attr-defined]
    jobs = app.state.jobs
    sandbox = TranscriptSandbox(claude)
    worker = dataclasses.replace(jobs.ctx.coding, sandbox=sandbox, storage=storage,
                                 secrets=app.state.secrets, pool=WarmPool(3600, 3))
    jobs.ctx = dataclasses.replace(jobs.ctx, coding=worker)
    claude.found_transcript, claude.argvs = [], []
    base = f"{ws}/projects/{kun['id']}"
    task = (await db_client.post(f"{base}/issues", json={"type": "task", "title": "Refunds"}, headers=ada.headers)).json()
    agent_script.say("Fine.", "Fine again.", "And again.")

    # Turn 1: a fresh sandbox, a new conversation; the sandbox stays up, the transcript is saved.
    claude.edits = {"src/refunds.py": "def refund(amount):\n    return amount\n"}
    first = (await db_client.post(f"{base}/coding/issues/{task['key']}/runs", json={}, headers=ada.headers)).json()
    first = await _approve(db_client, base, first, ada.headers)
    assert first["status"] == "pr_opened" and sandbox.opened == 1
    session_id = first["session_id"]
    conversation = claude.argvs[0][claude.argvs[0].index("--session-id") + 1]
    [listed] = (await db_client.get(f"{ws}/coding/sessions", headers=ada.headers)).json()
    assert listed["state"] == "warm" and worker.pool.sessions() == [uuid.UUID(session_id)]
    assert any(k.endswith(f"/sessions/{session_id}/transcript") for k in storage.objects)

    # Turn 2: the same sandbox (no new one), resuming the same conversation.
    claude.edits = {"src/refunds.py": "def refund(amount):\n    assert amount > 0\n    return amount\n"}
    turns = f"{base}/coding/sessions/{session_id}/turns"
    second = (await db_client.post(turns, json={"message": "Only positive amounts"}, headers=ada.headers)).json()
    second = await _approve(db_client, base, second, ada.headers)
    assert second["status"] == "pr_opened" and sandbox.opened == 1
    assert claude.argvs[1][claude.argvs[1].index("--resume") + 1] == conversation
    assert claude.found_transcript[1] == "turn 1\n"  # the warm sandbox still had it
    assert any("kept from the last turn" in e["text"] and "continuing the session" in e["text"] for e in second["events"])
    assert second["files_changed"] == [{"path": "src/refunds.py", "added": 1, "removed": 0}]  # only this turn's change

    # A restart: no warm sandbox. Turn 3 gets a fresh one with the transcript restored, and resumes.
    await worker.pool.close_all()
    claude.edits = {"src/refunds.py": "def refund(amount):\n    assert amount > 0, 'positive'\n    return amount\n"}
    third = (await db_client.post(turns, json={"message": "Say why"}, headers=ada.headers)).json()
    third = await _approve(db_client, base, third, ada.headers)
    assert third["status"] == "pr_opened" and sandbox.opened == 2
    assert claude.found_transcript[2] == "turn 1\nturn 2\n"  # restored from storage
    assert claude.argvs[2][claude.argvs[2].index("--resume") + 1] == conversation

    # Closing it by hand: its sandbox goes; its transcript, branch, and PR stay.
    assert (await db_client.post(f"{base}/coding/sessions/{session_id}/close", headers=ada.headers)).status_code == 204
    await worker.reap()
    assert worker.pool.sessions() == [] and any(k.endswith(f"/sessions/{session_id}/transcript") for k in storage.objects)
    [listed] = (await db_client.get(f"{ws}/coding/sessions", headers=ada.headers)).json()
    assert listed["state"] == "closed" and listed["pr_number"] == first["pr_number"]

    # A new turn opens it again and resumes from the transcript.
    agent_script.say("Once more.")
    claude.edits = {"src/refunds.py": "def refund(amount):\n    assert amount > 0, 'must be positive'\n    return amount\n"}
    fourth = (await db_client.post(turns, json={"message": "Clearer message"}, headers=ada.headers)).json()
    fourth = await _approve(db_client, base, fourth, ada.headers)
    assert fourth["status"] == "pr_opened" and claude.found_transcript[3] == "turn 1\nturn 2\nturn 3\n"
    [listed] = (await db_client.get(f"{ws}/coding/sessions", headers=ada.headers)).json()
    assert listed["state"] == "warm"

    # Renamed, pinned, archived (hidden from the list unless asked for).
    patch = f"{base}/coding/sessions/{session_id}"
    assert (await db_client.patch(patch, json={"title": "Refund rules", "pinned": True}, headers=ada.headers)).status_code == 204
    [listed] = (await db_client.get(f"{ws}/coding/sessions", headers=ada.headers)).json()
    assert listed["title"] == "Refund rules" and listed["pinned"] and listed["issue_title"] == "Refunds"
    assert (await db_client.patch(patch, json={"archived": True}, headers=ada.headers)).status_code == 204
    assert (await db_client.get(f"{ws}/coding/sessions", headers=ada.headers)).json() == []
    [listed] = (await db_client.get(f"{ws}/coding/sessions", params={"archived": "only"}, headers=ada.headers)).json()
    assert listed["archived"]

    # Deleting it: its turns and transcript go (and its sandbox); the PR stays on GitHub.
    assert (await db_client.delete(patch, headers=ada.headers)).status_code == 204
    await worker.reap()
    assert not any(k.endswith("/transcript") for k in storage.objects) and worker.pool.sessions() == []
    assert (await db_client.get(f"{ws}/coding/sessions", params={"archived": "include"}, headers=ada.headers)).json() == []
    assert (await db_client.get(f"{base}/coding/runs/{first['id']}", headers=ada.headers)).status_code == 404
    assert len(github.pulls) == 1


async def test_opencode_codes_on_the_model_the_server_names(
    db_client: AsyncClient, coding, github, origin: Path, agent_script
) -> None:
    ada, _, ws, kun, _, sandbox = coding
    settings = db_client._transport.app.state.settings  # type: ignore[attr-defined]
    settings.coding_agent, settings.coding_opencode_model = "opencode", "openai:gpt-5.5"
    await _save_key(db_client, ada.headers, "openai", "test-opencode-openai-personal-key")
    opencode = sandbox.agent = ScriptedOpenCode()
    opencode.edits = {"src/refunds.py": "def refund(amount):\n    return amount\n"}
    opencode.result = "Added refund()."
    agent_script.say("Fine.")
    base = f"{ws}/projects/{kun['id']}"
    task = (await db_client.post(f"{base}/issues", json={"type": "task", "title": "Refunds"}, headers=ada.headers)).json()

    assert (await db_client.get(f"{base}/coding", headers=ada.headers)).json()["agent"] == "opencode"
    run = (await db_client.post(f"{base}/coding/issues/{task['key']}/runs", json={}, headers=ada.headers)).json()
    assert run["agent"] == "opencode" and run["model"] == "openai:gpt-5.5"
    run = await _approve(db_client, base, run, ada.headers)
    assert run["status"] == "pr_opened", run
    assert run["summary"] == "Added refund()." and "Edited src/refunds.py" in [e["text"] for e in run["events"]]
    # The step its events left out, from the session's totals; the cost is the session's.
    assert (run["input_tokens"], run["output_tokens"], run["cost_usd"]) == (1500, 250, 0.2)
    # Its own config, the provider's model, our session id; only the provider's key in its environment.
    assert opencode.argv[0] == "env" and opencode.argv[opencode.argv.index("opencode"):-1] == [
        "opencode", "run", "--standalone", "--format", "json", "--auto", "-m", "openai/gpt-5.5", "-s"]
    assert re.fullmatch(r"ses_[0-9a-f]{32}", opencode.argv[-1])  # the session's own id: made, then continued
    assert "OPENCODE_DISABLE_PROJECT_CONFIG=1" in opencode.argv
    assert set(opencode.env) == {"PATH", "HOME", "LANG", "OPENAI_API_KEY"}
    assert opencode.env["OPENAI_API_KEY"] == "test-opencode-openai-personal-key"
    # OpenCode isn't an assignee of its own: the issue shows the built-in coding agent.
    issue = (await db_client.get(f"{base}/issues/{task['key']}", headers=ada.headers)).json()
    assert issue["status"] == "review" and issue["assignee_agent"] == "coding-agent"
    [pr] = github.pulls
    assert "Written by Kai in a dotrix coding run" in pr["body"] and "opencode" not in pr["body"].lower()


async def _opencode_turn(db_client: AsyncClient, coding, *, input_tokens: int = 1000, error: str | None = None) -> dict:
    ada, _, ws, kun, _, sandbox = coding
    settings = db_client._transport.app.state.settings  # type: ignore[attr-defined]
    settings.coding_agent, settings.coding_opencode_model = "opencode", "anthropic:claude-haiku-5-5"
    opencode = sandbox.agent = ScriptedOpenCode()
    opencode.input_tokens = input_tokens
    opencode.edits, opencode.error = {"src/refunds.py": "def refund(amount):\n    return amount\n"}, error
    base = f"{ws}/projects/{kun['id']}"
    task = (await db_client.post(f"{base}/issues", json={"type": "task", "title": "Refunds"}, headers=ada.headers)).json()
    run = (await db_client.post(f"{base}/coding/issues/{task['key']}/runs", json={}, headers=ada.headers)).json()
    return await _approve(db_client, base, run, ada.headers)


async def test_opencode_records_large_byok_usage_without_a_platform_cap(db_client: AsyncClient, coding, github, agent_script) -> None:
    agent_script.say("Fine.")
    run = await _opencode_turn(db_client, coding, input_tokens=4_000_000)
    assert run["status"] == "pr_opened", run
    assert run["input_tokens"] + run["output_tokens"] == 4_000_750 and run["pr_number"] is not None
    assert len(github.pulls) == 1


async def test_a_failed_opencode_turn_keeps_its_usage(db_client: AsyncClient, coding, github) -> None:
    run = await _opencode_turn(db_client, coding, error="invalid x-api-key")
    assert run["status"] == "failed" and "invalid x-api-key" in (run["error"] or ""), run
    assert (run["input_tokens"], run["output_tokens"], run["cost_usd"]) == (1500, 250, 0.2) and github.pulls == []


async def test_coding_uses_only_the_requesters_own_key(db_client: AsyncClient, coding, claude: ScriptedClaude, agent_script) -> None:
    ada, cat, ws, kun, _, _ = coding
    app = db_client._transport.app  # type: ignore[attr-defined]
    own_key = "test-personal-coding-key-" + "x" * 24
    app.state.settings.anthropic_api_key = SecretStr("legacy-server-key-never-used")
    app.state.settings.server_model_keys = True
    await _save_key(db_client, ada.headers, "anthropic", own_key)
    base = f"{ws}/projects/{kun['id']}"
    claude.edits = {"src/payments.py": "# tidy\n"}
    task = (await db_client.post(f"{base}/issues", json={"type": "task", "title": "Tidy payments"}, headers=ada.headers)).json()
    request = await db_client.post(f"{base}/coding/issues/{task['key']}/runs", json={}, headers=ada.headers)
    agent_script.say("Fine.")
    done = await _approve(db_client, base, request.json(), ada.headers)
    assert done["status"] == "pr_opened" and claude.env["ANTHROPIC_API_KEY"] == own_key
    await db_client.delete("/v1/me/model-keys/anthropic", headers=ada.headers)
    assert not (await db_client.get(f"{base}/coding", headers=ada.headers)).json()["available"]
    assert (await db_client.get(f"{base}/coding", headers=cat.headers)).json()["available"]


# -- recovery: leases, fencing, and settling an uncertain run from what GitHub shows ---------------


async def _set_run(db_client: AsyncClient, run_id: str, **values: Any) -> None:
    factory = db_client._transport.app.state.jobs.ctx.session_factory  # type: ignore[attr-defined]
    async with factory() as session:
        await session.execute(update(CodingRun).where(CodingRun.id == uuid.UUID(run_id)).values(**values))
        await session.commit()


async def _asked(db_client: AsyncClient, coding, title: str = "Refund a payment") -> tuple[str, dict[str, Any]]:
    ada, _, ws, kun, _, _ = coding
    base = f"{ws}/projects/{kun['id']}"
    issue = (await db_client.post(f"{base}/issues", headers=ada.headers, json={"type": "task", "title": title})).json()
    run = (await db_client.post(f"{base}/coding/issues/{issue['key']}/runs", json={}, headers=ada.headers)).json()
    assert run["status"] == "awaiting_approval", run
    return base, run


async def test_tool_choice_personal_default_and_session_tool_are_kept(db_client: AsyncClient, coding) -> None:
    ada, _, ws, kun, _, _ = coding
    await _save_key(db_client, ada.headers, "openai", "test-openai-personal-provider-key")
    await _save_key(db_client, ada.headers, "xai", "test-xai-personal-provider-key")
    base = f"{ws}/projects/{kun['id']}"
    await db_client.put("/v1/me/coding-tool", json={"default_coding_tool": "claude-code"}, headers=ada.headers)
    available = (await db_client.get(f"{base}/coding", headers=ada.headers)).json()
    assert available["default_tool"] == "claude-code"
    assert {t["agent"] for t in available["tools"] if t["available"]} == {"claude-code", "codex", "opencode", "fx"}
    task = (await db_client.post(f"{base}/issues", json={"type": "task", "title": "Tool choice"}, headers=ada.headers)).json()
    first = await db_client.post(f"{base}/coding/issues/{task['key']}/runs",
                                 json={"agent": "opencode", "model": "xai:grok-4.7"}, headers=ada.headers)
    assert first.status_code == 201, first.text
    run = first.json()
    assert (run["agent"], run["model"]) == ("opencode", "xai:grok-4.7")
    await db_client.post(f"{base}/coding/runs/{run['id']}/decision", json={"decision": "reject"}, headers=ada.headers)
    await db_client.put("/v1/me/coding-tool", json={"default_coding_tool": "codex"}, headers=ada.headers)
    follow = await db_client.post(f"{base}/coding/sessions/{run['session_id']}/turns",
                                  json={"message": "Try this approach instead"}, headers=ada.headers)
    assert follow.status_code == 201, follow.text
    assert (follow.json()["agent"], follow.json()["model"]) == ("opencode", "xai:grok-4.7")


async def test_fx_is_offered_and_keeps_its_model(db_client: AsyncClient, coding) -> None:
    ada, _, ws, kun, _, _ = coding
    await _save_key(db_client, ada.headers, "openai", "test-openai-personal-provider-key")
    base = f"{ws}/projects/{kun['id']}"
    task = (await db_client.post(f"{base}/issues", json={"type": "task", "title": "fx"}, headers=ada.headers)).json()
    settings = db_client._transport.app.state.settings  # type: ignore[attr-defined]
    settings.coding_fx_model = "openai:gpt-6.1"
    on = (await db_client.get(f"{base}/coding", headers=ada.headers)).json()
    fx = next(t for t in on["tools"] if t["agent"] == "fx")
    assert fx["available"] and fx["model"] == "openai:gpt-6.1" and "openai:gpt-6.1" in fx["models"]
    assert on["default_tool"] == "codex"  # never chosen for someone who didn't pick it
    wrong = await db_client.post(f"{base}/coding/issues/{task['key']}/runs",
                                 json={"agent": "fx", "model": "google_genai:gemini-3.8-flash"}, headers=ada.headers)
    assert wrong.status_code == 422
    asked = await db_client.post(f"{base}/coding/issues/{task['key']}/runs", json={"agent": "fx"}, headers=ada.headers)
    assert asked.status_code == 201, asked.text
    assert (asked.json()["agent"], asked.json()["model"]) == ("fx", "openai:gpt-6.1")


async def test_a_new_session_codes_on_your_model_and_the_engine_follows_it(db_client: AsyncClient, coding) -> None:
    ada, _, ws, kun, _, _ = coding
    await _save_key(db_client, ada.headers, "openai", "test-openai-personal-provider-key")
    await _save_key(db_client, ada.headers, "xai", "test-xai-personal-provider-key")
    base = f"{ws}/projects/{kun['id']}"
    available = (await db_client.get(f"{base}/coding", headers=ada.headers)).json()
    grok = next(m for m in available["models"] if m.startswith("xai:"))
    gpt = next(m for m in available["models"] if m.startswith("openai:"))
    saved = await db_client.put("/v1/me/models", json={"default_model": grok}, headers=ada.headers)
    assert saved.status_code == 200, saved.text
    assert (await db_client.get(f"{base}/coding", headers=ada.headers)).json()["default_model"] == grok

    async def start(body: dict) -> dict:
        issue = (await db_client.post(f"{base}/issues", json={"type": "task", "title": "Model"}, headers=ada.headers)).json()
        made = await db_client.post(f"{base}/coding/issues/{issue['key']}/runs", json=body, headers=ada.headers)
        assert made.status_code == 201, made.text
        return made.json()

    run = await start({})  # nothing picked: your default model, and the engine that runs it
    assert (run["agent"], run["model"]) == ("opencode", grok)
    run = await start({"model": gpt})
    assert (run["agent"], run["model"]) == ("codex", gpt)
    await db_client.put("/v1/me/coding-tool", json={"default_coding_tool": "opencode"}, headers=ada.headers)
    run = await start({"model": gpt})  # your preferred engine, where it can run the model
    assert (run["agent"], run["model"]) == ("opencode", gpt)
    refused = await db_client.post(f"{base}/coding/issues/{(await db_client.post(f'{base}/issues', json={'type': 'task', 'title': 'x'}, headers=ada.headers)).json()['key']}/runs",
                                   json={"model": "openai:not-a-catalogue-model"}, headers=ada.headers)
    assert refused.status_code == 422  # not one of your models


async def test_approval_needs_the_recorded_tools_key_even_if_another_tool_is_available(db_client: AsyncClient, coding) -> None:
    ada, _, ws, kun, _, _ = coding
    await _save_key(db_client, ada.headers, "openai", "test-openai-personal-provider-key")
    base = f"{ws}/projects/{kun['id']}"
    task = (await db_client.post(f"{base}/issues", json={"type": "task", "title": "Recorded provider"}, headers=ada.headers)).json()
    request = await db_client.post(f"{base}/coding/issues/{task['key']}/runs", json={"agent": "codex"}, headers=ada.headers)
    assert request.status_code == 201, request.text
    await db_client.delete("/v1/me/model-keys/openai", headers=ada.headers)
    result = await db_client.post(f"{base}/coding/runs/{request.json()['id']}/decision",
                                  json={"decision": "approve"}, headers=ada.headers)
    assert result.status_code == 409 and "provider key" in result.text and "codex" not in result.text.lower()


def _heads(origin: Path):
    def head(full_name: str, branch: str) -> str | None:
        found = subprocess.run(["git", "-C", str(origin), "rev-parse", "--verify", "-q", f"refs/heads/{branch}"],
                               capture_output=True, text=True)
        return found.stdout.strip() or None
    return head


async def test_a_run_cut_off_before_it_published_runs_again(
    db_client: AsyncClient, coding, github, origin: Path, claude: ScriptedClaude
) -> None:
    ada, cat, *_ = coding
    github.branch_heads = _heads(origin)
    base, run = await _asked(db_client, coding)
    # Its worker took it and died: the lease ran out, nothing reached GitHub.
    await _set_run(db_client, run["id"], status=CodingRunStatus.RUNNING, lease_token=1, decided_by_id=ada.id,
                   lease_expires_at=datetime.now(UTC) - timedelta(seconds=5), started_at=datetime.now(UTC))
    assert await expire_coding_leases(db_client._transport.app.state.jobs.ctx.session_factory) == 1  # type: ignore[attr-defined]
    seen = (await db_client.get(f"{base}/coding/runs/{run['id']}", headers=ada.headers)).json()
    assert seen["status"] == "recovery_required" and seen["can_recover"] and not seen["can_stop"]
    assert "lease" in seen["error"]
    # Cat didn't ask for it (and doesn't see it); Stop isn't how it's settled.
    assert (await db_client.get(f"{base}/coding/runs/{run['id']}", headers=cat.headers)).status_code == 404
    assert (await db_client.post(f"{base}/coding/runs/{run['id']}/recover", json={"action": "check"},
                                 headers=cat.headers)).status_code == 404
    assert (await db_client.post(f"{base}/coding/runs/{run['id']}/stop", headers=ada.headers)).status_code == 409

    claude.edits = {"src/payments.py": "class PaymentProvider:\n    def refund(self, amount):\n        return amount\n"}
    recovered = await db_client.post(f"{base}/coding/runs/{run['id']}/recover", json={"action": "check"}, headers=ada.headers)
    assert recovered.status_code == 200, recovered.text
    ready = recovered.json()
    assert ready["status"] == "changes_ready", ready  # the turn ran again, on a new lease (Manual: it waits)
    done = await _approve(db_client, base, ready, ada.headers)
    assert done["status"] == "pr_opened" and done["pr_number"] == 1, done
    assert "Recovered: nothing was published; running the turn again" in [e["text"] for e in done["events"]]
    assert _git(origin, "rev-parse", done["branch"]) == done["commit_sha"]
    async with db_client._transport.app.state.jobs.ctx.session_factory() as session:  # type: ignore[attr-defined]
        row = await session.get(CodingRun, uuid.UUID(run["id"]))
        assert row is not None and row.lease_token == 3 and row.lease_expires_at is None  # coded, pushed; released
    audit = (await db_client.get(f"{coding[2]}/audit", headers=ada.headers)).json()
    assert any(e["action"] == "coding.recovered" and e["details"]["outcome"] == "retried" for e in audit)


async def test_a_lost_pr_reply_is_settled_from_github(
    db_client: AsyncClient, coding, github, origin: Path, claude: ScriptedClaude
) -> None:
    ada, *_ = coding
    github.branch_heads = _heads(origin)
    base, run = await _asked(db_client, coding)
    claude.edits = {"src/payments.py": "class PaymentProvider:\n    def refund(self, amount):\n        return amount\n"}
    github.fail_pulls = 1  # the push lands; the PR request's reply is lost
    await _approve(db_client, base, run, ada.headers)
    run = (await db_client.get(f"{base}/coding/runs/{run['id']}", headers=ada.headers)).json()
    assert run["status"] == "recovery_required" and run["pr_number"] is None and run["can_recover"]
    assert _git(origin, "rev-parse", run["branch"]) == run["commit_sha"]

    # The push landed and no PR is there: recovery opens it, as the approved run would have.
    opened = (await db_client.post(f"{base}/coding/runs/{run['id']}/recover", json={"action": "check"},
                                   headers=ada.headers)).json()
    assert opened["status"] == "pr_opened" and opened["pr_number"] == 1, opened
    [pr] = github.pulls
    assert pr["head"] == run["branch"] and pr["base"] == "main"
    issue = (await db_client.get(f"{base}/issues/{run['issue_key']}", headers=ada.headers)).json()
    assert issue["status"] == "review" and any(link["url"] == opened["pr_url"] for link in issue["links"])

    # Had the PR been opened with its reply lost, recovery finds it rather than opening another,
    # as it is now (closed meanwhile, say: the next turn then starts a new branch and PR).
    await _set_run(db_client, run["id"], status=CodingRunStatus.RECOVERY_REQUIRED, pr_number=None, pr_url=None)
    github.pulls[0]["state"] = "closed"
    adopted = (await db_client.post(f"{base}/coding/runs/{run['id']}/recover", json={"action": "check"},
                                    headers=ada.headers)).json()
    assert adopted["status"] == "pr_opened" and adopted["pr_number"] == 1 and len(github.pulls) == 1
    assert adopted["pr_state"] == "closed"
    assert (await db_client.post(f"{base}/coding/runs/{run['id']}/recover", json={"action": "check"},
                                 headers=ada.headers)).status_code == 409  # settled


async def test_a_stopped_run_is_never_published_or_run_again_by_recovery(
    db_client: AsyncClient, coding, github, origin: Path, claude: ScriptedClaude
) -> None:
    ada, *_ = coding
    github.branch_heads = _heads(origin)
    base, run = await _asked(db_client, coding)
    claude.edits = {"src/payments.py": "class PaymentProvider:\n    def refund(self, amount):\n        return amount\n"}
    github.fail_pulls = 1
    await _approve(db_client, base, run, ada.headers)
    # Stopped after its push, before its PR (the Stop that came in as the reply was lost).
    await _set_run(db_client, run["id"], stop_requested=True)
    stopped = (await db_client.post(f"{base}/coding/runs/{run['id']}/recover", json={"action": "check"},
                                    headers=ada.headers)).json()
    assert stopped["status"] == "stopped" and "no PR was opened" in stopped["error"] and not github.pulls
    # And one stopped before it published anything isn't run again.
    _, other = await _asked(db_client, coding, "Another")
    await _set_run(db_client, other["id"], status=CodingRunStatus.RECOVERY_REQUIRED, lease_token=1, stop_requested=True)
    again = (await db_client.post(f"{base}/coding/runs/{other['id']}/recover", json={"action": "check"},
                                  headers=ada.headers)).json()
    assert again["status"] == "stopped" and again["error"] == "Stopped before it published anything"


async def test_a_branch_that_moved_on_waits_for_a_person(
    db_client: AsyncClient, coding, github, origin: Path, claude: ScriptedClaude
) -> None:
    ada, *_ = coding
    base, run = await _asked(db_client, coding)
    claude.edits = {"src/payments.py": "class PaymentProvider:\n    def refund(self, amount):\n        return amount\n"}
    github.fail_pulls = 1
    await _approve(db_client, base, run, ada.headers)
    github.branch_heads = lambda full_name, branch: "f" * 40  # neither this turn's commit nor its base
    unclear = (await db_client.post(f"{base}/coding/runs/{run['id']}/recover", json={"action": "check"},
                                    headers=ada.headers)).json()
    assert unclear["status"] == "recovery_required" and "moved on" in unclear["error"] and not github.pulls
    discarded = (await db_client.post(f"{base}/coding/runs/{run['id']}/recover", json={"action": "discard"},
                                      headers=ada.headers)).json()
    assert discarded["status"] == "failed" and discarded["error"].startswith("Discarded")


async def test_recovery_waits_for_a_live_lease_and_gives_up_after_two_attempts(
    db_client: AsyncClient, coding, github, origin: Path
) -> None:
    ada, *_ = coding
    github.branch_heads = _heads(origin)
    base, run = await _asked(db_client, coding)
    await _set_run(db_client, run["id"], status=CodingRunStatus.RECOVERY_REQUIRED, lease_token=2,
                   lease_expires_at=datetime.now(UTC) + timedelta(seconds=60))
    busy = await db_client.post(f"{base}/coding/runs/{run['id']}/recover", json={"action": "check"}, headers=ada.headers)
    assert busy.status_code == 409 and "still be working" in busy.json()["detail"]
    await _set_run(db_client, run["id"], lease_expires_at=None)
    failed = (await db_client.post(f"{base}/coding/runs/{run['id']}/recover", json={"action": "check"},
                                   headers=ada.headers)).json()
    assert failed["status"] == "failed" and failed["error"].startswith("Cut off 2 times")


async def test_the_sweep_settles_each_uncertain_run_once(db_client: AsyncClient, coding, github, origin: Path) -> None:
    github.branch_heads = _heads(origin)
    _, run = await _asked(db_client, coding)
    await _set_run(db_client, run["id"], status=CodingRunStatus.RECOVERY_REQUIRED, lease_token=1)
    app = db_client._transport.app  # type: ignore[attr-defined]
    factory, worker = app.state.jobs.ctx.session_factory, app.state.jobs.ctx.coding
    queued: list[uuid.UUID] = []

    async def requeue(session, row) -> None:
        queued.append(row.id)

    assert await recover_uncertain_runs(factory, worker.app, worker.settings, requeue) == 1
    assert queued == [uuid.UUID(run["id"])]
    async with factory() as session:
        row = await session.get(CodingRun, uuid.UUID(run["id"]))
        assert row is not None and row.status is CodingRunStatus.QUEUED and row.recovery_checked_at is not None
        row.status = CodingRunStatus.RECOVERY_REQUIRED  # cut off again: a person settles it this time
        await session.commit()
    assert await recover_uncertain_runs(factory, worker.app, worker.settings, requeue) == 0


async def test_a_worker_that_lost_its_lease_is_fenced_off(db_client: AsyncClient, coding, github) -> None:
    _, run = await _asked(db_client, coding)
    app = db_client._transport.app  # type: ignore[attr-defined]
    worker, settings = app.state.jobs.ctx.coding, app.state.settings
    run_id = uuid.UUID(run["id"])
    await _set_run(db_client, run["id"], status=CodingRunStatus.RUNNING, lease_token=1,
                   lease_expires_at=datetime.now(UTC) + timedelta(seconds=1))
    lease = _LEASE.set(1)  # this test's task is the worker's attempt with token 1
    before, settings.coding_lease_seconds = settings.coding_lease_seconds, 0.3  # renewed every 0.1 s
    try:
        holding = asyncio.create_task(worker._hold_lease(run_id, 1))
        await asyncio.sleep(0.25)
        async with app.state.jobs.ctx.session_factory() as session:
            row = await session.get(CodingRun, run_id)
            assert row is not None and row.lease_expires_at < datetime.now(UTC) + timedelta(seconds=0.35)  # renewed
        assert not await worker.stop_requested(run_id)
        # Recovery gave the run to another attempt: this worker's lease is gone.
        await _set_run(db_client, run["id"], lease_token=2)
        await asyncio.wait_for(holding, 1)  # it stops renewing
    finally:
        settings.coding_lease_seconds = before
    assert await worker.stop_requested(run_id)
    with pytest.raises(_ReconciliationRequired):
        await worker._ensure_running(run_id)
    await worker._end(run_id, CodingRunStatus.FAILED, error="stale")
    assert (await db_client.get(f"{coding[2]}/projects/{coding[3]['id']}/coding/runs/{run['id']}",
                                headers=coding[0].headers)).json()["status"] == "running"  # untouched
    _LEASE.reset(lease)

    # Two attempts on one worker (the first one cut off, still alive): each keeps its own token.
    async def sees_stop(token: int) -> bool:
        _LEASE.set(token)
        return await worker.stop_requested(run_id)

    # (one after the other: the test's connection is shared)
    assert [await asyncio.create_task(sees_stop(t)) for t in (1, 2)] == [True, False]


# -- work modes: Build hands issues to Kai from the conversation; Review reads what came of it -----


async def test_build_asks_kai_from_the_conversation_and_review_reads_the_evidence(
    db_client: AsyncClient, coding, github, claude: ScriptedClaude, agent_script
) -> None:
    ada, cat, ws, kun, _, _ = coding
    base = f"{ws}/projects/{kun['id']}"
    issue = (await db_client.post(f"{base}/issues", headers=ada.headers, json={"type": "task", "title": "Refunds"})).json()
    agent_script.say(tool_call("save_plan", title="Refunds", summary="Refund within a week.",
                               acceptance_criteria=["refund() returns the amount"], tasks=[{"title": "Add refund()"}]),
                     "Saved the plan.")
    planned = (await db_client.post(f"{base}/agent/runs", headers=ada.headers,
                                    json={"message": "Plan refunds", "work_mode": "plan"})).json()
    thread = planned["thread_id"]
    plan = (await db_client.get(f"{base}/agent/threads/{thread}/plans", headers=ada.headers)).json()[0]

    # Discussing can't start coding: the tool isn't there.
    model = agent_script.say("I'd add refund() to the payment provider.")
    await db_client.post(f"{base}/agent/runs", headers=ada.headers,
                         json={"message": "How would you do it?", "work_mode": "discuss", "thread_id": thread})
    assert "start_coding" not in model.tools_received[0]

    model = agent_script.say(tool_call("start_coding", issue_key=issue["key"], note="Task 1 of the plan"),
                             "Asked Kai; it waits for an approval.")
    built = (await db_client.post(f"{base}/agent/runs", headers=ada.headers,
                                  json={"message": "Build the plan", "work_mode": "build", "thread_id": thread})).json()
    assert built["status"] == "completed", built
    [run] = (await db_client.get(f"{base}/coding/runs?issue={issue['key']}", headers=ada.headers)).json()
    assert run["status"] == "awaiting_approval" and run["thread_id"] == thread and run["plan_id"] == plan["id"]
    assert run["requested_by_id"] == ada.id and "Task 1 of the plan" in run["brief"]
    audit = (await db_client.get(f"{ws}/audit", headers=ada.headers)).json()
    assert any(e["action"] == "coding.requested_in_conversation" for e in audit)

    claude.edits = {"src/payments.py": "class PaymentProvider:\n    def refund(self, amount):\n        return amount\n"}
    agent_script.say("Looks right.")  # the Reviewer, on the PR
    await _approve(db_client, base, run, ada.headers)

    model = agent_script.say(tool_call("coding_evidence"), "Kai opened PR #1; the tests weren't run by us.")
    await db_client.post(f"{base}/agent/runs", headers=ada.headers,
                         json={"message": "What changed?", "work_mode": "review", "thread_id": thread})
    evidence = [m.content for m in model.received[1] if m.type == "tool"][-1]  # (the thread's history comes first)
    assert "pr_opened" in evidence and "src/payments.py (+2 -1)" in evidence and "pull/1" in evidence

    # A follow-up from the Code tab is the same session: Review sees it too.
    turn = await db_client.post(f"{base}/coding/sessions/{run['session_id']}/turns", headers=ada.headers,
                                json={"message": "Handle partial refunds"})
    assert turn.status_code == 201, turn.text
    model = agent_script.say(tool_call("coding_evidence"), "Turn 2 waits for an approval.")
    await db_client.post(f"{base}/agent/runs", headers=ada.headers,
                         json={"message": "And now?", "work_mode": "review", "thread_id": thread})
    evidence = [m.content for m in model.received[1] if m.type == "tool"][-1]
    assert '"turn": 2' in evidence and "awaiting_approval" in evidence

    # The session belongs to its conversation (shown there, inline), for whoever's conversation it is.
    [mine] = [s for s in (await db_client.get(f"{ws}/coding/sessions", headers=ada.headers)).json()
              if s["session_id"] == run["session_id"]]
    assert mine["thread_id"] == thread and mine["turns"] == 2
    # Cat doesn't see Ada's session; as an approver while a turn waits on them, without her conversation.
    assert not [s for s in (await db_client.get(f"{ws}/coding/sessions", headers=cat.headers)).json()
                if s["session_id"] == run["session_id"]]
    await db_client.patch(ws, json={"member_permissions": ["agents:approve"]}, headers=ada.headers)
    [theirs] = [s for s in (await db_client.get(f"{ws}/coding/sessions", headers=cat.headers)).json()
                if s["session_id"] == run["session_id"]]
    assert theirs["thread_id"] is None  # another person's conversation isn't named to them
    await db_client.patch(ws, json={"member_permissions": []}, headers=ada.headers)

    # Cat may chat but not instruct Kai: Build says so instead of asking for a run.
    model = agent_script.say(tool_call("start_coding", issue_key=issue["key"]), "You can't ask Kai here.")
    await db_client.post(f"{base}/agent/runs", headers=cat.headers, json={"message": "Build it", "work_mode": "build"})
    refused = next(m.content for m in model.received[1] if m.type == "tool")
    assert "can't instruct Kai" in refused

    # Someone who lost the project after sending a Build message can't ask Kai for it.
    from dotrix_backend.modules.agents.work_modes import ModeContext, StartCoding, _start_coding

    other = (await db_client.post(f"{base}/issues", headers=ada.headers, json={"type": "task", "title": "Other"})).json()
    await db_client.patch(ws, json={"member_permissions": ["agents:code"]}, headers=ada.headers)  # Cat may instruct Kai
    assert (await db_client.patch(base, json={"access": "restricted"}, headers=ada.headers)).status_code == 200
    app = db_client._transport.app  # type: ignore[attr-defined]
    ctx = ModeContext(app.state.jobs.ctx.session_factory, app.state.settings, uuid.UUID(ws.split("/")[-1]),
                      uuid.UUID(kun["id"]), uuid.uuid4(), uuid.UUID(built["id"]), uuid.UUID(cat.id))
    gone = await _start_coding(ctx, StartCoding(issue_key=other["key"]))
    assert "gone" in gone["error"]
    assert (await db_client.get(f"{base}/coding/runs?issue={other['key']}", headers=ada.headers)).json() == []


# -- approval modes: in Accept edits a coding turn starts at once, approved by whoever asked ---------


async def test_accept_edits_starts_kai_at_once_and_manual_still_waits(
    db_client: AsyncClient, coding, github, claude: ScriptedClaude, agent_script
) -> None:
    ada, cat, ws, kun, _, _ = coding
    base = f"{ws}/projects/{kun['id']}"
    await db_client.patch(ws, json={"approval_mode_cap": "accept_edits",
                                    "member_permissions": ["agents:code"]}, headers=ada.headers)
    issue = (await db_client.post(f"{base}/issues", headers=ada.headers, json={"type": "task", "title": "Refunds"})).json()
    claude.edits = {"src/payments.py": "class PaymentProvider:\n    def refund(self, amount):\n        return amount\n"}
    agent_script.say("Looks right.")  # the Reviewer, on the PR
    started = await db_client.post(f"{base}/coding/issues/{issue['key']}/runs", headers=ada.headers,
                                   json={"approval_mode": "auto"})
    assert started.status_code == 201, started.text
    run = started.json()
    assert run["approval_mode"] == "accept_edits" and run["status"] == "pr_opened", run  # capped, and it ran
    assert run["decided_by_id"] == ada.id and run["decision_reason"].startswith("Started at once")
    audit = [e for e in (await db_client.get(f"{ws}/audit", headers=ada.headers)).json() if e["action"] == "coding.approved"]
    assert audit[0]["details"]["approval_mode"] == "accept_edits"

    # Cat may instruct Kai but not approve agent changes: Manual, so it waits.
    other = (await db_client.post(f"{base}/issues", headers=ada.headers, json={"type": "task", "title": "Other"})).json()
    theirs = (await db_client.post(f"{base}/coding/issues/{other['key']}/runs", headers=cat.headers,
                                   json={"approval_mode": "accept_edits"})).json()
    assert theirs["approval_mode"] == "manual" and theirs["status"] == "awaiting_approval"
    await db_client.post(f"{base}/coding/runs/{theirs['id']}/decision", json={"decision": "reject"}, headers=ada.headers)

    # Build in Accept edits: Kai starts at once from the conversation too.
    third = (await db_client.post(f"{base}/issues", headers=ada.headers, json={"type": "task", "title": "Third"})).json()
    model = agent_script.say(tool_call("start_coding", issue_key=third["key"]), "Kai has started.", "Looks right.")
    await db_client.post(f"{base}/agent/runs", headers=ada.headers, json={
        "message": "Build it", "work_mode": "build", "approval_mode": "accept_edits",
    })
    # (here the coding run, and its Reviewer, run inside the tool call: search every call for its result)
    said = [m.content for call in model.received for m in call if m.type == "tool" and m.name == "start_coding"]
    assert said and "Kai has started" in said[-1]
    [built] = (await db_client.get(f"{base}/coding/runs?issue={third['key']}", headers=ada.headers)).json()
    assert built["approval_mode"] == "accept_edits" and built["status"] in ("pr_opened", "no_changes", "running")


async def test_changes_to_files_ci_runs_wait_for_a_person_in_every_mode(
    db_client: AsyncClient, coding, github, origin: Path, claude: ScriptedClaude, agent_script
) -> None:
    """Accept edits and Auto push a turn's changes at once, unless they change files CI runs (build
    scripts, test setup): those wait for a person to accept them, and approvers are told why."""
    ada, _, ws, kun, _, _ = coding
    base = f"{ws}/projects/{kun['id']}"
    await db_client.patch(ws, json={"approval_mode_cap": "auto"}, headers=ada.headers)
    task = (await db_client.post(f"{base}/issues", json={"type": "task", "title": "Lint"}, headers=ada.headers)).json()
    claude.edits = {"src/lint.py": "RULES = []\n", "package.json": '{"scripts": {"test": "echo ok"}}\n'}
    run = (await db_client.post(f"{base}/coding/issues/{task['key']}/runs", headers=ada.headers,
                                json={"approval_mode": "auto"})).json()
    assert run["approval_mode"] == "auto" and run["status"] == "changes_ready", run  # started at once, then held
    assert run["ci_sensitive"] == ["package.json"] and github.pulls == []
    assert _git(origin, "branch", "--list", "dotrix/*") == ""  # nothing reached GitHub
    assert any("they change files CI runs (package.json)" in e["text"] for e in run["events"])
    [note] = (await db_client.get(f"{ws}/notifications", params={"kind": "approval"}, headers=ada.headers)).json()[:1]
    assert note["coding_run_id"] == run["id"] and "files CI runs" in note["title"]
    audit = [e for e in (await db_client.get(f"{ws}/audit", headers=ada.headers)).json() if e["action"] == "coding.changes_ready"]
    assert audit[0]["details"]["ci_sensitive"] == ["package.json"]

    agent_script.say("Looks right.")  # the Reviewer, on the PR
    accepted = await db_client.post(f"{base}/coding/runs/{run['id']}/decision", json={"decision": "approve"},
                                    headers=ada.headers)
    assert accepted.status_code == 200, accepted.text
    done = (await db_client.get(f"{base}/coding/runs/{run['id']}", headers=ada.headers)).json()
    assert done["status"] == "pr_opened" and done["accepted_by_id"] == ada.id and len(github.pulls) == 1, done
    assert "CI may run these changed files" in github.pulls[0]["body"]

    # A later turn that changes no such file goes straight through again.
    claude.edits = {"src/lint.py": "RULES = ['no-print']\n"}
    turn = (await db_client.post(f"{base}/coding/sessions/{run['session_id']}/turns", json={"message": "A rule", "approval_mode": "auto"},
                                 headers=ada.headers)).json()
    turn = (await db_client.get(f"{base}/coding/runs/{turn['id']}", headers=ada.headers)).json()
    assert turn["status"] == "pr_opened" and turn["ci_sensitive"] == [], turn


async def test_a_local_turn_changing_files_ci_runs_waits_for_a_person_in_accept_edits(
    db_client: AsyncClient, coding, github, origin: Path, checkout: Path, tmp_path: Path
) -> None:
    ada, _, ws, kun, _, _ = coding
    base = f"{ws}/projects/{kun['id']}"
    await db_client.patch(ws, json={"approval_mode_cap": "accept_edits"}, headers=ada.headers)
    task = (await db_client.post(f"{base}/issues", json={"type": "task", "title": "Build"}, headers=ada.headers)).json()
    runner = _local_runner(db_client, coding, checkout, tmp_path, _tool({"Makefile": "test:\n\techo ok\n"}))
    await runner.register()
    run = (await db_client.post(f"{base}/coding/issues/{task['key']}/runs", headers=ada.headers,
                                json={"location": "local", "approval_mode": "accept_edits"})).json()
    assert run["status"] == "queued", run  # Accept edits: it starts at once, on her computer
    assert await runner.once() is True
    ready = (await db_client.get(f"{base}/coding/runs/{run['id']}", headers=ada.headers)).json()
    assert ready["status"] == "changes_ready" and ready["ci_sensitive"] == ["Makefile"], ready
    assert github.pulls == [] and ready["accepted_at"] is None


# -- A2: in Manual, a turn's changes wait for a person before they're pushed; a pushed turn can be reverted --


async def test_manual_changes_wait_and_rejected_ones_never_reach_github(
    db_client: AsyncClient, coding, github, origin: Path, claude: ScriptedClaude
) -> None:
    ada, cat, ws, kun, _, _ = coding
    base = f"{ws}/projects/{kun['id']}"
    await db_client.patch(ws, json={"member_permissions": ["agents:approve"]}, headers=ada.headers)  # Cat approves
    task = (await db_client.post(f"{base}/issues", json={"type": "task", "title": "Refunds"}, headers=ada.headers)).json()
    run = (await db_client.post(f"{base}/coding/issues/{task['key']}/runs", json={}, headers=ada.headers)).json()
    claude.edits = {"src/refunds.py": "def refund(amount):\n    return amount\n"}
    await db_client.post(f"{base}/coding/runs/{run['id']}/decision", json={"decision": "approve"}, headers=ada.headers)

    # Cat, an approver, opens it while it waits on that decision, and rejects its changes.
    ready = (await db_client.get(f"{base}/coding/runs/{run['id']}", headers=cat.headers)).json()
    assert ready["status"] == "changes_ready" and ready["can_decide"] and not ready["can_stop"]
    assert (await db_client.post(f"{base}/coding/sessions/{run['session_id']}/turns", json={"message": "more"},
                                 headers=ada.headers)).status_code == 409  # a turn waits
    rejected = await db_client.post(f"{base}/coding/runs/{run['id']}/decision",
                                    json={"decision": "reject", "reason": "Not this way"}, headers=cat.headers)
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["status"] == "rejected" and "Not this way" in rejected.json()["error"]
    assert github.pulls == [] and _git(origin, "branch", "--list", "dotrix/*") == ""
    # Decided: it's Ada's alone again, and her notification says so.
    assert (await db_client.get(f"{base}/coding/runs/{run['id']}", headers=cat.headers)).status_code == 404
    [decided] = (await db_client.get(f"{ws}/notifications", params={"kind": "decided"}, headers=ada.headers)).json()
    assert "Changes for" in decided["title"] and decided["actor_user_id"] == cat.id
    async with db_client._transport.app.state.jobs.ctx.session_factory() as session:  # type: ignore[attr-defined]
        kept = await session.scalar(select(CodingRun.pending_patch).where(CodingRun.id == uuid.UUID(run["id"])))
        assert kept is None  # discarded

    # The next turn knows those changes aren't on the branch.
    turn = (await db_client.post(f"{base}/coding/sessions/{run['session_id']}/turns", json={"message": "Try again"},
                                 headers=ada.headers)).json()
    assert "rejected and never pushed" in turn["brief"]
    await db_client.post(f"{base}/coding/runs/{turn['id']}/decision", json={"decision": "approve"}, headers=ada.headers)
    # Stopped while its changes wait: discarded too.
    stopped = (await db_client.post(f"{base}/coding/runs/{turn['id']}/stop", headers=ada.headers)).json()
    assert stopped["status"] == "stopped" and "discarded" in stopped["error"] and github.pulls == []
    actions = [e["action"] for e in (await db_client.get(f"{ws}/audit", headers=ada.headers)).json()]
    assert {"coding.changes_ready", "coding.changes_rejected", "coding.stop_requested"} <= set(actions)


async def test_accepted_changes_are_pushed_without_a_model_key(
    db_client: AsyncClient, coding, github, origin: Path, claude: ScriptedClaude, agent_script
) -> None:
    """Pushing what's ready runs no model: a key removed while the changes waited doesn't lose them."""
    ada, *_ = coding
    base, run = await _asked(db_client, coding)
    claude.edits = {"src/refunds.py": "def refund(amount):\n    return amount\n"}
    await db_client.post(f"{base}/coding/runs/{run['id']}/decision", json={"decision": "approve"}, headers=ada.headers)
    assert (await db_client.get(f"{base}/coding/runs/{run['id']}", headers=ada.headers)).json()["status"] == "changes_ready"
    await db_client.delete("/v1/me/model-keys/anthropic", headers=ada.headers)
    agent_script.say("Fine.")
    done = await _approve(db_client, base, run, ada.headers)
    assert done["status"] == "pr_opened" and len(github.pulls) == 1, done
    assert _git(origin, "show", f"{done['branch']}:src/refunds.py") == "def refund(amount):\n    return amount"


async def test_a_pushed_turn_is_reverted_on_its_branch(
    db_client: AsyncClient, coding, github, origin: Path, claude: ScriptedClaude, agent_script
) -> None:
    ada, cat, ws, kun, _, _ = coding
    base = f"{ws}/projects/{kun['id']}"
    task = (await db_client.post(f"{base}/issues", json={"type": "task", "title": "Refunds"}, headers=ada.headers)).json()
    agent_script.say("Fine.", "Fine.", "Fine.")
    claude.edits = {"src/payments.py": "class PaymentProvider:\n    def refund(self, amount):\n        return amount\n"}
    first = (await db_client.post(f"{base}/coding/issues/{task['key']}/runs", json={}, headers=ada.headers)).json()
    first = await _approve(db_client, base, first, ada.headers)
    claude.edits = {"src/refunds.py": "LIMIT = 500\n"}
    second = (await db_client.post(f"{base}/coding/sessions/{first['session_id']}/turns", json={"message": "A limit"},
                                   headers=ada.headers)).json()
    second = await _approve(db_client, base, second, ada.headers)
    assert first["status"] == second["status"] == "pr_opened" and first["can_revert"]

    # Turn 1 undone: a new turn whose commit reverts it on the branch, turn 2 kept. Nothing runs the agent.
    asked = await db_client.post(f"{base}/coding/runs/{first['id']}/revert", json={}, headers=ada.headers)
    assert asked.status_code == 201, asked.text
    revert = asked.json()
    assert revert["status"] == "awaiting_approval" and revert["revert_of"] == first["id"] and revert["turn"] == 3
    briefs = len(claude.briefs)
    revert = await _approve(db_client, base, revert, ada.headers)  # approving the revert is enough: its diff is known
    assert revert["status"] == "pr_opened" and revert["summary"].startswith("Reverted turn 1"), revert
    assert len(claude.briefs) == briefs and revert["pr_number"] == first["pr_number"]
    assert [f["path"] for f in revert["files_changed"]] == ["src/payments.py"]
    branch = first["branch"]
    assert _git(origin, "show", f"{branch}:src/payments.py") == "class PaymentProvider:\n    pass"
    assert _git(origin, "show", f"{branch}:src/refunds.py") == "LIMIT = 500"
    assert _git(origin, "rev-parse", f"{branch}~1") == second["commit_sha"]  # on top: never forced
    assert len(github.pulls) == 1

    # Once only; not by Cat; not once its PR is merged.
    again = await db_client.post(f"{base}/coding/runs/{first['id']}/revert", json={}, headers=ada.headers)
    assert again.status_code == 409 and "already reverted" in again.json()["detail"]
    assert (await db_client.post(f"{base}/coding/runs/{second['id']}/revert", json={},
                                 headers=cat.headers)).status_code == 403
    await _set_run(db_client, second["id"], pr_state="merged")
    merged = await db_client.post(f"{base}/coding/runs/{second['id']}/revert", json={}, headers=ada.headers)
    assert merged.status_code == 409 and "merged" in merged.json()["detail"]


# -- M1: one coding run interrupted on purpose, recovered, and reviewed in the same conversation --------


async def test_m1_a_run_interrupted_recovered_and_reviewed_in_one_conversation(
    db_client: AsyncClient, coding, github, origin: Path, claude: ScriptedClaude, agent_script
) -> None:
    """Build asks Kai from the conversation; its worker is cut off twice (it dies while the agent works,
    then the PR's reply is lost after the push); the sweep settles both from GitHub without a person,
    and Review reads the outcome in the same conversation."""
    ada, _, ws, kun, _, _ = coding
    base = f"{ws}/projects/{kun['id']}"
    app = db_client._transport.app  # type: ignore[attr-defined]
    factory, worker = app.state.jobs.ctx.session_factory, app.state.jobs.ctx.coding
    github.branch_heads = _heads(origin)
    issue = (await db_client.post(f"{base}/issues", headers=ada.headers, json={"type": "task", "title": "Refunds"})).json()

    agent_script.say(tool_call("start_coding", issue_key=issue["key"]), "Asked Kai; it waits for your approval.")
    built = (await db_client.post(f"{base}/agent/runs", headers=ada.headers,
                                  json={"message": "Build refunds", "work_mode": "build"})).json()
    thread = built["thread_id"]
    [run] = (await db_client.get(f"{base}/coding/runs?issue={issue['key']}", headers=ada.headers)).json()
    assert run["thread_id"] == thread

    async def sweep() -> None:
        """The worker's sweep: lapsed leases become uncertain, uncertain runs are settled from GitHub."""
        await expire_coding_leases(factory)
        requeued: list[uuid.UUID] = []

        async def requeue(session, row) -> None:
            requeued.append(row.id)

        await recover_uncertain_runs(factory, worker.app, worker.settings, requeue)
        for run_id in requeued:  # what the dispatch would run
            await worker.execute(run_id)

    # 1. Approved and taken by a worker that dies while the agent works: its lease lapses, nothing is pushed.
    await _set_run(db_client, run["id"], status=CodingRunStatus.RUNNING, lease_token=1, decided_by_id=ada.id,
                   lease_expires_at=datetime.now(UTC) - timedelta(seconds=5), started_at=datetime.now(UTC))
    claude.edits = {"src/payments.py": "class PaymentProvider:\n    def refund(self, amount):\n        return amount\n"}
    await sweep()  # it runs again on a new lease; Manual: its changes wait
    ready = (await db_client.get(f"{base}/coding/runs/{run['id']}", headers=ada.headers)).json()
    assert ready["status"] == "changes_ready", ready
    assert "Recovered: nothing was published; running the turn again" in [e["text"] for e in ready["events"]]

    # 2. Accepted; the push lands and the PR request's reply is lost: uncertain, never assumed failed.
    github.fail_pulls = 1
    await db_client.post(f"{base}/coding/runs/{run['id']}/decision", json={"decision": "approve"}, headers=ada.headers)
    cut = (await db_client.get(f"{base}/coding/runs/{run['id']}", headers=ada.headers)).json()
    assert cut["status"] == "recovery_required" and _git(origin, "rev-parse", cut["branch"]) == cut["commit_sha"]
    agent_script.say("Looks right.")  # the Reviewer, once the PR is up
    await sweep()  # the branch is at the recorded commit, no PR: recovery opens it
    done = (await db_client.get(f"{base}/coding/runs/{run['id']}", headers=ada.headers)).json()
    assert done["status"] == "pr_opened" and done["pr_number"] == 1 and len(github.pulls) == 1, done
    assert done["accepted_by_id"] == ada.id

    # 3. Reviewed in the same conversation: Review reads what came of it, and the session is shown there.
    model = agent_script.say(tool_call("coding_evidence"), "Kai opened PR #1 after two interruptions.")
    reviewed = (await db_client.post(f"{base}/agent/runs", headers=ada.headers,
                                     json={"message": "What happened?", "work_mode": "review", "thread_id": thread})).json()
    assert reviewed["status"] == "completed" and reviewed["thread_id"] == thread
    evidence = [m.content for m in model.received[1] if m.type == "tool"][-1]
    assert "pr_opened" in evidence and "pull/1" in evidence and "src/payments.py (+2 -1)" in evidence
    [session] = [s for s in (await db_client.get(f"{ws}/coding/sessions", headers=ada.headers)).json()
                 if s["session_id"] == run["session_id"]]
    assert session["thread_id"] == thread and session["status"] == "pr_opened"
    audit = [e for e in (await db_client.get(f"{ws}/audit", headers=ada.headers)).json() if e["target"] == issue["key"]]
    outcomes = [e["details"]["outcome"] for e in audit if e["action"] == "coding.recovered"]
    assert sorted(outcomes) == ["opened_pr", "retried"]


# -- local coding: the person's own computer codes the turn; the platform pushes what's accepted --------


class _RunnerApi:
    """The CLI runner's platform calls, through the test client as Ada."""

    def __init__(self, db_client: AsyncClient, headers: dict) -> None:
        self.db_client, self.headers = db_client, headers
        # The test's requests share one database session: a test calling the API while the runner
        # works takes this lock too, so their requests never overlap.
        self.lock = asyncio.Lock()

    async def post(self, path: str, body: Any = None) -> Any:
        from dotrix_cli.platform import PlatformError

        async with self.lock:
            res = await self.db_client.post(f"/v1{path}", json=body, headers=self.headers)
        if res.status_code >= 400:
            problem = res.json()
            raise PlatformError(res.status_code, str(problem.get("type", "")).rsplit("/", 1)[-1], problem.get("detail", ""))
        return res.json() if res.content else None


def _tool(edits: dict[str, str], *, sleep: float = 0, result: str = "Added refunds; tests pass.") -> str:
    """A command standing in for Claude Code: reads the brief, edits files, prints stream-json."""
    import shlex
    import sys

    script = (
        "import json, sys, time, pathlib\n"
        "brief = sys.stdin.read()\n"
        f"for path, text in {edits!r}.items():\n"
        "    p = pathlib.Path(path); p.parent.mkdir(parents=True, exist_ok=True); p.write_text(text)\n"
        "    print(json.dumps({'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'name': 'Edit', 'input': {'file_path': path}}]}}), flush=True)\n"
        f"time.sleep({sleep})\n"
        f"print(json.dumps({{'type': 'result', 'subtype': 'success', 'result': {result!r}, 'total_cost_usd': 0.02, 'usage': {{'input_tokens': 10, 'output_tokens': 5}}}}), flush=True)\n"
    )
    return f"{shlex.quote(sys.executable)} -c {shlex.quote(script)}"


@pytest.fixture
def checkout(tmp_path: Path, origin: Path) -> Path:
    """Ada's own clone of kunemi/api, with work of her own in it."""
    root = tmp_path / "ada-api"
    _git(tmp_path, "clone", "-q", str(origin), str(root))
    (root / "notes.txt").write_text("mine, not committed\n")
    return root


def _local_runner(db_client: AsyncClient, coding, checkout: Path, tmp_path: Path, command: str, **kw: Any):
    from dotrix_cli.runner import LocalRunner

    ada, _, ws, kun, _, _ = coding
    return LocalRunner(_RunnerApi(db_client, ada.headers), checkout, ws.split("/")[-1], kun["id"], command=command,
                       worktrees=tmp_path / "worktrees", name="ada-laptop", echo=lambda _: None, **kw)


async def test_a_local_turn_codes_on_the_persons_computer_and_the_platform_pushes_it(
    db_client: AsyncClient, coding, github, origin: Path, checkout: Path, tmp_path: Path, agent_script
) -> None:
    ada, cat, ws, kun, _, sandbox = coding
    base = f"{ws}/projects/{kun['id']}"
    task = (await db_client.post(f"{base}/issues", json={"type": "task", "title": "Refunds"}, headers=ada.headers)).json()
    # Not before a runner of hers serves the project.
    refused = await db_client.post(f"{base}/coding/issues/{task['key']}/runs", json={"location": "local"}, headers=ada.headers)
    assert refused.status_code == 409 and "dotrix runner" in refused.json()["detail"]

    runner = _local_runner(db_client, coding, checkout, tmp_path, _tool({"src/refunds.py": "def refund(a):\n    return a\n"}))
    registered = await runner.register()
    assert registered["name"] == "ada-laptop" and registered["isolation"] == "none" and registered["online"]
    assert (await db_client.get(f"{base}/coding", headers=ada.headers)).json()["local_runner"] == "ada-laptop"
    assert await runner.once() is False  # nothing waits

    run = (await db_client.post(f"{base}/coding/issues/{task['key']}/runs", json={"location": "local"},
                                headers=ada.headers)).json()
    assert run["location"] == "local" and run["status"] == "awaiting_approval"
    await db_client.post(f"{base}/coding/runs/{run['id']}/decision", json={"decision": "approve"}, headers=ada.headers)
    queued = (await db_client.get(f"{base}/coding/runs/{run['id']}", headers=ada.headers)).json()
    assert queued["status"] == "queued" and sandbox.opened == 0  # no worker took it: it waits for her computer

    assert await runner.once() is True
    ready = (await db_client.get(f"{base}/coding/runs/{run['id']}", headers=ada.headers)).json()
    assert ready["status"] == "changes_ready" and ready["runner_name"] == "ada-laptop", ready
    assert [f["path"] for f in ready["files_changed"]] == ["src/refunds.py"]
    assert ready["summary"] == "Added refunds; tests pass." and ready["base_sha"] == _git(origin, "rev-parse", "main")
    texts = [e["text"] for e in ready["events"]]
    assert "On ada-laptop (a worktree only, not isolated)" in texts and "Edited src/refunds.py" in texts
    assert any(t.startswith("Worktree on main at") and "not isolated" in t for t in texts)
    # Her checkout is as she left it; nothing reached GitHub; the worktree is kept, outside it.
    assert _git(checkout, "status", "--porcelain") == "?? notes.txt" and not (checkout / "src/refunds.py").exists()
    assert github.pulls == [] and _git(origin, "branch", "--list", "dotrix/*") == ""
    [tree] = (tmp_path / "worktrees" / kun["id"]).iterdir()
    assert (tree / "src/refunds.py").read_text() == "def refund(a):\n    return a\n"
    # Where it is on her computer (the desktop app opens it): for her, no one else.
    assert ready["worktree"] == str(tree) and ready["runner_id"] == registered["id"]
    as_approver = await db_client.get(f"{base}/coding/runs/{run['id']}", headers=cat.headers)
    assert as_approver.status_code == 404 or as_approver.json()["worktree"] is None

    # Accepted: the platform pushes it (the worker's publish-only pass), as for a cloud turn.
    agent_script.say("Fine.")
    done = await _approve(db_client, base, ready, ada.headers)
    assert done["status"] == "pr_opened" and len(github.pulls) == 1 and sandbox.opened == 0, done
    assert _git(origin, "show", f"{done['branch']}:src/refunds.py") == "def refund(a):\n    return a"

    # A follow-up stays on her computer, on the session's branch.
    runner.command = _tool({"src/refunds.py": "def refund(a):\n    return -a\n"})
    turn = (await db_client.post(f"{base}/coding/sessions/{run['session_id']}/turns", json={"message": "Negative"},
                                 headers=ada.headers)).json()
    assert turn["location"] == "local"
    await db_client.post(f"{base}/coding/runs/{turn['id']}/decision", json={"decision": "approve"}, headers=ada.headers)
    assert await runner.once() is True
    turn = await _approve(db_client, base, turn, ada.headers)
    assert turn["status"] == "pr_opened" and turn["base_sha"] == done["commit_sha"] and len(github.pulls) == 1
    assert _git(origin, "rev-parse", f"{done['branch']}~1") == done["commit_sha"]

    # On a server that codes only locally (no cloud sandbox), a pushed local turn is still reverted (the
    # platform pushes the revert, nothing codes), and the session keeps coding on her computer.
    db_client._transport.app.state.settings.coding_sandbox = "off"  # type: ignore[attr-defined]
    assert not (await db_client.get(f"{base}/coding", headers=ada.headers)).json()["available"]
    asked = await db_client.post(f"{base}/coding/runs/{turn['id']}/revert", json={}, headers=ada.headers)
    assert asked.status_code == 201, asked.text
    agent_script.say("Fine.")
    reverted = await _approve(db_client, base, asked.json(), ada.headers)
    assert reverted["status"] == "pr_opened" and reverted["location"] == "cloud", reverted
    assert _git(origin, "show", f"{done['branch']}:src/refunds.py") == "def refund(a):\n    return a"
    after = (await db_client.post(f"{base}/coding/sessions/{run['session_id']}/turns", json={"message": "Again"},
                                  headers=ada.headers)).json()
    assert after["location"] == "local", after
    await db_client.post(f"{base}/coding/runs/{after['id']}/stop", headers=ada.headers)

    # Her runner claims only her turns: Cat's (on the platform) isn't one of them; revoked, it claims nothing.
    assert (await db_client.get(f"{ws}/coding/runners", headers=cat.headers)).json() == []
    assert (await db_client.delete(f"{ws}/coding/runners/{registered['id']}", headers=ada.headers)).status_code == 204
    with pytest.raises(Exception, match="Runner not found"):
        await runner.once()


async def test_a_local_turn_is_checked_stopped_fenced_and_recovered(
    db_client: AsyncClient, coding, github, origin: Path, checkout: Path, tmp_path: Path
) -> None:
    from dotrix_cli.runner import LeaseLost

    ada, _, ws, kun, _, sandbox = coding
    base = f"{ws}/projects/{kun['id']}"
    runner = _local_runner(db_client, coding, checkout, tmp_path, _tool({".github/workflows/ci.yml": "on: push\n"}),
                           beat_seconds=0.1)
    await runner.register()

    async def local_turn(title: str) -> dict:
        task = (await db_client.post(f"{base}/issues", json={"type": "task", "title": title}, headers=ada.headers)).json()
        run = (await db_client.post(f"{base}/coding/issues/{task['key']}/runs", json={"location": "local"},
                                    headers=ada.headers)).json()
        await db_client.post(f"{base}/coding/runs/{run['id']}/decision", json={"decision": "approve"}, headers=ada.headers)
        return run

    # The guard holds on the platform: CI configuration is never pushed, whoever coded it.
    run = await local_turn("Tidy CI")
    await runner.once()
    failed = (await db_client.get(f"{base}/coding/runs/{run['id']}", headers=ada.headers)).json()
    assert failed["status"] == "failed" and "CI configuration" in failed["error"]

    # Stop reaches the tool through the heartbeat; what it did is discarded, nothing pushed.
    runner.command = _tool({"src/slow.py": "x = 1\n"}, sleep=30)
    run = await local_turn("Slow")
    working = asyncio.create_task(runner.once())
    for _ in range(400):  # until its runner holds it (a loaded machine takes a while to fetch and add the worktree)
        await asyncio.sleep(0.05)
        async with runner.api.lock:
            seen = (await db_client.get(f"{base}/coding/runs/{run['id']}", headers=ada.headers)).json()["status"]
        if seen == "running":
            break
    async with runner.api.lock:
        await db_client.post(f"{base}/coding/runs/{run['id']}/stop", headers=ada.headers)
    await asyncio.wait_for(working, 60)  # the tool would sleep 30 s: Stop ends it well before
    stopped = (await db_client.get(f"{base}/coding/runs/{run['id']}", headers=ada.headers)).json()
    assert stopped["status"] == "stopped" and github.pulls == []

    # Fenced: once the turn is another attempt's, this runner stops writing (and keeps its worktree).
    run = await local_turn("Fenced")
    claimed = await runner.api.post(f"{runner.base}/{runner.runner_id}/claim")
    await _set_run(db_client, run["id"], lease_token=claimed["run"]["lease_token"] + 1)
    with pytest.raises(LeaseLost):
        await runner.work(claimed["run"])

    # Cut off (its computer went away mid-turn): the lease lapses, recovery runs it again on her computer.
    run = await local_turn("Cut off")
    await runner.api.post(f"{runner.base}/{runner.runner_id}/claim")
    await _set_run(db_client, run["id"], lease_expires_at=datetime.now(UTC) - timedelta(seconds=5))
    github.branch_heads = _heads(origin)
    assert await expire_coding_leases(db_client._transport.app.state.jobs.ctx.session_factory) == 1  # type: ignore[attr-defined]
    again = (await db_client.post(f"{base}/coding/runs/{run['id']}/recover", json={"action": "check"},
                                  headers=ada.headers)).json()
    assert again["status"] == "queued" and sandbox.opened == 0, again  # for her runner, not a worker
    runner.command = _tool({"src/fenced.py": "y = 2\n"})
    assert await runner.once() is True
    assert (await db_client.get(f"{base}/coding/runs/{run['id']}", headers=ada.headers)).json()["status"] == "changes_ready"


# -- the session's Changes, Files, and Terminal: a turn's diff, its tree, files before and after, output --


async def test_a_turns_files_diff_and_command_output_are_kept_for_the_panels(
    db_client: AsyncClient, coding, github, origin: Path, claude: ScriptedClaude, checkouts, agent_script
) -> None:
    ada, cat, ws, kun, _, _ = coding

    async def remote(ref) -> tuple[str, None]:
        return str(origin), None

    checkouts.remote = remote
    base = f"{ws}/projects/{kun['id']}"
    claude.edits = {"src/payments.py": "class PaymentProvider:\n    def refund(self, amount):\n        return amount\n",
                    "tests/test_refund.py": "def test_refund():\n    assert True\n"}
    scripted = claude.lines
    command = [  # it ran the tests: the command, then its output (failed, then passed)
        json.dumps({"type": "assistant", "message": {"id": "m-run", "content": [
            {"type": "tool_use", "id": "toolu_1", "name": "Bash", "input": {"command": "pytest -q"}},
            {"type": "tool_use", "id": "toolu_2", "name": "Read", "input": {"file_path": "/sandbox/repo/src/payments.py"}},
        ]}}) + "\n",
        json.dumps({"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "toolu_2", "content": "class PaymentProvider: ..."},
            {"type": "tool_result", "tool_use_id": "toolu_1", "is_error": True,
             "content": [{"type": "text", "text": "1 failed in 0.02s"}]},
        ]}}) + "\n",
    ]
    claude.lines = lambda: [*scripted()[:-1], *command, scripted()[-1]]  # type: ignore[method-assign]
    task = (await db_client.post(f"{base}/issues", json={"type": "task", "title": "Refunds"}, headers=ada.headers)).json()
    run = (await db_client.post(f"{base}/coding/issues/{task['key']}/runs", json={}, headers=ada.headers)).json()
    await db_client.post(f"{base}/coding/runs/{run['id']}/decision", json={"decision": "approve"}, headers=ada.headers)
    ready = (await db_client.get(f"{base}/coding/runs/{run['id']}", headers=ada.headers)).json()
    assert ready["status"] == "changes_ready"

    # Terminal: the command and its output, paired; a file it read isn't output.
    events = (await db_client.get(f"{base}/coding/runs/{run['id']}/events", params={"limit": 500},
                                  headers=ada.headers)).json()["events"]
    ran = next(e for e in events if e["text"] == "Ran pytest -q")
    [out] = [e for e in events if e["kind"].startswith("output")]
    assert ran["ref"] == out["ref"] == "toolu_1" and out["kind"] == "output-error" and out["text"] == "1 failed in 0.02s"

    # Changes: the diff, before anything is pushed. Files: the tree the turn leaves, and a file before and after.
    diff = (await db_client.get(f"{base}/coding/runs/{run['id']}/diff", headers=ada.headers)).json()
    assert "+    def refund(self, amount):" in diff["diff"] and diff["base_sha"] == ready["base_sha"]
    tree = (await db_client.get(f"{base}/coding/runs/{run['id']}/tree", headers=ada.headers)).json()
    assert {(e["path"], e["status"]) for e in tree["entries"]} == {
        ("src/payments.py", "modified"), ("tests/test_refund.py", "added")} and not tree["truncated"]
    file = (await db_client.get(f"{base}/coding/runs/{run['id']}/file", params={"path": "src/payments.py"},
                                headers=ada.headers)).json()
    assert file["before"] == "class PaymentProvider:\n    pass\n" and "def refund" in file["after"]
    assert file["status"] == "modified" and not file["binary"]
    assert (await db_client.get(f"{base}/coding/runs/{run['id']}/file", params={"path": "../etc/passwd"},
                                headers=ada.headers)).status_code == 422
    assert (await db_client.get(f"{base}/coding/runs/{run['id']}/tree", headers=cat.headers)).status_code == 404

    # Pushed, the diff is still the turn's (the patch waiting to be pushed is gone).
    agent_script.say("Fine.")
    done = await _approve(db_client, base, ready, ada.headers)
    assert done["status"] == "pr_opened"
    kept = (await db_client.get(f"{base}/coding/runs/{run['id']}/diff", headers=ada.headers)).json()
    assert kept["diff"] == diff["diff"]
    after = (await db_client.get(f"{base}/coding/runs/{run['id']}/file", params={"path": "tests/test_refund.py"},
                                 headers=ada.headers)).json()
    assert after["status"] == "added" and after["before"] is None and after["after"].startswith("def test_refund")
