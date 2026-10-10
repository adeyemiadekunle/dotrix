"""Reading and marking your notifications. Only projects you can still see count."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, exists, func, not_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from dotrix_backend.modules.agents.models import AgentApproval, AgentRun, ApprovalStatus
from dotrix_backend.modules.auth.models import User
from dotrix_backend.modules.coding.models import CodingRun, CodingRunStatus
from dotrix_backend.modules.issues.models import Issue
from dotrix_backend.modules.projects.models import Project
from dotrix_backend.modules.projects.repository import visible_to
from dotrix_backend.modules.workspaces.models import Membership

from .models import OPTIONAL_KINDS, Notification, NotificationKind
from .schemas import MarkRead, NotificationCounts, NotificationRead, NotificationSettings

DECISIONS = (NotificationKind.APPROVAL, NotificationKind.CHECKPOINT)


def _resolved() -> Any:
    """An approval or checkpoint is resolved once nothing from that pause waits any more (an
    agent run's changes, or a coding run waiting to start)."""
    still_waiting = exists().where(
        AgentApproval.run_id == Notification.run_id,
        AgentApproval.status == ApprovalStatus.PENDING,
        AgentApproval.created_at >= Notification.created_at,
    )
    waiting_run = aliased(CodingRun)  # (the list joins coding_runs itself)
    coding_waiting = exists().where(
        waiting_run.id == Notification.coding_run_id, waiting_run.status == CodingRunStatus.AWAITING_APPROVAL
    )
    return and_(Notification.kind.in_(DECISIONS), not_(still_waiting), not_(coding_waiting))


class NotificationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def settings(self, user: User) -> NotificationSettings:
        muted = set(user.muted_notifications or [])
        return NotificationSettings(
            **{kind.value: kind.value not in muted for kind in OPTIONAL_KINDS}, email=user.email_notifications
        )

    async def update_settings(self, user: User, data: NotificationSettings) -> NotificationSettings:
        user.muted_notifications = [kind.value for kind in OPTIONAL_KINDS if not getattr(data, kind.value)]
        user.email_notifications = data.email
        await self.session.commit()
        return await self.settings(user)

    def _mine(self, member: Membership) -> Any:
        # Kinds you turned off don't show (and don't count), here or anywhere you're a member.
        muted = select(func.unnest(User.muted_notifications)).where(User.id == member.user_id).scalar_subquery()
        return and_(
            Notification.workspace_id == member.workspace_id,
            Notification.user_id == member.user_id,
            Notification.kind.not_in(muted),
            Notification.project_id.in_(
                select(Project.id)
                .where(Project.workspace_id == member.workspace_id, visible_to(member.user_id, member.role))
                .correlate(None)
            ),
        )

    async def list(
        self,
        member: Membership,
        *,
        kind: NotificationKind | None,
        unread: bool,
        before: datetime | None,
        limit: int,
    ) -> list[NotificationRead]:
        resolved = _resolved().label("resolved")
        stmt = (
            select(Notification, Project.key, Project.name, Issue.key, AgentRun.thread_id, resolved,
                   CodingRun.session_id)
            .join(Project, Project.id == Notification.project_id)
            .outerjoin(Issue, Issue.id == Notification.issue_id)
            .outerjoin(AgentRun, AgentRun.id == Notification.run_id)
            .outerjoin(CodingRun, CodingRun.id == Notification.coding_run_id)
            .where(self._mine(member))
        )
        if kind is not None:
            stmt = stmt.where(Notification.kind == kind)
        if unread:
            stmt = stmt.where(Notification.read_at.is_(None))
        if before is not None:
            stmt = stmt.where(Notification.created_at < before)
        rows = await self.session.execute(
            stmt.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(limit)
        )
        return [
            NotificationRead(
                id=n.id,
                kind=n.kind,
                created_at=n.created_at,
                read=n.read_at is not None,
                resolved=bool(is_resolved),
                project_id=n.project_id,
                project_key=project_key,
                project_name=project_name,
                actor_user_id=n.actor_user_id,
                actor_agent=n.actor_agent,
                title=n.title,
                count=n.count,
                excerpt=n.excerpt,
                run_id=n.run_id,
                thread_id=thread_id,
                issue_key=issue_key,
                coding_run_id=n.coding_run_id,
                coding_session_id=coding_session_id,
            )
            for n, project_key, project_name, issue_key, thread_id, is_resolved, coding_session_id in rows
        ]

    async def counts(self, member: Membership) -> NotificationCounts:
        """What still needs you: approvals and checkpoints until they're decided (opening one
        doesn't make it any less waiting), everything else until it's read."""
        needs_you = or_(
            and_(Notification.kind.in_(DECISIONS), not_(_resolved())),
            and_(Notification.kind.not_in(DECISIONS), Notification.read_at.is_(None)),
        )
        rows = await self.session.execute(
            select(Notification.kind, func.count()).where(self._mine(member), needs_you).group_by(Notification.kind)
        )
        by_kind = {kind: 0 for kind in NotificationKind} | {kind: n for kind, n in rows.all()}
        return NotificationCounts(unread=sum(by_kind.values()), by_kind=by_kind)

    async def mark_read(self, member: Membership, data: MarkRead) -> NotificationCounts:
        stmt = update(Notification).where(
            Notification.workspace_id == member.workspace_id,
            Notification.user_id == member.user_id,
            Notification.read_at.is_(None),
        )
        if not data.all:
            stmt = stmt.where(Notification.id.in_(data.ids))
        if data.kind is not None:
            stmt = stmt.where(Notification.kind == data.kind)
        await self.session.execute(stmt.values(read_at=datetime.now(UTC)))
        await self.session.commit()
        return await self.counts(member)
