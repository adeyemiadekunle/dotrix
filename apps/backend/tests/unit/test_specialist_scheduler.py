import uuid
from types import SimpleNamespace

from dotrix_backend.modules.agents.delegation import ready_tasks
from dotrix_backend.modules.agents.models import RunStatus
from dotrix_backend.modules.agents.specialist_sessions import _policy_fingerprint
from dotrix_engine.builtins import builtin
from dotrix_engine.permissions import Access


def task(key, *, status=RunStatus.WAITING_DEPENDENCY, writes=False, dependencies=(), result=None,
         allow_partial=False):
    return SimpleNamespace(
        task_key=key, status=status, task_mutates=writes, depends_on=list(dependencies),
        task_result=result, specialist_session_id=None, allow_partial_dependencies=allow_partial,
    )


def test_parallel_analysis_and_exclusive_changes():
    a, b, c, d, e = [task(key) for key in "abcde"]
    assert ready_tasks([a, b, c, d, e]) == [a, b, c, d]
    assert ready_tasks([a, b, c, d, e], limit=2) == [a, b]
    a.status = RunStatus.RUNNING
    assert ready_tasks([a, b, c, d, e]) == [b, c, d]
    assert ready_tasks([a, b, c, d, e], limit=2) == [b]
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


def test_allow_partial_dependencies_proceeds_on_partial_but_blocks_failed_and_blocked():
    partial = task("x", status=RunStatus.COMPLETED, result={"status": "partial"})
    proceed = task("y", dependencies=["x"], allow_partial=True)
    assert ready_tasks([partial, proceed]) == [proceed]

    failed = task("f", status=RunStatus.FAILED)
    blocked_after_fail = task("y_fail", dependencies=["f"], allow_partial=True)
    assert ready_tasks([failed, blocked_after_fail]) == []
    assert blocked_after_fail.status is RunStatus.BLOCKED

    blocked_upstream = task("b", status=RunStatus.COMPLETED, result={"status": "blocked"})
    blocked_downstream = task("y_blocked", dependencies=["b"], allow_partial=True)
    assert ready_tasks([blocked_upstream, blocked_downstream]) == []
    assert blocked_downstream.status is RunStatus.BLOCKED


def test_a_specialist_session_only_has_one_active_task():
    first, second, other = [task(key) for key in "abc"]
    first.specialist_session_id = second.specialist_session_id = uuid.uuid4()
    other.specialist_session_id = uuid.uuid4()
    assert ready_tasks([first, second, other]) == [first, other]
    first.status = RunStatus.RUNNING
    assert ready_tasks([first, second, other]) == [other]
    first.status = RunStatus.COMPLETED
    assert ready_tasks([second, other], occupied_sessions={second.specialist_session_id}) == [other]


def test_policy_fingerprint_respects_first_matching_folder_rule():
    spec = builtin("research")
    assert spec is not None
    broad_first = spec.model_copy(update={"access": {"*": Access.READ, "research/*": Access.PROPOSE}})
    narrow_first = spec.model_copy(update={"access": {"research/*": Access.PROPOSE, "*": Access.READ}})
    assert broad_first.folder_access("research/runtime.md") != narrow_first.folder_access("research/runtime.md")
    assert _policy_fingerprint(broad_first) != _policy_fingerprint(narrow_first)
