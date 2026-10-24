"""Transactional run dispatch and recovery before execution begins.

The caller records intent in its existing transaction, then attempts publication
after commit. A worker sweep republishes unaccepted intent using the same arq job
    ID for each delivery. Acceptance is transactional with the run becoming RUNNING. This does not
implement leases, side-effect reconciliation, or recovery of running coding jobs.
"""
from __future__ import annotations

import asyncio
import logging
import random
import time
import uuid
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from arq.jobs import Job, JobStatus
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from uuid_utils.compat import uuid7

from dotrix_backend.modules.agents.models import AgentRun, RunStatus
from dotrix_backend.modules.agents.queue import RunQueue
from dotrix_backend.modules.audit.models import AuthorType
from dotrix_backend.modules.audit.service import AuditLog
from dotrix_backend.modules.coding.models import CodingRun, CodingRunStatus

from .models import RunDispatch

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]
Run = AgentRun | CodingRun
DispatchKind = Literal["agent", "coding"]
PUBLISH_TIMEOUT_SECONDS = 5
ACK_WAIT_SECONDS = 30
RECONCILIATION_GRACE_SECONDS = 60


@dataclass(frozen=True)
class DispatchOperation:
    id: uuid.UUID
    workspace_id: uuid.UUID
    run_id: uuid.UUID
    generation: int
    kind: DispatchKind
    payload: dict[str, Any]


def record_dispatch(
    session: AsyncSession,
    run: Run,
    payload: dict[str, Any],
    *,
    queue_name: str,
) -> RunDispatch:
    """Add intent without committing. Existing runs must be locked by the caller."""
    if run.id is None:
        run.id = uuid7()
    run.dispatch_generation = (run.dispatch_generation or 0) + 1
    now = datetime.now(UTC)
    operation = RunDispatch(
        id=uuid7(), workspace_id=run.workspace_id,
        agent_run_id=run.id if isinstance(run, AgentRun) else None,
        coding_run_id=run.id if isinstance(run, CodingRun) else None,
        generation=run.dispatch_generation, queue_name=queue_name, payload=payload,
        created_at=now, next_attempt_at=now, publish_attempts=0,
    )
    session.add(operation)
    return operation


async def load_operation(
    session_factory: SessionFactory,
    *,
    workspace_id: uuid.UUID,
    dispatch_id: uuid.UUID,
    run_id: uuid.UUID,
    kind: DispatchKind,
) -> DispatchOperation | None:
    """Resolve an internal queue reference; a later transactional claim rechecks it."""
    target = RunDispatch.agent_run_id if kind == "agent" else RunDispatch.coding_run_id
    async with session_factory() as session:
        row = await session.scalar(select(RunDispatch).where(
            RunDispatch.workspace_id == workspace_id, RunDispatch.id == dispatch_id,
            target == run_id, RunDispatch.discarded_at.is_(None),
        ))
        if row is None:
            return None
        return DispatchOperation(
            row.id, row.workspace_id, run_id, row.generation, kind, row.payload,
        )


async def accept_operation(
    session: AsyncSession,
    run: Run,
    operation: DispatchOperation | None,
    *,
    retry: bool = False,
) -> bool:
    """Called with the run locked, in the transaction setting it to RUNNING.

    Legacy jobs can execute generation zero only. An old start/resume job cannot
    consume a newer approval round. Only arq retries of the same agent operation
    can re-enter an already accepted RUNNING run; coding never does so.
    """
    if operation is None:
        return not run.dispatch_generation
    kind = "agent" if isinstance(run, AgentRun) else "coding"
    if (
        operation.workspace_id != run.workspace_id or operation.run_id != run.id
        or operation.generation != run.dispatch_generation or operation.kind != kind
    ):
        return False
    target = RunDispatch.agent_run_id if kind == "agent" else RunDispatch.coding_run_id
    row = await session.scalar(select(RunDispatch).where(
        RunDispatch.workspace_id == run.workspace_id, RunDispatch.id == operation.id,
        target == run.id, RunDispatch.generation == run.dispatch_generation,
        RunDispatch.discarded_at.is_(None),
    ).with_for_update())
    if row is None:
        return False
    if row.accepted_at is not None:
        return bool(retry and isinstance(run, AgentRun) and run.status is RunStatus.RUNNING)
    if run.status.value != "queued":
        return False
    row.accepted_at = datetime.now(UTC)
    return True


