"""Messages a person sends a coding session while Kai works, as in Claude Code: steering the turn that's working
now (it takes the message at its next step), or queued for the session's next turn.

Only whoever started the session sends them, sees them and cancels them, as with the session itself. A steer goes
only to a cloud fx turn (`accepts_steering`): the worker drops it in the turn's inbox in the sandbox once the driver
says it's open, and records what the driver reports (sent, accepted, delivered, cancelled, rejected). A steer the
turn didn't take before it ended is queued instead, so nothing a person sent is lost; Stop cancels what's left.
Queued messages, once nothing in the session waits or works and its last turn finished, become one follow-up turn
in the order they were sent, through the same follow-up path (and so the same access, approval and model checks)
as a message sent then. A turn that failed, was stopped or whose changes were rejected cancels them: the person
decides what comes next.
"""
from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession
from uuid_utils.compat import uuid7

from dotrix_backend.core.errors import Conflict, DomainError, Forbidden, NotFound, Unprocessable
from dotrix_backend.modules.audit.service import AuditLog
from dotrix_backend.modules.knowledge.models import AuthorType
from dotrix_backend.modules.projects.deps import ProjectAccess
from dotrix_backend.modules.projects.repository import ProjectRepository
from dotrix_backend.modules.workspaces.permissions import Permission, can
from dotrix_backend.modules.workspaces.repository import MembershipRepository

from .models import (
    ACTIVE,
    CodingAgent,
    CodingInput,
    CodingInputKind,
    CodingInputStatus,
    CodingLocation,
    CodingRun,
    CodingRunStatus,
)
from .schemas import CodingFollowUp, CodingInputCreate, CodingInputRead

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]
MAX_PENDING = 20  # a session's messages waiting at once
_FOLLOW_UP_CHARS = 5_000  # CodingFollowUp.message: queued messages join into one turn up to this
_OPEN = (CodingInputStatus.PENDING, CodingInputStatus.SENDING, CodingInputStatus.ACCEPTED)
# A session's last turn ended so that what was queued behind it no longer follows on its own.
_ENDS_THE_QUEUE = {
    CodingRunStatus.FAILED: "Kai's turn failed; send it again when you're ready",
    CodingRunStatus.STOPPED: "The turn was stopped",
    CodingRunStatus.REJECTED: "The turn was rejected or its changes discarded; send it again when you're ready",
}


def now() -> datetime:
    return datetime.now(UTC)


def accepts_steering(run: CodingRun) -> bool:
    """Whether a message can steer this turn now: a cloud fx turn that's working (fx takes a steering prompt into
    the running turn; the other engines don't), and not a parallel build, whose tasks run as separate turns."""
    return (run.status is CodingRunStatus.RUNNING and run.agent is CodingAgent.FX
            and run.location is CodingLocation.CLOUD and not run.execution_plan)


def _audit(session: AsyncSession, item: CodingInput, action: str) -> None:
    AuditLog(session).record(
        workspace_id=item.workspace_id, project_id=item.project_id, action=f"coding_input.{action}", target=str(item.id),
        actor_type=AuthorType.USER, actor_user_id=item.owner_id, instructed_by_id=item.owner_id,
        details={"kind": str(item.kind), "session_id": str(item.session_id), "run_id": str(item.run_id)},
    )


def _read(item: CodingInput) -> CodingInputRead:
    return CodingInputRead.model_validate(item)


async def _owned_turns(session: AsyncSession, access: ProjectAccess, session_id: uuid.UUID) -> list[CodingRun]:
    turns = list(await session.scalars(select(CodingRun).where(
        CodingRun.workspace_id == access.project.workspace_id, CodingRun.project_id == access.project.id,
        CodingRun.session_id == session_id,
    ).order_by(CodingRun.turn, CodingRun.created_at)))
    if not turns or turns[0].requested_by_id != access.member.user_id:
        raise NotFound("Coding session not found")  # private: someone else's session isn't here for you
    return turns


async def session_inputs(session: AsyncSession, access: ProjectAccess, session_id: uuid.UUID) -> list[CodingInputRead]:
    """Your messages to one of your sessions, the waiting ones first, then the latest."""
    await _owned_turns(session, access, session_id)
    rows = await session.scalars(select(CodingInput).where(
        CodingInput.workspace_id == access.project.workspace_id, CodingInput.project_id == access.project.id,
        CodingInput.session_id == session_id, CodingInput.owner_id == access.member.user_id,
    ).order_by(CodingInput.created_at.desc(), CodingInput.id.desc()).limit(100))
    items = list(rows)
    items.sort(key=lambda i: (i.status not in _OPEN, -i.created_at.timestamp()))
    return [_read(i) for i in items]


