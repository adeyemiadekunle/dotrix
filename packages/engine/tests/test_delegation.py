"""Team boundaries, protected guidance, and schedulable specialist briefs."""
import pytest
from deepagents.backends import CompositeBackend, StateBackend
from pydantic import ValidationError

from dotrix_engine.agent import build_team
from dotrix_engine.builtins import builtin, configure_builtin, role_instructions
from dotrix_engine.delegation import SpecialistBatch
from dotrix_engine.testing import ScriptedChatModel, tool_call


def task(key, depends_on=()):
    return {"key": key, "agent": "research", "brief": "Investigate this", "expected_result": "Evidence", "depends_on": list(depends_on)}


def test_batches_reject_cycles_missing_dependencies_and_custom_agents():
    for tasks in ([task("a", ["a"])], [task("a", ["missing"])], [task("a"), task("a")],
                  [task("a", ["b"]), task("b", ["a"])], [task("a") | {"agent": "security"}]):
        with pytest.raises(ValidationError):
            SpecialistBatch(tasks=tasks)


def test_additional_guidance_preserves_the_code_owned_role():
    base = builtin("reviewer")
    legacy = base.model_copy(update={"name": "New identity", "instructions": "Legacy guidance",
                                    "additional_instructions": "Check accessibility", "tools": [*base.tools, "knowledge.write"]})
    configured = configure_builtin(legacy, "Workspace conventions")
    assert configured.name == "Juno" and configured.instructions == base.instructions
    assert "knowledge.write" not in configured.tools
    prompt = role_instructions(configured)
    assert prompt.index(base.instructions) < prompt.index("Workspace conventions") < prompt.index("Legacy guidance") < prompt.index("Check accessibility")


def test_platform_has_no_native_delegation_path():
    model = ScriptedChatModel.of(tool_call("task", description="Skip durable work", subagent_type="research-agent"), "I will use durable delegation.")
    graph = build_team("Demo", "Demo", model, CompositeBackend(default=StateBackend(), routes={}), platform_delegation=True)
    result = graph.invoke({"messages": [{"role": "user", "content": "Research"}]})
    assert all("task" not in names for names in model.tools_received)
    message = next(message for message in result["messages"] if message.type == "tool")
    assert message.status == "error"
