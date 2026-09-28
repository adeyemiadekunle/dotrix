"""The context pack: what every agent run starts with, built by the platform (no model).

Without it, each run began knowing only its instructions and explored: listing folders,
opening files, reading the board, and every specialist did the same again. The pack gives
agents a map up front: the project and its current state, every document with what it's
about (pmagent_engine.knowledge_index), the board, recent decisions, and what changed since
this conversation last ran. Agents then open only what they need.

Kept small (a few thousand tokens) and placed after the fixed instructions, so the
unchanging part of the prompt can be cached.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pmagent_backend.modules.auth.models import User
from pmagent_backend.modules.issues.models import Issue, IssueEvent, IssueStatus
from pmagent_backend.modules.knowledge.models import KnowledgeFile, KnowledgeVersion
from pmagent_backend.modules.knowledge.repository import KnowledgeRepository
from pmagent_backend.modules.knowledge.service import describe_file
from pmagent_backend.modules.projects.models import Project

from .models import AgentRun

MAX_CHARS = 24_000  # ~6,000 tokens
EXCERPT_CHARS = 1_500
MAX_LISTED = 10
DUE_SOON = timedelta(days=7)
# Already in every agent's instructions (agent-rules/) or not documents (issues are listed below).
_NOT_INDEXED = ("agent-rules/",)


def _day(value: datetime | date | None) -> str:
    return value.strftime("%Y-%m-%d") if value else "?"


def _excerpt(content: str, limit: int = EXCERPT_CHARS) -> str:
    text = content.strip()
    if len(text) <= limit:
        return text
    return text[:limit].rsplit("\n", 1)[0] + "\n…(trimmed; read the file for the rest)"


async def build_context_pack(session: AsyncSession, project: Project, run: AgentRun | None = None) -> str:
    """The pack as Markdown. Describes documents that aren't yet (older rows), in passing."""
    files = [f for f in await KnowledgeRepository(session).list_files(project.id) if not f.deleted]
    stale = [f for f in files if f.described_version != f.version]
    for f in stale:
        describe_file(f)
    if stale:
        await session.commit()
    by_path = {f.path: f for f in files}

    parts = [
        f"# Project context: {project.name} ({project.key})",
        "Built by the platform for this run. It's a map, not the documents themselves: read a file "
        "(or a section of it) before quoting it, relying on its details, or changing it. Files under "
        "/pmagent/ in tools are these paths.",
    ]
    if f := by_path.get("project.md"):
        parts += ["## Project (project.md)", _excerpt(f.content)]
    if f := by_path.get("current-state.md"):
        parts += ["## Current state (current-state.md)", _excerpt(f.content)]
    parts += [await _changes(session, project, run), await _board(session, project), _decisions(files), _index(files)]
    pack = "\n\n".join(p for p in parts if p)
    if len(pack) > MAX_CHARS:
        pack = pack[:MAX_CHARS].rsplit("\n", 1)[0] + "\n…(the rest of the index is left out; use ls or glob)"
    return pack


def _index(files: list[KnowledgeFile]) -> str:
    listed = sorted((f for f in files if not f.path.startswith(_NOT_INDEXED)), key=lambda f: f.path)
    if not listed:
        return ""
    groups: dict[str, list[str]] = defaultdict(list)
    for f in listed:
        folder = f.path.split("/", 1)[0] + "/" if "/" in f.path else "(top level)"
        groups[folder].append(f"- {f.path}: **{f.title}**: {f.summary} (v{f.version}, {_day(f.updated_at)})")
    lines = [f"## Documents ({len(listed)})"]
    for folder in sorted(groups, key=lambda g: (g != "(top level)", g)):
        lines += [f"### {folder}", *groups[folder]]
    return "\n".join(lines)


def _decisions(files: list[KnowledgeFile]) -> str:
    decisions = sorted(
        (f for f in files if f.path.startswith("decisions/") and not f.path.endswith("README.md")),
        key=lambda f: f.updated_at,
        reverse=True,
    )[:5]
    if not decisions:
        return ""
    return "\n".join(["## Recent decisions", *(f"- {f.title} ({f.path}, {_day(f.updated_at)})" for f in decisions)])


