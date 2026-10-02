"""Writing notifications. Callers add them inside their own unit of work and commit it."""
from __future__ import annotations

import re
import uuid
from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from pmagent_backend.modules.auth.models import User
from pmagent_backend.modules.projects.models import Project
from pmagent_backend.modules.projects.repository import visible_to
from pmagent_backend.modules.workspaces.models import Membership
from pmagent_backend.modules.workspaces.permissions import Permission, can

from .models import Notification, NotificationKind

TITLE_CHARS = 300
EXCERPT_CHARS = 300
MAX_MENTIONS = 20


def _excerpt(text: str) -> str:
    """The start of what was said, on one line."""
    flat = " ".join(text.split())
    return flat if len(flat) <= EXCERPT_CHARS else flat[: EXCERPT_CHARS - 1].rstrip() + "…"


def _names(text: str, name: str) -> bool:
    """Whether the text @mentions this name (not as the start of a longer word)."""
    return re.search(rf"@{re.escape(name)}(?![\w])", text, flags=re.IGNORECASE) is not None


class Notifier:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def approvals_waiting(
        self, project: Project, run_id: uuid.UUID, title: str, count: int, at: datetime, agent: str | None
    ) -> None:
        """A run paused on changes: everyone who may approve them and can see the project."""
        for user_id in await self._approvers(project):
            self._add(project, user_id, NotificationKind.APPROVAL, at, run_id=run_id, title=title,
                      count=count, actor_agent=agent)

    def checkpoint(
        self, project: Project, requester_id: uuid.UUID, run_id: uuid.UUID, title: str, at: datetime, agent: str | None
    ) -> None:
        """An agent wants whoever asked to confirm or change its plan."""
        self._add(project, requester_id, NotificationKind.CHECKPOINT, at, run_id=run_id, title=title, actor_agent=agent)

    def findings(
        self, project: Project, requester_id: uuid.UUID, run_id: uuid.UUID, title: str, count: int, at: datetime,
        agent: str | None,
    ) -> None:
        """A run finished with findings for whoever asked."""
        self._add(project, requester_id, NotificationKind.FINDING, at, run_id=run_id, title=title, count=count,
                  actor_agent=agent)

    def assigned(
        self, project: Project, assignee_id: uuid.UUID, issue_id: uuid.UUID, title: str, at: datetime, *,
        actor_user_id: uuid.UUID | None, actor_agent: str | None,
    ) -> None:
        """An issue was assigned to someone. Not when people assign themselves."""
        if actor_agent is None and actor_user_id == assignee_id:
            return
        self._add(project, assignee_id, NotificationKind.ASSIGNED, at, issue_id=issue_id, title=title,
                  actor_user_id=actor_user_id, actor_agent=actor_agent)

    async def mentioned(
        self, project: Project, user_ids: Iterable[uuid.UUID], text: str, at: datetime, *, title: str,
        actor_user_id: uuid.UUID, issue_id: uuid.UUID | None = None, run_id: uuid.UUID | None = None,
    ) -> list[uuid.UUID]:
        """People @mentioned in a comment or a chat message. Each must be named in the text
        ("@Ada Lovelace") and able to see the project; mentioning yourself isn't news. Returns who
        was notified."""
        wanted = list(dict.fromkeys(u for u in user_ids if u != actor_user_id))[:MAX_MENTIONS]
        if not wanted:
            return []
        rows = await self.session.execute(
            select(Membership, User.display_name)
            .join(User, User.id == Membership.user_id)
            .where(Membership.workspace_id == project.workspace_id, Membership.user_id.in_(wanted))
        )
        notified = []
        for member, name in rows.all():
            seen = await self.session.scalar(
                select(Project.id).where(Project.id == project.id, visible_to(member.user_id, member.role))
            )
            if seen is None or not _names(text, name):
                continue
            self._add(project, member.user_id, NotificationKind.MENTION, at, title=title, issue_id=issue_id,
                      run_id=run_id, actor_user_id=actor_user_id, excerpt=_excerpt(text))
            notified.append(member.user_id)
        return notified

    async def _approvers(self, project: Project) -> list[uuid.UUID]:
        members = await self.session.scalars(
            select(Membership)
            .options(selectinload(Membership.workspace))
            .where(Membership.workspace_id == project.workspace_id)
        )
        candidates = [m for m in members if can(m, Permission.APPROVE_ACTIONS)]
        visible = []
        for member in candidates:
            seen = await self.session.scalar(
                select(Project.id).where(Project.id == project.id, visible_to(member.user_id, member.role))
            )
            if seen is not None:
                visible.append(member.user_id)
        return visible

    def _add(
        self, project: Project, user_id: uuid.UUID, kind: NotificationKind, at: datetime, *, title: str,
        count: int = 1, run_id: uuid.UUID | None = None, issue_id: uuid.UUID | None = None,
        actor_user_id: uuid.UUID | None = None, actor_agent: str | None = None, excerpt: str | None = None,
    ) -> None:
        self.session.add(
            Notification(
                workspace_id=project.workspace_id,
                project_id=project.id,
                user_id=user_id,
                kind=kind,
                run_id=run_id,
                issue_id=issue_id,
                actor_user_id=actor_user_id,
                actor_agent=actor_agent,
                title=title[:TITLE_CHARS],
                excerpt=excerpt,
                count=count,
                created_at=at,
            )
        )