async def submit(session: AsyncSession, access: ProjectAccess, session_id: uuid.UUID,
                 data: CodingInputCreate) -> CodingInputRead:
    """Steer the working turn, or queue a message for the next. The same `client_id` again returns the same
    message (a retry); with different content, a conflict."""
    await ProjectRepository(session).get(access.project.workspace_id, access.project.id, for_update=True)
    message = data.message.strip()
    payload = data.model_dump(mode="json", include={"work_mode", "approval_mode"}, exclude_none=True)
    existing = await session.scalar(select(CodingInput).where(
        CodingInput.workspace_id == access.project.workspace_id, CodingInput.owner_id == access.member.user_id,
        CodingInput.client_id == data.client_id,
    ))
    if existing is not None:
        if (existing.session_id != session_id or existing.kind != data.kind or existing.message != message
                or (existing.payload or {}) != payload):
            raise Conflict("This message ID was already used for another message")
        return _read(existing)
    if not message:
        raise Unprocessable("Enter a message")
    turns = await _owned_turns(session, access, session_id)
    latest = turns[-1]
    if latest.status not in ACTIVE:
        raise Conflict("Kai isn't working in this session; send it as a follow-up")
    if data.kind is CodingInputKind.STEER and not accepts_steering(latest):
        raise Conflict("This turn can't take a message while it works; queue it for the next turn")
    waiting = await session.scalar(select(CodingInput.id).where(
        CodingInput.workspace_id == access.project.workspace_id, CodingInput.session_id == session_id,
        CodingInput.owner_id == access.member.user_id, CodingInput.status.in_(_OPEN),
    ).offset(MAX_PENDING - 1).limit(1))
    if waiting is not None:
        raise Conflict(f"This session already has {MAX_PENDING} messages waiting")
    at = now()
    item = CodingInput(
        id=uuid7(), workspace_id=access.project.workspace_id, project_id=access.project.id, session_id=session_id,
        owner_id=access.member.user_id, client_id=data.client_id, run_id=latest.id, kind=data.kind,
        status=CodingInputStatus.PENDING, message=message, payload=payload, created_at=at, updated_at=at,
    )
    session.add(item)
    _audit(session, item, "submitted")
    await session.commit()
    return _read(item)


async def cancel(session: AsyncSession, access: ProjectAccess, session_id: uuid.UUID, input_id: uuid.UUID) -> CodingInputRead:
    """Take back a message that hasn't reached Kai yet."""
    await ProjectRepository(session).get(access.project.workspace_id, access.project.id, for_update=True)
    await _owned_turns(session, access, session_id)
    item = await session.scalar(select(CodingInput).where(
        CodingInput.workspace_id == access.project.workspace_id, CodingInput.session_id == session_id,
        CodingInput.owner_id == access.member.user_id, CodingInput.id == input_id,
    ).with_for_update())
    if item is None:
        raise NotFound("Message not found")
    if item.status is CodingInputStatus.CANCELLED:
        return _read(item)
    if item.status is not CodingInputStatus.PENDING:
        raise Conflict("Kai already has this message")
    item.status, item.note, item.updated_at = CodingInputStatus.CANCELLED, "Cancelled", now()
    _audit(session, item, "cancelled")
    await session.commit()
    return _read(item)


# -- The worker: a working turn's steers ------------------------------------------------------------------------


async def take_steers(sessions: SessionFactory, run_id: uuid.UUID) -> list[tuple[uuid.UUID, str]]:
    """The steers for a working turn not yet in its inbox, oldest first, marked sending (the caller drops each in
    the inbox; one it couldn't goes back with `steer_states(..., "pending")`)."""
    async with sessions() as session:
        run = await session.get(CodingRun, run_id)
        if run is None or not accepts_steering(run):
            return []
        rows = list(await session.scalars(select(CodingInput).where(
            CodingInput.workspace_id == run.workspace_id, CodingInput.run_id == run_id,
            CodingInput.owner_id == run.requested_by_id, CodingInput.kind == CodingInputKind.STEER,
            CodingInput.status == CodingInputStatus.PENDING,
        ).order_by(CodingInput.created_at, CodingInput.id).with_for_update(skip_locked=True)))
        for item in rows:
            item.status, item.updated_at = CodingInputStatus.SENDING, now()
        await session.commit()
        return [(item.id, item.message) for item in rows]


