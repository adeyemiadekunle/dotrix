"""The context pack: what every agent run starts with, built by the platform (no model).

Without it, each run began knowing only its instructions and explored: listing folders,
opening files, reading the board, and every specialist did the same again. The pack gives
agents a map up front: the project and its current state, every document with what it's
about (dotrix_engine.knowledge_index), the board, recent decisions, and what changed since
this conversation last ran. Agents then open only what they need.

Kept small (a few thousand tokens) and placed after the fixed instructions, so the
unchanging part of the prompt can be cached.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from dotrix_backend.core.errors import NotFound
from dotrix_backend.modules.auth.models import User
from dotrix_backend.modules.graph.service import GraphService
from dotrix_backend.modules.issues.models import Issue, IssueEvent, IssueStatus, Priority
from dotrix_backend.modules.knowledge.models import KnowledgeFile, KnowledgeVersion
from dotrix_backend.modules.knowledge.repository import KnowledgeRepository
from dotrix_backend.modules.knowledge.service import describe_file
from dotrix_backend.modules.projects.models import Project
from dotrix_backend.modules.search.models import ChunkSource
from dotrix_backend.modules.search.service import KnowledgeIndex
from dotrix_engine.graph import find_references

from .models import AgentApproval, AgentRun, ApprovalStatus, RunKind, RunStatus

INDEX_CHARS = 14_000  # the documents list's share of the pack (~3,500 tokens)
EXCERPT_CHARS = 1_500
MAX_LISTED = 10
DUE_SOON = timedelta(days=7)
FIRST_BRIEFING_LOOKBACK = timedelta(days=7)  # a first briefing covers the last week
# Already in every agent's instructions (agent-rules/) or not documents (issues are listed below).
STALE_SHOWN = 8
# Past this many characters of the full documents index (~1,500 tokens, ~30 documents), a
# run's pack lists the documents near its question instead.
FOCUS_ABOVE = 6_000
FOCUS_CHARS = 6_000
FOCUS_SEARCH = 16
FOCUS_SEEDS = 10
FOCUS_RECENT = 5
_NOT_INDEXED = ("agent-rules/",)

logger = logging.getLogger(__name__)


def _day(value: datetime | date | None) -> str:
    return value.strftime("%Y-%m-%d") if value else "?"


def _excerpt(content: str, limit: int = EXCERPT_CHARS) -> str:
    text = content.strip()
    if len(text) <= limit:
        return text
    return text[:limit].rsplit("\n", 1)[0] + "\n…(trimmed; read the file for the rest)"


async def build_context_pack(
    session: AsyncSession, project: Project, run: AgentRun | None = None, embedder: Any = None
) -> str:
    """The pack as Markdown. Describes documents that aren't yet (older rows), in passing.

    The documents index is most of the pack (measured: 85-94%) and is cut off past ~70
    documents. So in a project whose full index passes FOCUS_ABOVE, a run with a question gets
    the documents near it instead (`_focused_index`), after the stable parts."""
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
        "/dotrix/ in tools are these paths.",
    ]
    if f := by_path.get("project.md"):
        parts += ["## Project (project.md)", _excerpt(f.content)]
    if f := by_path.get("current-state.md"):
        parts += ["## Current state (current-state.md)", _excerpt(f.content)]
    changes = (
        await _since_last_briefing(session, project, run, by_path)
        if run is not None and run.kind is RunKind.BRIEFING
        else await _changes(session, project, run)
    )
    # Most stable first, most changeable last: providers cache the longest identical opening
    # of a prompt, so the documents index (changes only when documents do) comes before the
    # board, and what changed since last time comes at the very end. A focused index changes
    # with every question, so it goes after the board.
    index = _index(files)
    focused = ""
    if run is not None and run.message and len(index) > FOCUS_ABOVE:
        focused = await _focused_index(session, project, files, run.message, embedder)
    parts += [
        "" if focused else index, _decisions(files), await _board(session, project), focused,
        await _stale(session, project), changes,
    ]
    pack = "\n\n".join(p for p in parts if p)
    return pack


async def _stale(session: AsyncSession, project: Project) -> str:
    """Documents the project graph says may be out of date, with why."""
    try:
        found = await GraphService(session).stale(project)
    except Exception:  # the map is a bonus: a run never fails for it
        logger.exception("couldn't work out stale documents for project %s", project.id)
        await session.rollback()
        return ""
    if not found:
        return ""
    lines = ["## Documents that may be out of date"]
    for item in found[:STALE_SHOWN]:
        lines.append(f"- {item.node.ref}: {'; '.join(item.reasons)}")
    if len(found) > STALE_SHOWN:
        lines.append(f"- …and {len(found) - STALE_SHOWN} more (ask graph tools about any document)")
    return "\n".join(lines)


async def _focused_index(
    session: AsyncSession, project: Project, files: list[KnowledgeFile], question: str, embedder: Any
) -> str:
    """The documents near the question: those it names and search finds for it, the documents
    linked to those in the project graph, the top-level ones, and the latest changed; then every
    folder with how many documents it has, for ls / glob / search_knowledge."""
    listed = {f.path: f for f in files if not f.path.startswith(_NOT_INDEXED)}
    try:
        seeds = [r.target for r in find_references(question, source="", project_key=project.key, paths=list(listed))]
        hits = await KnowledgeIndex(session, embedder).search(project, question, limit=FOCUS_SEARCH, source=ChunkSource.DOCUMENT)
        seeds += [h.ref for h in hits if h.ref not in seeds]
        near: list[str] = [s for s in seeds if s in listed]
        graph = GraphService(session)
        for seed in seeds[:FOCUS_SEEDS]:
            try:
                found = await graph.neighbors(project, seed)
            except NotFound:
                continue
            near += [link.node.ref for link in found.links if link.node.kind.value == "document"]
    except Exception:  # the map is a bonus: fall back to the whole index
        logger.exception("couldn't focus the documents index for project %s", project.id)
        await session.rollback()
        return ""
    top = [p for p in listed if "/" not in p]
    recent = [f.path for f in sorted(listed.values(), key=lambda f: f.updated_at, reverse=True)[:FOCUS_RECENT]]
    chosen = list(dict.fromkeys([*near, *top, *recent]))
    lines = [f"## Documents near this question ({len(chosen)} of {len(listed)})"]
    used = len(lines[0])
    for path in chosen:
        f = listed[path]
        line = f"- {f.path}: **{f.title}**: {f.summary} (v{f.version}, {_day(f.updated_at)})"
        if used + len(line) > FOCUS_CHARS:
            break
        lines.append(line)
        used += len(line) + 1
    folders: dict[str, int] = defaultdict(int)
    for path in listed:
        folders[path.split("/", 1)[0] + "/" if "/" in path else "(top level)"] += 1
    lines.append(
        "All documents by folder: " + ", ".join(f"{folder} {count}" for folder, count in sorted(folders.items()))
        + ". Find others with search_knowledge, glob, or ls."
    )
    return "\n".join(lines)


def _index(files: list[KnowledgeFile]) -> str:
    """Every document with what it's about, grouped by folder. Capped (INDEX_CHARS) so the
    sections after it always fit; the rest is named by folder for `ls` / `glob`."""
    listed = sorted((f for f in files if not f.path.startswith(_NOT_INDEXED)), key=lambda f: f.path)
    if not listed:
        return ""
    groups: dict[str, list[str]] = defaultdict(list)
    for f in listed:
        folder = f.path.split("/", 1)[0] + "/" if "/" in f.path else "(top level)"
        groups[folder].append(f"- {f.path}: **{f.title}**: {f.summary} (v{f.version}, {_day(f.updated_at)})")
    lines = [f"## Documents ({len(listed)})"]
    used, left_out = len(lines[0]), 0
    for folder in sorted(groups, key=lambda g: (g != "(top level)", g)):
        for line in [f"### {folder}", *groups[folder]]:
            if used + len(line) > INDEX_CHARS:
                left_out += 0 if line.startswith("### ") else 1
                continue
            lines.append(line)
            used += len(line) + 1
    if left_out:
        lines.append(f"…and {left_out} more documents left out of this list; use ls or glob to see them.")
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


_PRIORITY_ORDER = case(
    {Priority.URGENT: 0, Priority.HIGH: 1, Priority.MEDIUM: 2, Priority.LOW: 3}, value=Issue.priority, else_=4
)


def _excerpt(text: str, limit: int = 200) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[:limit].rsplit(" ", 1)[0] + "…"


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

    async def listed(*conditions: object, by_priority: bool = False) -> list[Issue]:
        order = (_PRIORITY_ORDER, Issue.rank) if by_priority else (Issue.rank,)
        return list(await session.scalars(
            select(Issue).where(Issue.project_id == project.id, *conditions).order_by(*order).limit(MAX_LISTED)
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
        # What to pick up next: today's priorities come from here.
        ("Next up (to do, most urgent first)", await listed(Issue.status == IssueStatus.TODO, by_priority=True)),
    ):
        if issues:
            lines.append(f"{label}:")
            for i in issues:
                due = f", due {_day(i.due)}" if i.due else ""
                lines.append(f"- {i.key} [{i.status.value}, {i.priority.value}{due}] {i.title}{who(i)}")
                # Why it's stuck, or what the most urgent work is about, without opening it.
                if (i.status is IssueStatus.BLOCKED or i.priority is Priority.URGENT) and i.description.strip():
                    lines.append(f"  {_excerpt(i.description)}")
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


async def _since_last_briefing(
    session: AsyncSession, project: Project, run: AgentRun, by_path: dict[str, KnowledgeFile]
) -> str:
    """For a briefing, the platform works out what happened (from the board's log, document
    versions, and approvals), so the model writes it up instead of reading everything to find out."""
    last = await session.scalar(
        select(func.max(AgentRun.created_at)).where(
            AgentRun.project_id == project.id,
            AgentRun.kind == RunKind.BRIEFING,
            AgentRun.status == RunStatus.COMPLETED,
            AgentRun.created_at < run.created_at,
        )
    )
    since = last or run.created_at - FIRST_BRIEFING_LOOKBACK
    heading = (
        f"## Since the last briefing ({_day(last)})"
        if last
        else f"## In the last {FIRST_BRIEFING_LOOKBACK.days} days (the first briefing)"
    )
    lines = [heading]

    # The board: from each issue's log, where it started and where it is now.
    events = (await session.execute(
        select(Issue.key, Issue.title, IssueEvent.kind, IssueEvent.changes)
        .join(Issue, Issue.id == IssueEvent.issue_id)
        .where(Issue.project_id == project.id, IssueEvent.created_at > since)
        .order_by(IssueEvent.created_at)
    )).all()
    created: list[str] = []
    moved: dict[str, list[str]] = {}
    comments: dict[str, int] = defaultdict(int)
    titles: dict[str, str] = {}
    for key, title, kind, change in events:
        titles[key] = title
        if kind.value == "created":
            created.append(key)
        elif kind.value == "commented":
            comments[key] += 1
        elif change and "status" in change:
            old, new = change["status"]
            moved.setdefault(key, [old, new])[1] = new
    if created:
        lines.append("Created: " + "; ".join(f"{k} {titles[k]}" for k in created[:MAX_LISTED]))
    finished = [k for k, (old, new) in moved.items() if new == IssueStatus.DONE.value and old != new]
    if finished:
        lines.append("Done: " + "; ".join(f"{k} {titles[k]}" for k in finished[:MAX_LISTED]))
    blocked = [k for k, (old, new) in moved.items() if new == IssueStatus.BLOCKED.value and old != new]
    if blocked:
        lines.append("Newly blocked: " + "; ".join(f"{k} {titles[k]}" for k in blocked[:MAX_LISTED]))
    other = [
        f"{k} {old.replace('_', ' ')} → {new.replace('_', ' ')}"
        for k, (old, new) in moved.items()
        if old != new and k not in finished and k not in blocked
    ]
    if other:
        lines.append("Moved: " + "; ".join(other[:MAX_LISTED]))
    if comments:
        lines.append("Discussed: " + ", ".join(f"{k} ({n} comment{'s' if n > 1 else ''})" for k, n in list(comments.items())[:MAX_LISTED]))
    if len(lines) == 1:
        lines.append("Board: no changes.")

    # Documents changed, by whom and why.
    docs = (await session.execute(
        select(KnowledgeFile.path, KnowledgeVersion.version, KnowledgeVersion.deleted, KnowledgeVersion.agent,
               KnowledgeVersion.message, User.display_name)
        .join(KnowledgeFile, KnowledgeFile.id == KnowledgeVersion.file_id)
        .outerjoin(User, User.id == KnowledgeVersion.author_id)
        .where(KnowledgeVersion.project_id == project.id, KnowledgeVersion.created_at > since)
        .order_by(KnowledgeVersion.created_at.desc())
        .limit(20)
    )).all()
    if docs:
        lines.append("Documents changed:")
        for path, version, deleted, agent, message, person in docs:
            who = agent or person or "someone"
            note = f": {message}" if message else ""
            lines.append(f"- {path} {'deleted' if deleted else f'v{version}'} by {who}{note}")
    else:
        lines.append("Documents: no changes.")

    # Waiting on people.
    pending = list(await session.scalars(
        select(AgentApproval)
        .where(AgentApproval.project_id == project.id, AgentApproval.status == ApprovalStatus.PENDING)
        .order_by(AgentApproval.created_at)
        .limit(5)
    ))
    if pending:
        lines.append(
            f"Waiting for approval ({len(pending)}{'+' if len(pending) == 5 else ''}): "
            + "; ".join(f"{a.tool} {a.target or ''}".strip() for a in pending)
        )

    # Is the written state of the project keeping up with the work?
    state = by_path.get("current-state.md")
    if state is not None and state.updated_at <= since and (events or docs):
        lines.append(
            f"current-state.md was last changed {_day(state.updated_at)}, before these changes: "
            "say whether it needs updating."
        )
    return "\n".join(lines)

