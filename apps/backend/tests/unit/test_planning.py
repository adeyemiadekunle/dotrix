"""Planning rejects invalid execution graphs before accessing persistence."""
from types import SimpleNamespace

from dotrix_backend.modules.agents.work_modes import SavePlan, _save_plan


async def test_plan_rejects_dependency_cycle_before_saving():
    plan = SavePlan(title="Cycle", summary="Invalid", acceptance_criteria=[], tasks=[
        {"title": "A", "depends_on": [2]}, {"title": "B", "depends_on": [1]},
    ])
    assert await _save_plan(SimpleNamespace(), plan) == {"error": "Task dependencies contain a cycle"}


async def test_plan_rejects_unknown_dependency_before_saving():
    plan = SavePlan(title="Missing", summary="Invalid", acceptance_criteria=[], tasks=[
        {"title": "A", "depends_on": [2]},
    ])
    assert "isn't in the plan" in (await _save_plan(SimpleNamespace(), plan))["error"]


async def test_kai_receives_universal_custom_skills(monkeypatch):
    from unittest.mock import AsyncMock

    from dotrix_backend.modules.coding import brief

    shared = "# Shared procedure\nDescription: All agents follow this\nAlways check the agreed acceptance criteria."
    repo = SimpleNamespace(list_files=AsyncMock(return_value=[]))
    workspace = SimpleNamespace(texts=AsyncMock(return_value={"shared-procedure": shared}))
    monkeypatch.setattr(brief, "KnowledgeRepository", lambda session: repo)
    monkeypatch.setattr(brief, "WorkspaceSkills", lambda session: workspace)
    monkeypatch.setattr(brief, "default_skills", lambda: {})
    result = await brief._standards(None, SimpleNamespace(id="project", workspace_id="workspace", name="Test"), "Small fix")
    assert shared in "\n".join(result)


def test_readonly_process_cannot_edit_repository(tmp_path):
    import subprocess
    import sys

    import pytest

    from dotrix_backend.modules.coding.planning import readonly_command

    target = tmp_path / "source.txt"
    target.write_text("original")
    code = "from pathlib import Path; import os; Path(os.environ['HOME'], 'scratch').write_text('ok'); Path('source.txt').write_text('changed')"
    result = subprocess.run(readonly_command([sys.executable, "-c", code]), cwd=tmp_path, capture_output=True, text=True)
    if "Read-only planning" in result.stderr:
        assert result.returncode != 0 and target.read_text() == "original"
        pytest.skip("This host refuses Landlock; Plan turns fail closed here")
    assert result.returncode != 0 and "PermissionError" in result.stderr
    assert target.read_text() == "original"


def test_coding_plan_rejects_invalid_dependency_graph():
    import json

    import pytest

    from dotrix_backend.modules.coding.planning import parse_plan

    with pytest.raises(ValueError, match="cycle"):
        parse_plan(json.dumps({"title": "Plan", "summary": "Summary", "acceptance_criteria": [],
                               "tasks": [{"title": "Task", "depends_on": [1]}]}))


async def test_skill_snapshot_is_stable_across_recovery(monkeypatch):
    from unittest.mock import AsyncMock

    from dotrix_backend.modules.agents import skill_snapshots

    resolver = AsyncMock(return_value={"shared": "Description: Original instructions"})
    monkeypatch.setattr(skill_snapshots, "resolve", resolver)
    async def with_resources(session, project, texts):
        return skill_snapshots.versioned(texts)
    monkeypatch.setattr(skill_snapshots, "with_resources", with_resources)
    session = SimpleNamespace(commit=AsyncMock())
    run = SimpleNamespace(skill_snapshot=None, workspace_id="workspace", project_id="project")
    first = await skill_snapshots.pin(session, run, None)
    resolver.return_value = {"shared": "Description: Changed instructions"}
    assert await skill_snapshots.pin(session, run, None) == first
    assert resolver.await_count == 1
    assert len(run.skill_snapshot["shared"]["sha256"]) == 64


async def test_extra_worker_slot_never_waits_for_capacity():
    from dotrix_backend.modules.coding.slots import RunSlots

    slots = RunSlots(1)
    async def no():
        return False
    async def wait():
        pass
    async with slots.take(on_wait=wait, stopped=no):
        async with slots.extra() as admitted:
            assert admitted is False
    async with slots.extra() as admitted:
        assert admitted is True
