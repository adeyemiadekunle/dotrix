"""Issue-board tools for platform agent runs.

Reads (`list_issues`, `get_issue`) run freely. Writes (`create_issue`,
`update_issue`, `comment_issue`) are gated by the same approval pause as file
writes, and run as the agent that called them: the PRD matrix decides what it may
do (`pmagent_engine.permissions`), and every change is recorded with that agent,
the person who instructed the run, and the person who approved it.
"""
from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from pmagent_backend.core.errors import DomainError
from pmagent_backend.modules.audit.service import AuditLog
from pmagent_backend.modules.issues.models import AgentAssignee, IssueStatus, IssueType
from pmagent_backend.modules.issues.schemas import CommentCreate, IssueCreate, IssueUpdate
from pmagent_backend.modules.issues.service import IssueActor, IssueService
from pmagent_backend.modules.knowledge.models import AuthorType
from pmagent_backend.modules.projects.repository import ProjectRepository
from pmagent_backend.modules.workspaces.repository import MembershipRepository
from pmagent_engine.contracts import AgentPolicy

from .storage_backend import SessionFactory, current_agent_role

LOG_ENTRIES_SHOWN = 10

BOARD_INSTRUCTIONS = """
## The issue board
Work is tracked as issues with keys like {key}-42: epics, stories, tasks, bugs, spikes,
and sub-tasks. Read the board with list_issues and get_issue. Change it with create_issue,
update_issue, and comment_issue: every change pauses for a person's approval, so only use
them in ACTION MODE.

- Stories need acceptance criteria and bugs need steps to reproduce, in the description.
- Stories, tasks, bugs, and spikes may sit under an epic (`parent`); a sub-task needs a
  parent story, task, or bug.
- Who may do what: you (the Project Manager) create any type and are the only one who
  edits or closes issues. product-agent opens epics and stories; architecture-agent opens
  tasks; research-agent opens spikes; reviewer-agent opens bugs. Specialists can't edit
  existing issues; they propose changes and you apply them.
- Write each issue so a coding agent can work from it alone: what to build, where,
  acceptance criteria, and links to the relevant /pmagent/requirements/ and
  /pmagent/architecture/ files. Use depends_on for ordering.
- Assignees: a person's user ID, or "claude-code", "codex", or "coding-agent".

For a new feature ("I want scheduled delivery"): have product-agent define it and
propose the epic and stories, have architecture-agent note the impact, summarise, and
wait for the go-ahead before creating anything.
"""


def board_instructions(project_key: str) -> str:
    return BOARD_INSTRUCTIONS.format(key=project_key)


@dataclass(frozen=True)
class BoardContext:
    session_factory: SessionFactory
    workspace_id: uuid.UUID
    project_id: uuid.UUID
    instructed_by_id: uuid.UUID | None
    approved_by_id: uuid.UUID | None  # set only when resuming after a person approved
    policy: AgentPolicy | None = None  # the run's agent contracts (built-ins when None)
    # Each agent's definition version (None: the built-in), recorded when a standing rule is used.
    versions: dict[str, int | None] | None = None


def _assignee(value: str | None) -> dict[str, Any]:
    if value is None:
        return {}
    if value.lower() in ("", "none", "unassigned"):
        return {"assignee_user_id": None, "assignee_agent": None}
    if value in {a.value for a in AgentAssignee}:
        return {"assignee_agent": value, "assignee_user_id": None}
    return {"assignee_user_id": value, "assignee_agent": None}


