"""A connected repository's inventory and coverage: every tracked path at a commit, classified
without running anything; taken after each push; unchanged content stays read across commits.
GitHub's API is faked (conftest.FakeGitHub); the repo is fetched from a local git repo."""
import subprocess
import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import update

from dotrix_backend.modules.code.checkouts import CodeCheckouts, RepoRef
from dotrix_backend.modules.repo_knowledge.models import PathStatus, RepoPath


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout.strip()


def _commit(origin: Path, files: dict[str, bytes | str], message: str = "change") -> str:
    for path, content in files.items():
        file = origin / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(content if isinstance(content, bytes) else content.encode())
    _git(origin, "add", "-A")
    _git(origin, "-c", "user.email=a@b.c", "-c", "user.name=A", "commit", "-qm", message)
    return _git(origin, "rev-parse", "HEAD")


@pytest.fixture
def origin(tmp_path: Path, checkouts: CodeCheckouts) -> Path:
    root = tmp_path / "origin"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _commit(root, {
        "README.md": "# Kunemi\n\nMoves people around town.\n",
        "src/payments.py": "class PaymentProvider:\n    pass\n",
        "src/api/routes.py": "ROUTES = []\n",
        "tests/test_payments.py": "def test_it():\n    assert True\n",
        "package.json": '{"name": "kunemi"}\n',
        "pnpm-lock.yaml": "lockfileVersion: '9.0'\n",
        "node_modules/left-pad/index.js": "module.exports = 1\n",
        "web/logo.png": b"\x89PNG\r\n\x1a\n\0\0\0",
        ".github/workflows/ci.yml": "on: push\n",
        "migrations/001_init.sql": "create table rides (id int);\n",
    })

    async def remote(ref: RepoRef) -> tuple[str, str | None]:
        return str(root), None

    checkouts.remote = remote
    return root


async def _connect(db_client: AsyncClient, ws: str, project: dict, headers: dict) -> None:
    installation = (await db_client.post(f"{ws}/github/installations", json={"installation_id": 111, "code": "code-1"},
                                          headers=headers)).json()
    res = await db_client.put(f"{ws}/projects/{project['id']}/repository",
                              json={"installation_ref": installation["id"], "github_repo_id": 9001}, headers=headers)
    assert res.status_code == 200, res.text


async def test_connecting_takes_the_inventory_and_coverage_names_every_domain(
    db_client: AsyncClient, github_world, github, origin: Path
) -> None:
    ada, cat, ws, kun, _ = await github_world()
    base = f"{ws}/projects/{kun['id']}/repository/knowledge"
    empty = (await db_client.get(base, headers=ada.headers)).json()
    assert empty["snapshot"] is None and not empty["inventory_complete"]

    await _connect(db_client, ws, kun, ada.headers)  # its first sync takes the inventory
    coverage = (await db_client.get(base, headers=cat.headers)).json()
    assert coverage["snapshot"]["commit_sha"] == _git(origin, "rev-parse", "HEAD")
    assert coverage["snapshot"]["path_count"] == 10 and coverage["inventory_complete"]
    assert coverage["statuses"] == {"pending": 8, "excluded": 2} and not coverage["discovery_complete"]
    domains = {d["domain"]: d for d in coverage["domains"]}
    assert len(domains) == 12  # every required domain: evidence, or a named gap
    assert domains["quality"]["status"] == "pending" and domains["quality"]["paths"] == 2  # the test, CI
    assert domains["decisions"]["status"] == "gap" and "ADR" in domains["decisions"]["gap"]
    assert domains["design"]["excluded"] == 1 and domains["design"]["status"] == "gap"  # only a binary logo

    excluded = (await db_client.get(f"{base}/paths?status=excluded", headers=cat.headers)).json()["paths"]
    assert {p["path"]: p["reason"] for p in excluded} == {
        "node_modules/left-pad/index.js": "Vendored third-party code", "web/logo.png": "Binary: listed, not read"}
    page = (await db_client.get(f"{base}/paths?limit=3", headers=cat.headers)).json()
    rest = (await db_client.get(f"{base}/paths?limit=500&after={page['next']}", headers=cat.headers)).json()
    assert len(page["paths"]) == 3 and len(rest["paths"]) == 7 and rest["next"] is None
    deps = (await db_client.get(f"{base}/paths?domain=dependencies", headers=cat.headers)).json()["paths"]
    assert {p["path"] for p in deps} == {"package.json", "pnpm-lock.yaml"}

    # Taking it again at the same commit is the same inventory; members who don't edit documents can't.
    assert (await db_client.post(f"{base}/inventory", headers=cat.headers)).status_code == 403
    again = await db_client.post(f"{base}/inventory", headers=ada.headers)
    assert again.status_code == 201 and again.json()["id"] == coverage["snapshot"]["id"]


