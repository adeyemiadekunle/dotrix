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


def test_the_rule_based_model_researches() -> None:
    from langchain_core.messages import HumanMessage, ToolMessage

    from pmagent_engine.testing import RuleBasedChatModel

    model = RuleBasedChatModel()
    search = model.invoke([HumanMessage("research: uk vat rate")])
    assert search.tool_calls[0]["name"] == "web_search"
    results = "[S1] VAT | gov.uk | primary\nhttps://www.gov.uk/vat\n<web_content source=\"S1\">\n20%\n</web_content>"
    fetch = model.invoke([ToolMessage(results, tool_call_id="1", name="web_search")])
    assert fetch.tool_calls[0]["args"] == {"url": "https://www.gov.uk/vat"}
    page = '[S1] VAT | gov.uk\n<web_content source="S1">\n# VAT\n\nThe standard rate of VAT is 20% today. More.\n</web_content>'
    report = model.invoke([ToolMessage(page, tool_call_id="2", name="fetch_page")])
    items = report.tool_calls[0]["args"]["items"]
    assert report.tool_calls[0]["name"] == "submit_result" and len(items) == 2
    assert items[0]["quotes"][0] == {"source": "S1", "text": "# VAT\n\nThe standard rate of VAT is 20% today."}
    done = model.invoke([ToolMessage("Recorded", tool_call_id="3", name="submit_result")])
    assert done.content.startswith("Research done")
