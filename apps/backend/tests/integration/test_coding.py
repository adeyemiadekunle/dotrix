"""Coding runs (step 5c): asked for, approved, run in a sandbox, pushed to a new branch, and
opened as a PR. GitHub's API is faked (conftest.FakeGitHub), the repo is a local git repo, and the
"sandbox" is the local one with a scripted Claude Code in place of the real CLI."""
import asyncio
import dataclasses
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from pydantic import SecretStr

from pmagent_backend.modules.coding.runner import CodingWorker
from pmagent_backend.modules.coding.sandbox import ExecResult, LocalSandbox, LocalSession
from pmagent_backend.modules.connectors.github_app import get_github_app


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


class ScriptedSession(LocalSession):
    def __init__(self, root: Path, env: dict[str, str], agent: ScriptedClaude) -> None:
        super().__init__(root, env)
        self.agent = agent

    async def exec(self, argv, *, stdin=None, on_line=None, timeout, cancel=None) -> ExecResult:
        if argv[0] != "claude":
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


@pytest.fixture
async def coding(db_client: AsyncClient, github, github_world, origin: Path, claude: ScriptedClaude):
    """Ada (owner) and Cat (member); KUN connected to kunemi/api; coding on, with Claude Code."""
    app = db_client._transport.app  # type: ignore[attr-defined]
    settings = app.state.settings
    client = app.dependency_overrides[get_github_app]()
    settings.coding_sandbox = "local"
    settings.anthropic_api_key = SecretStr("sk-ant-test")
    settings.github_app_id, settings.github_app_slug = "4242", "pmagent-test"
    settings.github_app_private_key = SecretStr(client.private_key)
    ada, cat, ws, kun, mob = await github_world()
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
    assert availability == {"available": True, "agent": "claude-code", "sandbox": "local", "reason": None}
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
    # Cat sees it, can't decide it.
    seen = (await db_client.get(f"{base}/coding/runs/{run['id']}", headers=cat.headers)).json()
    assert not seen["can_decide"] and seen["input_tokens"] is None
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
    run = (await db_client.get(f"{base}/coding/runs/{run['id']}", headers=ada.headers)).json()
    assert run["status"] == "pr_opened", run
    assert run["pr_number"] == 1 and run["pr_url"] == "https://github.com/kunemi/api/pull/1"
    assert run["branch"].startswith(f"pmagent/{story['key'].lower()}-refund-a-payment-")
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
    assert set(claude.env) - {"ANTHROPIC_BASE_URL"} == {"PATH", "HOME", "LANG", "ANTHROPIC_API_KEY"} and claude.env["ANTHROPIC_API_KEY"] == "sk-ant-test"
    assert claude.argv[:3] == ["claude", "-p", "--bare"] and "--dangerously-skip-permissions" not in claude.argv

    # The issue is the coding tool's, in review, with the PR linked; a person closes it.
    issue = (await db_client.get(f"{base}/issues/{story['key']}", headers=ada.headers)).json()
    assert issue["status"] == "review" and issue["assignee_agent"] == "claude-code"
    assert {"kind": "pr", "url": run["pr_url"], "title": "PR #1: Refund a payment"} in issue["links"]

    # The Reviewer read the PR in a conversation of its own.
    review = (await db_client.get(f"{base}/agent/runs/{run['review_run_id']}", headers=ada.headers)).json()
    assert review["status"] == "completed" and review["reply"].startswith("Looks right")
    assert "src/payments.py (+2 -1)" in review["message"] and "<repo_content" in review["message"]

    actions = [e["action"] for e in (await db_client.get(f"{ws}/audit", headers=ada.headers)).json()]
    assert {"coding.requested", "coding.approved", "coding.pr_opened"} <= set(actions)


async def test_changes_to_pmagent_or_workflows_are_never_pushed(
    db_client: AsyncClient, coding, github, origin: Path, claude: ScriptedClaude
) -> None:
    ada, _, ws, kun, _, _ = coding
    base = f"{ws}/projects/{kun['id']}"
    task = (await db_client.post(f"{base}/issues", json={"type": "task", "title": "Tidy"}, headers=ada.headers)).json()
    claude.edits = {"src/payments.py": "# tidy\n", ".pmagent/requirements/x.md": "# sneaky\n"}
    run = (await db_client.post(f"{base}/coding/issues/{task['key']}/runs", json={}, headers=ada.headers)).json()
    await db_client.post(f"{base}/coding/runs/{run['id']}/decision", json={"decision": "approve"}, headers=ada.headers)
    run = (await db_client.get(f"{base}/coding/runs/{run['id']}", headers=ada.headers)).json()
    assert run["status"] == "failed" and ".pmagent/ stays on the platform" in run["error"]
    assert run["branch"] is None and github.pulls == []
    assert _git(origin, "branch", "--list", "pmagent/*") == ""

    # Workflows likewise; and a run that changes nothing ends without a PR.
    claude.edits = {".github/workflows/ci.yml": "on: push\n"}
    run = (await db_client.post(f"{base}/coding/issues/{task['key']}/runs", json={}, headers=ada.headers)).json()
    await db_client.post(f"{base}/coding/runs/{run['id']}/decision", json={"decision": "approve"}, headers=ada.headers)
    run = (await db_client.get(f"{base}/coding/runs/{run['id']}", headers=ada.headers)).json()
    assert run["status"] == "failed" and "CI workflows" in run["error"]
    claude.edits = {}
    run = (await db_client.post(f"{base}/coding/issues/{task['key']}/runs", json={}, headers=ada.headers)).json()
    await db_client.post(f"{base}/coding/runs/{run['id']}/decision", json={"decision": "approve"}, headers=ada.headers)
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
    assert [r["status"] for r in (await db_client.get(f"{base}/coding/runs", params={"issue": task["key"]},
                                                       headers=cat.headers)).json()] == ["stopped", "rejected"]

    # MOB has no connected repo; epics are too big; nothing runs without a model key.
    mob_task = (await db_client.post(f"{ws}/projects/{mob['id']}/issues", json={"type": "task", "title": "x"},
                                     headers=ada.headers)).json()
    refused = await db_client.post(f"{ws}/projects/{mob['id']}/coding/issues/{mob_task['key']}/runs", json={},
                                   headers=ada.headers)
    assert refused.status_code == 409 and refused.json()["type"].endswith("/coding_unavailable")
    epic = (await db_client.post(f"{base}/issues", json={"type": "epic", "title": "Big"}, headers=ada.headers)).json()
    assert (await db_client.post(f"{base}/coding/issues/{epic['key']}/runs", json={},
                                 headers=ada.headers)).status_code == 422
    app = db_client._transport.app  # type: ignore[attr-defined]
    app.state.settings.anthropic_api_key = None
    reason = (await db_client.get(f"{base}/coding", headers=ada.headers)).json()["reason"]
    assert "Anthropic key" in reason


async def test_a_running_agent_is_stopped_and_nothing_is_pushed(
    db_client: AsyncClient, coding, github, claude: ScriptedClaude, monkeypatch
) -> None:
    """The worker polls for Stop while the agent works, and kills it."""
    from pmagent_backend.modules.coding import runner as runner_module

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
    await db_client.post(f"{base}/coding/runs/{run['id']}/decision", json={"decision": "approve"}, headers=ada.headers)
    run = (await db_client.get(f"{base}/coding/runs/{run['id']}", headers=ada.headers)).json()
    assert run["status"] == "stopped" and run["error"] == "Stopped by a person" and github.pulls == []
