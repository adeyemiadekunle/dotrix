"""Platform observability for the admin console (apps/admin): the deployment's health, trends,
failures, coding, and workspaces. Reads only, from the modules' own tables.

The console is for whoever operates dotrix, not a workspace's people, so it reads every workspace,
but never what people wrote: no conversation titles or messages, briefs, diffs, or documents. Runs
are named by their workspace, project and issue key; failures by the error the platform recorded."""
from __future__ import annotations

import time
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import Date, case, cast, func, literal_column, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from dotrix_backend.core.settings import Settings
from dotrix_backend.modules.agents.models import ACTIVE_STATUSES, AgentRun, RunStatus
from dotrix_backend.modules.audit.models import AuditEvent
from dotrix_backend.modules.auth.models import User
from dotrix_backend.modules.coding.models import ACTIVE as CODING_ACTIVE
from dotrix_backend.modules.coding.models import (
    CodingRun,
    CodingRunner,
    CodingRunStatus,
    CodingSession,
    CodingSessionState,
)
from dotrix_backend.modules.documents.models import Document
from dotrix_backend.modules.execution.models import RunDispatch
from dotrix_backend.modules.projects.models import Project
from dotrix_backend.modules.workspaces.models import Membership, Workspace

from .schemas import (
    CodingBreakdown,
    DayStats,
    FailureGroup,
    FailureReport,
    PlatformAuditEvent,
    PlatformCounts,
    PlatformHealth,
    StuckRun,
    WorkspaceUsage,
)

RUNNER_ONLINE = timedelta(minutes=2)
# A literal, not a bound parameter: GROUP BY must repeat the SELECT's expression exactly.
UTC_NAME = literal_column("'UTC'")
CODING_FAILED = (CodingRunStatus.FAILED, CodingRunStatus.RECOVERY_REQUIRED)
# Coding turns that finished their work (the rest were stopped, rejected, or are still going).
CODING_DONE = (CodingRunStatus.PR_OPENED, CodingRunStatus.NO_CHANGES, CodingRunStatus.CHANGES_READY)


def _error_line(error: str | None) -> str:
    """The first line of a recorded error, short: enough to group the same failure together."""
    line = (error or "").strip().splitlines()[0] if (error or "").strip() else "(no message)"
    return line[:160]