def _error(exc: Exception) -> dict[str, str]:
    if isinstance(exc, DomainError):
        return {"error": exc.detail}
    if isinstance(exc, ValidationError):
        return {"error": "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())}
    return {"error": str(exc)}


def build_board_tools(ctx: BoardContext) -> tuple[list[Callable], list[Callable], list[Callable]]:
    """(read tools, PM write tools, specialists' write tools)."""

    async def _run(write: bool, fn: Callable[[IssueService, Any, IssueActor], Any], action: str | None = None) -> Any:
        rule: dict[str, Any] | None = None
        if write and (ctx.approved_by_id is None or ctx.instructed_by_id is None):
            # Not approved by a person in this step: only an owner's standing rule lets it through.
            agent = current_agent_role()
            if ctx.instructed_by_id is None or action is None or not (ctx.policy and ctx.policy.allowed(agent, action)):
                return {"error": "Changes need a person's instruction and approval"}
            rule = {"agent": agent, "action": action, "version": (ctx.versions or {}).get(agent)}
        async with ctx.session_factory() as session:
            project = await ProjectRepository(session).get(ctx.workspace_id, ctx.project_id)
            member = (
                await MembershipRepository(session).effective(ctx.workspace_id, ctx.instructed_by_id)
                if ctx.instructed_by_id
                else None
            )
            if project is None or member is None:
                return {"error": "The project or the person who instructed this run is gone"}
            actor = IssueActor(
                member, thinking_agent=current_agent_role(), approved_by_id=ctx.approved_by_id, policy=ctx.policy
            )
            try:
                result = await fn(IssueService(session), project, actor)
                if rule is not None:
                    # Allowed without a person approving it: say which standing rule allowed it.
                    AuditLog(session).record(
                        workspace_id=ctx.workspace_id, project_id=ctx.project_id, action=f"{action}.allowed",
                        target=str((result or {}).get("key") or ""), actor_type=AuthorType.AGENT,
                        agent=rule["agent"], instructed_by_id=ctx.instructed_by_id, details={"rule": rule},
                    )
                    await session.commit()
                return result
            except (DomainError, ValidationError) as exc:
                return _error(exc)  # nothing was committed; closing the session discards it

    def _detail(issue: Any) -> dict[str, Any]:
        data = issue.model_dump(mode="json")
        data["log"] = data["log"][-LOG_ENTRIES_SHOWN:]
        return data

    async def list_issues(
        status: str | None = None,
        type: str | None = None,  # noqa: A002 - the field's name in the issue model
        assignee: str | None = None,
        label: str | None = None,
        epic: str | None = None,
        ready_only: bool = False,
    ) -> Any:
        """List issues on the board in backlog order (up to 200).

        Args:
            status: todo, in_progress, blocked, review, or done.
            type: epic, story, task, bug, spike, or sub-task.
            assignee: A user ID, "claude-code", "codex", "coding-agent", or "none".
            label: Only issues with this label.
            epic: Only children of this epic key, e.g. "KUN-1".
            ready_only: Only issues that could start now (todo, dependencies done).
        """

        async def fn(service: IssueService, project: Any, actor: IssueActor) -> Any:
            issues = await service.list(
                project,
                statuses=[IssueStatus(status)] if status else (),
                types=[IssueType(type)] if type else (),
                assignee=assignee,
                label=label,
                parent=epic,
                ready=ready_only,
                limit=200,
            )
            return [i.model_dump(mode="json") for i in issues]

        try:
            return await _run(False, fn)
        except ValueError as exc:
            return {"error": str(exc)}

    async def get_issue(key: str) -> Any:
        """Get one issue in full: description, dependencies, children, and recent log.

        Args:
            key: The issue key, e.g. "KUN-42".
        """
        return await _run(False, lambda service, project, actor: _get(service, project, key))

    async def _get(service: IssueService, project: Any, key: str) -> Any:
        return _detail(await service.get(project, key))

    async def create_issue(
        type: str,  # noqa: A002
        title: str,
        description: str = "",
        priority: str = "medium",
        parent: str | None = None,
        depends_on: list[str] | None = None,
        labels: list[str] | None = None,
        due: str | None = None,
        assignee: str | None = None,
    ) -> Any:
        """Create an issue. ACTION MODE ONLY: pauses for a person's approval.

        Args:
            type: epic, story, task, bug, spike, or sub-task.
            title: Short, imperative.
            description: Markdown. Stories need acceptance criteria; bugs need repro steps.
            priority: low, medium, high, or urgent.
            parent: Parent issue key: an epic, or for a sub-task its story, task, or bug.
            depends_on: Keys of issues that must be done first.
            labels: Free-form tags.
            due: Deadline, YYYY-MM-DD.
            assignee: A user ID, "claude-code", "codex", or "coding-agent".
        """

        async def fn(service: IssueService, project: Any, actor: IssueActor) -> Any:
            data = IssueCreate(
                type=type, title=title, description=description, priority=priority, parent=parent,
                depends_on=depends_on or [], labels=labels or [], due=due, **_assignee(assignee),
            )
            return _detail(await service.create(project, actor, data))

        return await _run(True, fn, "issues.create")

    async def update_issue(
        key: str,
        status: str | None = None,
        priority: str | None = None,
        title: str | None = None,
        description: str | None = None,
        parent: str | None = None,
        depends_on: list[str] | None = None,
        labels: list[str] | None = None,
        due: str | None = None,
        assignee: str | None = None,
        note: str | None = None,
    ) -> Any:
        """Change an existing issue; only pass what changes. ACTION MODE ONLY: pauses for
        approval. Only the Project Manager edits issues.

        Args:
            key: The issue key, e.g. "KUN-42".
            status: todo, in_progress, blocked, review, or done.
            priority: low, medium, high, or urgent.
            title: New title.
            description: New Markdown description.
            parent: New parent issue key.
            depends_on: Replaces the list of keys this issue waits on.
            labels: Replaces the labels.
            due: Deadline, YYYY-MM-DD.
            assignee: A user ID, "claude-code", "codex", "coding-agent", or "none".
            note: Why, added to the issue's log.
        """
        fields: dict[str, Any] = {
            name: value
            for name, value in {
                "status": status, "priority": priority, "title": title, "description": description,
                "parent": parent, "depends_on": depends_on, "labels": labels, "due": due, "note": note,
            }.items()
            if value is not None
        }
        fields.update(_assignee(assignee))

        async def fn(service: IssueService, project: Any, actor: IssueActor) -> Any:
            return _detail(await service.update(project, key, actor, IssueUpdate(**fields)))

        return await _run(True, fn, "issues.update")

    async def comment_issue(key: str, text: str) -> Any:
        """Add a comment to an issue's log. ACTION MODE ONLY: pauses for approval.

        Args:
            key: The issue key, e.g. "KUN-42".
            text: The comment.
        """
        async def fn(service: IssueService, project: Any, actor: IssueActor) -> Any:
            return _detail(await service.comment(project, key, actor, CommentCreate(body=text)))

        return await _run(True, fn, "issues.comment")

    return [list_issues, get_issue], [create_issue, update_issue, comment_issue], [create_issue, comment_issue]
