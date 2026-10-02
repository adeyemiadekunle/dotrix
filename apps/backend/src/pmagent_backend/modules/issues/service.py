"""Issue rules (FR-29, FR-30, FR-32).

- Keys come from a per-project counter taken under a row lock: never reused.
- Parent rules follow the PRD hierarchy; dependencies can't form a cycle.
- Coding tools (`as_agent`) may only work on issues assigned to them: comment,
  add sub-tasks, and move their issue as far as `review`. Only a person closes.
- `claim` is atomic (`FOR UPDATE SKIP LOCKED`): two agents never get the same issue.
"""
from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import and_, case, delete, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from uuid_utils.compat import uuid7

from pmagent_backend.core.errors import Conflict, Forbidden, NotFound, Unprocessable
from pmagent_backend.modules.audit.service import AuditLog
from pmagent_backend.modules.knowledge.models import AuthorType
from pmagent_backend.modules.notifications.notify import Notifier
from pmagent_backend.modules.projects.models import Project
from pmagent_backend.modules.projects.repository import ProjectRepository, visible_to
from pmagent_backend.modules.workspaces.models import Membership
from pmagent_backend.modules.workspaces.permissions import Permission, can
from pmagent_engine.contracts import AgentPolicy

from .models import (
    DESCRIPTION_REQUIRED,
    PARENT_REQUIRED,
    PARENT_TYPES,
    PRIORITY_ORDER,
    AgentAssignee,
    Issue,
    IssueDependency,
    IssueEvent,
    IssueEventKind,
    IssueStatus,
    IssueType,
    IssueWatcher,
)
from .schemas import (
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
            rank=(max_rank or 0.0) + RANK_STEP,
            created_at=now,
            updated_at=now,
            resolved_at=now if data.status is IssueStatus.DONE else None,
        )
        if data.assignee_user_id is not None:
            await self._check_member(project, data.assignee_user_id)
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
        await self.session.commit()
        return await self.get(project, issue.key)

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
        return IssueRead.model_validate(issue).model_copy(
            update={
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
    ) -> list[IssueSummary]:
        stmt = self._summary_query(project, types, statuses, assignee, label)
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
        rows = await self.session.execute(stmt.order_by(*ordering, Issue.number).limit(limit).offset(offset))
        return [self._summary(issue, parent_key) for issue, parent_key in rows]

    async def across_projects(
        self,
        member: Membership,
        *,
        types: Sequence[IssueType] = (),
        statuses: Sequence[IssueStatus] = (),
        assignee: str | None = None,
        reporter: str | None = None,
        watching: bool = False,
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
        stmt = self._filtered(stmt, types, statuses, me if assignee == "me" else assignee, label)
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
        if due_before is not None:
            stmt = stmt.where(Issue.due <= due_before)
        ordering = {
            "due": (Issue.due.asc().nulls_last(), priority_rank(), Issue.created_at),
            "priority": (priority_rank(), Issue.due.asc().nulls_last(), Issue.created_at),
            "created": (Issue.created_at.desc(),),
            "updated": (Issue.updated_at.desc(),),
        }[order]
        rows = await self.session.execute(stmt.order_by(*ordering, Issue.id).limit(limit).offset(offset))
        return [
            WorkspaceIssue.model_validate(
                self._summary(issue, parent_key).model_dump()
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
        stmt = self._summary_query(project, types, (), assignee, label)
        if epic is not None:
            epic_issue = await self._by_key(project, epic)
            stmt = stmt.where(Issue.parent_id == epic_issue.id)
        rows = await self.session.execute(stmt.order_by(Issue.rank, Issue.number))
        columns: dict[IssueStatus, list[IssueSummary]] = {status: [] for status in IssueStatus}
        for issue, parent_key in rows:
            columns[issue.status].append(self._summary(issue, parent_key))
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
            elif data.status is not IssueStatus.DONE:
                issue.resolved_at = None

        if "depends_on" in sent:
            old_keys = await self._dependency_keys(issue)
            new_keys = sorted({normalize_key(k) for k in data.depends_on or []})
            if old_keys != new_keys:
                await self._set_dependencies(project, issue, new_keys, replace=True)
                changes["depends_on"] = [old_keys, new_keys]

        if changes.get("assignee_user_id") and issue.assignee_user_id is not None:
            self._notify_assignee(project, issue, actor)
        if changes or note:
            issue.updated_at = _now()
            self._event(issue, actor, IssueEventKind.UPDATED, changes=changes, body=note)
            self._audit(project, actor, "issue.update", issue, {"fields": sorted(changes)})
            await self.session.commit()
        return await self.get(project, issue.key)

    async def comment(self, project: Project, key: str, actor: IssueActor, data: CommentCreate) -> IssueRead:
        issue = await self._by_key(project, key)
        if actor.agent is not None:
            self._check_agent_owns(actor, issue)
        issue.updated_at = _now()
        self._event(issue, actor, IssueEventKind.COMMENTED, body=data.body)
        if data.mentions:
            await Notifier(self.session).mentioned(
                project, data.mentions, data.body, issue.updated_at, title=issue.title,
                actor_user_id=actor.user_id, issue_id=issue.id,
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
    def _summary(issue: Issue, parent_key: str | None) -> IssueSummary:
        return IssueSummary.model_validate(issue).model_copy(update={"parent_key": parent_key})

    def _ready_query(self, project: Project, mine: Any) -> Any:
        unassigned = and_(Issue.assignee_user_id.is_(None), Issue.assignee_agent.is_(None))
        return (
            select(Issue)
            .where(
                Issue.project_id == project.id,
                Issue.status == IssueStatus.TODO,
                Issue.type != IssueType.EPIC,  # epics are containers, not work
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