async def test_a_push_takes_a_new_inventory_and_unchanged_content_stays_read(
    db_client: AsyncClient, github_world, deliver, github, origin: Path
) -> None:
    ada, _, ws, kun, _ = await github_world()
    base = f"{ws}/projects/{kun['id']}/repository/knowledge"
    await _connect(db_client, ws, kun, ada.headers)
    first = (await db_client.get(base, headers=ada.headers)).json()["snapshot"]
    # The skill read the two source files (it records that itself; here, directly).
    factory = db_client._transport.app.state.jobs.ctx.session_factory  # type: ignore[attr-defined]
    async with factory() as session:
        await session.execute(update(RepoPath).where(
            RepoPath.snapshot_id == uuid.UUID(first["id"]), RepoPath.path.in_(["src/payments.py", "src/api/routes.py"]),
        ).values(status=PathStatus.ANALYZED))
        await session.commit()

    second = _commit(origin, {"src/payments.py": "class PaymentProvider:\n    def refund(self):\n        pass\n",
                              "src/refunds.py": "def refund():\n    pass\n"})
    push = {"ref": "refs/heads/main", "after": second,
            "repository": {"id": 9001, "full_name": "kunemi/api", "default_branch": "main"}}
    assert (await deliver("push", push)).status_code == 202
    coverage = (await db_client.get(base, headers=ada.headers)).json()
    assert coverage["snapshot"]["commit_sha"] == second and coverage["snapshot"]["path_count"] == 11
    statuses = {p["path"]: p["status"] for p in (await db_client.get(f"{base}/paths?prefix=src/",
                                                                      headers=ada.headers)).json()["paths"]}
    # Unchanged since it was read: still read. Changed or new: to read again.
    assert statuses == {"src/api/routes.py": "analyzed", "src/payments.py": "pending", "src/refunds.py": "pending"}
    architecture = next(d for d in coverage["domains"] if d["domain"] == "architecture")
    assert architecture["status"] == "partial" and architecture["analyzed"] == 1


async def test_a_moved_project_keeps_its_inventory(db_client: AsyncClient, github_world, github, origin: Path) -> None:
    ada, _, ws, kun, _ = await github_world()
    await _connect(db_client, ws, kun, ada.headers)
    before = (await db_client.get(f"{ws}/projects/{kun['id']}/repository/knowledge", headers=ada.headers)).json()
    personal = next(w for w in (await db_client.get("/v1/workspaces", headers=ada.headers)).json()
                    if w["kind"] == "personal")
    moved = await db_client.post(f"{ws}/projects/{kun['id']}/move", json={"workspace_id": personal["id"]},
                                 headers=ada.headers)
    assert moved.status_code == 200, moved.text
    base = f"/v1/workspaces/{personal['id']}/projects/{kun['id']}/repository/knowledge"
    after = (await db_client.get(base, headers=ada.headers)).json()
    assert after["snapshot"]["id"] == before["snapshot"]["id"] and after["statuses"] == before["statuses"]
    assert len((await db_client.get(f"{base}/paths", headers=ada.headers)).json()["paths"]) == 10


async def test_explaining_the_repository_reads_marks_and_cites(
    db_client: AsyncClient, github_world, github, origin: Path, agent_script
) -> None:
    from langchain_core.messages import ToolMessage

    from dotrix_engine.testing import tool_call

    ada, cat, ws, kun, _ = await github_world()
    base = f"{ws}/projects/{kun['id']}/repository/knowledge"
    await _connect(db_client, ws, kun, ada.headers)
    page = ("# Architecture\n\nPayments go through one provider class (observed) `src/payments.py:1`, "
            "routes are listed in one place `src/api/routes.py:1`.\n\n## Gaps and questions\n- Who owns refunds?\n")
    model = agent_script.say(
        tool_call("repo_coverage", call_id="c1"),
        tool_call("repo_paths", call_id="c2", domain="architecture"),
        tool_call("repo_mark_read", call_id="c3", paths=["src/payments.py", "src/api/routes.py", "src/nope.py"]),
        tool_call("repo_check_page", call_id="c4", content=page + "Also `src/payments.py:40` and `src/gone.py:1`."),
        tool_call("repo_check_page", call_id="c5", content=page),
        tool_call("write_file", call_id="c6", file_path="/dotrix/docs/wiki/architecture.md", content=page),
        "Explained the architecture; data, delivery, and the rest are still to read.",
    )
    assert (await db_client.post(f"{base}/explain", json={}, headers=cat.headers)).status_code == 403
    assert (await db_client.post(f"{base}/explain", json={"domains": ["vibes"]}, headers=ada.headers)).status_code == 422
    res = await db_client.post(f"{base}/explain", json={"domains": ["architecture"]}, headers=ada.headers)
    assert res.status_code == 202, res.text
    run = res.json()
    assert run["mode"] == "docs.repository" and run["agent"] == "documentation"
    assert run["status"] == "awaiting_approval", run  # the page waits for a person, like any document
    assert {"repo_coverage", "repo_paths", "repo_mark_read", "repo_check_page"} <= set(model.tools_received[0])
    assert "Start with: architecture." in model.received[0][-1].content

    said = {m.tool_call_id: m.content for m in model.received[-1] if isinstance(m, ToolMessage)}
    assert '"status": "pending"' in said["c1"] and "src/payments.py" in said["c2"]
    assert '"marked": 2' in said["c3"] and "src/nope.py" in said["c3"]
    assert "the file has 2 lines" in said["c4"] and "src/gone.py:1`: no such path" in said["c4"]
    assert '"ok": true' in said["c5"]

    coverage = (await db_client.get(base, headers=cat.headers)).json()
    architecture = next(d for d in coverage["domains"] if d["domain"] == "architecture")
    assert architecture["analyzed"] == 2 and architecture["status"] == "covered"  # its two source files
    read = (await db_client.get(f"{base}/paths?status=analyzed", headers=cat.headers)).json()["paths"]
    assert {p["path"] for p in read} == {"src/payments.py", "src/api/routes.py"}
