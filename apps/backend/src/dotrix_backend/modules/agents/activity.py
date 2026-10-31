"""What the Project Manager is doing right now, in words, for the live stream: "Reading
roadmap.md", "Checking the board", "Asking the research agent". Shown while a run works so
people aren't staring at a spinner; never stored.

Labels are built from the tool name and a few safe arguments (file paths, issue keys, the
subagent's name, a web page's host), never from free text the model wrote.
"""
from __future__ import annotations

import re
from typing import Any

from dotrix_engine.outputs import PIPELINES
from dotrix_engine.web.tiers import host_of

_KNOWLEDGE_ROOT = "/dotrix/"
# A custom agent's LangGraph name: its handle (validated: lower-case letters, digits, dashes) + "-agent".
_AGENT_NAME = re.compile(r"^[a-z][a-z0-9-]{1,30}-agent$")
_HOST = re.compile(r"^[a-z0-9][a-z0-9.-]{0,79}$")
_STAGES = {stage for stages in PIPELINES.values() for stage in stages}
# Each pipeline stage (dotrix_engine/outputs.py PIPELINES) as what a person would say they're doing.
STAGE_LABELS = {
    "classify": "Working out what's being asked",
    "plan": "Planning the steps",
    "dispatch": "Handing parts to the specialists",
    "merge": "Weighing what the specialists found",
    "propose": "Drafting the changes to propose",
    "follow_up": "Noting what's left to do",
    "read": "Reading",
    "duplicates": "Checking for duplicates",
    "clarify": "Working out what's needed",
    "related": "Looking at related work",
    "draft": "Drafting",
    "check": "Checking the draft",
    "understand": "Understanding the change",
    "impact": "Weighing the impact",
    "options": "Considering options",
    "recommend": "Choosing what to recommend",
    "our_knowledge": "Checking what the project already knows",
    "search": "Searching",
    "extract": "Pulling out the findings",
    "verify": "Checking the facts against the sources",
    "report": "Writing the report",
    "requirements": "Reading the requirements",
    "board": "Checking the board",
    "code": "Reading the code",
    "assess": "Assessing what it found",
    "issue": "Reading the issue",
    "criteria": "Checking the acceptance criteria",
    "evidence": "Gathering the evidence",
    "diff": "Reading the changes",
    "blast_radius": "Working out what the change could affect",
    "findings": "Writing up the findings",
    "change": "Understanding the change",
    "affected": "Finding the documents it affects",
    "excerpts": "Collecting the relevant excerpts",
    "tests": "Picking the tests to run",
    "hand_off": "Handing the work to Kai",
    "scope": "Scoping the work",
}
WRITING = "Writing the reply"
WEIGHING_SPECIALISTS = "Weighing what the specialists found"
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


def _who(args: dict[str, Any]) -> str:
    name = str(args.get("subagent_type") or "")
    return _SUBAGENTS.get(name, f"@{name.removesuffix('-agent')}" if _AGENT_NAME.match(name) else "a specialist agent")


def result_label(tool: str, args: dict[str, Any] | None) -> str | None:
    """What the agent does with a tool's result, when that's worth saying: a specialist's answer is
    weighed before the agent goes on. None for every other result."""
    args = args if isinstance(args, dict) else {}
    match tool:
        case "task":
            return f"Weighing what {_who(args)} found"
        case "delegate_tasks":
            return WEIGHING_SPECIALISTS
        case _:
            return None


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
        case "code_tree":
            return "Looking through the code"
        case "code_search":
            return "Searching the code"
        case "code_read":
            path = str(args.get("path") or "").strip().strip("/")[:80]
            return f"Reading {path} in the code" if path else "Reading the code"
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
        case "stage":
            current = str(args.get("current") or "")
            # Only the fixed stage names (dotrix_engine.pipelines), never model text.
            if current not in _STAGES:
                return None
            return STAGE_LABELS.get(current, f"Now: {current.replace('_', ' ')}")
        case "graph_neighbors" | "graph_impact" | "graph_path":
            return "Following how things connect"
        case "link_items":
            return "Drafting a link"
        case "submit_result":
            return "Recording the result"
        case "checkpoint":
            return "Showing the plan before going on"
        case "delegate_tasks":
            return "Asking specialists"
        case "task":
            return f"Asking {_who(args)}"
        case "web_search":
            return "Searching the web"
        case "fetch_page":
            host = host_of(str(args.get("url") or ""))
            return f"Reading {host}" if _HOST.match(host) else "Reading a web page"
        case _:
            return None
