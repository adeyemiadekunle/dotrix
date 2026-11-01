"""The observability reads behind Ops: the workspace's health in one query set, and a
unified run history across chat and coding. Reads only — the numbers come from the modules'
own tables. Runs stay under the same privacy as everywhere else (each person sees their own,
plus what's waiting on a decision they may make)."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import func, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from dotrix_backend.core.settings import Settings
from dotrix_backend.modules.agents.models import ACTIVE_STATUSES, AgentRun, RunStatus
from dotrix_backend.modules.agents.privacy import runs_visible_to
from dotrix_backend.modules.coding.models import ACTIVE as CODING_ACTIVE
from dotrix_backend.modules.coding.models import WAITING as CODING_WAITING
from dotrix_backend.modules.coding.models import CodingRun, CodingRunner, CodingRunStatus
from dotrix_backend.modules.coding.service import visible_runs
from dotrix_backend.modules.documents.models import Document
from dotrix_backend.modules.execution.models import RunDispatch
from dotrix_backend.modules.projects.models import Project
from dotrix_backend.modules.projects.repository import visible_to
from dotrix_backend.modules.workspaces.models import Membership, Workspace

from .schemas import (
    ObserveCounts,
    ObservedRun,
    ObserveOverview,
    ObserveQueue,
    RunGroupSummary,
    RunPage,
)


class ObserveService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    async def overview(self, member: Membership) -> ObserveOverview:
        """Workspace counts, visible runs and dispatches, and runs with lapsed leases."""
        return await self._overview(member)

    async def _overview(self, member: Membership | None) -> ObserveOverview:
        ws = member.workspace_id if member else None  # None: the whole deployment
        now = datetime.now(UTC)
        since = now - timedelta(days=7)

        def w(col) -> Any:  # workspace filter when scoped to one workspace
            return col == ws if ws is not None else true()

        def scope_runs(kind: str) -> Any:  # privacy filter only inside a workspace
            if member is None:
                return true()
            return runs_visible_to(member) if kind == "chat" else visible_runs(member)

        async def scalar(stmt) -> int:
            return int((await self.session.execute(stmt)).scalar() or 0)

        counts = ObserveCounts(
            projects=await scalar(
                select(func.count(Project.id)).where(
                    w(Project.workspace_id),
                    visible_to(member.user_id, member.role) if member else true(),
                )
            ),
            members=await scalar(select(func.count(Membership.id)).where(w(Membership.workspace_id))),
            documents=await scalar(select(func.count(Document.id)).where(w(Document.workspace_id))),
            document_bytes=await scalar(
                select(func.coalesce(func.sum(Document.size), 0)).where(w(Document.workspace_id))
            ),
            coding_runners=await scalar(
                select(func.count(CodingRunner.id)).where(w(CodingRunner.workspace_id))
            ),
        )

        # Token and cost columns are cumulative per run. Chat runs resume in place, so the
        # window is "runs with activity this week" (updated_at); coding turns are a new row
        # each time, so created_at is already the right window there.
        chat = await self._run_summary(
            member,
            since,
            model=AgentRun,
            scope=scope_runs("chat"),
            window=AgentRun.updated_at >= since,
            active=AgentRun.status.in_((RunStatus.QUEUED, RunStatus.RUNNING)),
            waiting=AgentRun.status == RunStatus.AWAITING_APPROVAL,
            failed=AgentRun.status == RunStatus.FAILED,
            tokens_in=AgentRun.input_tokens,
            tokens_out=AgentRun.output_tokens,
            calls=AgentRun.model_calls,
        )
        coding = await self._run_summary(
            member,
            since,
            model=CodingRun,
            scope=scope_runs("coding"),
            window=CodingRun.created_at >= since,
            active=CodingRun.status.in_((CodingRunStatus.QUEUED, CodingRunStatus.RUNNING)),
            waiting=CodingRun.status.in_(CODING_WAITING),
            failed=CodingRun.status == CodingRunStatus.FAILED,
            tokens_in=CodingRun.input_tokens,
            tokens_out=CodingRun.output_tokens,
            cost=CodingRun.cost_usd,
        )

        # Inside a workspace the queue counts only dispatches for runs the member may see; on
        # the platform console all dispatches count (there is no member privacy to preserve).
        dispatch_visible = true() if member is None else (
            RunDispatch.agent_run_id.in_(
                select(AgentRun.id).where(AgentRun.workspace_id == ws, runs_visible_to(member))
            )
            | RunDispatch.coding_run_id.in_(
                select(CodingRun.id).where(CodingRun.workspace_id == ws, visible_runs(member))
            )
        )
        pending = select(func.count(RunDispatch.id)).where(
            w(RunDispatch.workspace_id),
            RunDispatch.accepted_at.is_(None),
            RunDispatch.discarded_at.is_(None),
            dispatch_visible,
        )
        oldest = await self.session.scalar(
            select(func.min(RunDispatch.created_at)).where(
                w(RunDispatch.workspace_id),
                RunDispatch.accepted_at.is_(None),
                RunDispatch.discarded_at.is_(None),
                dispatch_visible,
            )
        )
        queue = ObserveQueue(
            pending=await scalar(pending),
            oldest_pending_seconds=(now - oldest).total_seconds() if oldest is not None else None,
            discarded_7d=await scalar(
                select(func.count(RunDispatch.id)).where(
                    w(RunDispatch.workspace_id), RunDispatch.discarded_at >= since, dispatch_visible
                )
            ),
        )

        stuck = (
            await scalar(
                select(func.count(AgentRun.id)).where(
                    w(AgentRun.workspace_id),
                    AgentRun.status.in_(ACTIVE_STATUSES),
                    AgentRun.lease_expires_at < now,
                    scope_runs("chat"),
                )
            )
            + await scalar(
                select(func.count(CodingRun.id)).where(
                    w(CodingRun.workspace_id),
                    CodingRun.status.in_(CODING_ACTIVE),
                    CodingRun.lease_expires_at < now,
                    scope_runs("coding"),
                )
            )
        )

        return ObserveOverview(
            generated_at=now,
            jobs=self.settings.jobs,
            counts=counts,
            chat=chat,
            coding=coding,
            queue=queue,
            stuck=stuck,
        )

    async def _run_summary(
        self,
        member: Membership | None,
        since: datetime,
        *,
        model,
        scope,
        window,
        active,
        waiting,
        failed,
        tokens_in,
        tokens_out,
        calls=None,
        cost=None,
    ) -> RunGroupSummary:
        ws = member.workspace_id if member else None
        w = (lambda col: col == ws) if ws is not None else (lambda col: true())

        async def scalar(stmt) -> int | float:
            return (await self.session.execute(stmt)).scalar() or 0

        return RunGroupSummary(
            total=await scalar(select(func.count(model.id)).where(w(model.workspace_id), scope)),
            active=await scalar(select(func.count(model.id)).where(w(model.workspace_id), scope, active)),
            waiting=await scalar(select(func.count(model.id)).where(w(model.workspace_id), scope, waiting)),
            failed_7d=await scalar(
                select(func.count(model.id)).where(w(model.workspace_id), scope, failed, model.finished_at >= since)
            ),
            input_tokens_7d=await scalar(
                select(func.coalesce(func.sum(tokens_in), 0)).where(w(model.workspace_id), scope, window)
            ),
            output_tokens_7d=await scalar(
                select(func.coalesce(func.sum(tokens_out), 0)).where(w(model.workspace_id), scope, window)
            ),
            model_calls_7d=await scalar(
                select(func.coalesce(func.sum(calls), 0)).where(w(model.workspace_id), scope, window)
            )
            if calls is not None
            else 0,
            cost_usd_7d=float(
                await scalar(
                    select(func.coalesce(func.sum(cost), 0)).where(w(model.workspace_id), scope, window)
                )
            )
            if cost is not None
            else None,
        )

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

    async def runs(
        self,
        member: Membership,
        *,
        kind: Literal["chat", "coding"] | None = None,
        before: datetime | None = None,
        before_id: uuid.UUID | None = None,
        limit: int = 50,
    ) -> list[ObservedRun]:
        """The workspace's recent runs in one list (chat and coding), newest first. Each kind is
        fetched at `limit` and merged, so paging `before` the last row is exact. `before_id`
        keeps the same (created_at, id) order as the sort, so rows tied on created_at aren't
        skipped when a page boundary lands inside them."""
        return await self._runs(member, kind=kind, before=before, before_id=before_id, limit=limit)

    async def _runs(
        self,
        member: Membership | None,
        *,
        kind: Literal["chat", "coding"] | None = None,
        failed: bool = False,
        before: datetime | None = None,
        before_id: uuid.UUID | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> list[ObservedRun]:
        ws = member.workspace_id if member else None
        found: list[ObservedRun] = []

        def keyset(model) -> Any:
            if before is None:
                return None
            clause = model.created_at < before
            if before_id is not None:
                clause |= (model.created_at == before) & (model.id < before_id)
            return clause

        if kind in (None, "chat"):
            stmt = (
                select(AgentRun)
                .where(
                    *( [AgentRun.workspace_id == ws] if ws is not None else [] ),
                    runs_visible_to(member) if member else true(),
                    AgentRun.status == RunStatus.FAILED if failed else true(),
                )
                .order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
                .limit(offset + limit)
            )
            if (clause := keyset(AgentRun)) is not None:
                stmt = stmt.where(clause)
            for r in await self.session.scalars(stmt):
                found.append(
                    ObservedRun(
                        kind="chat",
                        id=r.id,
                        workspace_id=r.workspace_id,
                        status=r.status.value,
                        label=r.title or r.message[:100],
                        project_id=r.project_id,
                        agent=r.agent or "auto",
                        model=r.conversation_model or r.model,
                        work_mode=r.work_mode.value if r.work_mode else None,
                        input_tokens=r.input_tokens,
                        output_tokens=r.output_tokens,
                        error=r.error,
                        error_kind=r.error_kind,
                        requested_by_id=r.requested_by_id,
                        automation=r.automation_id is not None,
                        created_at=r.created_at,
                        finished_at=r.finished_at,
                    )
                )

        if kind in (None, "coding"):
            stmt = (
                select(CodingRun)
                .where(
                    *( [CodingRun.workspace_id == ws] if ws is not None else [] ),
                    visible_runs(member) if member else true(),
                    CodingRun.status.in_((CodingRunStatus.FAILED, CodingRunStatus.RECOVERY_REQUIRED)) if failed else true(),
                )
                .order_by(CodingRun.created_at.desc(), CodingRun.id.desc())
                .limit(offset + limit)
            )
            if (clause := keyset(CodingRun)) is not None:
                stmt = stmt.where(clause)
            for r in await self.session.scalars(stmt):
                found.append(
                    ObservedRun(
                        kind="coding",
                        id=r.id,
                        workspace_id=r.workspace_id,
                        started_at=r.started_at,
                        status=r.status.value,
                        label=r.issue_key,
                        project_id=r.project_id,
                        agent=r.agent.value,
                        model=r.model,
                        location=r.location.value,
                        input_tokens=r.input_tokens,
                        output_tokens=r.output_tokens,
                        cost_usd=r.cost_usd,
                        error=r.error,
                        requested_by_id=r.requested_by_id,
                        created_at=r.created_at,
                        finished_at=r.finished_at,
                    )
                )

        found.sort(key=lambda r: (r.created_at, r.id), reverse=True)
        return found[offset : offset + limit]
