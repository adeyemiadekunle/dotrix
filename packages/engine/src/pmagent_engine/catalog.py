"""The tools an agent can be given (agent contracts, docs/agents-v2.md §4.3).

A contract lists tool ids from here. The platform (or the local CLI) supplies the actual
tools; `tool_id` says which id a supplied tool belongs to, by its name. Each id also names
the actions it can take, which autonomy rules (allow / ask / block) refer to.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ToolGroup:
    id: str
    label: str
    description: str
    names: tuple[str, ...]  # the supplied tools' names that belong to it
    actions: tuple[str, ...] = ()  # what it can change, for autonomy rules


CATALOG: tuple[ToolGroup, ...] = (
    ToolGroup(
        "knowledge.read", "Read documents",
        "List, read, and search inside the project's documents; outlines and sections.",
        ("ls", "read_file", "glob", "grep", "document_outline", "read_section", "read_skill"),
    ),
    ToolGroup(
        "knowledge.search", "Search the project",
        "Search documents and issues by meaning and keywords.",
        ("search_knowledge",),
    ),
    ToolGroup(
        "knowledge.write", "Write documents",
        "Create and edit documents in the folders its access allows. Writes wait for approval unless an owner allowed them.",
        ("write_file", "edit_file"),
        ("knowledge.write",),
    ),
    ToolGroup(
        "code.read", "Read the code",
        "List, read, and search the project's connected repository (read-only; nothing is run).",
        ("code_tree", "code_read", "code_search"),
    ),
    ToolGroup(
        "board.read", "Read the board",
        "List issues and read them in full.",
        ("list_issues", "get_issue", "list_tasks", "get_task"),
    ),
    ToolGroup(
        "issues.create", "Open issues",
        "Open issues of the types it may create.",
        ("create_issue", "create_task"),
        ("issues.create",),
    ),
    ToolGroup(
        "issues.update", "Edit issues",
        "Change issues' fields and status; closing always needs a person.",
        ("update_issue", "update_task"),
        ("issues.update",),
    ),
    ToolGroup(
        "issues.comment", "Comment on issues",
        "Add comments to issues.",
        ("comment_issue", "comment_task"),
        ("issues.comment",),
    ),
    ToolGroup(
        "graph.read", "Follow the project graph",
        "See how requirements, issues, decisions, and modules connect, and what a change affects.",
        ("graph_neighbors", "graph_impact", "graph_path"),
    ),
    ToolGroup(
        "graph.link", "Link things",
        "Link two things the text doesn't (a requirement and a decision, say).",
        ("link_items",),
        ("graph.link",),
    ),
    ToolGroup(
        "web.search", "Search and read the web",
        "Search the web and read pages in full, citing each as a source.",
        ("web_search", "fetch_page"),
    ),
    ToolGroup(
        "delegate", "Ask other agents",
        "Hand part of the work to the agents it may call (one level deep).",
        ("task",),
    ),
)

TOOL_IDS: tuple[str, ...] = tuple(group.id for group in CATALOG)
_BY_ID = {group.id: group for group in CATALOG}
_ID_BY_NAME = {name: group.id for group in CATALOG for name in group.names}

# Every action an autonomy rule can name. Owners may allow any of them without asking (a standing
# rule); the low-risk ones (D1) are also what admins may keep and what automations take without
# their own switch. Closing an issue, coding, and anything outside the catalogue always ask a person.
ACTIONS: tuple[str, ...] = tuple(action for group in CATALOG for action in group.actions)
LOW_RISK_ACTIONS = frozenset({"issues.comment", "graph.link"})


def action_for(name: str) -> str | None:
    """The action a supplied tool's name takes (write_file -> knowledge.write), or None for a tool
    that changes nothing an autonomy rule covers."""
    found = _ID_BY_NAME.get(name)
    actions = _BY_ID[found].actions if found else ()
    return actions[0] if len(actions) == 1 else None


def group(tool_id: str) -> ToolGroup:
    return _BY_ID[tool_id]


def tool_name(tool: object) -> str:
    """A supplied tool's name: a function's `__name__`, a LangChain tool's `name`, or a
    provider-native tool dict's `name` (web search is the only dict we pass)."""
    if isinstance(tool, dict):
        return str(tool.get("name") or "web_search")
    return str(getattr(tool, "name", None) or getattr(tool, "__name__", ""))


def tool_id(tool: object) -> str | None:
    """Which catalogue id a supplied tool belongs to, or None if it isn't in the catalogue."""
    return _ID_BY_NAME.get(tool_name(tool))