_REPORTED = {
    "pending": CodingInputStatus.PENDING,
    "sent": CodingInputStatus.SENDING,
    "accepted": CodingInputStatus.ACCEPTED,
    "delivered": CodingInputStatus.DELIVERED,
    "cancelled": CodingInputStatus.CANCELLED,
    "rejected": CodingInputStatus.REJECTED,
}
_ORDER = [CodingInputStatus.PENDING, CodingInputStatus.SENDING, CodingInputStatus.ACCEPTED]


async def steer_states(sessions: SessionFactory, run_id: uuid.UUID, reports: list[tuple[str, str, str | None]]) -> None:
    """Record what the driver reported for a turn's steers. A state never goes back (a late `sent` after
    `accepted`), and a settled one (delivered, cancelled, rejected) stays."""
    if not reports:
        return
    async with sessions() as session:
        run = await session.get(CodingRun, run_id)
        if run is None:
            return
        for key, state, message in reports:
            try:
                input_id = uuid.UUID(key)
            except ValueError:
                continue
            item = await session.scalar(select(CodingInput).where(
                CodingInput.workspace_id == run.workspace_id, CodingInput.run_id == run_id, CodingInput.id == input_id,
                CodingInput.kind == CodingInputKind.STEER,
            ).with_for_update())
            target = _REPORTED.get(state)
            if item is None or target is None or item.status not in _OPEN:
                continue
            if target in _ORDER and _ORDER.index(target) < _ORDER.index(item.status) and state != "pending":
                continue
            item.status, item.updated_at = target, now()
            if target is CodingInputStatus.REJECTED:
                item.note = (message or "Kai couldn't take the message")[:200]
            if target in (CodingInputStatus.DELIVERED, CodingInputStatus.ACCEPTED):
                item.delivered_run_id = run_id
            if target in (CodingInputStatus.DELIVERED, CodingInputStatus.REJECTED, CodingInputStatus.ACCEPTED):
                _audit(session, item, str(target))
        await session.commit()


async def settle_steers(session: AsyncSession, run: CodingRun) -> None:
    """A turn that no longer works: a steer it took is delivered; one it never took goes to the next turn
    (queued), or is cancelled when the turn was stopped or failed. The caller commits."""
    stopped = run.status in _ENDS_THE_QUEUE
    for item in await session.scalars(select(CodingInput).where(
        CodingInput.workspace_id == run.workspace_id, CodingInput.run_id == run.id,
        CodingInput.kind == CodingInputKind.STEER, CodingInput.status.in_(_OPEN),
    ).with_for_update()):
        if item.status is CodingInputStatus.ACCEPTED:
            item.status, item.delivered_run_id = CodingInputStatus.DELIVERED, run.id
        elif stopped:
            item.status, item.note = CodingInputStatus.CANCELLED, _ENDS_THE_QUEUE[run.status]
        else:
            item.kind, item.status = CodingInputKind.QUEUE, CodingInputStatus.PENDING
            item.note = "Arrived as Kai's turn finished: sent as the next turn"
        item.updated_at = now()


# -- Queued messages: the session's next turn --------------------------------------------------------------------


async def deliver_queued(sessions: SessionFactory, make_service: Callable[[AsyncSession], Any], *,
                         session_id: uuid.UUID | None = None) -> int:
    """Each session whose queued messages can go now: its steers settled, then its queued messages as one
    follow-up turn (or cancelled, after a turn that failed, was stopped or rejected). Returns the turns made."""
    async with sessions() as session:
        query = select(CodingInput.session_id, CodingInput.workspace_id).where(
            CodingInput.status.in_(_OPEN),
            ~exists(select(CodingRun.id).where(  # a session still waiting or working takes nothing yet
                CodingRun.workspace_id == CodingInput.workspace_id, CodingRun.session_id == CodingInput.session_id,
                CodingRun.status.in_(ACTIVE),
            )),
        ).distinct()
        if session_id is not None:
            query = query.where(CodingInput.session_id == session_id)
        candidates = list((await session.execute(query.limit(100))).all())
    made = 0
    for candidate, workspace_id in candidates:
        try:
            made += await _deliver(sessions, make_service, workspace_id, candidate)
        except Exception:
            logger.exception("coding session %s: queued messages weren't delivered", candidate)
    return made


