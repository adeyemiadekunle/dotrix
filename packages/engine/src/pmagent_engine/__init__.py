"""pmagent engine: agents, issues, approvals, jobs, ingestion, and the .pmagent/ layout.

Exports are loaded lazily, so importing a light module (layout, permissions)
doesn't pull in the agent runtime (deepagents, LangChain).
"""
from __future__ import annotations

import importlib
from typing import Any

_EXPORTS = {
    "build_agent": ".agent",
    "ProjectConfig": ".config",
    "scaffold": ".config",
    "ingest_doc": ".ingest",
    "Task": ".tasks",
    "create_task": ".tasks",
    "get_task": ".tasks",
    "list_tasks": ".tasks",
    "next_task": ".tasks",
    "update_task": ".tasks",
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    if name in _EXPORTS:
        return getattr(importlib.import_module(_EXPORTS[name], __name__), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