async def _board(session: AsyncSession, project: Project) -> str:
    counts = dict(
        (await session.execute(
            select(Issue.status, func.count()).where(Issue.project_id == project.id).group_by(Issue.status)
        )).all()
    )
    total = sum(counts.values())
    if not total:
        return "## Board\nNo issues yet."
    names = dict(
        (await session.execute(
            select(User.id, User.display_name)
            .join(Issue, Issue.assignee_user_id == User.id)
            .where(Issue.project_id == project.id)
            .distinct()
        )).all()
    )

    def who(issue: Issue) -> str:
        if issue.assignee_agent:
            return f" ({issue.assignee_agent})"
        return f" ({names.get(issue.assignee_user_id, 'unassigned')})" if issue.assignee_user_id else " (unassigned)"

    async def listed(*conditions: object) -> list[Issue]:
        return list(await session.scalars(
            select(Issue).where(Issue.project_id == project.id, *conditions).order_by(Issue.rank).limit(MAX_LISTED)
        ))

    summary = ", ".join(f"{counts.get(s, 0)} {s.value.replace('_', ' ')}" for s in IssueStatus)
    lines = [f"## Board ({total} issues: {summary})"]
    today = datetime.now(UTC).date()
    for label, issues in (
        ("In progress", await listed(Issue.status.in_([IssueStatus.IN_PROGRESS, IssueStatus.REVIEW]))),
        ("Blocked", await listed(Issue.status == IssueStatus.BLOCKED)),
        ("Due within a week or overdue", await listed(
            Issue.status != IssueStatus.DONE, Issue.due.is_not(None), Issue.due <= today + DUE_SOON
        )),
    ):
        if issues:
            lines.append(f"{label}:")
            lines += [
                f"- {i.key} [{i.status.value}, {i.priority.value}{', due ' + _day(i.due) if i.due else ''}] {i.title}{who(i)}"
                for i in issues
            ]
    return "\n".join(lines)


async def _changes(session: AsyncSession, project: Project, run: AgentRun | None) -> str:
    """What changed since this conversation's previous run (nothing for a new conversation)."""
    if run is None:
        return ""
    since = await session.scalar(
        select(func.max(AgentRun.created_at)).where(
            AgentRun.thread_id == run.thread_id, AgentRun.created_at < run.created_at
        )
    )
    if since is None:
        return ""
    docs = (await session.execute(
        select(KnowledgeVersion.version, KnowledgeFile.path, KnowledgeVersion.deleted, KnowledgeVersion.agent)
        .join(KnowledgeFile, KnowledgeFile.id == KnowledgeVersion.file_id)
        .where(KnowledgeVersion.project_id == project.id, KnowledgeVersion.created_at > since)
        .order_by(KnowledgeVersion.created_at.desc())
        .limit(15)
    )).all()
    events = (await session.execute(
        select(Issue.key, IssueEvent.kind, func.count())
        .join(Issue, Issue.id == IssueEvent.issue_id)
        .where(Issue.project_id == project.id, IssueEvent.created_at > since)
        .group_by(Issue.key, IssueEvent.kind)
        .order_by(Issue.key)
        .limit(20)
    )).all()
    if not docs and not events:
        return f"## Since this conversation's last message ({_day(since)})\nNothing changed in documents or on the board."
    lines = [f"## Since this conversation's last message ({_day(since)})"]
    for version, path, deleted, agent in docs:
        what = "deleted" if deleted else f"v{version}"
        lines.append(f"- {path}: {what}{' by ' + agent if agent else ''}")
    changed: dict[str, list[str]] = defaultdict(list)
    for key, kind, count in events:
        changed[key].append(kind.value if count == 1 else f"{kind.value} ×{count}")
    lines += [f"- {key}: {', '.join(kinds)}" for key, kinds in changed.items()]
    return "\n".join(lines)

