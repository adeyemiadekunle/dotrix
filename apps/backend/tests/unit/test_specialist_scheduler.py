from types import SimpleNamespace

from dotrix_backend.modules.agents.delegation import ready_tasks
from dotrix_backend.modules.agents.models import RunStatus


def task(key, *, status=RunStatus.WAITING_DEPENDENCY, writes=False, dependencies=(), result=None):
    return SimpleNamespace(task_key=key, status=status, task_mutates=writes, depends_on=list(dependencies), task_result=result)


def test_parallel_analysis_and_exclusive_changes():
    a, b, c = [task(key) for key in "abc"]
    assert ready_tasks([a, b, c]) == [a, b]
    a.status = RunStatus.RUNNING
    assert ready_tasks([a, b, c]) == [b]
    writer = task("writer", writes=True)
    assert ready_tasks([writer, a]) == []
    a.status = RunStatus.COMPLETED
    assert ready_tasks([writer, a]) == [writer]
    assert ready_tasks([writer, a], other_active=True) == []
    assert ready_tasks([b, c], writer_busy=True) == []


def test_failed_or_partial_dependencies_block_descendants_but_not_siblings():
    failed = task("a", status=RunStatus.FAILED)
    dependent = task("b", dependencies=["a"])
    independent = task("c")
    assert ready_tasks([failed, dependent, independent]) == [independent]
    assert dependent.status is RunStatus.BLOCKED
    partial = task("x", status=RunStatus.COMPLETED, result={"status": "partial"})
    next_task = task("y", dependencies=["x"])
    assert ready_tasks([partial, next_task]) == [] and next_task.status is RunStatus.BLOCKED
