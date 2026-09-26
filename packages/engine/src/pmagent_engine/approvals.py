"""Action Mode approvals, independent of any UI.

The approval gate is langchain's HumanInTheLoopMiddleware (what deepagents'
`interrupt_on` installs). When it pauses, it raises a LangGraph interrupt
whose value is an HITLRequest:

    {"action_requests": [{"name": "write_file", "args": {...}, "description": ...}, ...],
     "review_configs":  [...]}

and it expects to be resumed with ONE decision per action request:

    {"decisions": [{"type": "approve"}, {"type": "reject", "message": "..."}, ...]}

Passing a bare string like "approve" (what the previous CLI did) raises
inside the middleware. On top of that, if several subagents run in parallel
and each pauses, a single step can yield several interrupts at once. Those
must be resumed as a mapping {interrupt_id: payload}.

The CLI, the background job worker, and a future desktop app all go through
these helpers, so none of them needs to know about that shape.
"""
from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from langgraph.types import Command

_MAX_ARG_CHARS = 1500


def _pending(result: dict) -> list:
    return list(result.get("__interrupt__") or [])


def has_pending(result: dict) -> bool:
    return bool(_pending(result))


def pending_actions(result: dict) -> list[dict]:
    """Flatten every pending action across every interrupt into plain dicts
    (JSON-serializable, so jobs can store them and a UI can render them)."""
    out = []
    for intr in _pending(result):
        value = intr.value if isinstance(intr.value, dict) else {}
        for req in value.get("action_requests", []) or [{"name": "?", "args": intr.value}]:
            out.append({
                "interrupt_id": getattr(intr, "id", None),
                "tool": req.get("name"),
                "args": req.get("args", {}),
                "description": req.get("description"),
            })
    return out


def format_action(action: dict) -> str:
    args = action["args"]
    if action["tool"] in ("write_file",) and isinstance(args, dict):
        body = args.get("content", "")
        shown = body if len(body) <= _MAX_ARG_CHARS else body[:_MAX_ARG_CHARS] + "\n… (truncated)"
        return f"{action['tool']} -> {args.get('file_path')}\n{shown}"
    rendered = json.dumps(args, indent=2, default=str)
    if len(rendered) > _MAX_ARG_CHARS:
        rendered = rendered[:_MAX_ARG_CHARS] + "\n… (truncated)"
    return f"{action['tool']}\n{rendered}"


def _decision(kind: str, message: str | None) -> dict:
    if kind not in ("approve", "reject"):
        raise ValueError(f"decision must be 'approve' or 'reject', got {kind!r}")
    d: dict[str, Any] = {"type": kind}
    if kind == "reject" and message:
        d["message"] = message
    return d


def resume_command(result_or_actions: dict | list[dict],
                   decisions: Iterable[str | tuple[str, str | None]] | str,
                   message: str | None = None) -> Command:
    """Build the Command that resumes a paused run.

    `decisions` is either one decision applied to every pending action, or
    one per action in the same order as pending_actions(). A per-action
    decision may be a ("reject", reason) pair, so each rejection carries its
    own reason back to the agent; `message` is the fallback reason.
    """
    actions = (pending_actions(result_or_actions)
               if isinstance(result_or_actions, dict) else result_or_actions)
    if isinstance(decisions, str):
        decisions = [decisions] * len(actions)
    decisions = list(decisions)
    if len(decisions) != len(actions):
        raise ValueError(f"{len(actions)} pending action(s) but {len(decisions)} decision(s)")

    # Group decisions per interrupt, preserving order.
    grouped: dict[Any, list[dict]] = {}
    for action, decision in zip(actions, decisions, strict=True):
        kind, reason = decision if isinstance(decision, tuple) else (decision, message)
        grouped.setdefault(action["interrupt_id"], []).append(_decision(kind, reason or message))

    if len(grouped) == 1:
        return Command(resume={"decisions": next(iter(grouped.values()))})
    return Command(resume={iid: {"decisions": ds} for iid, ds in grouped.items()})
