"""Structural evals: saved cases per agent (tests/evals/*.yaml), run with the scripted model.

Each case builds the team from the built-in contracts (plus an inline custom one, if given),
lets the named agent lead, plays a scripted conversation, and checks what the agent was offered,
what paused for approval, what was refused, and what it returned. They guard the contracts: a
change to an agent's tools, gates, or prompts that breaks one fails here.
"""
from pathlib import Path
from typing import Any

import pytest
import yaml
from deepagents.backends import CompositeBackend, StateBackend
from langgraph.checkpoint.memory import InMemorySaver

from pmagent_engine import approvals
from pmagent_engine.agent import build_team
from pmagent_engine.builtins import builtin_specs
from pmagent_engine.contracts import AgentSpec
from pmagent_engine.testing import ScriptedChatModel, tool_call

CASES = [
    pytest.param(case, id=f"{path.stem}: {case['name']}")
    for path in sorted((Path(__file__).parent / "evals").glob("*.yaml"))
    for case in yaml.safe_load(path.read_text(encoding="utf-8"))
]


def _board() -> tuple[list, list]:
    """A stand-in board: the platform's tool names, answering with fixed data."""

    def list_issues() -> list[dict]:
        """List issues."""
        return [{"key": "KUN-1", "title": "Rotate keys"}]

    def get_issue(key: str) -> dict:
        """Get one issue."""
        return {"key": key}

    def create_issue(type: str, title: str, description: str = "") -> dict:  # noqa: A002
        """Create an issue."""
        return {"key": "KUN-2", "title": title}

    def update_issue(key: str, status: str | None = None) -> dict:
        """Update an issue."""
        return {"key": key}

    def comment_issue(key: str, text: str) -> dict:
        """Comment on an issue."""
        return {"key": key}

    def search_knowledge(query: str) -> str:
        """Search the project."""
        return "Nothing found."

    return [list_issues, get_issue, search_knowledge], [create_issue, update_issue, comment_issue]


def _script(steps: list[dict[str, Any]]) -> ScriptedChatModel:
    return ScriptedChatModel.of(
        *(tool_call(s["tool"], **s.get("args", {})) if "tool" in s else s["text"] for s in steps)
    )


@pytest.mark.parametrize("case", CASES)
def test_eval(case: dict[str, Any]) -> None:
    model = _script(case["script"])
    agents = builtin_specs()
    if "spec" in case:
        agents.append(AgentSpec.model_validate(case["spec"]))
    reads, writes = _board()
    results: list = []
    team = build_team(
        "Kunemi", "Logistics platform", model,
        CompositeBackend(default=StateBackend(), routes={"/pmagent/": StateBackend()}),
        checkpointer=InMemorySaver(),
        task_tools=(reads[:2], writes), subagent_task_tools=writes, knowledge_tools=reads[2:],
        web_search={"name": "web_search", "type": "web_search_20250305"},
        agents=agents, lead=case["agent"],
        result_sink=lambda schema, items: results.extend(items), stage_sink=lambda handle, stage: None,
    )
    result = team.invoke({"messages": [{"role": "user", "content": case["message"]}]},
                         {"configurable": {"thread_id": case["name"]}})
    expect = case.get("expect", {})
    offered = set(model.tools_received[0])
    for name in expect.get("tools_include", []):
        assert name in offered, f"{name} not offered: {sorted(offered)}"
    for name in expect.get("tools_exclude", []):
        assert name not in offered, f"{name} offered"
    if "pending" in expect:
        assert [a["tool"] for a in approvals.pending_actions(result)] == expect["pending"]
    tool_messages = [str(m.content) for m in result["messages"] if m.type == "tool"]
    if expect.get("denied"):
        assert any("denied" in m.lower() for m in tool_messages), tool_messages
    if "tool_errors" in expect:
        assert sum(m.startswith("Error") for m in tool_messages) == expect["tool_errors"], tool_messages
    if "results" in expect:
        assert len(results) == expect["results"]
    if "reply" in expect:
        assert result["messages"][-1].content == expect["reply"]
    system = str(model.received[0][0].content)
    for text in expect.get("prompt_contains", []):
        assert text in system, text