def mark_coding_recovery_required(
    session: AsyncSession, run: CodingRun, *, reason: str, source: str,
) -> bool:
    """Classify an uncertain result without asserting that execution or a push failed."""
    if run.status is not CodingRunStatus.RUNNING:
        return False
    run.status, run.error = CodingRunStatus.RECOVERY_REQUIRED, reason
    AuditLog(session).record(
        workspace_id=run.workspace_id, project_id=run.project_id,
        action="coding.recovery_required", target=run.issue_key,
        actor_type=AuthorType.SYSTEM, instructed_by_id=run.requested_by_id,
        approved_by_id=run.decided_by_id,
        details={"run_id": str(run.id), "source": source, "workspace_recorded": bool(run.workspace_path)},
    )
    return True


async def expire_coding_leases(session_factory: SessionFactory, *, limit: int = 50) -> int:
    """Running coding runs whose worker stopped renewing its lease (it, or its host, died): their
    outcome is uncertain, so they need recovery. Never assumes they failed."""
    now = datetime.now(UTC)
    async with session_factory() as session:
        candidates = list((await session.execute(select(CodingRun.workspace_id, CodingRun.id).where(
            CodingRun.status == CodingRunStatus.RUNNING, CodingRun.lease_expires_at < now,
        ).order_by(CodingRun.lease_expires_at).limit(limit))).all())
    expired = 0
    for workspace_id, run_id in candidates:
        async with session_factory() as session:
            run = await session.scalar(select(CodingRun).where(
                CodingRun.workspace_id == workspace_id, CodingRun.id == run_id,
            ).with_for_update(skip_locked=True))
            if run is None or run.lease_expires_at is None or run.lease_expires_at >= now:
                continue  # renewed meanwhile, or another sweep has it
            if mark_coding_recovery_required(
                session, run, source="lease_expired",
                reason="Its worker stopped renewing its lease (it or its host stopped). Recovery checks "
                       "GitHub before anything runs again.",
            ):
                await session.commit()
                expired += 1
    return expired