class PlatformObserve:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    async def _scalar(self, stmt) -> Any:
        return (await self.session.execute(stmt)).scalar() or 0

    async def health(self, version: str) -> PlatformHealth:
        """Is the deployment working: the database, the run queue, workers, leases, sandboxes."""
        now = datetime.now(UTC)
        day = now - timedelta(days=1)
        started = time.perf_counter()
        await self.session.execute(text("SELECT 1"))
        database_ms = round((time.perf_counter() - started) * 1000, 1)

        open_dispatch = (RunDispatch.accepted_at.is_(None), RunDispatch.discarded_at.is_(None))
        oldest = await self.session.scalar(select(func.min(RunDispatch.created_at)).where(*open_dispatch))
        last_taken = await self.session.scalar(select(func.max(RunDispatch.accepted_at)))

        stuck_rows: list[StuckRun] = []
        chat_stuck = await self.session.execute(
            select(AgentRun.id, AgentRun.status, AgentRun.lease_expires_at, Workspace.slug)
            .join(Workspace, Workspace.id == AgentRun.workspace_id)
            .where(AgentRun.status.in_(ACTIVE_STATUSES), AgentRun.lease_expires_at < now)
            .order_by(AgentRun.lease_expires_at)
            .limit(20)
        )
        for run_id, status, lapsed, slug in chat_stuck:
            stuck_rows.append(StuckRun(kind="chat", id=run_id, status=status.value, workspace=slug, lease_expired_at=lapsed))
        coding_stuck = await self.session.execute(
            select(CodingRun.id, CodingRun.status, CodingRun.lease_expires_at, Workspace.slug, CodingRun.issue_key)
            .join(Workspace, Workspace.id == CodingRun.workspace_id)
            .where(CodingRun.status.in_(CODING_ACTIVE), CodingRun.lease_expires_at < now)
            .order_by(CodingRun.lease_expires_at)
            .limit(20)
        )
        for run_id, status, lapsed, slug, key in coding_stuck:
            stuck_rows.append(
                StuckRun(kind="coding", id=run_id, status=status.value, workspace=slug, label=key, lease_expired_at=lapsed)
            )

        sessions = dict(
            (state, count)
            for state, count in await self.session.execute(
                select(CodingSession.state, func.count(CodingSession.id)).group_by(CodingSession.state)
            )
        )
        asleep = await self._scalar(select(func.count(CodingSession.id)).where(CodingSession.sandbox_handle.is_not(None)))
        runners_online = await self._scalar(
            select(func.count(CodingRunner.id)).where(
                CodingRunner.revoked_at.is_(None), CodingRunner.last_seen_at >= now - RUNNER_ONLINE
            )
        )
        runners = await self._scalar(select(func.count(CodingRunner.id)).where(CodingRunner.revoked_at.is_(None)))

        return PlatformHealth(
            generated_at=now,
            version=version,
            environment=self.settings.env,
            jobs=self.settings.jobs,
            sandbox=self.settings.coding_sandbox,
            database_ms=database_ms,
            queue_pending=await self._scalar(select(func.count(RunDispatch.id)).where(*open_dispatch)),
            queue_oldest_seconds=(now - oldest).total_seconds() if oldest is not None else None,
            queue_discarded_24h=await self._scalar(
                select(func.count(RunDispatch.id)).where(RunDispatch.discarded_at >= day)
            ),
            worker_last_took_at=last_taken,
            runs_running=await self._scalar(
                select(func.count(AgentRun.id)).where(AgentRun.status == RunStatus.RUNNING)
            )
            + await self._scalar(
                select(func.count(CodingRun.id)).where(CodingRun.status == CodingRunStatus.RUNNING)
            ),
            runs_queued=await self._scalar(select(func.count(AgentRun.id)).where(AgentRun.status == RunStatus.QUEUED))
            + await self._scalar(
                select(func.count(CodingRun.id)).where(CodingRun.status == CodingRunStatus.QUEUED)
            ),
            stuck=stuck_rows,
            recovery_required=await self._scalar(
                select(func.count(CodingRun.id)).where(CodingRun.status == CodingRunStatus.RECOVERY_REQUIRED)
            ),
            interrupted=await self._scalar(
                select(func.count(AgentRun.id)).where(
                    AgentRun.status == RunStatus.FAILED, AgentRun.error_kind == "interrupted"
                )
            ),
            sandboxes_warm=int(sessions.get(CodingSessionState.WARM, 0)),
            sandboxes_asleep=int(asleep),
            runners_online=int(runners_online),
            runners=int(runners),
            failed_24h=await self._scalar(
                select(func.count(AgentRun.id)).where(AgentRun.status == RunStatus.FAILED, AgentRun.finished_at >= day)
            )
            + await self._scalar(
                select(func.count(CodingRun.id)).where(CodingRun.status.in_(CODING_FAILED), CodingRun.finished_at >= day)
            ),
            finished_24h=await self._scalar(
                select(func.count(AgentRun.id)).where(AgentRun.finished_at >= day)
            )
            + await self._scalar(select(func.count(CodingRun.id)).where(CodingRun.finished_at >= day)),
        )

    async def counts(self, days: int = 7) -> PlatformCounts:
        """How big the deployment is, and how much of it was used lately."""
        since = datetime.now(UTC) - timedelta(days=days)
        active = (
            select(AgentRun.requested_by_id.label("uid")).where(AgentRun.created_at >= since)
            .union(select(CodingRun.requested_by_id.label("uid")).where(CodingRun.created_at >= since))
            .subquery()
        )
        active_ws = (
            select(AgentRun.workspace_id.label("wid")).where(AgentRun.created_at >= since)
            .union(select(CodingRun.workspace_id.label("wid")).where(CodingRun.created_at >= since))
            .subquery()
        )
        return PlatformCounts(
            days=days,
            workspaces=await self._scalar(select(func.count(Workspace.id))),
            workspaces_new=await self._scalar(select(func.count(Workspace.id)).where(Workspace.created_at >= since)),
            workspaces_active=await self._scalar(select(func.count()).select_from(active_ws)),
            people=await self._scalar(select(func.count(User.id))),
            people_new=await self._scalar(select(func.count(User.id)).where(User.created_at >= since)),
            people_active=await self._scalar(
                select(func.count()).select_from(active).where(active.c.uid.is_not(None))
            ),
            projects=await self._scalar(select(func.count(Project.id))),
            documents=await self._scalar(select(func.count(Document.id))),
            document_bytes=await self._scalar(select(func.coalesce(func.sum(Document.size), 0))),
        )

    async def trends(self, days: int = 14) -> list[DayStats]:
        """Each of the last `days` days (UTC): runs started, how they ended, tokens and coding cost."""
        today = datetime.now(UTC).date()
        start = today - timedelta(days=days - 1)
        since = datetime.combine(start, datetime.min.time(), tzinfo=UTC)
        out: dict[date, DayStats] = {
            start + timedelta(days=i): DayStats(day=start + timedelta(days=i)) for i in range(days)
        }

        chat_day = cast(func.timezone(UTC_NAME, AgentRun.created_at), Date)
        for day, started, failed, tin, tout in await self.session.execute(
            select(
                chat_day,
                func.count(AgentRun.id),
                func.count(case((AgentRun.status == RunStatus.FAILED, 1))),
                func.coalesce(func.sum(AgentRun.input_tokens), 0),
                func.coalesce(func.sum(AgentRun.output_tokens), 0),
            )
            .where(AgentRun.created_at >= since)
            .group_by(chat_day)
        ):
            if day in out:
                d = out[day]
                d.chat_runs, d.chat_failed = int(started), int(failed)
                d.input_tokens += int(tin)
                d.output_tokens += int(tout)

        coding_day = cast(func.timezone(UTC_NAME, CodingRun.created_at), Date)
        for day, started, failed, tin, tout, cost in await self.session.execute(
            select(
                coding_day,
                func.count(CodingRun.id),
                func.count(case((CodingRun.status.in_(CODING_FAILED), 1))),
                func.coalesce(func.sum(CodingRun.input_tokens), 0),
                func.coalesce(func.sum(CodingRun.output_tokens), 0),
                func.coalesce(func.sum(CodingRun.cost_usd), 0),
            )
            .where(CodingRun.created_at >= since)
            .group_by(coding_day)
        ):
            if day in out:
                d = out[day]
                d.coding_runs, d.coding_failed = int(started), int(failed)
                d.input_tokens += int(tin)
                d.output_tokens += int(tout)
                d.coding_cost_usd = round(float(cost), 4)

        for day, count in await self.session.execute(
            select(cast(func.timezone(UTC_NAME, User.created_at), Date), func.count(User.id))
            .where(User.created_at >= since)
            .group_by(cast(func.timezone(UTC_NAME, User.created_at), Date))
        ):
            if day in out:
                out[day].signups = int(count)
        return list(out.values())

    async def failures(self, days: int = 7) -> FailureReport:
        """What went wrong lately: chat runs by the kind of error, coding turns by engine, and the
        recorded errors grouped by their first line, most frequent first."""
        since = datetime.now(UTC) - timedelta(days=days)
        chat_kinds = [
            FailureGroup(key=kind or "error", count=int(count), last_at=last)
            for kind, count, last in await self.session.execute(
                select(AgentRun.error_kind, func.count(AgentRun.id), func.max(AgentRun.finished_at))
                .where(AgentRun.status == RunStatus.FAILED, AgentRun.finished_at >= since)
                .group_by(AgentRun.error_kind)
                .order_by(func.count(AgentRun.id).desc())
            )
        ]
        by_model = [
            FailureGroup(key=model or "(default)", count=int(count), last_at=last)
            for model, count, last in await self.session.execute(
                select(
                    func.coalesce(AgentRun.conversation_model, AgentRun.model),
                    func.count(AgentRun.id),
                    func.max(AgentRun.finished_at),
                )
                .where(AgentRun.status == RunStatus.FAILED, AgentRun.finished_at >= since)
                .group_by(func.coalesce(AgentRun.conversation_model, AgentRun.model))
                .order_by(func.count(AgentRun.id).desc())
                .limit(10)
            )
        ]

        messages: dict[tuple[str, str], FailureGroup] = {}
        rows = await self.session.execute(
            select(AgentRun.error, AgentRun.finished_at, AgentRun.error_kind)
            .where(AgentRun.status == RunStatus.FAILED, AgentRun.finished_at >= since)
            .order_by(AgentRun.finished_at.desc())
            .limit(500)
        )
        for error, at, kind in rows:
            self._group(messages, "chat", _error_line(error), at, kind)
        rows = await self.session.execute(
            select(CodingRun.error, CodingRun.finished_at, CodingRun.status)
            .where(CodingRun.status.in_(CODING_FAILED), CodingRun.finished_at >= since)
            .order_by(CodingRun.finished_at.desc())
            .limit(500)
        )
        for error, at, status in rows:
            self._group(messages, "coding", _error_line(error), at, status.value)
        top = sorted(messages.values(), key=lambda g: (g.count, g.last_at or datetime.min.replace(tzinfo=UTC)), reverse=True)

        return FailureReport(days=days, chat_kinds=chat_kinds, chat_models=by_model, messages=top[:25])

    @staticmethod
    def _group(found: dict[tuple[str, str], FailureGroup], kind: str, line: str, at: datetime | None, detail: str | None) -> None:
        group = found.get((kind, line))
        if group is None:
            found[(kind, line)] = FailureGroup(key=line, kind=kind, detail=detail, count=1, last_at=at)
        else:
            group.count += 1
            if at and (group.last_at is None or at > group.last_at):
                group.last_at = at

    async def coding(self, days: int = 7) -> list[CodingBreakdown]:
        """Coding turns by engine and where they ran: how many, how they ended, how long they took
        (median and 95th percentile, from start to finish), tokens and cost."""
        since = datetime.now(UTC) - timedelta(days=days)
        seconds = func.extract("epoch", CodingRun.finished_at - CodingRun.started_at)
        rows = await self.session.execute(
            select(
                CodingRun.agent,
                CodingRun.location,
                func.count(CodingRun.id),
                func.count(case((CodingRun.status.in_(CODING_DONE), 1))),
                func.count(case((CodingRun.status.in_(CODING_FAILED), 1))),
                func.count(case((CodingRun.status == CodingRunStatus.PR_OPENED, 1))),
                func.percentile_cont(0.5).within_group(seconds),
                func.percentile_cont(0.95).within_group(seconds),
                func.coalesce(func.sum(CodingRun.input_tokens + CodingRun.output_tokens), 0),
                func.coalesce(func.sum(CodingRun.cost_usd), 0),
            )
            .where(CodingRun.created_at >= since)
            .group_by(CodingRun.agent, CodingRun.location)
            .order_by(func.count(CodingRun.id).desc())
        )
        return [
            CodingBreakdown(
                engine=engine.value,
                location=location.value,
                turns=int(turns),
                finished=int(done),
                failed=int(failed),
                prs=int(prs),
                p50_seconds=round(float(p50), 1) if p50 is not None else None,
                p95_seconds=round(float(p95), 1) if p95 is not None else None,
                tokens=int(tokens),
                cost_usd=round(float(cost), 4),
            )
            for engine, location, turns, done, failed, prs, p50, p95, tokens, cost in rows
        ]

    async def workspaces(self, days: int = 7, limit: int = 50) -> list[WorkspaceUsage]:
        """Workspaces by how much they used the platform lately: runs, failures, tokens and cost."""
        since = datetime.now(UTC) - timedelta(days=days)
        usage: dict[Any, dict[str, Any]] = defaultdict(
            lambda: {"chat": 0, "coding": 0, "failed": 0, "tokens": 0, "cost": 0.0, "last": None}
        )
        for wid, runs, failed, tokens, last in await self.session.execute(
            select(
                AgentRun.workspace_id,
                func.count(AgentRun.id),
                func.count(case((AgentRun.status == RunStatus.FAILED, 1))),
                func.coalesce(func.sum(AgentRun.input_tokens + AgentRun.output_tokens), 0),
                func.max(AgentRun.created_at),
            )
            .where(AgentRun.created_at >= since)
            .group_by(AgentRun.workspace_id)
        ):
            u = usage[wid]
            u.update(chat=int(runs), failed=u["failed"] + int(failed), tokens=u["tokens"] + int(tokens), last=last)
        for wid, runs, failed, tokens, cost, last in await self.session.execute(
            select(
                CodingRun.workspace_id,
                func.count(CodingRun.id),
                func.count(case((CodingRun.status.in_(CODING_FAILED), 1))),
                func.coalesce(func.sum(CodingRun.input_tokens + CodingRun.output_tokens), 0),
                func.coalesce(func.sum(CodingRun.cost_usd), 0),
                func.max(CodingRun.created_at),
            )
            .where(CodingRun.created_at >= since)
            .group_by(CodingRun.workspace_id)
        ):
            u = usage[wid]
            u.update(
                coding=int(runs),
                failed=u["failed"] + int(failed),
                tokens=u["tokens"] + int(tokens),
                cost=float(cost),
                last=max(filter(None, [u["last"], last]), default=None),
            )

        members = (
            select(Membership.workspace_id, func.count(Membership.id).label("n"))
            .group_by(Membership.workspace_id)
            .subquery()
        )
        projects = (
            select(Project.workspace_id, func.count(Project.id).label("n")).group_by(Project.workspace_id).subquery()
        )
        rows = await self.session.execute(
            select(Workspace, func.coalesce(members.c.n, 0), func.coalesce(projects.c.n, 0))
            .outerjoin(members, members.c.workspace_id == Workspace.id)
            .outerjoin(projects, projects.c.workspace_id == Workspace.id)
        )
        found = [
            WorkspaceUsage(
                id=ws.id,
                name=ws.name,
                slug=ws.slug,
                kind=ws.kind.value,
                members=int(m),
                projects=int(p),
                created_at=ws.created_at,
                chat_runs=usage[ws.id]["chat"] if ws.id in usage else 0,
                coding_runs=usage[ws.id]["coding"] if ws.id in usage else 0,
                failed=usage[ws.id]["failed"] if ws.id in usage else 0,
                tokens=usage[ws.id]["tokens"] if ws.id in usage else 0,
                cost_usd=round(usage[ws.id]["cost"], 4) if ws.id in usage else 0.0,
                last_run_at=usage[ws.id]["last"] if ws.id in usage else None,
                paused=ws.unattended_paused,
            )
            for ws, m, p in rows
        ]
        found.sort(key=lambda w: (w.chat_runs + w.coding_runs, w.tokens, w.created_at), reverse=True)
        return found[:limit]

    async def audit(self, *, action: str | None = None, before: datetime | None = None, limit: int = 100) -> list[PlatformAuditEvent]:
        """Audit events across every workspace, newest first. `action` matches a prefix
        (`coding.` finds every coding event)."""
        stmt = select(AuditEvent, Workspace.slug).outerjoin(Workspace, Workspace.id == AuditEvent.workspace_id)
        if action:
            escaped = action.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            stmt = stmt.where(AuditEvent.action.like(f"{escaped}%", escape="\\"))
        if before is not None:
            stmt = stmt.where(AuditEvent.created_at < before)
        rows = await self.session.execute(stmt.order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc()).limit(limit))
        return [
            PlatformAuditEvent(
                id=e.id,
                action=e.action,
                workspace=slug,
                actor_type=e.actor_type.value,
                actor_user_id=e.actor_user_id,
                agent=e.agent,
                created_at=e.created_at,
            )
            for e, slug in rows
        ]
