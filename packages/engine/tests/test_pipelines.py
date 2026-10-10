"""Pipelines: stage guidance, the defaults, a run's mode, and the checkpoint round trip."""
import pytest
from deepagents.backends import CompositeBackend, StateBackend
from langgraph.checkpoint.memory import InMemorySaver

from dotrix_engine import approvals
from dotrix_engine.agent import build_team
from dotrix_engine.builtins import builtin_specs
from dotrix_engine.outputs import SCHEMAS
from dotrix_engine.pipelines import DEFAULTS, MODES, PIPELINES, instructions
from dotrix_engine.testing import ScriptedChatModel, tool_call


def _team(model, **kwargs):
    backend = CompositeBackend(default=StateBackend(), routes={"/dotrix/": StateBackend()})
    return build_team("Kunemi", "x", model, backend, checkpointer=InMemorySaver(),
                      stage_sink=lambda handle, stage: None, result_sink=lambda schema, items: None, **kwargs)


def test_every_pipeline_is_well_formed() -> None:
    for pipeline in PIPELINES.values():
        names = pipeline.stage_names
        assert len(names) == len(set(names)) and all(s.guidance for s in pipeline.stages), pipeline.name
        assert pipeline.output is None or pipeline.output in SCHEMAS
    assert set(MODES) <= set(PIPELINES)


def test_built_ins_follow_their_default_pipelines() -> None:
    for spec in builtin_specs():
        assert spec.pipeline == DEFAULTS[spec.handle]
        expected = PIPELINES[spec.pipeline].output if spec.handle != "project-manager" else None
        assert spec.output == expected


def test_the_checkpoint_line_only_when_the_agent_can_steer() -> None:
    assert "call `checkpoint`" in instructions("pm.request", can_steer=True)
    assert "checkpoint" not in instructions("pm.request", can_steer=False)
    assert "call `checkpoint`" not in instructions("pm.triage", can_steer=True)  # no checkpoint stage


def test_an_unknown_mode_is_refused() -> None:
    with pytest.raises(ValueError, match="Unknown mode"):
        _team(ScriptedChatModel.of("x"), mode="reviewer.coverage")


def _checkpointed(decision):
    model = ScriptedChatModel.of(
        tool_call("checkpoint", summary="Big job", plan=["Spec", "Impact"]),
        "Done.",
    )
    team = _team(model)
    config = {"configurable": {"thread_id": "c"}}
    result = team.invoke({"messages": [{"role": "user", "content": "plan it"}]}, config)
    assert [a["tool"] for a in approvals.pending_actions(result)] == ["checkpoint"]
    result = team.invoke(approvals.resume_command(result, [decision]), config)
    return [str(m.content) for m in result["messages"] if m.type == "tool"], result


def test_continuing_at_a_checkpoint_says_go_ahead() -> None:
    tool_messages, result = _checkpointed("approve")
    assert tool_messages[-1] == "The person said to go ahead with the plan."
    assert result["messages"][-1].content == "Done."


def test_changing_the_plan_reaches_the_agent() -> None:
    tool_messages, _ = _checkpointed(("reject", "Skip the impact; just the spec."))
    assert "Skip the impact; just the spec." in tool_messages[-1]


def test_only_the_agent_talking_to_the_person_checkpoints() -> None:
    model = ScriptedChatModel.of("Fine.")
    _team(model, lead="research").invoke({"messages": [{"role": "user", "content": "q"}]},
                                         {"configurable": {"thread_id": "r"}})
    assert "checkpoint" in model.tools_received[0]  # leading, it may

    # Called by the PM, it reports stages but can't stop for the person.
    model = ScriptedChatModel.of(
        tool_call("task", subagent_type="research-agent", description="Who else does multi-zone?"),
        "Three competitors.",
        "Summary.",
    )
    _team(model).invoke({"messages": [{"role": "user", "content": "q"}]}, {"configurable": {"thread_id": "s"}})
    pm_tools, research_tools = model.tools_received[0], model.tools_received[1]
    assert "checkpoint" in pm_tools
    assert "stage" in research_tools and "checkpoint" not in research_tools and "submit_result" not in research_tools
