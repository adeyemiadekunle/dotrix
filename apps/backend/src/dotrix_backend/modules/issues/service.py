"""Issue rules (FR-29, FR-30, FR-32).

- Keys come from a per-project counter taken under a row lock: never reused.
- Parent rules follow the PRD hierarchy; dependencies can't form a cycle.
- Coding tools (`as_agent`) may only work on issues assigned to them: comment,
  add sub-tasks, and move their issue as far as `review`. Only a person closes.
- `claim` is atomic (`FOR UPDATE SKIP LOCKED`): two agents never get the same issue.
"""
from __future__ import annotations

import calendar
import hashlib
import mimetypes
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import and_, case, delete, exists, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from uuid_utils.compat import uuid7

from dotrix_backend.core.errors import Conflict, Forbidden, NotFound, Unprocessable
from dotrix_backend.core.storage import BlobStorage
from dotrix_backend.modules.audit.service import AuditLog
from dotrix_backend.modules.automations.events import record_event
from dotrix_backend.modules.automations.models import AutomationEvent
from dotrix_backend.modules.coding.models import CodingRun
from dotrix_backend.modules.documents.service import safe_filename
from dotrix_backend.modules.knowledge.models import AuthorType
from dotrix_backend.modules.notifications.notify import Notifier
from dotrix_backend.modules.projects.models import Project
from dotrix_backend.modules.projects.repository import ProjectRepository, visible_to
from dotrix_backend.modules.workspaces.models import Membership
from dotrix_backend.modules.workspaces.permissions import Permission, can
from dotrix_engine.contracts import AgentPolicy

from .models import (
    DESCRIPTION_REQUIRED,
    PARENT_REQUIRED,
    PARENT_TYPES,
    PRIORITY_ORDER,
    AgentAssignee,
    Issue,
    IssueAttachment,
    IssueDependency,
    IssueEvent,
    IssueEventKind,
    IssueStar,
    IssueStatus,
    IssueType,
    IssueWatcher,
    Recurrence,
)
from .schemas import (
    AttachmentRead,
    Board,
    BoardColumn,
    ClaimRequest,
    CommentCreate,
    EpicProgress,
    IssueCreate,
    IssueEventRead,
    IssueRead,
    IssueSummary,
    IssueUpdate,
    RankRequest,
    WorkspaceIssue,
)

RANK_STEP = 1024.0
_INTERVAL_DAYS = {Recurrence.DAILY: 1, Recurrence.WEEKLY: 7, Recurrence.BIWEEKLY: 14}
# Statuses a coding tool may move its own issue to.
AGENT_STATUSES = frozenset({IssueStatus.IN_PROGRESS, IssueStatus.BLOCKED, IssueStatus.REVIEW})
# Fields a coding tool may change on its own issue.
AGENT_FIELDS = frozenset({"status", "links", "note"})

Parent = aliased(Issue, name="parent")
Blocker = aliased(Issue, name="blocker")


class InvalidIssue(Unprocessable):
    code = "invalid_issue"


class DependencyCycle(Unprocessable):
    code = "dependency_cycle"


class NothingReady(NotFound):
    code = "nothing_ready"


_BUILTIN_POLICY = AgentPolicy()

@dataclass(frozen=True)
class IssueActor:
    """Who is changing the board. `member` is the person behind it: the caller, or the
    person who instructed an agent run."""

    member: Membership
    agent: AgentAssignee | None = None  # a coding tool acting through this member's credentials
    # A platform agent ("project-manager", "product", ...) in an approved agent run.
    thinking_agent: str | None = None
    approved_by_id: uuid.UUID | None = None
    # The run's agent contracts (built-ins when None): which issues each agent may open or edit.
    policy: AgentPolicy | None = None

    @property
    def user_id(self) -> uuid.UUID:
        return self.member.user_id

    @property
    def agent_name(self) -> str | None:
        return self.thinking_agent or (self.agent.value if self.agent else None)


def _now() -> datetime:
    return datetime.now(UTC)


def normalize_key(key: str) -> str:
    return key.strip().upper()


_FIELD_NAMES = {
    "assignee_user_id": "assignee", "assignee_agent": "assignee", "due": "due date", "scheduled": "start date",
    "depends_on": "dependencies",
}


def _what_changed(changes: dict[str, list[Any]]) -> str:
    """"moved to done; changed the due date and priority", for watchers."""
    parts = []
    if "status" in changes:
        parts.append(f"moved to {str(changes['status'][1]).replace('_', ' ')}")
    fields = list(dict.fromkeys(_FIELD_NAMES.get(f, f) for f in changes if f != "status"))
    if fields:
        listed = fields[0] if len(fields) == 1 else f"{', '.join(fields[:-1])} and {fields[-1]}"
        parts.append(f"changed the {listed}")
    return "; ".join(parts)


def next_due(due: date, recurrence: Recurrence) -> date:
    """One interval after `due`. Monthly keeps the day of the month, or the month's last day
    when it's shorter (31 January -> 28 February)."""
    if recurrence is Recurrence.MONTHLY:
        year, month = (due.year + 1, 1) if due.month == 12 else (due.year, due.month + 1)
        return due.replace(year=year, month=month, day=min(due.day, calendar.monthrange(year, month)[1]))
    return due + timedelta(days=_INTERVAL_DAYS[recurrence])


def _checklist_progress(items: list[dict[str, Any]]) -> str:
    return f"{sum(1 for i in items if i.get('done'))}/{len(items)} done"


class AttachmentTooLarge(Unprocessable):
    code = "attachment_too_large"


ArchivedFilter = str  # "exclude" (default), "include", or "only"


def _archived(mode: ArchivedFilter) -> Any:
    """Which issues by archive state: in use (exclude archived), all (include), or archived only."""
    if mode == "only":
        return Issue.archived_at.is_not(None)
    if mode == "include":
        return True
    return Issue.archived_at.is_(None)


def blocked_clause() -> Any:
    """True while some issue this one depends on isn't done."""
    return exists(
        select(IssueDependency.issue_id)
        .join(Blocker, Blocker.id == IssueDependency.depends_on_id)
        .where(IssueDependency.issue_id == Issue.id, Blocker.status != IssueStatus.DONE)
    )