async def _deliver(sessions: SessionFactory, make_service: Callable[[AsyncSession], Any], workspace_id: uuid.UUID,
                   session_id: uuid.UUID) -> int:
    from .service import CodingService

    async with sessions() as session:
        turns = list(await session.scalars(select(CodingRun).where(
            CodingRun.workspace_id == workspace_id, CodingRun.session_id == session_id,
        ).order_by(CodingRun.turn, CodingRun.created_at)))
        if not turns:
            return 0
        project = await ProjectRepository(session).get(workspace_id, turns[0].project_id, for_update=True)
        # Settle every finished turn's steers first: what it didn't take joins the queue (or is cancelled).
        for turn in turns:
            if turn.status is not CodingRunStatus.RUNNING:
                await settle_steers(session, turn)
        await session.flush()
        latest = turns[-1]
        if latest.status in ACTIVE:
            await session.commit()
            return 0
        queued = list(await session.scalars(select(CodingInput).where(
            CodingInput.workspace_id == workspace_id, CodingInput.session_id == session_id,
            CodingInput.kind == CodingInputKind.QUEUE, CodingInput.status == CodingInputStatus.PENDING,
        ).order_by(CodingInput.created_at, CodingInput.id).with_for_update()))
        if not queued:
            await session.commit()
            return 0
        reason = _ENDS_THE_QUEUE.get(latest.status)
        if reason is not None:
            for item in queued:
                item.status, item.note, item.updated_at = CodingInputStatus.CANCELLED, reason, now()
                _audit(session, item, "cancelled")
            await session.commit()
            return 0
        taking, size = [], 0
        for item in queued:
            if taking and size + len(item.message) + 2 > _FOLLOW_UP_CHARS:
                break
            taking.append(item)
            size += len(item.message) + 2
        first = taking[0]
        taken = [item.id for item in taking]  # read now: a rollback below expires the rows
        member = await MembershipRepository(session).get(workspace_id, first.owner_id)
        try:
            if (project is None or member is None or not can(member, Permission.INSTRUCT_CODING_AGENT)
                    or await ProjectRepository(session).visible(member, project.id) is None):
                raise Forbidden("You can no longer instruct Kai in this project")
            payload = first.payload or {}
            text = "\n\n".join(item.message for item in taking)[:_FOLLOW_UP_CHARS]
            follow = CodingFollowUp(message=text, work_mode=payload.get("work_mode") or latest.work_mode or "build",
                                    approval_mode=payload.get("approval_mode") or latest.approval_mode)
            service: CodingService = make_service(session)
            at = now()
            for item in taking:  # committed with the turn, by follow_up
                item.status, item.updated_at = CodingInputStatus.DELIVERED, at
                _audit(session, item, "delivered")
            turn = await service.follow_up(ProjectAccess(project, member), session_id, follow)
        except DomainError as exc:
            await session.rollback()
            async with sessions() as again:
                for key in taken:
                    row = await again.get(CodingInput, key, with_for_update=True)
                    if row is not None and row.status is CodingInputStatus.PENDING:
                        row.status, row.note, row.updated_at = CodingInputStatus.REJECTED, str(exc.detail)[:200], now()
                        _audit(again, row, "rejected")
                await again.commit()
            return 0
        async with sessions() as again:
            for key in taken:
                row = await again.get(CodingInput, key, with_for_update=True)
                if row is not None:
                    row.delivered_run_id = turn.id
            await again.commit()
        return 1



async def deliver_for_job(ctx: Any, run_id: uuid.UUID | None = None) -> int:
    """`deliver_queued` from a job's context (the worker, or local jobs): after a turn's job ends, for its session,
    and from the worker's sweep for every session (`run_id` None)."""
    from .service import CodingService

    coding, queue = getattr(ctx, "coding", None), getattr(ctx, "jobs", None)
    if queue is None:
        return 0

    def make(session: AsyncSession) -> CodingService:
        return CodingService(session, ctx.settings, queue, secrets=getattr(coding, "secrets", None),
                             github=getattr(coding, "app", None))

    session_id = None
    if run_id is not None:
        async with ctx.session_factory() as session:
            session_id = await session.scalar(select(CodingRun.session_id).where(CodingRun.id == run_id))
        if session_id is None:
            return 0
    return await deliver_queued(ctx.session_factory, make, session_id=session_id)
