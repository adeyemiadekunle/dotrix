"""Findings are deduplicated as they're saved (docs/agents-v2.md §4.6).

A finding gets a fingerprint from its title and what it concerns. One that matches an open
finding from an earlier run is dismissed as a repeat; one that matches an open issue on the
board is marked done with that issue's key. Either way it stays visible, with why.
"""
from __future__ import annotations

import hashlib
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dotrix_backend.modules.issues.models import Issue, IssueStatus

from .models import AgentRunOutput

# How far back to look for earlier findings (most recent outputs first).
RECENT_OUTPUTS = 200


def normalize(title: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", title.lower()))


def fingerprint(item: dict[str, Any]) -> str:
    refs = ",".join(sorted(str(r).strip().lower() for r in item.get("refs") or []))
    return hashlib.sha256(f"{normalize(str(item.get('title', '')))}|{refs}".encode()).hexdigest()[:16]


async def dedupe_findings(
    session: AsyncSession, project_id: uuid.UUID, items: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """The output entries for new findings: open, or already settled as repeats."""
    earlier: set[str] = set()
    outputs = await session.scalars(
        select(AgentRunOutput)
        .where(AgentRunOutput.project_id == project_id, AgentRunOutput.schema_name == "finding")
        .order_by(AgentRunOutput.created_at.desc())
        .limit(RECENT_OUTPUTS)
    )
    for output in outputs:
        for entry in output.items:
            if entry.get("state") == "open" and (fp := entry.get("data", {}).get("fingerprint")):
                earlier.add(fp)
    open_issues = {
        normalize(title): key
        for key, title in (
            await session.execute(
                select(Issue.key, Issue.title).where(Issue.project_id == project_id, Issue.status != IssueStatus.DONE)
            )
        ).all()
    }
    now = datetime.now(UTC).isoformat()
    entries, seen = [], set()
    for item in items:
        fp = fingerprint(item)
        data = {**item, "fingerprint": fp}
        key = open_issues.get(normalize(str(item.get("title", ""))))
        if key:
            entries.append({"data": data, "state": "done", "link": key, "reason": f"Already on the board as {key}",
                            "acted_at": now})
        elif fp in earlier or fp in seen:
            entries.append({"data": data, "state": "dismissed", "reason": "Same as an open finding from an earlier run",
                            "acted_at": now})
        else:
            entries.append({"data": data, "state": "open"})
        seen.add(fp)
    return entries
