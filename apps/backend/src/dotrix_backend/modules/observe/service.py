"""The observability reads behind Ops: the workspace's health in one query set, and a
unified run history across chat and coding. Reads only — the numbers come from the modules'
own tables. Runs stay under the same privacy as everywhere else (each person sees their own,
plus what's waiting on a decision they may make)."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import func, select
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
from dotrix_backend.modules.workspaces.models import Membership

from .schemas import (
    ObserveCounts,
    ObservedRun,
    ObserveOverview,
    ObserveQueue,
    RunGroupSummary,
)


class ObserveService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    async def overview(self, member: Membership) -> ObserveOverview:
        """Workspace counts, visible runs and dispatches, and runs with lapsed leases."""
        ws = member.workspace_id
        now = datetime.now(UTC)
        since = now - timedelta(days=7)

        async def scalar(stmt) -> int:
            return int((await self.session.execute(stmt)).scalar() or 0)

        counts = ObserveCounts(
            projects=await scalar(
                select(func.count(Project.id)).where(
                    Project.workspace_id == ws, visible_to(member.user_id, member.role)
                )
            ),
            members=await scalar(select(func.count(Membership.id)).where(Membership.workspace_id == ws)),
            documents=await scalar(select(func.count(Document.id)).where(Document.workspace_id == ws)),
            document_bytes=await scalar(
                select(func.coalesce(func.sum(Document.size), 0)).where(Document.workspace_id == ws)
            ),
            coding_runners=await scalar(
                select(func.count(CodingRunner.id)).where(CodingRunner.workspace_id == ws)
            ),
        )

        chat = await self._run_summary(
            member,
            since,
            model=AgentRun,
            scope=runs_visible_to(member),
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
            scope=visible_runs(member),
            active=CodingRun.status.in_(
                (CodingRunStatus.QUEUED, CodingRunStatus.RUNNING)
            ),
            waiting=CodingRun.status.in_(CODING_WAITING),
            failed=CodingRun.status == CodingRunStatus.FAILED,
            tokens_in=CodingRun.input_tokens,
            tokens_out=CodingRun.output_tokens,
            cost=CodingRun.cost_usd,
        )

        # The queue only counts dispatches for runs the member may see: a private run's
        # pending dispatch would otherwise hint at a conversation they can't open.
        visible = (
            RunDispatch.agent_run_id.in_(select(AgentRun.id).where(AgentRun.workspace_id == ws, runs_visible_to(member)))
            | RunDispatch.coding_run_id.in_(select(CodingRun.id).where(CodingRun.workspace_id == ws, visible_runs(member)))
        )
        pending = select(func.count(RunDispatch.id)).where(
            RunDispatch.workspace_id == ws,
            RunDispatch.accepted_at.is_(None),
            RunDispatch.discarded_at.is_(None),
            visible,
        )
        oldest = await self.session.scalar(
            select(func.min(RunDispatch.created_at)).where(
                RunDispatch.workspace_id == ws,
                RunDispatch.accepted_at.is_(None),
                RunDispatch.discarded_at.is_(None),
                visible,
            )
        )
        queue = ObserveQueue(
            pending=await scalar(pending),
            oldest_pending_seconds=(now - oldest).total_seconds() if oldest is not None else None,
            discarded_7d=await scalar(
                select(func.count(RunDispatch.id)).where(
                    RunDispatch.workspace_id == ws, RunDispatch.discarded_at >= since, visible
                )
            ),
        )

        stuck = (
            await scalar(
                select(func.count(AgentRun.id)).where(
                    AgentRun.workspace_id == ws,
                    AgentRun.status.in_(ACTIVE_STATUSES),
                    AgentRun.lease_expires_at < now,
                    runs_visible_to(member),
                )
            )
            + await scalar(
                select(func.count(CodingRun.id)).where(
                    CodingRun.workspace_id == ws,
                    CodingRun.status.in_(CODING_ACTIVE),
                    CodingRun.lease_expires_at < now,
                    visible_runs(member),
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
        member: Membership,
        since: datetime,
        *,
        model,
        scope,
        active,
        waiting,
        failed,
        tokens_in,
        tokens_out,
        calls=None,
        cost=None,
    ) -> RunGroupSummary:
        ws = member.workspace_id

        async def scalar(stmt) -> int | float:
            return (await self.session.execute(stmt)).scalar() or 0

        return RunGroupSummary(
            total=await scalar(select(func.count(model.id)).where(model.workspace_id == ws, scope)),
            active=await scalar(select(func.count(model.id)).where(model.workspace_id == ws, scope, active)),
            waiting=await scalar(select(func.count(model.id)).where(model.workspace_id == ws, scope, waiting)),
            failed_7d=await scalar(
                select(func.count(model.id)).where(model.workspace_id == ws, scope, failed, model.finished_at >= since)
            ),
            input_tokens_7d=await scalar(
                select(func.coalesce(func.sum(tokens_in), 0)).where(model.workspace_id == ws, scope, model.created_at >= since)
            ),
            output_tokens_7d=await scalar(
                select(func.coalesce(func.sum(tokens_out), 0)).where(model.workspace_id == ws, scope, model.created_at >= since)
            ),
            model_calls_7d=await scalar(
                select(func.coalesce(func.sum(calls), 0)).where(model.workspace_id == ws, scope, model.created_at >= since)
            )
            if calls is not None
            else 0,
            cost_usd_7d=float(
                await scalar(
                    select(func.coalesce(func.sum(cost), 0)).where(model.workspace_id == ws, scope, model.created_at >= since)
                )
            )
            if cost is not None
            else None,
        )

    async def runs(
        self,
        member: Membership,
        *,
        kind: Literal["chat", "coding"] | None = None,
        before: datetime | None = None,
        limit: int = 50,
    ) -> list[ObservedRun]:
        """The workspace's recent runs in one list (chat and coding), newest first. Each kind is
        fetched at `limit` and merged, so paging `before` the last row is exact."""
        ws = member.workspace_id
        found: list[ObservedRun] = []

        if kind in (None, "chat"):
            stmt = (
                select(AgentRun)
                .where(AgentRun.workspace_id == ws, runs_visible_to(member))
                .order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
                .limit(limit)
            )
            if before is not None:
                stmt = stmt.where(AgentRun.created_at < before)
            for r in await self.session.scalars(stmt):
                found.append(
                    ObservedRun(
                        kind="chat",
                        id=r.id,
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
                .where(CodingRun.workspace_id == ws, visible_runs(member))
                .order_by(CodingRun.created_at.desc(), CodingRun.id.desc())
                .limit(limit)
            )
            if before is not None:
                stmt = stmt.where(CodingRun.created_at < before)
            for r in await self.session.scalars(stmt):
                found.append(
                    ObservedRun(
                        kind="coding",
                        id=r.id,
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
        return found[:limit]
