"""The rule-based model that end-to-end tests run the agents on."""
from langchain_core.messages import HumanMessage, ToolMessage

from pmagent_engine.testing import RuleBasedChatModel


def test_rules() -> None:
    model = RuleBasedChatModel()
    echo = model.invoke([HumanMessage("What's open?")])
    assert echo.content == "Test model reply: What's open?"
    create = model.invoke([HumanMessage("Create issue: Add dark mode")])
    assert create.tool_calls[0]["name"] == "create_issue"
    assert create.tool_calls[0]["args"] == {"type": "task", "title": "Add dark mode", "priority": "medium"}
    done = model.invoke([HumanMessage("Create issue: x"), ToolMessage("Created KUN-9", tool_call_id="c")])
    assert done.content.startswith("Done.")
    plan = model.invoke([HumanMessage("Plan: Spec it; Assess impact")])
    assert plan.tool_calls[0]["name"] == "checkpoint"
    assert plan.tool_calls[0]["args"]["plan"] == ["Spec it", "Assess impact"]
