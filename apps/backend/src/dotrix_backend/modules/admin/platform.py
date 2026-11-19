"""Platform observability for the admin console (apps/admin): the deployment's health, trends,
failures, coding, and workspaces. Reads only, from the modules' own tables.

The console is for whoever operates dotrix, not a workspace's people, so it reads every workspace,
but never what people wrote: no conversation titles or messages, briefs, diffs, or documents. Runs
are named by their workspace, project and issue key; failures by the error the platform recorded."""
from __future__ import annotations

import asyncio
import re
import time
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import Date, case, cast, func, literal_column, select, text, true
from sqlalchemy.ext.asyncio import AsyncSession

from dotrix_backend.core.jobs import QUEUE_NAME
from dotrix_backend.core.model_prices import cost_of
from dotrix_backend.core.settings import Settings
from dotrix_backend.modules.admin.schemas import (
    AuditPage,
    CodingBreakdown,
    DayStats,
    DependencyCheck,
    FailureGroup,
    FailureReport,
    ModelUsage,
    PlatformAuditEvent,
    PlatformCounts,
    PlatformHealth,
    RunPage,
    StuckRun,
    WorkspaceUsage,
)
from dotrix_backend.modules.agents.models import ACTIVE_STATUSES, AgentRun, RunStatus
from dotrix_backend.modules.audit.models import AuditEvent
from dotrix_backend.modules.auth.models import User
from dotrix_backend.modules.automations.models import AutomationEventRow
from dotrix_backend.modules.coding.models import ACTIVE as CODING_ACTIVE
from dotrix_backend.modules.coding.models import (
    CodingLocation,
    CodingRun,
    CodingRunner,
    CodingRunStatus,
    CodingSession,
    CodingSessionState,
)
from dotrix_backend.modules.documents.models import Document
from dotrix_backend.modules.execution.models import RunDispatch
from dotrix_backend.modules.issues.models import IssueAttachment
from dotrix_backend.modules.knowledge.models import AuthorType
from dotrix_backend.modules.notifications.models import Notification
from dotrix_backend.modules.observe.service import ObserveService
from dotrix_backend.modules.projects.models import Project
from dotrix_backend.modules.workspaces.models import Membership, Workspace
from dotrix_backend.modules.workspaces.storage import limit_bytes

RUNNER_ONLINE = timedelta(minutes=2)
ARQ_HEALTH_SUFFIX = ":health-check"  # arq's key for a queue; worker.py keeps arq's default interval
ARQ_HEALTH_INTERVAL = 3600
EMAIL_GRACE = timedelta(minutes=5)
# A literal, not a bound parameter: GROUP BY must repeat the SELECT's expression exactly.
UTC_NAME = literal_column("'UTC'")
CODING_FAILED = (CodingRunStatus.FAILED, CodingRunStatus.RECOVERY_REQUIRED)
# Coding turns that finished their work (the rest were stopped, rejected, or are still going).
CODING_DONE = (CodingRunStatus.PR_OPENED, CodingRunStatus.NO_CHANGES, CodingRunStatus.CHANGES_READY)


# Messages the platform itself writes (agents/runner.py, coding/runner.py, coding/local.py): only their
# fixed opening is kept, since what follows can carry a person's name or words.
_PLATFORM_PREFIXES = (
    "Kai didn't finish",
    "Stopped by",
    "Stopped before it started",
    "Stopped for outcome reconciliation",
    "Stopped because the server shut down",
    "Stopped:",
    "The person who asked no longer sees this project",
    "Whoever asked is no longer in this workspace",
    "You can no longer see every project in this conversation",
    "The PM finished without writing a reply",
    "A required specialist result is no longer available",
    "The specialist history could not be validated",
    "Something went wrong running the coding agent",
)
_EXCEPTION = re.compile(r"^([A-Za-z_][A-Za-z0-9_.]*(?:Error|Exception|Timeout|Refused|Limit)\w*):")
_STATUS = re.compile(r"\b([45]\d\d)\b")
_KINDS = (
    (re.compile(r"rate.?limit|quota|too many requests|credit|overloaded", re.I), "rate limited"),
    (re.compile(r"timeout|timed out", re.I), "timed out"),
    (re.compile(r"connect|network|dns", re.I), "connection failed"),
    (re.compile(r"auth|api key|unauthori[sz]ed|permission", re.I), "authentication failed"),
    (re.compile(r"context.*(length|window)|(length|window).*context|too many tokens", re.I), "context too long"),
)


