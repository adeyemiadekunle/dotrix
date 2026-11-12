"""Execute task graphs through real git checkouts and isolated local test sandboxes."""
import json
import subprocess
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from dotrix_backend.modules.coding import parallel
from dotrix_backend.modules.coding.runner import RunFailed
from dotrix_backend.modules.coding.sandbox import LocalSandbox
from dotrix_backend.modules.coding.slots import RunSlots


@pytest.mark.parametrize("dependent", [True, False])
async def test_task_graph_integrates_dependencies_and_rejects_scope(tmp_path, monkeypatch, dependent):
    host = tmp_path / "host"
    host.mkdir()

    def git(*args):
        return subprocess.check_output(["git", "-C", str(host), *args], text=True).strip()

    git("init", "-q")
    (host / "base.txt").write_text("base")
    git("add", ".")
    git("-c", "user.name=test", "-c", "user.email=test@example.com", "commit", "-qm", "base")
    sha = git("rev-parse", "HEAD")
    run = SimpleNamespace(repo_full_name="owner/repo", task_records={})

    @asynccontextmanager
    async def sessions():
        class Session:
            async def get(self, *args):
                return run
        yield Session()

    async def record(runner, run_id, key, **fields):
        run.task_records[key] = {**run.task_records.get(key, {}), **fields}

    monkeypatch.setattr(parallel, "record", record)
    calls = []

    async def code(run_id, box, tool, model, session_id, brief, extra, cost, **kw):
        task = json.loads(brief.split("## Assigned task\n")[1].split("\nImplement only")[0])
        calls.append(task["key"])
        root = box.root / "repo"
        if task["key"] == "second" and dependent:
            assert (root / "first.txt").read_text() == "first"
        (root / task["owned_paths"][0]).write_text(task["key"])
        return task["key"], None

    async def no(*args):
        return False

    runner = SimpleNamespace(session_factory=sessions, sandbox=LocalSandbox(), slots=RunSlots(2), _code=code,
                             stop_requested=no, reconciliation_required=no,
                             settings=SimpleNamespace(coding_timeout_minutes=1))
    tool = SimpleNamespace(sandbox_env=lambda key: {}, session_args=lambda *args: [])
    tasks = [{"key": key, "task_number": i, "owned_paths": [f"{key}.txt"], "instructions": "Implement",
              "checks": [{"command": "true", "expected": "passes"}], "stop_conditions": ["drift"]}
             for i, key in enumerate(["first", "second"], 1)]
    spec = {"repository": "owner/repo", "base_sha": sha, "tasks": tasks}
    import uuid

    summary, patch = await parallel.execute(runner, uuid.uuid4(), tmp_path / "work", host, tool, "test", None,
                                             "Task", [], spec, {1: [], 2: [1] if dependent else []})
    assert calls == ["first", "second"]
    assert b"first.txt" in patch and b"second.txt" in patch
    assert "Combined verification passed" in summary
    assert git("rev-parse", "HEAD") == sha
    assert all(item["status"] == "completed" for item in run.task_records.values())
    with pytest.raises(RunFailed, match="unassigned"):
        parallel.check_scope(["other.txt"], ["src/"])
    with pytest.raises(RunFailed, match="changed since"):
        await parallel.execute(runner, uuid.uuid4(), tmp_path / "drift", host, tool, "test", None,
                               "Task", [], {**spec, "base_sha": "a" * 40}, {1: [], 2: [1] if dependent else []})