class RunDispatcher:
    def __init__(self, session_factory: SessionFactory, queue: RunQueue) -> None:
        self.session_factory, self.queue = session_factory, queue

    async def kick(self, workspace_id: uuid.UUID, dispatch_id: uuid.UUID) -> None:
        """Best-effort low-latency wake-up after commit; the sweep owns retries."""
        try:
            await self.publish(workspace_id, dispatch_id)
        except Exception as exc:
            logger.warning("run dispatch %s deferred (%s)", dispatch_id, type(exc).__name__)

    async def publish(self, workspace_id: uuid.UUID, dispatch_id: uuid.UUID) -> bool:
        now = datetime.now(UTC)
        async with self.session_factory() as session:
            row = await session.scalar(select(RunDispatch).where(
                RunDispatch.workspace_id == workspace_id, RunDispatch.id == dispatch_id,
                RunDispatch.queue_name == self.queue.queue_name,
                RunDispatch.accepted_at.is_(None), RunDispatch.discarded_at.is_(None),
                RunDispatch.next_attempt_at <= now,
            ).with_for_update(skip_locked=True))
            if row is None:
                return False
            model = AgentRun if row.agent_run_id is not None else CodingRun
            run_id = row.agent_run_id or row.coding_run_id
            run = await session.scalar(select(model).where(
                model.workspace_id == workspace_id, model.id == run_id,
            ))
            if (
                run is None or run.dispatch_generation != row.generation
                or run.status.value != "queued"
                or (isinstance(run, CodingRun) and run.stop_requested)
            ):
                row.discarded_at, row.last_error = now, "superseded_or_inactive"
                await session.commit()
                return False
            row.publish_attempts += 1
            try:
                async with asyncio.timeout(PUBLISH_TIMEOUT_SECONDS):
                    delivery_id = f"dispatch:{row.id}:{row.delivery_generation}"
                    status = await Job(
                        delivery_id, self.queue.redis, _queue_name=self.queue.queue_name,
                    ).status()
                    if status is JobStatus.complete:
                        # The worker exhausted a delivery before accepting it. A
                        # retained result key prevents reuse of that arq job ID.
                        row.delivery_generation += 1
                        delivery_id = f"dispatch:{row.id}:{row.delivery_generation}"
                    elif status in (JobStatus.queued, JobStatus.deferred, JobStatus.in_progress):
                        row.published_at = row.published_at or now
                        row.next_attempt_at = now + timedelta(seconds=ACK_WAIT_SECONDS)
                        await session.commit()
                        return False
                    if row.agent_run_id is not None:
                        await self.queue.enqueue(
                            row.agent_run_id, None, operation_id=row.id, workspace_id=workspace_id,
                            delivery_generation=row.delivery_generation,
                        )
                    else:
                        await self.queue.redis.enqueue_job(
                            "run_coding", run_id=str(row.coding_run_id),
                            workspace_id=str(workspace_id), dispatch_id=str(row.id),
                            _job_id=delivery_id, _queue_name=self.queue.queue_name,
                        )
            except Exception as exc:
                row.last_error = type(exc).__name__[:100]
                delay = min(5 * 2 ** min(row.publish_attempts - 1, 6), 300)
                row.next_attempt_at = now + timedelta(seconds=delay * random.uniform(0.8, 1.2))
                await session.commit()
                logger.warning("run dispatch %s awaits publication (%s)", row.id, row.last_error)
                return False
            row.published_at, row.last_error = now, None
            # Reconcile publication until execution accepts it. This also recovers
            # Redis losing an enqueued job before a worker starts it.
            row.next_attempt_at = now + timedelta(seconds=ACK_WAIT_SECONDS)
            await session.commit()
            return True

    async def sweep(self, *, limit: int = 50, budget_seconds: float = 10) -> int:
        # The internal scheduler enumerates IDs across workspaces. Every subsequent
        # read/update is scoped to the workspace returned with that operation.
        async with self.session_factory() as session:
            candidates = list((await session.execute(select(
                RunDispatch.workspace_id, RunDispatch.id,
            ).where(
                RunDispatch.queue_name == self.queue.queue_name,
                RunDispatch.accepted_at.is_(None), RunDispatch.discarded_at.is_(None),
                RunDispatch.next_attempt_at <= datetime.now(UTC),
            ).order_by(RunDispatch.next_attempt_at, RunDispatch.id).limit(limit))).all())
        started, published = time.monotonic(), 0
        for workspace_id, dispatch_id in candidates:
            if time.monotonic() - started >= budget_seconds:
                break
            published += await self.publish(workspace_id, dispatch_id)
        return published

    async def reconcile_coding(self, *, limit: int = 50, budget_seconds: float = 10) -> int:
        """Flag accepted coding jobs missing from arq; never replay their side effects."""
        cutoff = datetime.now(UTC) - timedelta(seconds=RECONCILIATION_GRACE_SECONDS)
        async with self.session_factory() as session:
            candidates = list((await session.execute(select(
                RunDispatch.workspace_id, RunDispatch.id, RunDispatch.coding_run_id,
                RunDispatch.delivery_generation,
            ).join(CodingRun, CodingRun.id == RunDispatch.coding_run_id).where(
                RunDispatch.queue_name == self.queue.queue_name,
                RunDispatch.coding_run_id.is_not(None), RunDispatch.accepted_at <= cutoff,
                CodingRun.status == CodingRunStatus.RUNNING,
            ).order_by(RunDispatch.accepted_at).limit(limit))).all())
        started, classified = time.monotonic(), 0
        for workspace_id, dispatch_id, run_id, delivery_generation in candidates:
            if time.monotonic() - started >= budget_seconds:
                break
            try:
                async with asyncio.timeout(PUBLISH_TIMEOUT_SECONDS):
                    status = await Job(
                        f"dispatch:{dispatch_id}:{delivery_generation}", self.queue.redis,
                        _queue_name=self.queue.queue_name,
                    ).status()
            except Exception as exc:
                logger.warning("coding dispatch %s could not be inspected (%s)", dispatch_id, type(exc).__name__)
                continue
            if status not in (JobStatus.complete, JobStatus.not_found):
                continue
            reason = (
                "The worker finished without recording an outcome. A branch or PR may already exist; "
                "inspect GitHub and the recorded workspace reference before another coding turn."
                if status is JobStatus.complete else
                "The worker queue no longer tracks this run. It may still be active; inspect its "
                "process, GitHub branch or PR, and recorded workspace before another coding turn."
            )
            async with self.session_factory() as session:
                run = await session.scalar(select(CodingRun).where(
                    CodingRun.workspace_id == workspace_id, CodingRun.id == run_id,
                ).with_for_update(skip_locked=True))
                if run is None or run.status is not CodingRunStatus.RUNNING:
                    continue
                operation = await session.scalar(select(RunDispatch).where(
                    RunDispatch.workspace_id == workspace_id, RunDispatch.id == dispatch_id,
                    RunDispatch.coding_run_id == run_id, RunDispatch.accepted_at.is_not(None),
                ).with_for_update(skip_locked=True))
                if operation is None or operation.delivery_generation != delivery_generation:
                    continue
                if mark_coding_recovery_required(session, run, reason=reason, source=f"arq:{status.value}"):
                    await session.commit()
                    classified += 1
        return classified