def _classify(message: str) -> str:
    status = _STATUS.search(message)
    if status:
        return f"HTTP {status.group(1)}"
    for pattern, kind in _KINDS:
        if pattern.search(message):
            return kind
    return "other"


def _failure_key(error: str | None) -> str:
    """A recorded error as a kind of failure, to group the same one together. The raw text can repeat
    part of what someone asked, so the console gets a class name and a fixed classification, or the
    opening of a message the platform wrote, never the rest."""
    text_ = (error or "").strip()
    if not text_:
        return "(no message)"
    line = text_.splitlines()[0].strip()
    if line.startswith("Stopped by"):
        return "Stopped by a person"
    for prefix in _PLATFORM_PREFIXES:
        if line.startswith(prefix):
            return prefix.rstrip(":")[:80]
    if re.match(r"The @\S+ agent no longer exists", line):
        return "An agent no longer exists"
    named = _EXCEPTION.match(line)
    if named:
        return f"{named.group(1)}: {_classify(line[named.end():])}"[:80]
    return _classify(line)


class PlatformObserve:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    async def _scalar(self, stmt) -> Any:
        return (await self.session.execute(stmt)).scalar() or 0

    async def dependencies(self, state: Any) -> list[DependencyCheck]:
        """Redis, workers, file storage, email and the GitHub App, each checked on its own: one that
        fails reports `down` (by its exception's class, never its message) and never fails the read."""
        s = self.settings
        redis = getattr(state, "redis", None)
        storage = getattr(state, "storage", None)

        async def guarded(check_id: str, run: Any) -> DependencyCheck:
            try:
                return await asyncio.wait_for(run(), timeout=2)
            except TimeoutError:
                return DependencyCheck(id=check_id, state="down", detail="No answer within 2 seconds")
            except Exception as exc:
                return DependencyCheck(id=check_id, state="down", detail=f"Check failed: {type(exc).__name__}")

        async def redis_check() -> DependencyCheck:
            if redis is None:
                return DependencyCheck(id="redis", state="off", detail="Not configured here")
            started = time.perf_counter()
            await redis.ping()
            ms = round((time.perf_counter() - started) * 1000, 1)
            return DependencyCheck(id="redis", state="ok", detail=f"Answered in {ms} ms", latency_ms=ms)

        async def workers_check() -> DependencyCheck:
            if s.jobs != "worker":
                return DependencyCheck(id="workers", state="off", detail=f"Background work runs in {s.jobs} mode")
            if redis is None:
                return DependencyCheck(id="workers", state="degraded", detail="Can't confirm a worker is alive")
            # arq's worker sets "<queue>:health-check" with a TTL of its interval + 1 s (3600 by default).
            ttl_ms = await redis.pttl(QUEUE_NAME + ARQ_HEALTH_SUFFIX)
            if ttl_ms is None or ttl_ms < 0:
                return DependencyCheck(id="workers", state="down", detail="No worker has checked in recently")
            age = max(0, ARQ_HEALTH_INTERVAL + 1 - ttl_ms / 1000)
            return DependencyCheck(id="workers", state="ok", detail=f"A worker checked in {round(age)} s ago")

        async def storage_check() -> DependencyCheck:
            if storage is None:
                return DependencyCheck(id="storage", state="off", detail="Not configured here")
            started = time.perf_counter()
            await storage.ping()
            ms = round((time.perf_counter() - started) * 1000, 1)
            return DependencyCheck(id="storage", state="ok", detail=f"Answered in {ms} ms", latency_ms=ms)

        async def email_check() -> DependencyCheck:
            if s.email_backend == "sendly":
                return DependencyCheck(id="email", state="ok", detail="Sendly")
            return DependencyCheck(id="email", state="degraded", detail="Console (emails are only logged)")

        async def github_check() -> DependencyCheck:
            if not s.github_app_id:
                return DependencyCheck(id="github", state="off", detail="Not configured here")
            if s.github_webhook_secret is None:
                return DependencyCheck(id="github", state="degraded", detail="Webhooks can't be verified")
            return DependencyCheck(id="github", state="ok", detail="App configured")

        return list(
            await asyncio.gather(
                guarded("redis", redis_check),
                guarded("workers", workers_check),
                guarded("storage", storage_check),
                guarded("email", email_check),
                guarded("github", github_check),
            )
        )

    async def health(self, version: str, state: Any = None) -> PlatformHealth:
        """Is the deployment working: the database, the run queue, workers, leases, sandboxes, and
        what dotrix depends on."""
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

        dependencies = await self.dependencies(state)
        # What the minute job hands out: everything unemailed older than its one-minute batch wait
        # (send_due marks digest and no-email people's rows handled too).
        unsent = (Notification.emailed_at.is_(None), Notification.created_at <= now - EMAIL_GRACE)
        oldest_unsent = await self.session.scalar(select(func.min(Notification.created_at)).where(*unsent))
        workers = next((d for d in dependencies if d.id == "workers"), None)

        return PlatformHealth(
            generated_at=now,
            dependencies=dependencies,
            workers_alive=None if workers is None or workers.state in ("off", "degraded") else int(workers.state == "ok"),
            notification_emails_waiting=await self._scalar(select(func.count(Notification.id)).where(*unsent)),
            notification_email_oldest_seconds=(now - oldest_unsent).total_seconds() if oldest_unsent is not None else None,
            automation_events_waiting=await self._scalar(select(func.count(AutomationEventRow.id))),
            coding_slots=self.settings.coding_max_runs or None,
            coding_running_cloud=await self._scalar(
                select(func.count(CodingRun.id)).where(
                    CodingRun.status == CodingRunStatus.RUNNING, CodingRun.location == CodingLocation.CLOUD
                )
            ),
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
        # The model a run worked on (a specialist's own, when Nova delegated), else its conversation's.
        chat_model = func.coalesce(AgentRun.model, AgentRun.conversation_model)
        for day, model, started, failed, tin, tout, cached in await self.session.execute(
            select(
                chat_day,
                chat_model,
                func.count(AgentRun.id),
                func.count(case((AgentRun.status == RunStatus.FAILED, 1))),
                func.coalesce(func.sum(AgentRun.input_tokens), 0),
                func.coalesce(func.sum(AgentRun.output_tokens), 0),
                func.coalesce(func.sum(AgentRun.cached_input_tokens), 0),
            )
            .where(AgentRun.created_at >= since)
            .group_by(chat_day, chat_model)
        ):
            if day in out:
                d = out[day]
                d.chat_runs += int(started)
                d.chat_failed += int(failed)
                d.input_tokens += int(tin)
                d.output_tokens += int(tout)
                cost = self._chat_cost(model, int(tin), int(tout), int(cached))
                if cost is None:
                    d.unpriced_chat_runs += int(started)
                else:
                    d.chat_cost_usd = round(d.chat_cost_usd + cost, 4)

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

    def _chat_cost(self, model: str | None, tin: int, tout: int, cached: int) -> float | None:
        """A chat run group's cost from list prices; None when the model has no price (never a guess)."""
        return cost_of(
            model, input_tokens=tin, output_tokens=tout, cached_input_tokens=cached, overrides=self.settings.model_prices
        )

    async def models(self, days: int = 7) -> list[ModelUsage]:
        """Each model's use in the window, chat and coding together: runs, failures, limit stops, tokens
        and an estimated cost (chat from list prices, coding as recorded)."""
        since = datetime.now(UTC) - timedelta(days=days)
        chat_model = func.coalesce(AgentRun.model, AgentRun.conversation_model)
        rows: dict[str, dict[str, Any]] = {}

        def row(model: str | None) -> dict[str, Any]:
            key = model or "(default)"
            return rows.setdefault(
                key,
                {"chat": 0, "coding": 0, "failed": 0, "limit": 0, "tin": 0, "tout": 0, "chat_cost": 0.0,
                 "chat_unpriced": False, "coding_cost": None},
            )

        for model, runs, failed, limit, tin, tout, cached in await self.session.execute(
            select(
                chat_model,
                func.count(AgentRun.id),
                func.count(case((AgentRun.status == RunStatus.FAILED, 1))),
                func.count(case((AgentRun.error_kind == "model_limit", 1))),
                func.coalesce(func.sum(AgentRun.input_tokens), 0),
                func.coalesce(func.sum(AgentRun.output_tokens), 0),
                func.coalesce(func.sum(AgentRun.cached_input_tokens), 0),
            )
            .where(AgentRun.created_at >= since)
            .group_by(chat_model)
        ):
            r = row(model)
            r["chat"], r["failed"], r["limit"] = int(runs), r["failed"] + int(failed), int(limit)
            r["tin"] += int(tin)
            r["tout"] += int(tout)
            cost = self._chat_cost(model, int(tin), int(tout), int(cached))
            if cost is None:
                r["chat_unpriced"] = True
            else:
                r["chat_cost"] = cost

        for model, runs, failed, tin, tout, cost in await self.session.execute(
            select(
                CodingRun.model,
                func.count(CodingRun.id),
                func.count(case((CodingRun.status.in_(CODING_FAILED), 1))),
                func.coalesce(func.sum(CodingRun.input_tokens), 0),
                func.coalesce(func.sum(CodingRun.output_tokens), 0),
                func.sum(CodingRun.cost_usd),
            )
            .where(CodingRun.created_at >= since)
            .group_by(CodingRun.model)
        ):
            r = row(model)
            r["coding"] = int(runs)
            r["failed"] += int(failed)
            r["tin"] += int(tin)
            r["tout"] += int(tout)
            r["coding_cost"] = float(cost) if cost is not None else None

        out: list[ModelUsage] = []
        for key, r in rows.items():
            coding_cost = r["coding_cost"]
            if r["chat"] and r["chat_unpriced"]:
                cost = coding_cost  # chat tokens with no price add nothing, never a guess
            elif r["chat"] or coding_cost is not None:
                cost = r["chat_cost"] + (coding_cost or 0.0)
            else:
                cost = None
            out.append(
                ModelUsage(
                    model=key,
                    provider=key.split(":", 1)[0] if ":" in key else "unknown",
                    chat_runs=r["chat"],
                    coding_runs=r["coding"],
                    failed=r["failed"],
                    limit_stops=r["limit"],
                    input_tokens=r["tin"],
                    output_tokens=r["tout"],
                    cost_usd=round(cost, 4) if cost is not None else None,
                )
            )
        out.sort(key=lambda m: (m.chat_runs + m.coding_runs, m.model), reverse=True)
        return out[:50]

    async def failures(self, days: int = 7) -> FailureReport:
        """What went wrong lately: chat runs by the kind of error, coding turns by engine, and the
        recorded errors grouped by their first line, most frequent first."""
        since = datetime.now(UTC) - timedelta(days=days)
        # A failure without a kind recorded is an ordinary error.
        error_kind = func.coalesce(AgentRun.error_kind, literal_column("'error'"))
        chat_kinds = [
            FailureGroup(key=kind, count=int(count), last_at=last)
            for kind, count, last in await self.session.execute(
                select(error_kind, func.count(AgentRun.id), func.max(AgentRun.finished_at))
                .where(AgentRun.status == RunStatus.FAILED, AgentRun.finished_at >= since)
                .group_by(error_kind)
                .order_by(func.count(AgentRun.id).desc())
            )
        ]
        by_model = [
            FailureGroup(key=model or "(default)", count=int(count), last_at=last)
            for model, count, last in await self.session.execute(
                select(
                    func.coalesce(AgentRun.model, AgentRun.conversation_model),
                    func.count(AgentRun.id),
                    func.max(AgentRun.finished_at),
                )
                .where(AgentRun.status == RunStatus.FAILED, AgentRun.finished_at >= since)
                .group_by(func.coalesce(AgentRun.model, AgentRun.conversation_model))
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
            self._group(messages, "chat", _failure_key(error), at, kind)
        rows = await self.session.execute(
            select(CodingRun.error, CodingRun.finished_at, CodingRun.status)
            .where(CodingRun.status.in_(CODING_FAILED), CodingRun.finished_at >= since)
            .order_by(CodingRun.finished_at.desc())
            .limit(500)
        )
        for error, at, status in rows:
            self._group(messages, "coding", _failure_key(error), at, status.value)
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
        stored = {
            wid: int(n)
            for wid, n in await self.session.execute(
                select(Document.workspace_id, func.sum(Document.size)).group_by(Document.workspace_id)
            )
        }
        for wid, n in await self.session.execute(
            select(IssueAttachment.workspace_id, func.sum(IssueAttachment.size)).group_by(IssueAttachment.workspace_id)
        ):
            stored[wid] = stored.get(wid, 0) + int(n)
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
                used_bytes=stored.get(ws.id, 0),
                storage_limit_mb=ws.storage_limit_mb,
                effective_limit_bytes=limit_bytes(ws, self.settings),
            )
            for ws, m, p in rows
        ]
        found.sort(key=lambda w: (w.chat_runs + w.coding_runs, w.tokens, w.created_at), reverse=True)
        return found[:limit]

    async def audit(
        self,
        *,
        action: str | None = None,
        workspace: str | None = None,
        actor_type: AuthorType | None = None,
        since: date | None = None,
        until: date | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> AuditPage:
        """A page of audit events across every workspace, newest first, with the total. `action`
        matches a prefix (`coding.` finds every coding event); `workspace` is a slug, `since` and
        `until` are inclusive UTC days. The total follows the filters."""
        where = []
        if workspace:
            where.append(Workspace.slug == workspace)
        if actor_type:
            where.append(AuditEvent.actor_type == actor_type)
        if since:
            where.append(AuditEvent.created_at >= datetime.combine(since, datetime.min.time(), tzinfo=UTC))
        if until:
            where.append(AuditEvent.created_at < datetime.combine(until + timedelta(days=1), datetime.min.time(), tzinfo=UTC))
        if action:
            escaped = action.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            where.append(AuditEvent.action.like(f"{escaped}%", escape="\\"))
        rows = await self.session.execute(
            select(AuditEvent, Workspace.slug)
            .outerjoin(Workspace, Workspace.id == AuditEvent.workspace_id)
            .where(*where)
            .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
            .offset(offset)
            .limit(limit)
        )
        items = [
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
        total = await self._scalar(
            select(func.count(AuditEvent.id)).outerjoin(Workspace, Workspace.id == AuditEvent.workspace_id).where(*where)
        )
        return AuditPage(items=items, total=int(total))


class AdminRunService(ObserveService):
    async def platform_runs(
        self,
        *,
        kind: Literal["chat", "coding"] | None = None,
        failed: bool = False,
        offset: int = 0,
        limit: int = 50,
    ) -> RunPage:
        """One page of every workspace's runs, newest first, with the total, for the admin console.
        It sees every workspace but not what people wrote: a run is named by its workspace, project and
        issue, never by its conversation's title or message."""
        runs = await self._runs(None, kind=kind, failed=failed, offset=offset, limit=limit)
        slugs = dict(
            (await self.session.execute(
                select(Workspace.id, Workspace.slug).where(Workspace.id.in_({r.workspace_id for r in runs}))
            )).all()
        )
        keys = dict(
            (await self.session.execute(
                select(Project.id, Project.key).where(Project.id.in_({r.project_id for r in runs if r.project_id}))
            )).all()
        )
        for r in runs:
            r.workspace = slugs.get(r.workspace_id)
            project = keys.get(r.project_id) if r.project_id else None
            if r.kind == "chat":
                r.label = " · ".join(filter(None, [project or "Across projects", r.work_mode]))
        total = 0
        if kind in (None, "chat"):
            total += (await self.session.scalar(
                select(func.count(AgentRun.id)).where(AgentRun.status == RunStatus.FAILED if failed else true())
            )) or 0
        if kind in (None, "coding"):
            total += (await self.session.scalar(
                select(func.count(CodingRun.id)).where(
                    CodingRun.status.in_((CodingRunStatus.FAILED, CodingRunStatus.RECOVERY_REQUIRED)) if failed else true()
                )
            )) or 0
        return RunPage(items=runs, total=total)