def priority_rank() -> Any:
    return case(PRIORITY_ORDER, value=Issue.priority)  # urgent first


def _jsonable(value: Any) -> Any:
    if isinstance(value, (datetime,)):
        return value.isoformat()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    return value


class IssueService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # -- create ------------------------------------------------------------------------

    async def create(self, project: Project, actor: IssueActor, data: IssueCreate) -> IssueRead:
        issue = await self._insert(project, actor, data)
        await self.session.commit()
        return await self.get(project, issue.key)

    async def _insert(self, project: Project, actor: IssueActor, data: IssueCreate) -> Issue:
        """Add an issue to the transaction (with its log, audit, and events); the caller commits."""
        parent = await self._by_key(project, data.parent) if data.parent else None
        if actor.agent is not None:
            if data.type is not IssueType.SUB_TASK or parent is None or parent.assignee_agent is not actor.agent:
                raise Forbidden(f"{actor.agent} can only add sub-tasks to issues assigned to it")
        if actor.thinking_agent is not None and not (actor.policy or _BUILTIN_POLICY).can_create_issue(
            actor.thinking_agent, data.type.value
        ):
            raise Forbidden(
                f"The {actor.thinking_agent} agent can't open {data.type} issues; "
                "ask the Project Manager to create it"
            )
        self._check_parent(data.type, parent)
        self._check_description(data.type, data.description)
        self._check_assignment(actor, data.assignee_agent)

        locked = await ProjectRepository(self.session).get(project.workspace_id, project.id, for_update=True)
        assert locked is not None
        number = locked.next_issue_number
        locked.next_issue_number += 1
        max_rank = await self.session.scalar(select(func.max(Issue.rank)).where(Issue.project_id == project.id))
        now = _now()
        issue = Issue(
            id=uuid7(),
            workspace_id=project.workspace_id,
            project_id=project.id,
            number=number,
            key=f"{project.key}-{number}",
            type=data.type,
            title=data.title,
            description=data.description,
            status=data.status,
            priority=data.priority,
            assignee_user_id=data.assignee_user_id,
            assignee_agent=data.assignee_agent,
            reporter_user_id=None if actor.agent_name else actor.user_id,
            reporter_agent=actor.agent_name,
            parent_id=parent.id if parent else None,
            estimate=data.estimate,
            due=data.due,
            scheduled=data.scheduled,
            labels=data.labels,
            components=data.components,
            links=[link.model_dump() for link in data.links],
            checklist=[item.model_dump(mode="json") for item in data.checklist],
            recurrence=data.recurrence,
            rank=(max_rank or 0.0) + RANK_STEP,
            created_at=now,
            updated_at=now,
            resolved_at=now if data.status is IssueStatus.DONE else None,
        )
        if data.assignee_user_id is not None:
            await self._check_member(project, data.assignee_user_id)
        await self._check_checklist(project, issue.checklist)
        self.session.add(issue)
        await self.session.flush()
        if data.depends_on:
            await self._set_dependencies(project, issue, data.depends_on)
        if actor.agent_name is None:
            self.session.add(IssueWatcher(issue_id=issue.id, user_id=actor.user_id))
        if issue.assignee_user_id is not None:
            self._notify_assignee(project, issue, actor)
        self._event(issue, actor, IssueEventKind.CREATED)
        self._audit(project, actor, "issue.create", issue)
        if actor.agent_name is None:  # people's changes set automations off; an agent's never do
            await record_event(
                self.session, workspace_id=project.workspace_id, project_id=project.id,
                event=AutomationEvent.ISSUE_CREATED, summary=f"{issue.key} created: {issue.title}",
                details={"key": issue.key, "type": issue.type.value},
            )
        return issue

    # -- read --------------------------------------------------------------------------

    async def get(self, project: Project, key: str) -> IssueRead:
        issue = await self._by_key(project, key)
        parent_key = (
            await self.session.scalar(select(Issue.key).where(Issue.id == issue.parent_id))
            if issue.parent_id
            else None
        )
        depends_on = list(
            await self.session.scalars(
                select(Issue.key)
                .join(IssueDependency, IssueDependency.depends_on_id == Issue.id)
                .where(IssueDependency.issue_id == issue.id)
                .order_by(Issue.number)
            )
        )
        blocks = list(
            await self.session.scalars(
                select(Issue.key)
                .join(IssueDependency, IssueDependency.issue_id == Issue.id)
                .where(IssueDependency.depends_on_id == issue.id)
                .order_by(Issue.number)
            )
        )
        children = list(
            await self.session.scalars(
                select(Issue.key).where(Issue.parent_id == issue.id).order_by(Issue.number)
            )
        )
        watchers = list(
            await self.session.scalars(
                select(IssueWatcher.user_id).where(IssueWatcher.issue_id == issue.id)
            )
        )
        is_blocked = await self.session.scalar(select(blocked_clause()).where(Issue.id == issue.id))
        events = await self.session.scalars(
            select(IssueEvent)
            .where(IssueEvent.issue_id == issue.id)
            .order_by(IssueEvent.created_at, IssueEvent.id)
        )
        attachments = [
            AttachmentRead.model_validate(a)
            for a in await self.session.scalars(
                select(IssueAttachment)
                .where(IssueAttachment.issue_id == issue.id)
                .order_by(IssueAttachment.created_at, IssueAttachment.id)
            )
        ]
        return IssueRead.model_validate(issue).model_copy(
            update={
                "attachments": attachments,
                "attachment_count": len(attachments),
                "parent_key": parent_key,
                "depends_on": depends_on,
                "blocks": blocks,
                "children": children,
                "watchers": watchers,
                "ready": issue.status is IssueStatus.TODO and not is_blocked,
                "log": [IssueEventRead.model_validate(e) for e in events],
            }
        )

    async def list(
        self,
        project: Project,
        *,
        types: Sequence[IssueType] = (),
        statuses: Sequence[IssueStatus] = (),
        assignee: str | None = None,
        label: str | None = None,
        parent: str | None = None,
        ready: bool = False,
        order: str = "rank",
        limit: int = 500,
        offset: int = 0,
        archived: ArchivedFilter = "exclude",
    ) -> list[IssueSummary]:
        stmt = self._summary_query(project, types, statuses, assignee, label).where(_archived(archived))
        if parent is not None:
            parent_issue = await self._by_key(project, parent)
            stmt = stmt.where(Issue.parent_id == parent_issue.id)
        if ready:
            stmt = stmt.where(Issue.status == IssueStatus.TODO, ~blocked_clause())
        ordering = {
            "rank": (Issue.rank,),
            "priority": (priority_rank(), Issue.due.asc().nulls_last(), Issue.created_at),
            "created": (Issue.created_at.desc(),),
            "updated": (Issue.updated_at.desc(),),
        }[order]
        rows = (await self.session.execute(stmt.order_by(*ordering, Issue.number).limit(limit).offset(offset))).all()
        deps, counts = await self._row_extras([issue.id for issue, _ in rows])
        return [self._summary(issue, parent_key, deps, counts) for issue, parent_key in rows]

    async def across_projects(
        self,
        member: Membership,
        *,
        types: Sequence[IssueType] = (),
        statuses: Sequence[IssueStatus] = (),
        assignee: str | None = None,
        reporter: str | None = None,
        watching: bool = False,
        starred: bool = False,
        archived: ArchivedFilter = "exclude",
        label: str | None = None,
        due_before: date | None = None,
        order: str = "due",
        limit: int = 500,
        offset: int = 0,
    ) -> list[WorkspaceIssue]:
        """Issues in every project of the workspace that `member` can see (My issues, Tasks).
        `me` stands for the member in `assignee` and `reporter`."""
        me = str(member.user_id)
        stmt = (
            select(Issue, Parent.key, Project.key, Project.name)
            .join(Project, Project.id == Issue.project_id)
            .outerjoin(Parent, Parent.id == Issue.parent_id)
            .where(
                Issue.workspace_id == member.workspace_id,
                Project.workspace_id == member.workspace_id,
                visible_to(member.user_id, member.role),
            )
        )
        stmt = self._filtered(stmt, types, statuses, me if assignee == "me" else assignee, label).where(_archived(archived))
        if reporter is not None:
            try:
                reporter_id = uuid.UUID(me if reporter == "me" else reporter)
            except ValueError as exc:
                raise InvalidIssue("reporter must be a user ID or 'me'") from exc
            stmt = stmt.where(Issue.reporter_user_id == reporter_id)
        if watching:
            stmt = stmt.where(
                exists().where(IssueWatcher.issue_id == Issue.id, IssueWatcher.user_id == member.user_id)
            )
        if starred:
            stmt = stmt.where(
                exists().where(IssueStar.issue_id == Issue.id, IssueStar.user_id == member.user_id)
            )
        if due_before is not None:
            stmt = stmt.where(Issue.due <= due_before)
        ordering = {
            "due": (Issue.due.asc().nulls_last(), priority_rank(), Issue.created_at),
            "priority": (priority_rank(), Issue.due.asc().nulls_last(), Issue.created_at),
            "created": (Issue.created_at.desc(),),
            "updated": (Issue.updated_at.desc(),),
        }[order]
        rows = (await self.session.execute(stmt.order_by(*ordering, Issue.id).limit(limit).offset(offset))).all()
        deps, counts = await self._row_extras([row[0].id for row in rows])
        return [
            WorkspaceIssue.model_validate(
                self._summary(issue, parent_key, deps, counts).model_dump()
                | {"project_id": issue.project_id, "project_key": key, "project_name": name}
            )
            for issue, parent_key, key, name in rows
        ]

    async def board(
        self,
        project: Project,
        *,
        types: Sequence[IssueType] = (),
        assignee: str | None = None,
        label: str | None = None,
        epic: str | None = None,
    ) -> Board:
        stmt = self._summary_query(project, types, (), assignee, label).where(Issue.archived_at.is_(None))
        if epic is not None:
            epic_issue = await self._by_key(project, epic)
            stmt = stmt.where(Issue.parent_id == epic_issue.id)
        rows = (await self.session.execute(stmt.order_by(Issue.rank, Issue.number))).all()
        deps, counts = await self._row_extras([issue.id for issue, _ in rows])
        columns: dict[IssueStatus, list[IssueSummary]] = {status: [] for status in IssueStatus}
        for issue, parent_key in rows:
            columns[issue.status].append(self._summary(issue, parent_key, deps, counts))
        return Board(columns=[BoardColumn(status=s, issues=columns[s]) for s in IssueStatus])

    async def epics(self, project: Project) -> list[EpicProgress]:
        child = aliased(Issue, name="child")
        rows = await self.session.execute(
            select(
                Issue.key,
                Issue.title,
                Issue.status,
                func.count(child.id),
                func.count(child.id).filter(child.status == IssueStatus.DONE),
            )
            .outerjoin(child, child.parent_id == Issue.id)
            .where(Issue.project_id == project.id, Issue.type == IssueType.EPIC)
            .group_by(Issue.id)
            .order_by(Issue.rank, Issue.number)
        )
        return [
            EpicProgress(
                key=key, title=title, status=status, total=total, done=done,
                percent=round(100 * done / total) if total else 0,
            )
            for key, title, status, total, done in rows
        ]

    # -- change ------------------------------------------------------------------------

    async def update(self, project: Project, key: str, actor: IssueActor, data: IssueUpdate) -> IssueRead:
        issue = await self._by_key(project, key, for_update=True)
        sent = data.model_dump(exclude_unset=True)
        note = sent.pop("note", None)
        sent.pop("as_agent", None)
        if actor.thinking_agent is not None and not (actor.policy or _BUILTIN_POLICY).can_edit_issues(actor.thinking_agent):
            raise Forbidden(
                f"The {actor.thinking_agent} agent can't edit issues; ask the Project Manager"
            )
        if actor.agent is not None:
            self._check_agent_owns(actor, issue)
            extra = set(sent) - AGENT_FIELDS
            if extra:
                raise Forbidden(f"{actor.agent} may only change status and links on its issue, not {sorted(extra)}")
            if "status" in sent and data.status not in AGENT_STATUSES:
                raise Forbidden(f"{actor.agent} can move its issue to in_progress, blocked, or review; a person closes it")

        changes: dict[str, list[Any]] = {}

        def change(field: str, new: Any) -> None:
            old = getattr(issue, field)
            if old != new:
                changes[field] = [_jsonable(old), _jsonable(new)]
                setattr(issue, field, new)

        for field in ("title", "description", "priority", "estimate", "due", "scheduled", "labels", "components"):
            if field in sent:
                value = getattr(data, field)
                if field in ("title", "description", "priority", "labels", "components") and value is None:
                    raise InvalidIssue(f"{field} can't be empty")
                change(field, value)
        if "links" in sent:
            change("links", [link.model_dump() for link in data.links or []])
        if "checklist" in sent:
            items = [item.model_dump(mode="json") for item in data.checklist or []]
            if items != issue.checklist:
                await self._check_checklist(project, items)
                changes["checklist"] = [_checklist_progress(issue.checklist), _checklist_progress(items)]
                issue.checklist = items
        if "recurrence" in sent:
            change("recurrence", data.recurrence)
        if data.archived is not None and data.archived != (issue.archived_at is not None):
            changes["archived"] = [issue.archived_at is not None, data.archived]
            issue.archived_at = _now() if data.archived else None

        if "assignee_user_id" in sent or "assignee_agent" in sent:
            self._check_assignment(actor, data.assignee_agent)
            if data.assignee_user_id is not None:
                await self._check_member(project, data.assignee_user_id)
            change("assignee_user_id", data.assignee_user_id)
            change("assignee_agent", data.assignee_agent)

        new_type = data.type if "type" in sent and data.type is not None else issue.type
        if "parent" in sent:
            parent = await self._by_key(project, data.parent) if data.parent else None
            if parent is not None and parent.id == issue.id:
                raise InvalidIssue("An issue can't be its own parent")
            self._check_parent(new_type, parent)
            if (parent.id if parent else None) != issue.parent_id:
                old_parent = (
                    await self.session.scalar(select(Issue.key).where(Issue.id == issue.parent_id))
                    if issue.parent_id else None
                )
                changes["parent"] = [old_parent, parent.key if parent else None]
                issue.parent_id = parent.id if parent else None
        elif new_type is not issue.type:
            current = await self.session.get(Issue, issue.parent_id) if issue.parent_id else None
            self._check_parent(new_type, current)
        if new_type is not issue.type:
            await self._check_children_allow(issue, new_type)
            change("type", new_type)
        self._check_description(issue.type, issue.description)

        if "status" in sent:
            if data.status is None:
                raise InvalidIssue("status can't be empty")
            before = issue.status
            change("status", data.status)
            if data.status is IssueStatus.DONE and before is not IssueStatus.DONE:
                issue.resolved_at = _now()
                if issue.recurrence is not None and issue.due is not None and issue.repeated_as is None:
                    following = await self._repeat(project, issue, actor)
                    changes["repeated_as"] = [None, following.key]
                    issue.repeated_as = following.key
            elif data.status is not IssueStatus.DONE:
                issue.resolved_at = None

        if "depends_on" in sent:
            old_keys = await self._dependency_keys(issue)
            new_keys = sorted({normalize_key(k) for k in data.depends_on or []})
            if old_keys != new_keys:
                await self._set_dependencies(project, issue, new_keys, replace=True)
                changes["depends_on"] = [old_keys, new_keys]

        told: list[uuid.UUID] = []
        if changes.get("assignee_user_id") and issue.assignee_user_id is not None:
            self._notify_assignee(project, issue, actor)
            told.append(issue.assignee_user_id)
        if changes or note:
            issue.updated_at = _now()
            await Notifier(self.session).watched(
                project, issue.id, f"{issue.key} {issue.title}", _what_changed(changes) or "added a note",
                issue.updated_at, actor_user_id=actor.user_id, actor_agent=actor.agent_name, excerpt=note, skip=told,
            )
            self._event(issue, actor, IssueEventKind.UPDATED, changes=changes, body=note)
            self._audit(project, actor, "issue.update", issue, {"fields": sorted(changes)})
            if "status" in changes and issue.status is IssueStatus.DONE and actor.agent_name is None:
                await record_event(
                    self.session, workspace_id=project.workspace_id, project_id=project.id,
                    event=AutomationEvent.ISSUE_DONE, summary=f"{issue.key} done: {issue.title}",
                    details={"key": issue.key, "type": issue.type.value},
                )
            await self.session.commit()
        return await self.get(project, issue.key)

    async def comment(self, project: Project, key: str, actor: IssueActor, data: CommentCreate) -> IssueRead:
        issue = await self._by_key(project, key)
        if actor.agent is not None:
            self._check_agent_owns(actor, issue)
        issue.updated_at = _now()
        self._event(issue, actor, IssueEventKind.COMMENTED, body=data.body)
        mentioned = await Notifier(self.session).mentioned(
            project, data.mentions, data.body, issue.updated_at, title=issue.title,
            actor_user_id=actor.user_id, issue_id=issue.id,
        ) if data.mentions else []
        await Notifier(self.session).watched(
            project, issue.id, f"{issue.key} {issue.title}", "a new comment", issue.updated_at,
            actor_user_id=actor.user_id, actor_agent=actor.agent_name, excerpt=data.body, skip=mentioned,
        )
        await self.session.commit()
        return await self.get(project, issue.key)

    async def rank(self, project: Project, key: str, data: RankRequest) -> IssueRead:
        issue = await self._by_key(project, key, for_update=True)
        anchor = await self._by_key(project, data.before or data.after or "")
        if anchor.id == issue.id:
            raise InvalidIssue("Can't rank an issue relative to itself")
        if data.before is not None:
            neighbour = await self.session.scalar(
                select(func.max(Issue.rank)).where(
                    Issue.project_id == project.id, Issue.rank < anchor.rank, Issue.id != issue.id
                )
            )
            new_rank = (anchor.rank + neighbour) / 2 if neighbour is not None else anchor.rank - RANK_STEP
        else:
            neighbour = await self.session.scalar(
                select(func.min(Issue.rank)).where(
                    Issue.project_id == project.id, Issue.rank > anchor.rank, Issue.id != issue.id
                )
            )
            new_rank = (anchor.rank + neighbour) / 2 if neighbour is not None else anchor.rank + RANK_STEP
        if new_rank in (anchor.rank, neighbour):  # floats exhausted between two neighbours
            await self._rebalance(project)
            return await self.rank(project, key, data)
        issue.rank = new_rank
        await self.session.commit()
        return await self.get(project, issue.key)

    async def watch(self, project: Project, key: str, user_id: uuid.UUID, *, on: bool) -> IssueRead:
        issue = await self._by_key(project, key)
        await self.session.execute(
            delete(IssueWatcher).where(IssueWatcher.issue_id == issue.id, IssueWatcher.user_id == user_id)
        )
        if on:
            self.session.add(IssueWatcher(issue_id=issue.id, user_id=user_id))
        await self.session.commit()
        return await self.get(project, issue.key)

    # -- delete and move -------------------------------------------------------------------

    async def delete(self, project: Project, key: str, actor: IssueActor) -> list[str]:
        """Delete an issue and its log, files, and stars: owners and admins, or whoever reported
        it. Not while it has sub-issues. Returns its files' storage keys, to delete once committed."""
        issue = await self._by_key(project, key, for_update=True)
        if actor.agent_name is not None:
            raise Forbidden("Agents can't delete issues")
        if not (can(actor.member, Permission.MANAGE_PROJECTS) or issue.reporter_user_id == actor.user_id):
            raise Forbidden("Only owners, admins, or whoever reported it can delete an issue")
        await self._check_no_children(issue)
        keys = list(await self.session.scalars(select(IssueAttachment.storage_key).where(IssueAttachment.issue_id == issue.id)))
        self._audit(project, actor, "issue.deleted", issue, {"title": issue.title})
        await self.session.delete(issue)
        await self.session.commit()
        return keys

    async def move(self, project: Project, key: str, actor: IssueActor, target: Project) -> IssueRead:
        """Move an issue to another project of the workspace: it's created there with the next key
        (its log, comments, watchers, stars, and files go with it) and deleted here. Links that only
        make sense in one project (its parent, dependencies) stay behind. Not while it has sub-issues
        or coding sessions (their branch belongs to this project's repo)."""
        if target.id == project.id:
            raise InvalidIssue(f"{normalize_key(key)} is already in {project.key}")
        if actor.agent_name is not None:
            raise Forbidden("Agents can't move issues")
        issue = await self._by_key(project, key, for_update=True)
        await self._check_no_children(issue)
        if await self.session.scalar(select(CodingRun.id).where(CodingRun.issue_id == issue.id).limit(1)) is not None:
            raise Conflict(f"{issue.key} has coding sessions, which belong to {project.key}'s repo")
        assignee = issue.assignee_user_id
        if assignee is not None and not await ProjectRepository(self.session).can_see(target, assignee):
            assignee = None  # they can't see the other project
        data = IssueCreate(
            type=IssueType.TASK if issue.type is IssueType.SUB_TASK else issue.type,
            title=issue.title, description=issue.description, status=issue.status, priority=issue.priority,
            estimate=issue.estimate, due=issue.due, scheduled=issue.scheduled, labels=issue.labels,
            components=issue.components, links=issue.links, checklist=issue.checklist, recurrence=issue.recurrence,
            assignee_user_id=assignee, assignee_agent=issue.assignee_agent,
        )
        moved = await self._insert(target, actor, data)
        moved.created_at, moved.resolved_at, moved.archived_at = issue.created_at, issue.resolved_at, issue.archived_at
        await self.session.flush()
        # What goes with it: its log (comments included), watchers, stars, and files.
        await self.session.execute(delete(IssueWatcher).where(IssueWatcher.issue_id == moved.id))
        for model in (IssueEvent, IssueWatcher, IssueStar):
            await self.session.execute(update(model).where(model.issue_id == issue.id).values(issue_id=moved.id))
        await self.session.execute(
            update(IssueAttachment).where(IssueAttachment.issue_id == issue.id).values(issue_id=moved.id, project_id=target.id)
        )
        self._event(moved, actor, IssueEventKind.UPDATED, changes={"key": [issue.key, moved.key]})
        self._audit(project, actor, "issue.moved", issue, {"to": moved.key})
        await self.session.delete(issue)
        await self.session.commit()
        return await self.get(target, moved.key)

    async def _check_no_children(self, issue: Issue) -> None:
        children = list(await self.session.scalars(select(Issue.key).where(Issue.parent_id == issue.id).order_by(Issue.number)))
        if children:
            raise Conflict(f"{issue.key} has sub-issues ({', '.join(children)}); move or delete them first")

    # -- comments ---------------------------------------------------------------------------

    async def _comment(self, issue: Issue, comment_id: uuid.UUID) -> IssueEvent:
        found = await self.session.scalar(
            select(IssueEvent).where(
                IssueEvent.id == comment_id, IssueEvent.issue_id == issue.id, IssueEvent.kind == IssueEventKind.COMMENTED
            )
        )
        if found is None:
            raise NotFound("Comment not found")
        return found

    async def edit_comment(
        self, project: Project, key: str, actor: IssueActor, comment_id: uuid.UUID, body: str
    ) -> IssueRead:
        """Change a comment's text: its author only."""
        issue = await self._by_key(project, key)
        comment = await self._comment(issue, comment_id)
        if actor.agent_name is not None or comment.author_user_id != actor.user_id:
            raise Forbidden("Only its author can edit a comment")
        if body != comment.body:
            comment.body, comment.edited_at = body, _now()
            await self.session.commit()
        return await self.get(project, issue.key)

    async def delete_comment(self, project: Project, key: str, actor: IssueActor, comment_id: uuid.UUID) -> IssueRead:
        """Delete a comment: its author, or owners and admins."""
        issue = await self._by_key(project, key)
        comment = await self._comment(issue, comment_id)
        mine = actor.agent_name is None and comment.author_user_id == actor.user_id
        if not (mine or can(actor.member, Permission.MANAGE_PROJECTS)):
            raise Forbidden("Only its author, owners, or admins can delete a comment")
        self._audit(project, actor, "issue.comment_deleted", issue, {"author_user_id": str(comment.author_user_id)})
        await self.session.delete(comment)
        await self.session.commit()
        return await self.get(project, issue.key)

    async def react(
        self, project: Project, key: str, user_id: uuid.UUID, comment_id: uuid.UUID, emoji: str, *, on: bool
    ) -> IssueRead:
        """Add or take back your reaction to a comment."""
        issue = await self._by_key(project, key)
        comment = await self._comment(issue, comment_id)
        reactions = {k: list(v) for k, v in (comment.reactions or {}).items()}
        who = reactions.get(emoji, [])
        if on and str(user_id) not in who:
            if emoji not in reactions and len(reactions) >= 20:
                raise InvalidIssue("A comment takes at most 20 different reactions")
            reactions[emoji] = [*who, str(user_id)]
        elif not on and str(user_id) in who:
            rest = [u for u in who if u != str(user_id)]
            if rest:
                reactions[emoji] = rest
            else:
                reactions.pop(emoji)
        if reactions != comment.reactions:
            comment.reactions = reactions  # a new dict, so the change is saved
            await self.session.commit()
        return await self.get(project, issue.key)

    # -- stars (per person) ----------------------------------------------------------------

    async def star(self, project: Project, key: str, user_id: uuid.UUID, *, on: bool) -> None:
        issue = await self._by_key(project, key)
        existing = await self.session.scalar(
            select(IssueStar).where(IssueStar.issue_id == issue.id, IssueStar.user_id == user_id)
        )
        if on and existing is None:
            self.session.add(
                IssueStar(workspace_id=issue.workspace_id, issue_id=issue.id, user_id=user_id, created_at=_now())
            )
        elif not on and existing is not None:
            await self.session.delete(existing)
        await self.session.commit()

    # -- attachments -----------------------------------------------------------------------

    async def attach(
        self,
        project: Project,
        key: str,
        actor: IssueActor,
        storage: BlobStorage,
        filename: str,
        data: bytes,
        *,
        max_bytes: int,
    ) -> IssueRead:
        """Store a file and list it under the issue (any type; nothing converts it)."""
        issue = await self._by_key(project, key)
        if actor.agent is not None:
            self._check_agent_owns(actor, issue)
        if len(data) > max_bytes:
            raise AttachmentTooLarge(f"Attachments are limited to {max_bytes // 1_000_000} MB")
        if not data:
            raise InvalidIssue("The file is empty")
        filename = safe_filename(filename)
        attachment_id = uuid7()
        storage_key = f"{project.workspace_id}/{project.id}/attachments/{attachment_id}/{filename}"
        # From the extension, never the client's header, so the type it's served with can be trusted.
        content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        await storage.put(storage_key, data, content_type)
        self.session.add(
            IssueAttachment(
                id=attachment_id, workspace_id=project.workspace_id, project_id=project.id, issue_id=issue.id,
                filename=filename, content_type=content_type, size=len(data), storage_key=storage_key,
                uploaded_by_id=actor.user_id, created_at=_now(),
            )
        )
        issue.updated_at = _now()
        self._event(issue, actor, IssueEventKind.UPDATED, changes={"attachments": [None, filename]})
        self._audit(
            project, actor, "issue.attachment_added", issue,
            {"filename": filename, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()},
        )
        await self.session.commit()
        return await self.get(project, issue.key)

    async def attachment(self, project: Project, key: str, attachment_id: uuid.UUID) -> IssueAttachment:
        issue = await self._by_key(project, key)
        found = await self.session.scalar(
            select(IssueAttachment).where(IssueAttachment.id == attachment_id, IssueAttachment.issue_id == issue.id)
        )
        if found is None:
            raise NotFound("Attachment not found")
        return found

    async def detach(
        self, project: Project, key: str, actor: IssueActor, storage: BlobStorage, attachment_id: uuid.UUID
    ) -> IssueRead:
        """Take a file off the issue and delete it."""
        found = await self.attachment(project, key, attachment_id)
        issue = await self._by_key(project, key)
        if actor.agent is not None:
            self._check_agent_owns(actor, issue)
        await self.session.delete(found)
        issue.updated_at = _now()
        self._event(issue, actor, IssueEventKind.UPDATED, changes={"attachments": [found.filename, None]})
        self._audit(project, actor, "issue.attachment_removed", issue, {"filename": found.filename})
        await self.session.commit()
        await storage.delete(found.storage_key)  # after the commit: a failed delete only leaves an orphaned file
        return await self.get(project, issue.key)

    # -- next and claim (FR-32) ----------------------------------------------------------

    async def next(self, project: Project, actor: IssueActor, agent: AgentAssignee | None) -> IssueRead:
        """The requester's own in-progress issue first (a crashed session resumes), else the
        best ready issue: priority, then earliest due date, then oldest."""
        mine = self._assigned_to(actor, agent)
        own = await self.session.scalar(
            select(Issue)
            .where(Issue.project_id == project.id, Issue.status == IssueStatus.IN_PROGRESS, mine)
            .order_by(priority_rank(), Issue.created_at)
            .limit(1)
        )
        if own is not None:
            return await self.get(project, own.key)
        candidate = await self.session.scalar(self._ready_query(project, mine).limit(1))
        if candidate is None:
            raise NothingReady("Nothing is ready for you right now")
        return await self.get(project, candidate.key)

    async def claim(self, project: Project, actor: IssueActor, data: ClaimRequest) -> IssueRead:
        agent = data.as_agent
        self._check_assignment(actor, agent)
        mine = self._assigned_to(actor, agent)
        stmt = self._ready_query(project, mine)
        if data.key is not None:
            stmt = stmt.where(Issue.key == normalize_key(data.key))
        # SKIP LOCKED: a concurrent claimer gets the next issue instead of waiting for this one.
        issue = await self.session.scalar(stmt.limit(1).with_for_update(skip_locked=True, of=Issue))
        if issue is None:
            if data.key is not None:
                await self._by_key(project, data.key)  # 404 if it doesn't exist at all
                raise Conflict(f"{normalize_key(data.key)} isn't ready to claim (claimed, not todo, or blocked)")
            raise NothingReady("Nothing is ready for you right now")
        changes = {"status": [issue.status.value, IssueStatus.IN_PROGRESS.value]}
        issue.status = IssueStatus.IN_PROGRESS
        if agent is not None:
            issue.assignee_agent, issue.assignee_user_id = agent, None
            changes["assignee_agent"] = [None, agent.value]
        else:
            issue.assignee_user_id, issue.assignee_agent = actor.user_id, None
            changes["assignee_user_id"] = [None, str(actor.user_id)]
        issue.updated_at = _now()
        claimer = IssueActor(actor.member, agent)
        self._event(issue, claimer, IssueEventKind.CLAIMED, changes=changes)
        self._audit(project, claimer, "issue.claim", issue)
        await self.session.commit()
        return await self.get(project, issue.key)

    # -- helpers -----------------------------------------------------------------------

    def _summary_query(
        self,
        project: Project,
        types: Sequence[IssueType],
        statuses: Sequence[IssueStatus],
        assignee: str | None,
        label: str | None,
    ) -> Any:
        stmt = (
            select(Issue, Parent.key)
            .outerjoin(Parent, Parent.id == Issue.parent_id)
            .where(Issue.project_id == project.id)
        )
        return self._filtered(stmt, types, statuses, assignee, label)

    @staticmethod
    def _filtered(
        stmt: Any,
        types: Sequence[IssueType],
        statuses: Sequence[IssueStatus],
        assignee: str | None,
        label: str | None,
    ) -> Any:
        if types:
            stmt = stmt.where(Issue.type.in_(types))
        if statuses:
            stmt = stmt.where(Issue.status.in_(statuses))
        if label:
            stmt = stmt.where(Issue.labels.contains([label]))  # @>, served by the GIN index
        if assignee is not None:
            if assignee == "none":
                stmt = stmt.where(Issue.assignee_user_id.is_(None), Issue.assignee_agent.is_(None))
            elif assignee in {a.value for a in AgentAssignee}:
                stmt = stmt.where(Issue.assignee_agent == AgentAssignee(assignee))
            else:
                try:
                    stmt = stmt.where(Issue.assignee_user_id == uuid.UUID(assignee))
                except ValueError as exc:
                    raise InvalidIssue("assignee must be a user ID, an agent name, or 'none'") from exc
        return stmt

    @staticmethod
    def _summary(
        issue: Issue,
        parent_key: str | None,
        deps: dict[uuid.UUID, list[str]] | None = None,
        counts: dict[uuid.UUID, int] | None = None,
    ) -> IssueSummary:
        return IssueSummary.model_validate(issue).model_copy(
            update={
                "parent_key": parent_key,
                "depends_on": (deps or {}).get(issue.id, []),
                "attachment_count": (counts or {}).get(issue.id, 0),
            }
        )

    async def _row_extras(
        self, issue_ids: list[uuid.UUID]
    ) -> tuple[dict[uuid.UUID, list[str]], dict[uuid.UUID, int]]:
        """What list rows need beyond the issue: the keys each waits for, and its attachment count."""
        if not issue_ids:
            return {}, {}
        counts: dict[uuid.UUID, int] = {
            issue_id: count
            for issue_id, count in await self.session.execute(
                select(IssueAttachment.issue_id, func.count())
                .where(IssueAttachment.issue_id.in_(issue_ids))
                .group_by(IssueAttachment.issue_id)
            )
        }
        return await self._dependency_map(issue_ids), counts

    async def _dependency_map(self, issue_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[str]]:
        """The keys each of these issues waits for, in one query."""
        if not issue_ids:
            return {}
        found: dict[uuid.UUID, list[str]] = {}
        rows = await self.session.execute(
            select(IssueDependency.issue_id, Blocker.key)
            .join(Blocker, Blocker.id == IssueDependency.depends_on_id)
            .where(IssueDependency.issue_id.in_(issue_ids))
            .order_by(Blocker.number)
        )
        for issue_id, key in rows:
            found.setdefault(issue_id, []).append(key)
        return found

    def _ready_query(self, project: Project, mine: Any) -> Any:
        unassigned = and_(Issue.assignee_user_id.is_(None), Issue.assignee_agent.is_(None))
        return (
            select(Issue)
            .where(
                Issue.project_id == project.id,
                Issue.status == IssueStatus.TODO,
                Issue.type != IssueType.EPIC,  # epics are containers, not work
                Issue.archived_at.is_(None),
                ~blocked_clause(),
                or_(unassigned, mine),
            )
            .order_by(priority_rank(), Issue.due.asc().nulls_last(), Issue.created_at, Issue.number)
        )

    @staticmethod
    def _assigned_to(actor: IssueActor, agent: AgentAssignee | None) -> Any:
        if agent is not None:
            return Issue.assignee_agent == agent
        return Issue.assignee_user_id == actor.user_id

    async def _by_key(self, project: Project, key: str, *, for_update: bool = False) -> Issue:
        stmt = select(Issue).where(Issue.project_id == project.id, Issue.key == normalize_key(key))
        if for_update:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        issue = await self.session.scalar(stmt)
        if issue is None:
            raise NotFound(f"Issue {normalize_key(key)} not found")
        return issue

    @staticmethod
    def _check_parent(issue_type: IssueType, parent: Issue | None) -> None:
        allowed = PARENT_TYPES[issue_type]
        if parent is None:
            if issue_type in PARENT_REQUIRED:
                raise InvalidIssue(f"A {issue_type} needs a parent: {', '.join(sorted(allowed))}")
            return
        if parent.type not in allowed:
            what = ", ".join(sorted(allowed)) or "no parent"
            raise InvalidIssue(f"A {issue_type} can't sit under a {parent.type}; allowed: {what}")

    async def _check_children_allow(self, issue: Issue, new_type: IssueType) -> None:
        child_types = set(await self.session.scalars(select(Issue.type).where(Issue.parent_id == issue.id)))
        for child_type in child_types:
            if new_type not in PARENT_TYPES[child_type]:
                raise InvalidIssue(f"Can't make this a {new_type}: it has {child_type} children")

    @staticmethod
    def _check_description(issue_type: IssueType, description: str) -> None:
        if issue_type in DESCRIPTION_REQUIRED and not description.strip():
            what = "acceptance criteria" if issue_type is IssueType.STORY else "steps to reproduce"
            raise InvalidIssue(f"A {issue_type} needs a description with {what}")

    @staticmethod
    def _check_assignment(actor: IssueActor, agent: AgentAssignee | None) -> None:
        if agent is AgentAssignee.CODING_AGENT and not can(actor.member, Permission.INSTRUCT_CODING_AGENT):
            raise Forbidden("Your role can't instruct the coding agent")

    @staticmethod
    def _check_agent_owns(actor: IssueActor, issue: Issue) -> None:
        if issue.assignee_agent is not actor.agent:
            raise Forbidden(f"{issue.key} isn't assigned to {actor.agent}")

    async def _check_member(self, project: Project, user_id: uuid.UUID) -> None:
        if not await ProjectRepository(self.session).can_see(project, user_id):
            raise InvalidIssue("The assignee must be someone who can see this project")

    async def _check_checklist(self, project: Project, items: list[dict[str, Any]]) -> None:
        for user_id in {i["assignee_user_id"] for i in items if i.get("assignee_user_id")}:
            if not await ProjectRepository(self.session).can_see(project, uuid.UUID(user_id)):
                raise InvalidIssue("A checklist item's assignee must be someone who can see this project")

    async def _repeat(self, project: Project, issue: Issue, actor: IssueActor) -> Issue:
        """The next occurrence of a repeating issue that was just finished: the same issue, to do,
        its checklist unticked, due (and planned to start) one interval later."""
        assert issue.recurrence is not None and issue.due is not None
        due = next_due(issue.due, issue.recurrence)
        parent_key = (
            await self.session.scalar(select(Issue.key).where(Issue.id == issue.parent_id))
            if issue.parent_id else None
        )
        data = IssueCreate(
            type=issue.type, title=issue.title, description=issue.description, status=IssueStatus.TODO,
            priority=issue.priority, parent=parent_key, estimate=issue.estimate, due=due,
            scheduled=issue.scheduled + (due - issue.due) if issue.scheduled else None,
            labels=issue.labels, components=issue.components,
            checklist=[{**item, "done": False} for item in issue.checklist],
            recurrence=issue.recurrence,
            assignee_user_id=issue.assignee_user_id, assignee_agent=issue.assignee_agent,
        )
        return await self._insert(project, actor, data)

    async def _dependency_keys(self, issue: Issue) -> list[str]:
        return sorted(
            await self.session.scalars(
                select(Issue.key)
                .join(IssueDependency, IssueDependency.depends_on_id == Issue.id)
                .where(IssueDependency.issue_id == issue.id)
            )
        )

    async def _set_dependencies(
        self, project: Project, issue: Issue, keys: Iterable[str], *, replace: bool = False
    ) -> None:
        wanted = {normalize_key(k) for k in keys}
        if issue.key in wanted:
            raise DependencyCycle(f"{issue.key} can't depend on itself")
        targets = list(
            await self.session.scalars(
                select(Issue).where(Issue.project_id == project.id, Issue.key.in_(wanted))
            )
        )
        missing = wanted - {t.key for t in targets}
        if missing:
            raise InvalidIssue(f"Unknown issues: {', '.join(sorted(missing))}")
        # A cycle exists if `issue` is reachable from any new dependency.
        edges: dict[uuid.UUID, set[uuid.UUID]] = {}
        for src, dst in await self.session.execute(
            select(IssueDependency.issue_id, IssueDependency.depends_on_id)
            .join(Issue, Issue.id == IssueDependency.issue_id)
            .where(Issue.project_id == project.id)
        ):
            if src != issue.id:  # this issue's own edges are being replaced
                edges.setdefault(src, set()).add(dst)
        stack, seen = [t.id for t in targets], set()
        while stack:
            node = stack.pop()
            if node == issue.id:
                raise DependencyCycle("That would create a dependency cycle")
            if node not in seen:
                seen.add(node)
                stack.extend(edges.get(node, ()))
        if replace:
            await self.session.execute(delete(IssueDependency).where(IssueDependency.issue_id == issue.id))
        for target in targets:
            self.session.add(IssueDependency(issue_id=issue.id, depends_on_id=target.id))

    async def _rebalance(self, project: Project) -> None:
        issues = await self.session.scalars(
            select(Issue).where(Issue.project_id == project.id).order_by(Issue.rank, Issue.number).with_for_update()
        )
        for position, issue in enumerate(issues, start=1):
            issue.rank = position * RANK_STEP
        await self.session.flush()

    def _notify_assignee(self, project: Project, issue: Issue, actor: IssueActor) -> None:
        assert issue.assignee_user_id is not None
        Notifier(self.session).assigned(
            project, issue.assignee_user_id, issue.id, issue.title, _now(),
            actor_user_id=actor.user_id, actor_agent=actor.agent_name,
        )

    def _event(
        self,
        issue: Issue,
        actor: IssueActor,
        kind: IssueEventKind,
        *,
        changes: dict[str, Any] | None = None,
        body: str | None = None,
    ) -> None:
        self.session.add(
            IssueEvent(
                workspace_id=issue.workspace_id,
                issue_id=issue.id,
                kind=kind,
                author_user_id=None if actor.agent_name else actor.user_id,
                author_agent=actor.agent_name,
                body=body,
                changes=changes or {},
                created_at=_now(),
            )
        )

    def _audit(
        self,
        project: Project,
        actor: IssueActor,
        action: str,
        issue: Issue,
        details: dict[str, Any] | None = None,
    ) -> None:
        AuditLog(self.session).record(
            workspace_id=project.workspace_id,
            project_id=project.id,
            action=action,
            target=issue.key,
            actor_type=AuthorType.AGENT if actor.agent_name else AuthorType.USER,
            actor_user_id=None if actor.agent_name else actor.user_id,
            agent=actor.agent_name,
            instructed_by_id=actor.user_id,
            approved_by_id=actor.approved_by_id,
            details=details or {},
        )
