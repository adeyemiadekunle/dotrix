"""What the Project Manager is doing right now, in words, for the live stream: "Reading
roadmap.md", "Checking the board", "Asking the research agent". Shown while a run works so
people aren't staring at a spinner; never stored.

Labels are built from the tool name and a few safe arguments (file paths, issue keys, the
subagent's name), never from free text the model wrote.
"""
from __future__ import annotations

from typing import Any

_KNOWLEDGE_ROOT = "/pmagent/"
_SUBAGENTS = {
    "product-agent": "the product agent",
    "architecture-agent": "the architecture agent",
    "research-agent": "the research agent",
    "reviewer-agent": "the reviewer agent",
    "documentation-agent": "the documentation agent",
    "general-purpose": "a helper agent",
}


def _path(args: dict[str, Any]) -> str:
    raw = str(args.get("file_path") or args.get("path") or "").strip()
    if raw.startswith(_KNOWLEDGE_ROOT):
        raw = raw[len(_KNOWLEDGE_ROOT):]
    raw = raw.strip("/")
    return raw[:80] if raw else "the project files"


def _key(args: dict[str, Any]) -> str:
    key = str(args.get("key") or "").strip().upper()
    return key[:24] if key else "an issue"


def activity_label(tool: str, args: dict[str, Any] | None) -> str | None:
    """A short present-tense description of a tool call, or None to show nothing for it."""
    args = args if isinstance(args, dict) else {}
    match tool:
        case "read_file":
            return f"Reading {_path(args)}"
        case "read_section":
            return f"Reading part of {_path(args)}"
        case "document_outline":
            return f"Looking over {_path(args)}"
        case "search_knowledge":
            return "Searching the project's documents and issues"
        case "ls" | "glob" | "grep":
            return "Looking through the project files"
        case "write_file" | "edit_file":
            return f"Drafting a change to {_path(args)}"
        case "write_todos":
            return "Planning the steps"
        case "list_issues":
            return "Checking the board"
        case "get_issue":
            return f"Looking at {_key(args)}"
        case "create_issue":
            return "Drafting a new issue"
        case "update_issue":
            return f"Drafting changes to {_key(args)}"
        case "comment_issue":
            return f"Drafting a comment on {_key(args)}"
        case "task":
            who = _SUBAGENTS.get(str(args.get("subagent_type") or ""), "a specialist agent")
            return f"Asking {who}"
        case "web_search":
            return "Searching the web"
        case _:
            return None
