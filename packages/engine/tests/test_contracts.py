"""Agent contracts: validation, the permission policy, and teams built from contracts."""
import pytest
from deepagents.backends import CompositeBackend, StateBackend
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import ValidationError

from pmagent_engine import approvals, permissions
from pmagent_engine.agent import build_team, role_for_agent_name
from pmagent_engine.builtins import BUILTIN_HANDLES, builtin, builtin_specs
from pmagent_engine.contracts import AgentPolicy, AgentSpec
from pmagent_engine.permissions import Access
from pmagent_engine.testing import ScriptedChatModel, tool_call

PATHS = [
    "project.md", "docs/README.md", "vision.md", "roadmap.md", "current-state.md",
    "requirements/modules/drivers.md", "architecture/database.md", "research/postcodes.md",
    "reviews/pr-12.md", "decisions/ADR-014.md", "progress/blocked.md", "issues/KUN-1.md",
    "sprints/sprint-1.md", "agent-rules/base.md", "somewhere-else.md",
]


def spec(**fields) -> AgentSpec:
    return AgentSpec(**({"handle": "security", "name": "Security reviewer", "instructions": "Look for risks."} | fields))


def test_builtins_keep_the_folder_matrix_and_issue_rules() -> None:
    policy = AgentPolicy()
    assert tuple(policy.specs) == BUILTIN_HANDLES
    for handle in BUILTIN_HANDLES:
        for path in PATHS:
            expected = permissions.access(handle, path)
            if handle == "reviewer" and expected is Access.WRITE:
                expected = Access.PROPOSE  # the reviewer has no document writes: read-only, as enforced today
            assert policy.access(handle, path) is expected, (handle, path)
        for issue_type in permissions.ISSUE_TYPES:
            assert policy.can_create_issue(handle, issue_type) == permissions.can_create_issue(handle, issue_type)
        assert policy.can_edit_issues(handle) == permissions.can_edit_issues(handle)


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ({"handle": "Security"}, "lower-case"),
        ({"handle": "sec-agent"}, "lower-case"),
        ({"tools": ["knowledge.read", "shell"]}, "Unknown tools: shell"),
        ({"access": {"agent-rules/*": "write"}}, "agent-rules"),
        ({"access": {"/etc/*": "write"}}, "relative"),
        ({"issue_types": ["story"]}, "issues.create"),
        ({"issue_types": ["saga"], "tools": ["issues.create"]}, "Unknown issue types"),
        ({"autonomy": {"issues.create": "allow"}}, "low-risk"),
        ({"autonomy": {"deploy": "block"}}, "Unknown actions"),
    ],
)
def test_contracts_are_validated(fields: dict, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        spec(**fields)


def test_a_custom_agent_gets_exactly_its_contract() -> None:
    security = spec(
        tools=["knowledge.read", "knowledge.write", "board.read", "issues.create", "issues.comment"],
        access={"reviews/security/*": "write", "requirements/*": "propose"},
        issue_types=["bug"],
        autonomy={"issues.comment": "allow"},
    )
    policy = AgentPolicy([*builtin_specs(), security])
    assert policy.can_write("security", "reviews/security/2026-09.md")
    assert not policy.can_write("security", "reviews/other.md")
    assert policy.access("security", "requirements/checkout.md") is Access.PROPOSE
    assert policy.can_create_issue("security", "bug") and not policy.can_create_issue("security", "story")
    assert not policy.can_edit_issues("security")
    assert security.rule("issues.comment") == "allow" and security.rule("issues.create") == "ask"
    # Unknown agents may do nothing.
    assert not policy.can_write("marketing", "research/x.md")


def test_without_document_writes_an_agent_is_read_only_whatever_its_access_says() -> None:
    reader = spec(tools=["knowledge.read"], access={"reviews/*": "write"})
    assert reader.folder_access("reviews/r.md") is Access.PROPOSE
    assert not AgentPolicy([reader]).can_write("security", "reviews/r.md")


def test_agent_rules_stay_people_only() -> None:
    doc = builtin("documentation").model_copy(update={"access": {"*": Access.WRITE}})
    assert doc.folder_access("agent-rules/base.md") is Access.READ
    assert doc.folder_access("roadmap.md") is Access.WRITE


def test_role_for_custom_agent_names() -> None:
    assert role_for_agent_name("security-agent") == "security"
    assert role_for_agent_name("product-agent") == "product"
    assert role_for_agent_name(None) == "project-manager"


def _backend():
    return CompositeBackend(default=StateBackend(), routes={"/pmagent/": StateBackend()})


def test_the_pm_delegates_to_a_custom_agent() -> None:
    model = ScriptedChatModel.of(
        tool_call("task", description="Check the auth flow", subagent_type="security-agent"),
        "No secrets in the flow.",
        "Security says the flow is fine.",
    )
    agents = [*builtin_specs(), spec(description="Reviews changes for security risks.")]
    agent = build_team("Kunemi", "x", model, _backend(), checkpointer=InMemorySaver(), agents=agents)
    result = agent.invoke({"messages": [{"role": "user", "content": "is auth safe?"}]},
                          {"configurable": {"thread_id": "c1"}})
    assert result["messages"][-1].content == "Security says the flow is fine."
    pm, called = str(model.received[0][0].content), str(model.received[1][0].content)
    assert "security-agent" in pm
    assert "You are the Security reviewer for Kunemi" in called and "Look for risks." in called


def test_a_custom_agent_leads_with_its_own_gates() -> None:
    model = ScriptedChatModel.of(
        tool_call("write_file", file_path="/pmagent/reviews/security/r.md", content="# Review"),
        "Written.",
    )
    writer = spec(tools=["knowledge.read", "knowledge.write"], access={"reviews/security/*": "write"})
    agent = build_team("Kunemi", "x", model, _backend(), checkpointer=InMemorySaver(),
                       agents=[*builtin_specs(), writer], lead="security")
    result = agent.invoke({"messages": [{"role": "user", "content": "write it"}]}, {"configurable": {"thread_id": "c2"}})
    assert [a["tool"] for a in approvals.pending_actions(result)] == ["write_file"]
    assert "You are the Security reviewer" in str(model.received[0][0].content)


def test_a_custom_agent_without_document_writes_is_refused_outright() -> None:
    model = ScriptedChatModel.of(
        tool_call("write_file", file_path="/pmagent/reviews/r.md", content="x"),
        "I can't write that.",
    )
    agent = build_team("Kunemi", "x", model, _backend(), checkpointer=InMemorySaver(),
                       agents=[*builtin_specs(), spec()], lead="security")
    result = agent.invoke({"messages": [{"role": "user", "content": "write"}]}, {"configurable": {"thread_id": "c3"}})
    assert not approvals.has_pending(result)
    denied = [m for m in result["messages"] if m.type == "tool"][0]
    assert "denied" in str(denied.content).lower()


def test_an_unknown_lead_is_refused() -> None:
    with pytest.raises(ValueError, match="Unknown lead agent"):
        build_team("Kunemi", "x", ScriptedChatModel.of("hi"), _backend(), lead="security")


def test_autonomy_shapes_tools_and_gates() -> None:
    from pmagent_engine.agent import _gate, _toolbox, _tools_for

    def create_issue(): ...
    def comment_issue(): ...
    def list_issues(): ...

    box = _toolbox([create_issue, comment_issue, list_issues])
    agent = spec(tools=["board.read", "issues.create", "issues.comment", "knowledge.write"],
                 issue_types=["bug"], autonomy={"issues.comment": "allow", "issues.create": "block"})
    names = {t.__name__ for t in _tools_for(agent, box)}
    assert names == {"list_issues", "comment_issue"}  # blocked: no create tool at all
    gate = _gate(agent, box)
    assert "comment_issue" not in gate and "write_file" in gate  # allowed: no pause
    policy = AgentPolicy([agent])
    assert policy.allowed("security", "issues.comment")
    assert not policy.allowed("security", "issues.create") and not policy.can_create_issue("security", "bug")
    blocked_writes = spec(tools=["knowledge.write"], access={"reviews/*": "write"}, autonomy={"knowledge.write": "block"})
    assert not AgentPolicy([blocked_writes]).can_write("security", "reviews/r.md")


def test_an_agent_reports_stages_and_submits_a_result() -> None:
    results, stages = [], []
    model = ScriptedChatModel.of(
        tool_call("stage", current="diff"),
        tool_call("submit_result", items=[{"severity": "high", "title": "Token in logs", "detail": "auth.py logs it",
                                           "refs": ["auth.py"]}]),
        "One high-severity finding.",
    )
    reviewer = spec(output="finding", pipeline="reviewer.commit")
    agent = build_team("Kunemi", "x", model, _backend(), checkpointer=InMemorySaver(), agents=[*builtin_specs(), reviewer],
                       lead="security", result_sink=lambda schema, items: results.append((schema, items)),
                       stage_sink=lambda handle, name: stages.append((handle, name)))
    result = agent.invoke({"messages": [{"role": "user", "content": "review"}]}, {"configurable": {"thread_id": "o1"}})
    assert result["messages"][-1].content == "One high-severity finding."
    assert stages == [("security", "diff")]
    assert results == [("finding", [{"severity": "high", "title": "Token in logs", "detail": "auth.py logs it",
                                     "refs": ["auth.py"], "suggested_fix": ""}])]
    system = str(model.received[0][0].content)
    assert "1. **diff**: " in system and "2. **blast_radius**: " in system and "call `submit_result` once" in system


def test_output_and_pipeline_names_are_checked() -> None:
    with pytest.raises(ValidationError, match="Unknown output"):
        spec(output="essay")
    with pytest.raises(ValidationError, match="Unknown pipeline"):
        spec(pipeline="freestyle")
