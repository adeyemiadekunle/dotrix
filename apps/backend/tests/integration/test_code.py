"""Checkouts of connected repos and agents reading them (agents v2 step 5b). GitHub's API is
faked (conftest.FakeGitHub); the repo is fetched from a local git repo instead of github.com."""
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient
from langchain_core.messages import ToolMessage

from dotrix_backend.modules.code.checkouts import CodeCheckouts, RepoRef
from dotrix_engine.testing import tool_call


def _git(root: Path, *args: str) -> str:
    out = subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True)
    return out.stdout.strip()


def _commit(origin: Path, path: str, text: str) -> str:
    file = origin / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(text)
    _git(origin, "add", path)
    _git(origin, "-c", "user.email=a@b.c", "-c", "user.name=A", "commit", "-qm", f"change {path}")
    return _git(origin, "rev-parse", "HEAD")


@pytest.fixture
def origin(tmp_path: Path, checkouts: CodeCheckouts) -> Path:
    """kunemi/api on "GitHub": fetched from this folder."""
    root = tmp_path / "origin"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _commit(root, "src/payments.py", "class PaymentProvider:\n    pass\n")
    fetched: list[RepoRef] = []

    async def remote(ref: RepoRef) -> tuple[str, str | None]:
        fetched.append(ref)
        assert (ref.full_name, ref.installation_id, ref.default_branch) == ("kunemi/api", 111, "main")
        return str(root), None

    checkouts.remote = remote
    return root


async def _connect(db_client: AsyncClient, ws: str, project: dict, headers: dict) -> dict:
    installation = (await db_client.post(f"{ws}/github/installations", json={"installation_id": 111, "code": "code-1"},
                                          headers=headers)).json()
    res = await db_client.put(f"{ws}/projects/{project['id']}/repository",
                              json={"installation_ref": installation["id"], "github_repo_id": 9001}, headers=headers)
    assert res.status_code == 200, res.text
    return res.json()


async def test_connecting_checks_the_code_out_and_pushes_keep_it_current(
    db_client: AsyncClient, github_world, deliver, github, origin: Path, checkouts: CodeCheckouts
) -> None:
    ada, cat, ws, kun, _ = await github_world()
    first = _git(origin, "rev-parse", "HEAD")
    repo = await _connect(db_client, ws, kun, ada.headers)
    assert repo["checkout_sha"] == first and repo["checkout_error"] is None and repo["checked_out_at"]
    root = checkouts.path(uuid.UUID(kun["workspace_id"]), uuid.UUID(kun["id"]))
    assert (root / "src/payments.py").read_text().startswith("class PaymentProvider")

    # A push to the default branch: the checkout follows.
    second = _commit(origin, "src/refunds.py", "def refund():\n    pass\n")
    push = {"ref": "refs/heads/main", "after": second,
            "repository": {"id": 9001, "full_name": "kunemi/api", "default_branch": "main"}}
    assert (await deliver("push", push)).status_code == 202
    repo = (await db_client.get(f"{ws}/projects/{kun['id']}/repository", headers=ada.headers)).json()
    assert repo["checkout_sha"] == repo["last_push_sha"] == second
    assert (root / "src/refunds.py").exists()
    # The token never goes into the checkout's git config.
    assert "extraheader" not in (root / ".git" / "config").read_text().lower()

    # Sync now: owners and admins only.
    base = f"{ws}/projects/{kun['id']}/repository/sync"
    assert (await db_client.post(base, headers=cat.headers)).status_code == 403
    assert (await db_client.post(base, headers=ada.headers)).status_code == 202


async def test_a_sync_that_fails_says_why(
    db_client: AsyncClient, github_world, deliver, github, origin: Path, checkouts: CodeCheckouts
) -> None:
    ada, _, ws, kun, mob = await github_world()
    remote = checkouts.remote
    checkouts.remote = None
    repo = await _connect(db_client, ws, kun, ada.headers)
    assert repo["checkout_sha"] is None and "isn't set up" in repo["checkout_error"]

    checkouts.remote, checkouts.max_bytes = remote, 10
    res = await db_client.post(f"{ws}/projects/{kun['id']}/repository/sync", headers=ada.headers)
    assert res.status_code == 202 and "MB limit" in res.json()["checkout_error"]

    checkouts.max_bytes = 50_000_000
    res = await db_client.post(f"{ws}/projects/{kun['id']}/repository/sync", headers=ada.headers)
    assert res.json()["checkout_error"] is None and res.json()["checkout_sha"]
    # Without a connected repo there's nothing to sync.
    assert (await db_client.post(f"{ws}/projects/{mob['id']}/repository/sync", headers=ada.headers)).status_code == 404


