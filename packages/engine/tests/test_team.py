"""build_team() runs offline with a scripted model: Chat Mode answers, writes pause."""
from deepagents.backends import CompositeBackend, StateBackend
from langgraph.checkpoint.memory import InMemorySaver

from pmagent_engine import approvals
from pmagent_engine.agent import build_team, role_for_agent_name
from pmagent_engine.testing import ScriptedChatModel, tool_call


def team(model: ScriptedChatModel, rules: dict[str, str] | None = None):
    backend = CompositeBackend(default=StateBackend(), routes={"/pmagent/": StateBackend()})
    return build_team(
        "Kunemi", "Logistics platform", model, backend, checkpointer=InMemorySaver(), rules=rules
    )


def config(thread: str) -> dict:
    return {"configurable": {"thread_id": thread}}


def test_chat_mode_answers() -> None:
    agent = team(ScriptedChatModel.of("Phase: logistics core."))
    result = agent.invoke({"messages": [{"role": "user", "content": "status?"}]}, config("t1"))
    assert result["messages"][-1].content == "Phase: logistics core."
    assert not approvals.has_pending(result)


def test_writes_pause_for_approval_then_resume() -> None:
    model = ScriptedChatModel.of(
        tool_call("write_file", file_path="/pmagent/decisions/ADR-001.md", content="# ADR-001"),
        "Action complete: wrote ADR-001.",
    )
    agent = team(model)
    result = agent.invoke({"messages": [{"role": "user", "content": "log it"}]}, config("t2"))
    pending = approvals.pending_actions(result)
    assert [a["tool"] for a in pending] == ["write_file"]
    assert pending[0]["args"]["file_path"] == "/pmagent/decisions/ADR-001.md"

    resumed = agent.invoke(approvals.resume_command(result, "approve"), config("t2"))
    assert resumed["messages"][-1].content == "Action complete: wrote ADR-001."


def test_rules_are_prepended_to_prompts() -> None:
    model = ScriptedChatModel.of("ok")
    agent = team(model, rules={"base": "BASE RULES", "project-manager": "PM RULES"})
    agent.invoke({"messages": [{"role": "user", "content": "hi"}]}, config("t3"))
    system = str(model.received[0][0].content)
    assert system.index("BASE RULES") < system.index("PM RULES") < system.index("Project Manager for Kunemi")


def test_role_for_agent_name() -> None:
    assert role_for_agent_name("product-agent") == "product"
    assert role_for_agent_name("documentation-agent") == "documentation"
    assert role_for_agent_name(None) == "project-manager"
    assert role_for_agent_name("unknown") == "project-manager"


def test_delegation_briefs_and_findings() -> None:
    model = ScriptedChatModel.of(
        tool_call("task", description="Check the vision", subagent_type="product-agent"),
        "The vision covers drivers.",
        "Done.",
    )
    agent = team(model)
    agent.invoke({"messages": [{"role": "user", "content": "check the vision"}]}, config("t4"))
    pm, specialist = str(model.received[0][0].content), str(model.received[1][0].content)
    assert "## Delegating" in pm and "delegate straight away" in pm
    assert "Answer with findings" in specialist and "ask for all of it in one turn" in specialist
    assert "## Delegating" not in specialist
