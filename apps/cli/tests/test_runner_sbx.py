"""`dotrix runner` with Docker Sandboxes (`sbx`): each local turn's tool in a microVM of its own.

A real sbx needs KVM (or Hyper-V, or Apple's hypervisor), so these run a fake `sbx` that records how
it's called and, for `exec`, runs a scripted tool in the worktree as the sandbox would.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from dotrix_cli.runner import LocalRunner, Sbx

FAKE_SBX = r'''
import json, os, subprocess, sys
log = os.environ["FAKE_SBX_LOG"]
args = sys.argv[1:]
with open(log, "a") as f:
    f.write(json.dumps(args) + "\n")
if args[0] == "run" and os.environ.get("FAKE_SBX_START_FAILS"):
    sys.stderr.write("sbx: policy not initialized; run `sbx policy init`\n")
    sys.exit(2)
if args[0] == "exec":
    workdir = args[args.index("--workdir") + 1]
    brief = sys.stdin.read()
    tool = os.environ["FAKE_TOOL"]
    sys.exit(subprocess.run([sys.executable, "-c", tool, brief], cwd=workdir).returncode)
'''

EDITS = (
    "import json, sys; open('a.txt', 'a').write('fixed\\n'); "
    "print(json.dumps({'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'id': 't1', 'name': 'Bash', "
    "'input': {'command': 'pytest -q'}}]}}), flush=True); "
    "print(json.dumps({'type': 'result', 'result': 'Fixed it; the tests pass.'}), flush=True)"
)
NO_KEY = "import sys; sys.stderr.write('Invalid API key · Please run /login\\n'); sys.exit(1)"


def checkout(tmp_path: Path) -> Path:
    origin = tmp_path / "origin"
    subprocess.run(["git", "init", "-q", "-b", "main", str(origin)], check=True)
    (origin / "a.txt").write_text("a\n")
    subprocess.run(["git", "-C", str(origin), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(origin), "-c", "user.email=a@b.c", "-c", "user.name=A", "commit", "-qm", "1"], check=True)
    repo = tmp_path / "checkout"
    subprocess.run(["git", "clone", "-q", str(origin), str(repo)], check=True)
    return repo


@pytest.fixture
def fake_sbx(tmp_path: Path, monkeypatch) -> tuple[Sbx, Path]:
    script = tmp_path / "fake_sbx.py"
    script.write_text(FAKE_SBX)
    binary = tmp_path / "sbx"
    binary.write_text(f"#!/bin/sh\nexec {sys.executable} {script} \"$@\"\n")
    binary.chmod(0o755)
    log = tmp_path / "sbx.log"
    monkeypatch.setenv("FAKE_SBX_LOG", str(log))
    return Sbx(str(binary)), log


def calls(log: Path) -> list[list[str]]:
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


class Api:
    def __init__(self) -> None:
        self.bodies: list[tuple[str, dict]] = []

    async def post(self, path: str, body=None):
        self.bodies.append((path.rsplit("/", 1)[-1], body or {}))
        if path.endswith("/runners"):
            return {"id": "r1", "name": "laptop", "isolation": body["isolation"], "tools": body["tools"]}
        return {"stop": False}

    def result(self) -> dict:
        return next(body for kind, body in self.bodies if kind == "result")


RUN = {"run_id": "run-000001", "project_id": "p", "lease_token": 7, "lease_seconds": 120, "issue_key": "KUN-1", "turn": 1,
       "title": "Fix it", "base_branch": "main", "branch": None, "tool": "claude-code", "brief": "Fix a.txt"}


@pytest.mark.skipif(os.name == "nt", reason="the fake sbx is a shell script")
async def test_a_turn_runs_in_its_own_sandbox_and_may_run_commands(tmp_path: Path, fake_sbx, monkeypatch) -> None:
    sbx, log = fake_sbx
    monkeypatch.setenv("FAKE_TOOL", EDITS)
    api = Api()
    runner = LocalRunner(api=api, repo=checkout(tmp_path), workspace_id="w", project_id="p", sbx=sbx,
                         worktrees=tmp_path / "trees", echo=lambda _: None)
    registered = await runner.register()
    # Registered as isolated, offering every tool: the templates carry them, nothing to install here.
    assert registered["isolation"] == "sbx" and registered["tools"] == ["claude-code", "opencode"]

    await runner.work(RUN)
    run, exec_, *_ = calls(log)
    tree = run[-1]
    assert run[:5] == ["run", "-d", "--name", "dotrix-kun-1-000001-7", "claude"]
    assert Path(tree).is_relative_to(tmp_path / "trees")  # only the turn's worktree is mounted
    assert exec_[:6] == ["exec", "-i", "--workdir", tree, "dotrix-kun-1-000001-7", "--"]
    assert "--dangerously-skip-permissions" in exec_ and "acceptEdits" not in exec_  # the VM is the boundary
    result = api.result()
    assert result["outcome"] == "changes" and "+fixed" in result["patch"]
    assert result["summary"] == "Fixed it; the tests pass."
    sent = [e["text"] for kind, body in api.bodies if kind in ("heartbeat", "result") for e in body.get("events", [])]
    assert any(text.startswith("In a Docker sandbox on this computer") for text in sent)


@pytest.mark.skipif(os.name == "nt", reason="the fake sbx is a shell script")
async def test_the_sandbox_is_removed_when_the_turn_ends(tmp_path: Path, fake_sbx, monkeypatch) -> None:
    sbx, log = fake_sbx
    monkeypatch.setenv("FAKE_TOOL", EDITS)

    class Claiming(Api):
        async def post(self, path: str, body=None):
            if path.endswith("/claim"):
                return {"run": RUN}
            return await super().post(path, body)

    runner = LocalRunner(api=Claiming(), repo=checkout(tmp_path), workspace_id="w", project_id="p", sbx=sbx,
                         worktrees=tmp_path / "trees", echo=lambda _: None, runner_id="r1")
    assert await runner.once()
    assert calls(log)[-1] == ["rm", "--force", "dotrix-kun-1-000001-7"]


@pytest.mark.skipif(os.name == "nt", reason="the fake sbx is a shell script")
async def test_a_turn_without_a_key_says_how_to_add_one(tmp_path: Path, fake_sbx, monkeypatch) -> None:
    sbx, _ = fake_sbx
    monkeypatch.setenv("FAKE_TOOL", NO_KEY)
    api = Api()
    runner = LocalRunner(api=api, repo=checkout(tmp_path), workspace_id="w", project_id="p", sbx=sbx, runner_id="r1",
                         worktrees=tmp_path / "trees", echo=lambda _: None)
    await runner.work(RUN)
    result = api.result()
    assert result["outcome"] == "failed" and "sbx secret set anthropic" in result["error"]


@pytest.mark.skipif(os.name == "nt", reason="the fake sbx is a shell script")
async def test_a_sandbox_that_will_not_start_fails_the_turn_with_why(tmp_path: Path, fake_sbx, monkeypatch) -> None:
    sbx, log = fake_sbx
    monkeypatch.setenv("FAKE_TOOL", EDITS)
    monkeypatch.setenv("FAKE_SBX_START_FAILS", "1")
    api = Api()
    runner = LocalRunner(api=api, repo=checkout(tmp_path), workspace_id="w", project_id="p", sbx=sbx, runner_id="r1",
                         worktrees=tmp_path / "trees", echo=lambda _: None)
    await runner.work(RUN)
    result = api.result()
    assert result["outcome"] == "failed" and "Couldn't start the Docker sandbox" in result["error"]
    assert "policy not initialized" in result["error"]
    assert not any(c[0] == "exec" for c in calls(log))  # the tool never ran outside it


async def test_isolation_choices(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("dotrix_cli.runner.shutil.which", lambda name: None)  # no sbx, no tools here
    plain = LocalRunner(api=Api(), repo=tmp_path, workspace_id="w", project_id="p", command="true")
    assert plain.sbx is None and (await plain.register())["isolation"] == "none"
    required = LocalRunner(api=Api(), repo=tmp_path, workspace_id="w", project_id="p", isolation="sbx")
    with pytest.raises(RuntimeError, match="Docker Sandboxes isn't installed"):
        await required.register()
    off = LocalRunner(api=Api(), repo=tmp_path, workspace_id="w", project_id="p", sbx=Sbx("/usr/bin/sbx"), isolation="none")
    assert off.sbx is None
    with pytest.raises(ValueError):
        LocalRunner(api=Api(), repo=tmp_path, workspace_id="w", project_id="p", isolation="maybe")