async def test_agents_read_the_code(
    db_client: AsyncClient, github_world, agent_script, github, origin: Path,
    checkouts: CodeCheckouts,
) -> None:
    ada, _, ws, kun, mob = await github_world()
    await _connect(db_client, ws, kun, ada.headers)
    # This machine lost its checkout (e.g. another worker): the run checks it out again first.
    shutil.rmtree(checkouts.path(uuid.UUID(kun["workspace_id"]), uuid.UUID(kun["id"])))

    model = agent_script.say(tool_call("code_search", pattern="PaymentProvider"), "PaymentProvider is in src/payments.py.")
    run = (await db_client.post(f"{ws}/projects/{kun['id']}/agent/runs", json={"message": "Where are payments?"},
                                headers=ada.headers)).json()
    assert run["status"] == "completed", run
    assert {"code_tree", "code_read", "code_search"} <= set(model.tools_received[0])
    assert "## Code\nThe repository kunemi/api (main at" in model.received[0][0].content
    result = next(m for m in model.received[1] if isinstance(m, ToolMessage))
    assert '<repo_content repo="kunemi/api"' in result.content
    assert "src/payments.py:1:class PaymentProvider:" in result.content

    # A project without a connected repo: no code tools, and nothing said about code.
    model = agent_script.say("No code here.")
    await db_client.post(f"{ws}/projects/{mob['id']}/agent/runs", json={"message": "Hi"}, headers=ada.headers)
    assert "code_search" not in model.tools_received[0]
    assert "## Code" not in model.received[0][0].content


async def test_a_disconnected_repo_s_checkout_is_cleaned_up(
    db_client: AsyncClient, github_world, deliver, github, origin: Path, checkouts: CodeCheckouts
) -> None:
    ada, _, ws, kun, _ = await github_world()
    await _connect(db_client, ws, kun, ada.headers)
    root = checkouts.path(uuid.UUID(kun["workspace_id"]), uuid.UUID(kun["id"]))
    assert root.exists()
    assert (await db_client.delete(f"{ws}/projects/{kun['id']}/repository", headers=ada.headers)).status_code == 204
    app = db_client._transport.app  # type: ignore[attr-defined]
    await app.state.jobs.enqueue("cleanup_expired")
    assert not root.exists()


async def test_a_push_sets_off_automations(
    db_client: AsyncClient, github_world, deliver, github, origin: Path, agent_script
) -> None:
    ada, _, ws, kun, _ = await github_world()
    await _connect(db_client, ws, kun, ada.headers)
    base = f"{ws}/projects/{kun['id']}"
    await db_client.post(f"{base}/automations", json={
        "name": "Review pushes", "agent": "reviewer", "events": ["code.pushed"],
        "instructions": "Check what was pushed against the requirements.",
    }, headers=ada.headers)
    sha = _commit(origin, "src/refunds.py", "def refund():\n    pass\n")
    push = {"ref": "refs/heads/main", "after": sha, "head_commit": {"message": "Add refunds\n\nLonger text"},
            "repository": {"id": 9001, "full_name": "kunemi/api", "default_branch": "main"}}
    await deliver("push", push)
    model = agent_script.say("Looks consistent with the requirements.")
    await db_client._transport.app.state.jobs.enqueue("run_automations")  # type: ignore[attr-defined]
    runs = (await db_client.get(f"{base}/agent/runs", headers=ada.headers)).json()
    assert len(runs) == 1 and runs[0]["title"] == "Automation: Review pushes"
    assert f"Pushed to main at {sha[:7]}: Add refunds" in model.received[0][-1].content
