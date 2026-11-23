"""Evaluation and unit coverage for Nova orchestration guidance, batch DAGs, and delegation boundaries."""
from types import SimpleNamespace

import pytest
from deepagents.backends import CompositeBackend, StateBackend
from langchain_core.messages import ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import ValidationError

from dotrix_engine.agent import build_team
from dotrix_engine.builtins import PM_INSTRUCTIONS
from dotrix_engine.delegation import DelegationBoundary, SpecialistBatch, SpecialistTask
from dotrix_engine.pipelines import instructions as pipeline_instructions
from dotrix_engine.testing import ScriptedChatModel


def _task(key: str, agent: str, *, depends_on: list[str] | None = None, allow_partial: bool = False) -> SpecialistTask:
    return SpecialistTask(
        key=key,
        agent=agent,  # type: ignore[arg-type]
        brief=f"Investigate {key}",
        expected_result=f"Summary for {key}",
        depends_on=depends_on or [],
        allow_partial_dependencies=allow_partial,
    )


def test_nova_instructions_and_pipeline_cover_orchestration_rubric() -> None:
    assert "without delegating" in PM_INSTRUCTIONS
    assert "Batch independent read-only" in PM_INSTRUCTIONS
    assert "allow_partial_dependencies=True" in PM_INSTRUCTIONS
    assert "Surface any conflicts" in PM_INSTRUCTIONS

    steerable = pipeline_instructions("pm.request", can_steer=True)
    unsteerable = pipeline_instructions("pm.request", can_steer=False)
    assert "call `checkpoint`" in steerable
    assert "checkpoint" not in unsteerable
    assert "allow_partial_dependencies" in unsteerable
    assert "conflicts explicitly" in unsteerable


def test_specialist_batch_validates_four_way_fanout_and_partial_merge() -> None:
    batch = SpecialistBatch(tasks=[
        _task("spec", "product"),
        _task("arch", "architecture"),
        _task("research", "research"),
        _task("review", "reviewer"),
        _task(
            "docs",
            "documentation",
            depends_on=["spec", "arch", "research", "review"],
            allow_partial=True,
        ),
    ])
    assert len(batch.tasks) == 5
    assert batch.tasks[-1].allow_partial_dependencies is True

    with pytest.raises(ValidationError, match="unique"):
        SpecialistBatch(tasks=[_task("dup", "product"), _task("dup", "architecture")])

    with pytest.raises(ValidationError, match="Unknown dependency"):
        SpecialistBatch(tasks=[_task("a", "product", depends_on=["missing"])])

    with pytest.raises(ValidationError, match="cycle"):
        SpecialistBatch(tasks=[
            _task("a", "product", depends_on=["b"]),
            _task("b", "architecture", depends_on=["a"]),
        ])


def test_delegation_boundary_blocks_inline_task_tool() -> None:
    boundary = DelegationBoundary()
    seen_tools: list[str] = []

    def model_handler(req):
        seen_tools.extend(getattr(t, "name", str(t)) for t in req.tools)
        return "ok"

    fake_tools = [SimpleNamespace(name="task"), SimpleNamespace(name="read_file")]
    req = SimpleNamespace(tools=fake_tools, override=lambda **kw: SimpleNamespace(**kw))
    assert boundary.wrap_model_call(req, model_handler) == "ok"
    assert seen_tools == ["read_file"]

    blocked = boundary.wrap_tool_call(
        SimpleNamespace(tool_call={"name": "task", "id": "call-1", "args": {"subagent_type": "research"}}),
        lambda _: "unexpected",
    )
    assert isinstance(blocked, ToolMessage)
    assert blocked.status == "error"
    assert "delegate_tasks" in str(blocked.content)


def test_nova_direct_answer_skips_specialist_delegation() -> None:
    model = ScriptedChatModel.of("The project deploys to FastAPI and Postgres without calling specialists.")
    backend = CompositeBackend(default=StateBackend(), routes={"/dotrix/": StateBackend()})
    team = build_team(
        "Kunemi",
        "FastAPI + Postgres app",
        model,
        backend,
        checkpointer=InMemorySaver(),
        stage_sink=lambda handle, stage: None,
        result_sink=lambda schema, items: None,
    )
    result = team.invoke(
        {"messages": [{"role": "user", "content": "What stack does this project use?"}]},
        {"configurable": {"thread_id": "nova-direct"}},
    )
    assert "FastAPI and Postgres" in str(result["messages"][-1].content)
    assert len(model.tools_received) == 1
    assert not any(m.type == "tool" for m in result["messages"])
