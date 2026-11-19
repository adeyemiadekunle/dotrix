from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from dotrix_engine.planning import ExecutionSpec, ExecutionTask, paths_overlap


def task(number, path):
    return {"key": f"task-{number}", "task_number": number, "owned_paths": [path],
            "instructions": "Implement the agreed behavior", "checks": [{"command": "pytest", "expected": "passes"}],
            "stop_conditions": ["The shared interface differs from the plan"]}


def spec(*paths):
    return ExecutionSpec(repository="owner/repo", base_sha="a" * 40,
                         tasks=[task(i, path) for i, path in enumerate(paths, 1)])


@pytest.mark.parametrize("path", ["/tmp/x", "../x", "src/../x", "src//x", "./x", ".git/config", "src/.git/config",
                                   ".dotrix/a", "src/*.py", "C:/x", "src\\x", "x\n", ""])
def test_execution_paths_cannot_escape_or_expand(path):
    with pytest.raises(ValidationError):
        ExecutionTask(**task(1, path))


def test_scheduler_limits_concurrency_and_waits_for_dependencies():
    plan = spec("api/", "web/", "tests/")
    deps = {1: [], 2: [], 3: [1, 2]}
    assert plan.ready_tasks(deps, set(), set(), limit=20) == [1, 2]
    assert plan.ready_tasks(deps, {1}, {2}) == []
    assert plan.ready_tasks(deps, {1, 2}, set()) == [3]


def test_scheduler_serializes_overlapping_ownership():
    plan = spec("src/", "src/main.py", "src-other/main.py")
    deps = {1: [], 2: [], 3: []}
    assert plan.ready_tasks(deps, set(), set()) == [1, 3]
    assert plan.ready_tasks(deps, set(), {1}) == [3]
    assert paths_overlap("src", "src/main.py")
    assert not paths_overlap("src", "src-other/main.py")


def test_execution_plan_requires_full_coverage_and_resolved_questions():
    plan = spec("src/")
    with pytest.raises(ValueError, match="cover every"):
        plan.validate_plan([SimpleNamespace(depends_on=[])] * 2, [])
    with pytest.raises(ValueError, match="Resolve open questions"):
        plan.validate_plan([SimpleNamespace(depends_on=[])], ["Which API?"])
    with pytest.raises(ValueError, match="cycle"):
        plan.validate_plan([SimpleNamespace(depends_on=[1])], [])


def test_scheduler_rejects_inconsistent_state():
    plan = spec("src/")
    with pytest.raises(ValueError, match="scheduler state"):
        plan.ready_tasks({1: []}, {1}, {1})
    with pytest.raises(ValueError, match="scheduler state"):
        plan.ready_tasks({1: [2]}, set(), set())
