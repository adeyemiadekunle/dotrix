"""build_team() runs offline with a scripted model: Chat Mode answers, writes pause."""
from deepagents.backends import CompositeBackend, StateBackend
from langgraph.checkpoint.memory import InMemorySaver

from dotrix_engine import approvals
from dotrix_engine.agent import build_team, role_for_agent_name
from dotrix_engine.testing import ScriptedChatModel, tool_call


def team(model: ScriptedChatModel, rules: dict[str, str] | None = None):
    backend = CompositeBackend(default=StateBackend(), routes={"/dotrix/": StateBackend()})
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
        tool_call("write_file", file_path="/dotrix/decisions/ADR-001.md", content="# ADR-001"),
        "Action complete: wrote ADR-001.",
    )
    agent = team(model)
    result = agent.invoke({"messages": [{"role": "user", "content": "log it"}]}, config("t2"))
    pending = approvals.pending_actions(result)
    assert [a["tool"] for a in pending] == ["write_file"]
    assert pending[0]["args"]["file_path"] == "/dotrix/decisions/ADR-001.md"

    resumed = agent.invoke(approvals.resume_command(result, "approve"), config("t2"))
    assert resumed["messages"][-1].content == "Action complete: wrote ADR-001."


def test_rules_are_prepended_to_prompts() -> None:
    model = ScriptedChatModel.of("ok")
    agent = team(model, rules={"base": "BASE RULES", "project-manager": "PM RULES"})
    agent.invoke({"messages": [{"role": "user", "content": "hi"}]}, config("t3"))
    system = str(model.received[0][0].content)
    assert system.index("BASE RULES") < system.index("PM RULES") < system.index("project manager, for Kunemi")


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


def test_a_specialist_can_lead_and_call_the_others() -> None:
    import pytest

    model = ScriptedChatModel.of(
        tool_call("task", description="Which modules does multi-zone touch?", subagent_type="architecture-agent"),
        "Dispatch and driver zones.",  # the architecture agent
        "Stories drafted; architecture says dispatch and driver zones are affected.",
    )
    backend = CompositeBackend(default=StateBackend(), routes={"/dotrix/": StateBackend()})
    agent = build_team("Kunemi", "Logistics platform", model, backend, checkpointer=InMemorySaver(), lead="product")
    result = agent.invoke({"messages": [{"role": "user", "content": "draft multi-zone stories"}]}, config("t5"))
    assert result["messages"][-1].content.startswith("Stories drafted")
    lead_prompt, called_prompt = str(model.received[0][0].content), str(model.received[1][0].content)
    assert "You are Lyra, the product agent" in lead_prompt and "You're in the project's chat" in lead_prompt
    assert "project manager, for Kunemi" not in lead_prompt
    assert "You are Orion, the architecture agent" in called_prompt and "Answer with findings" in called_prompt

    with pytest.raises(ValueError, match="Unknown lead agent"):
        build_team("Kunemi", "x", model, backend, lead="marketing")


def test_the_reviewer_leads_read_only() -> None:
    model = ScriptedChatModel.of(
        tool_call("write_file", file_path="/dotrix/reviews/r.md", content="x"),
        "I can't write; here is the review instead.",
    )
    backend = CompositeBackend(default=StateBackend(), routes={"/dotrix/": StateBackend()})
    agent = build_team("Kunemi", "x", model, backend, checkpointer=InMemorySaver(), lead="reviewer")
    result = agent.invoke({"messages": [{"role": "user", "content": "review it"}]}, config("t6"))
    assert not approvals.has_pending(result)  # denied outright, never offered for approval
    denied = [m for m in result["messages"] if m.type == "tool"][0]
    assert "denied" in str(denied.content).lower()
