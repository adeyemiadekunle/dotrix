"""Issues as Markdown files (`issues/KUN-42.md`) for the `.pmagent/` export: YAML fields,
the description, and the append-only log, as the PRD describes the file format."""
from __future__ import annotations

import uuid
from collections import defaultdict
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from .models import Issue, IssueDependency, IssueEvent


def _clean(fields: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in fields.items() if v not in (None, [], "")}


def _changes(changes: dict[str, Any]) -> str:
    return "; ".join(f"{field}: {old} -> {new}" for field, (old, new) in changes.items())


def render_issue(issue: Issue, parent_key: str | None, depends_on: list[str], events: list[IssueEvent]) -> str:
    fields = _clean(
        {
            "key": issue.key,
            "type": issue.type.value,
            "title": issue.title,
            "status": issue.status.value,
            "priority": issue.priority.value,
            "assignee": issue.assignee_agent.value if issue.assignee_agent else (
                str(issue.assignee_user_id) if issue.assignee_user_id else None
            ),
            "reporter": issue.reporter_agent or (str(issue.reporter_user_id) if issue.reporter_user_id else None),
            "parent": parent_key,
            "estimate": issue.estimate,
            "due": issue.due.isoformat() if issue.due else None,
            "scheduled": issue.scheduled.isoformat() if issue.scheduled else None,
            "depends_on": depends_on,
            "labels": list(issue.labels),
            "components": list(issue.components),
            "links": list(issue.links),
            "created": issue.created_at.isoformat(),
            "updated": issue.updated_at.isoformat(),
            "resolved": issue.resolved_at.isoformat() if issue.resolved_at else None,
        }
    )
    lines = ["---", yaml.safe_dump(fields, sort_keys=False, allow_unicode=True).rstrip(), "---", ""]
    lines += [f"# {issue.key}: {issue.title}", "", issue.description.strip() or "_No description._", "", "## Log", ""]
    for event in events:
        who = event.author_agent or (str(event.author_user_id) if event.author_user_id else "system")
        detail = event.body or _changes(event.changes)
        lines.append(f"- {event.created_at:%Y-%m-%d %H:%M} {who} {event.kind.value}" + (f": {detail}" if detail else ""))
    return "\n".join(lines) + "\n"


async def render_project_issues(session: AsyncSession, project_id: uuid.UUID) -> dict[str, str]:
    """{"issues/KUN-1.md": markdown, ...} for every issue in the project."""
    parent = aliased(Issue)
    rows = list(
        await session.execute(
            select(Issue, parent.key)
            .outerjoin(parent, parent.id == Issue.parent_id)
            .where(Issue.project_id == project_id)
            .order_by(Issue.number)
        )
    )
    if not rows:
        return {}
    blocker = aliased(Issue)
    depends: dict[uuid.UUID, list[str]] = defaultdict(list)
    for issue_id, key in await session.execute(
        select(IssueDependency.issue_id, blocker.key)
        .join(blocker, blocker.id == IssueDependency.depends_on_id)
        .where(blocker.project_id == project_id)
        .order_by(blocker.number)
    ):
        depends[issue_id].append(key)
    events: dict[uuid.UUID, list[IssueEvent]] = defaultdict(list)
    for event in await session.scalars(
        select(IssueEvent)
        .join(Issue, Issue.id == IssueEvent.issue_id)
        .where(Issue.project_id == project_id)
        .order_by(IssueEvent.created_at, IssueEvent.id)
    ):
        events[event.issue_id].append(event)
    return {
        f"issues/{issue.key}.md": render_issue(issue, parent_key, depends[issue.id], events[issue.id])
        for issue, parent_key in rows
    }
