"""Emails to the operators when the deployment needs attention, and again when it clears.

The conditions are read from the same health the admin console shows (`PlatformObserve.health`). A
condition is opened on the first check that finds it and emailed on the second, so a blip pages no one;
one email per check lists what started and what cleared. Summaries carry counts only: never a workspace's
name, an error message, or anything people wrote."""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from dotrix_backend.core.email import EmailMessage
from dotrix_backend.core.jobs import JobContext
from dotrix_backend.core.settings import Settings

from .models import AdminAlert, AdminUser
from .platform import PlatformObserve
from .schemas import AdminAlertRead, AdminAlerts, PlatformHealth

logger = logging.getLogger(__name__)

# Thresholds: tune them here after watching real traffic.
STUCK_LAPSED_FOR = timedelta(minutes=10)  # the sweep should recover a run within about two
QUEUE_STALLED_SECONDS = 600
FAILURE_RATE_MIN_RUNS = 10
FAILURE_RATE_ABOVE = 0.5
EMAILS_WAITING_SECONDS = 3600
RESOLVED_SHOWN = timedelta(hours=24)

DEPENDENCY_NAMES = {"redis": "Redis", "storage": "File storage", "email": "Email", "github": "The GitHub App"}


def conditions(health: PlatformHealth, now: datetime) -> dict[str, str]:
    """Every condition that holds now, as {key: summary}."""
    found: dict[str, str] = {}
    for dep in health.dependencies:
        if dep.id != "workers" and dep.state == "down":  # workers have a condition of their own
            found[f"dependency:{dep.id}"] = f"{DEPENDENCY_NAMES.get(dep.id, dep.id)} is down"
    if health.jobs == "worker" and health.workers_alive == 0:
        found["workers"] = "No worker has checked in recently"
    lapsed = [s for s in health.stuck if s.lease_expired_at is not None and now - s.lease_expired_at > STUCK_LAPSED_FOR]
    if lapsed:
        found["stuck_runs"] = f"{len(lapsed)} run{'s' if len(lapsed) != 1 else ''} stuck for more than 10 minutes"
    if health.queue_pending > 0 and (health.queue_oldest_seconds or 0) > QUEUE_STALLED_SECONDS:
        found["queue_stalled"] = (
            f"{health.queue_pending} queued dispatch{'es' if health.queue_pending != 1 else ''}, "
            f"the oldest waiting {round((health.queue_oldest_seconds or 0) / 60)} minutes"
        )
    if health.recovery_required > 0:
        found["recovery_required"] = f"{health.recovery_required} coding turn{'s' if health.recovery_required != 1 else ''} waiting to be recovered"
    if health.finished_24h >= FAILURE_RATE_MIN_RUNS and health.failed_24h > health.finished_24h * FAILURE_RATE_ABOVE:
        found["failure_rate"] = f"{health.failed_24h} of {health.finished_24h} runs failed in the last 24 hours"
    if health.notification_emails_waiting > 0 and (health.notification_email_oldest_seconds or 0) > EMAILS_WAITING_SECONDS:
        found["emails_waiting"] = (
            f"{health.notification_emails_waiting} notification email{'s' if health.notification_emails_waiting != 1 else ''} "
            f"unsent for over an hour"
        )
    return found


async def recipients(session: AsyncSession, settings: Settings) -> list[str]:
    if settings.alert_emails:
        return list(dict.fromkeys(settings.alert_emails))
    rows = await session.scalars(
        select(AdminUser.email).where(AdminUser.role == "owner", AdminUser.disabled_at.is_(None)).order_by(AdminUser.email)
    )
    return list(rows)


def _message(to: str, opened: list[AdminAlert], cleared: list[AdminAlert], admin_url: str | None) -> EmailMessage:
    parts = []
    if opened:
        parts.append(f"{len(opened)} need{'s' if len(opened) == 1 else ''} attention")
    if cleared:
        parts.append(f"{len(cleared)} cleared")
    lines = []
    if opened:
        lines += ["Needs attention:", *(f"- {a.summary}" for a in opened), ""]
    if cleared:
        lines += ["Cleared:", *(f"- {a.summary}" for a in cleared), ""]
    if admin_url:
        lines.append(f"Admin console: {admin_url.rstrip('/')}")
    return EmailMessage(to=to, subject=f"dotrix: {', '.join(parts)}", body="\n".join(lines).strip() + "\n")


async def evaluate(ctx: JobContext, redis: Any = None, now: datetime | None = None) -> dict[str, int]:
    """One check: open, refresh and resolve alert rows from the current health, then send one email
    listing what started (on its second check) and what cleared. A failed send leaves the rows
    unnotified, so the next check tries again."""
    now = now or datetime.now(UTC)
    state = SimpleNamespace(redis=redis, storage=ctx.storage)
    async with ctx.session_factory() as session:
        health = await PlatformObserve(session, ctx.settings).health("", state)
        holding = conditions(health, now)
        open_rows = {a.key: a for a in await session.scalars(select(AdminAlert).where(AdminAlert.resolved_at.is_(None)))}
        for key, summary in holding.items():
            row = open_rows.get(key)
            if row is None:
                session.add(AdminAlert(key=key, summary=summary, opened_at=now, last_seen_at=now))
            else:
                row.summary, row.last_seen_at = summary, now
        for key, row in open_rows.items():
            if key not in holding:
                row.resolved_at = now
        await session.flush()

        opened = [a for k, a in open_rows.items() if k in holding and a.notified_at is None]  # held on two checks
        cleared = list(
            await session.scalars(
                select(AdminAlert)
                .where(
                    AdminAlert.resolved_at.is_not(None),
                    AdminAlert.resolved_at > now - RESOLVED_SHOWN,
                    AdminAlert.notified_at.is_not(None),
                    AdminAlert.clear_notified_at.is_(None),
                )
                .order_by(AdminAlert.opened_at)
            )
        )
        sent = 0
        if opened or cleared:
            for to in await recipients(session, ctx.settings):
                try:
                    await ctx.email.send(_message(to, opened, cleared, ctx.settings.admin_url))
                    sent += 1
                except Exception as exc:  # a provider outage must not fail the job in a loop
                    logger.error("operator alert email not sent: %s", type(exc).__name__)
            if sent or not await recipients(session, ctx.settings):
                for alert in opened:
                    alert.notified_at = now
                for alert in cleared:
                    alert.clear_notified_at = now
        await session.commit()
    return {"open": len(holding), "opened": len(opened), "cleared": len(cleared), "emails": sent}


async def listing(session: AsyncSession) -> AdminAlerts:
    """Open alerts, and those cleared in the last 24 hours."""
    since = datetime.now(UTC) - RESOLVED_SHOWN
    rows = list(
        await session.scalars(
            select(AdminAlert).where(or_(AdminAlert.resolved_at.is_(None), AdminAlert.resolved_at > since)).order_by(AdminAlert.opened_at.desc())
        )
    )

    def read(a: AdminAlert) -> AdminAlertRead:
        return AdminAlertRead(
            key=a.key, summary=a.summary, opened_at=a.opened_at, resolved_at=a.resolved_at, notified=a.notified_at is not None
        )

    return AdminAlerts(
        open=[read(a) for a in rows if a.resolved_at is None],
        resolved=[read(a) for a in sorted((a for a in rows if a.resolved_at is not None), key=lambda a: a.resolved_at, reverse=True)],  # type: ignore[arg-type, return-value]
    )
