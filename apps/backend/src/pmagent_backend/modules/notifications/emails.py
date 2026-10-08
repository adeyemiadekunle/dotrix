"""Notifications by email: as they happen (each minute, one email per person per batch, so a
run's changes come as one) or as a daily digest at 08:00 UTC, as each person chooses
(Settings → Notifications). Only to verified addresses, never for what was already read or
decided, kinds they turned off, or projects they can no longer see.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, exists, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from pmagent_backend.core.email import EmailSender
from pmagent_backend.core.email_templates import EmailContent, render
from pmagent_backend.modules.agents.models import AgentApproval, ApprovalStatus
from pmagent_backend.modules.auth.models import User
from pmagent_backend.modules.coding.models import CodingRun, CodingRunStatus
from pmagent_backend.modules.projects.models import Project
from pmagent_backend.modules.projects.repository import visible_to
from pmagent_backend.modules.workspaces.models import Membership, Workspace

from .models import Notification, NotificationKind

logger = logging.getLogger(__name__)

BATCH_WAIT = timedelta(minutes=1)  # wait this long, so what one run does arrives as one email
DIGEST_HOUR = 8  # UTC
MAX_LINES = 12
DECISIONS = (NotificationKind.APPROVAL, NotificationKind.CHECKPOINT)


@dataclass(frozen=True)
class Item:
    notification: Notification
    workspace_slug: str
    project_key: str


def _line(n: Notification, project_key: str, actor: str | None) -> str:
    who = actor or (f"The {n.actor_agent} agent" if n.actor_agent else "Someone")
    plural = "s" if n.count != 1 else ""
    text = {
        NotificationKind.APPROVAL: f"{n.count} change{plural} {'wait' if plural else 'waits'} for your decision: {n.title}",
        NotificationKind.CHECKPOINT: f"A plan waits for you to go on: {n.title}",
        NotificationKind.ASSIGNED: f"{who} assigned you {n.title}",
        NotificationKind.FINDING: f"{n.count} finding{plural} to look at: {n.title}",
        NotificationKind.MENTION: f"{who} mentioned you: {n.excerpt or n.title}",
        NotificationKind.DECIDED: f"{who} decided your agent's changes ({n.title})"
        + (f'. Why: "{n.excerpt}"' if n.excerpt else ""),
        NotificationKind.WATCHING: f"{who} on {n.title}" + (f': "{n.excerpt}"' if n.excerpt else ""),
    }[n.kind]
    return f"{project_key} · {text}"


def _content(items: list[Item], names: dict[uuid.UUID, str], app_url: str, *, digest: bool) -> EmailContent:
    first = items[0]
    lines = [_line(i.notification, i.project_key, names.get(i.notification.actor_user_id or uuid.UUID(int=0)))
             for i in items[:MAX_LINES]]
    if len(items) > MAX_LINES:
        lines.append(f"…and {len(items) - MAX_LINES} more.")
    waiting = sum(i.notification.kind in DECISIONS for i in items)
    if digest:
        subject = f"Your day in dotrix: {len(items)} notification{'s' * (len(items) != 1)}"
    elif len(items) == 1:
        subject = lines[0].split(" · ", 1)[1][:120]
    else:
        subject = f"{len(items)} things in dotrix" + (f", {waiting} waiting for you" if waiting else "")
    link = f"{app_url.rstrip('/')}/w/{first.workspace_slug}/approvals"
    if len(items) == 1:
        link += f"?n={first.notification.id}"
    return EmailContent(
        subject=subject,
        heading="Waiting for your decision" if waiting and waiting == len(items) else ("Today in dotrix" if digest else "What's new"),
        paragraphs=lines,
        action_label="Open notifications",
        action_url=link,
        note=(
            "A daily digest of what you haven't read. " if digest else "Sent as things happen, a minute apart at most. "
        ) + "Choose immediately, daily, or off in Settings → Notifications.",
    )


class NotificationEmails:
    def __init__(self, session: AsyncSession, sender: EmailSender, app_url: str) -> None:
        self.session = session
        self.sender = sender
        self.app_url = app_url

    async def send_due(self, now: datetime | None = None) -> dict[str, int]:
        """Email what's new to people who want it as it happens; mark everything handled."""
        now = now or datetime.now(UTC)
        rows = list((await self.session.execute(
            select(Notification, User, Workspace.slug, Project.key)
            .join(User, User.id == Notification.user_id)
            .join(Workspace, Workspace.id == Notification.workspace_id)
            .join(Project, Project.id == Notification.project_id)
            .where(Notification.emailed_at.is_(None), Notification.created_at <= now - BATCH_WAIT)
            .order_by(Notification.created_at)
            .limit(1000)
            .with_for_update(of=Notification, skip_locked=True)
        )).all())
        by_user: dict[uuid.UUID, tuple[User, list[Item]]] = {}
        for n, user, slug, key in rows:
            by_user.setdefault(user.id, (user, []))[1].append(Item(n, slug, key))
        sent = 0
        for user, items in by_user.values():
            wanted = await self._wanted(user, items) if user.email_notifications == "immediately" else []
            if wanted:
                sent += await self._send(user, wanted, digest=False)
        if rows:
            await self.session.execute(
                update(Notification).where(Notification.id.in_([n.id for n, *_ in rows])).values(emailed_at=now)
            )
        await self.session.commit()
        return {"handled": len(rows), "emails": sent}

    async def send_digests(self, now: datetime | None = None) -> int:
        """Once a day from 08:00 UTC, each daily-digest person's unread notifications since the last."""
        now = now or datetime.now(UTC)
        today = now.replace(hour=DIGEST_HOUR, minute=0, second=0, microsecond=0)
        if now < today:
            return 0
        users = list(await self.session.scalars(
            select(User).where(
                User.email_notifications == "daily",
                User.email_verified_at.is_not(None),
                or_(User.digest_sent_at.is_(None), User.digest_sent_at < today),
            ).with_for_update(skip_locked=True)
        ))
        sent = 0
        for user in users:
            since = user.digest_sent_at or now - timedelta(days=1)
            rows = (await self.session.execute(
                select(Notification, Workspace.slug, Project.key)
                .join(Workspace, Workspace.id == Notification.workspace_id)
                .join(Project, Project.id == Notification.project_id)
                .where(Notification.user_id == user.id, Notification.read_at.is_(None), Notification.created_at > since)
                .order_by(Notification.created_at)
            )).all()
            wanted = await self._wanted(user, [Item(n, slug, key) for n, slug, key in rows])
            if wanted:
                sent += await self._send(user, wanted, digest=True)
            user.digest_sent_at = now
        await self.session.commit()
        return sent

    async def _wanted(self, user: User, items: list[Item]) -> list[Item]:
        """What's still worth telling them: verified address, not read or decided, a kind they
        get, and a project they can still see."""
        if not user.is_active or user.email_verified_at is None:
            return []
        muted = set(user.muted_notifications or [])
        out = []
        visible: dict[uuid.UUID, bool] = {}
        for item in items:
            n = item.notification
            if n.read_at is not None or n.kind.value in muted:
                continue
            if n.kind in DECISIONS and not await self._still_waiting(n):
                continue
            if n.project_id not in visible:
                visible[n.project_id] = await self._can_see(user.id, n.workspace_id, n.project_id)
            if visible[n.project_id]:
                out.append(item)
        return out

    async def _still_waiting(self, n: Notification) -> bool:
        if n.coding_run_id is not None:
            return await self.session.scalar(
                select(CodingRun.status).where(CodingRun.id == n.coding_run_id)
            ) is CodingRunStatus.AWAITING_APPROVAL
        return bool(await self.session.scalar(select(exists().where(and_(
            AgentApproval.run_id == n.run_id, AgentApproval.status == ApprovalStatus.PENDING,
            AgentApproval.created_at >= n.created_at,
        )))))

    async def _can_see(self, user_id: uuid.UUID, workspace_id: uuid.UUID, project_id: uuid.UUID) -> bool:
        member = await self.session.scalar(
            select(Membership).where(Membership.workspace_id == workspace_id, Membership.user_id == user_id)
        )
        if member is None:
            return False
        return await self.session.scalar(
            select(Project.id).where(Project.id == project_id, visible_to(user_id, member.role))
        ) is not None

    async def _send(self, user: User, items: list[Item], *, digest: bool) -> int:
        actors = {i.notification.actor_user_id for i in items if i.notification.actor_user_id}
        names = dict((await self.session.execute(select(User.id, User.display_name).where(User.id.in_(actors)))).all()) if actors else {}
        try:
            await self.sender.send(render(user.email, _content(items, names, self.app_url, digest=digest)))
        except Exception:  # one person's failed email doesn't stop everyone else's
            logger.exception("notification email to user %s failed", user.id)
            return 0
        return 1

