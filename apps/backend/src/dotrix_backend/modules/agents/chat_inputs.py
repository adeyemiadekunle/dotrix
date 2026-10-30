"""Host-owned, private chat input ordering and delivery for both runtimes."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage
from sqlalchemy import case, exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from uuid_utils.compat import uuid7

from dotrix_backend.core.errors import Conflict, DomainError, Forbidden, NotFound, Unprocessable
from dotrix_backend.modules.audit.service import AuditLog
from dotrix_backend.modules.knowledge.models import AuthorType
from dotrix_backend.modules.projects.deps import ProjectAccess
from dotrix_backend.modules.projects.repository import ProjectRepository
from dotrix_backend.modules.workspaces.permissions import Permission, can
from dotrix_backend.modules.workspaces.repository import MembershipRepository

from .models import ACTIVE_STATUSES, AgentRun, ChatInput, RunKind, RunStatus
from .runtime_sessions import admit_runtime_run
from .schemas import ChatInputCreate, ChatInputRead, RunCreate
from .storage_backend import SessionFactory

STEERING_MARK = "dotrix_chat_steering"

if TYPE_CHECKING:
    from .runner import AgentRunner


def now() -> datetime:
    return datetime.now(UTC)


def audit(session: AsyncSession, item: ChatInput, action: str) -> None:
    AuditLog(session).record(workspace_id=item.workspace_id, project_id=item.project_id,
        action=f"chat_input.{action}", target=str(item.id), actor_type=AuthorType.USER,
        actor_user_id=item.owner_id, instructed_by_id=item.owner_id,
        details={"kind": item.kind, "run_id": str(item.run_id)})


async def owned_thread(session: AsyncSession, access: ProjectAccess, thread_id: uuid.UUID, *,
                       for_update: bool = False) -> AgentRun:
    query = select(AgentRun).where(
        AgentRun.workspace_id == access.project.workspace_id, AgentRun.project_id == access.project.id,
        AgentRun.thread_id == thread_id, AgentRun.requested_by_id == access.member.user_id,
        AgentRun.parent_run_id.is_(None), AgentRun.source == "user", AgentRun.kind == RunKind.CHAT,
        AgentRun.automation_id.is_(None),
    ).order_by(AgentRun.created_at.desc(), AgentRun.id.desc()).limit(1)
    run = await session.scalar(query.with_for_update() if for_update else query)
    if run is None:
        raise NotFound("Conversation not found")
    return run


async def inputs(session: AsyncSession, access: ProjectAccess, thread_id: uuid.UUID) -> list[ChatInput]:
    await owned_thread(session, access, thread_id)
    return list(await session.scalars(select(ChatInput).where(
        ChatInput.workspace_id == access.project.workspace_id, ChatInput.project_id == access.project.id,
        ChatInput.thread_id == thread_id, ChatInput.owner_id == access.member.user_id,
    ).order_by(case((ChatInput.status.in_(("pending", "sending")), 0), else_=1),
               ChatInput.created_at.desc(), ChatInput.id.desc()).limit(100)))


async def submit(session: AsyncSession, access: ProjectAccess, thread_id: uuid.UUID, data: ChatInputCreate) -> ChatInputRead:
    project = await ProjectRepository(session).get(access.project.workspace_id, access.project.id, for_update=True)
    existing = await session.scalar(select(ChatInput).where(
        ChatInput.workspace_id == project.workspace_id, ChatInput.project_id == project.id,
        ChatInput.owner_id == access.member.user_id, ChatInput.client_id == data.client_id,
    ))
    payload = data.model_dump(mode="json", exclude={"client_id", "kind", "message"})
    if existing:
        if (existing.project_id != project.id or existing.thread_id != thread_id or existing.kind != data.kind
                or existing.message != data.message.strip() or existing.payload != payload):
            raise Conflict("This chat input ID was already used for another instruction")
        return ChatInputRead.model_validate(existing)
    run = await owned_thread(session, access, thread_id, for_update=True)
    if run.status not in ACTIVE_STATUSES:
        raise Conflict("The conversation is idle; send a normal message")
    if data.kind == "steer" and run.status is RunStatus.AWAITING_APPROVAL:
        raise Conflict("Decide the pending approval before steering this turn")
    if not data.message.strip():
        raise Unprocessable("Enter an instruction")
    pending = await session.scalar(select(ChatInput.id).where(
        ChatInput.workspace_id == project.workspace_id, ChatInput.project_id == project.id,
        ChatInput.owner_id == access.member.user_id, ChatInput.thread_id == thread_id,
        ChatInput.status.in_(("pending", "sending")),
    ).offset(19).limit(1))
    if pending:
        raise Conflict("This conversation already has 20 pending instructions")
    item = ChatInput(id=uuid7(), workspace_id=project.workspace_id, project_id=project.id,
        owner_id=access.member.user_id, thread_id=thread_id, run_id=run.id, client_id=data.client_id,
        kind=data.kind, status="pending", message=data.message.strip(), payload=payload,
        created_at=now(), updated_at=now())
    session.add(item)
    audit(session, item, "submitted")
    await session.commit()
    return ChatInputRead.model_validate(item)


async def cancel(session: AsyncSession, access: ProjectAccess, thread_id: uuid.UUID, input_id: uuid.UUID) -> ChatInputRead:
    await ProjectRepository(session).get(access.project.workspace_id, access.project.id, for_update=True)
    await owned_thread(session, access, thread_id)
    item = await session.scalar(select(ChatInput).where(
        ChatInput.workspace_id == access.project.workspace_id, ChatInput.project_id == access.project.id,
        ChatInput.thread_id == thread_id, ChatInput.owner_id == access.member.user_id, ChatInput.id == input_id,
    ).with_for_update())
    if item is None:
        raise NotFound("Instruction not found")
    if item.status == "cancelled":
        return ChatInputRead.model_validate(item)
    if item.status != "pending":
        raise Conflict("This instruction has already entered delivery")
    item.status, item.updated_at = "cancelled", now()
    audit(session, item, "cancelled")
    await session.commit()
    return ChatInputRead.model_validate(item)


async def steering(sessions: SessionFactory, workspace_id: uuid.UUID, run_id: uuid.UUID, token: int,
                   messages: Any = ()) -> list[tuple[uuid.UUID, str]]:
    """Reserve inputs under the lease. Stable message IDs survive checkpoint retries."""
    async with sessions() as session:
        run = await admit_runtime_run(session, workspace_id, run_id, token)
        seen = {getattr(message, "id", None) for message in messages}
        rows = list(await session.scalars(select(ChatInput).where(
            ChatInput.workspace_id == workspace_id, ChatInput.run_id == run_id,
            ChatInput.owner_id == run.requested_by_id, ChatInput.kind == "steer",
            ChatInput.status.in_(("pending", "sending")),
        ).order_by(ChatInput.created_at, ChatInput.id).with_for_update()))
        result = []
        for item in rows:
            if str(item.id) in seen:
                item.status = "accepted"
                audit(session, item, "accepted")
            else:
                item.status = "sending"
                result.append((item.id, item.message))
            item.updated_at = now()
        await session.commit()
        return result


async def accepted(sessions: SessionFactory, workspace_id: uuid.UUID, run_id: uuid.UUID, token: int,
                   input_id: uuid.UUID) -> None:
    async with sessions() as session:
        await admit_runtime_run(session, workspace_id, run_id, token)
        item = await session.scalar(select(ChatInput).where(
            ChatInput.workspace_id == workspace_id, ChatInput.run_id == run_id, ChatInput.id == input_id,
        ).with_for_update())
        if item is not None and item.status == "sending":
            item.status, item.updated_at = "accepted", now()
            audit(session, item, "accepted")
            await session.commit()


class ChatSteering(AgentMiddleware):
    def __init__(self, sessions, workspace_id, run_id, token):
        self.sessions, self.workspace_id, self.run_id, self.token = sessions, workspace_id, run_id, token

    async def abefore_model(self, state, runtime):
        rows = await steering(self.sessions, self.workspace_id, self.run_id, self.token, state["messages"])
        if rows:
            return {"messages": [HumanMessage(content=text, id=str(key), additional_kwargs={STEERING_MARK: True}) for key, text in rows]}
        return None


async def finish_steering(session: AsyncSession, run: AgentRun, messages: Any = ()) -> None:
    seen = {getattr(message, "id", None) for message in messages}
    for item in await session.scalars(select(ChatInput).where(
        ChatInput.workspace_id == run.workspace_id, ChatInput.run_id == run.id, ChatInput.kind == "steer",
        ChatInput.status.in_(("pending", "sending")),
    ).with_for_update()):
        if str(item.id) in seen:
            item.status = "accepted"
            audit(session, item, "accepted")
        elif run.status not in ACTIVE_STATUSES:
            item.status, item.error = "rejected", "The turn ended before delivery could be confirmed"
        item.updated_at = now()


async def deliver_queued(sessions: SessionFactory, runner: AgentRunner, *, workspace_id: uuid.UUID | None = None,
                         thread_id: uuid.UUID | None = None) -> int:
    """One next turn per conversation; outbox publication and input delivery commit together."""
    from .service import AgentService

    async with sessions() as session:
        # Waiting conversations must not occupy the whole sweep's candidate page.
        same_thread = (
            AgentRun.workspace_id == ChatInput.workspace_id, AgentRun.project_id == ChatInput.project_id,
            AgentRun.thread_id == ChatInput.thread_id, AgentRun.parent_run_id.is_(None),
        )
        latest = select(AgentRun).where(*same_thread, AgentRun.requested_by_id == ChatInput.owner_id,
            AgentRun.source == "user").order_by(AgentRun.created_at.desc(), AgentRun.id.desc()).limit(1)
        latest_status = latest.with_only_columns(AgentRun.status).scalar_subquery()
        latest_error = latest.with_only_columns(AgentRun.error_kind).scalar_subquery()
        query = select(ChatInput.id, ChatInput.workspace_id, ChatInput.project_id).where(
            ChatInput.kind == "queue", ChatInput.status == "pending",
            ~exists(select(AgentRun.id).where(*same_thread, AgentRun.status.in_(ACTIVE_STATUSES))),
            or_(latest_status != RunStatus.FAILED, latest_error.is_(None),
                latest_error.not_in(("model_limit", "interrupted"))))
        if workspace_id is not None:
            query = query.where(ChatInput.workspace_id == workspace_id, ChatInput.thread_id == thread_id)
        candidates = list((await session.execute(query.order_by(ChatInput.created_at, ChatInput.id).limit(100))).all())
    delivered = 0
    for item_id, workspace, project_id in candidates:
        async with sessions() as session:
            project = await ProjectRepository(session).get(workspace, project_id, for_update=True)
            item = await session.scalar(select(ChatInput).where(ChatInput.workspace_id == workspace,
                ChatInput.id == item_id, ChatInput.status == "pending").with_for_update())
            if item is None:
                continue
            first = await session.scalar(select(ChatInput.id).where(ChatInput.workspace_id == workspace,
                ChatInput.project_id == project_id, ChatInput.owner_id == item.owner_id,
                ChatInput.thread_id == item.thread_id, ChatInput.kind == "queue", ChatInput.status == "pending"
            ).order_by(ChatInput.created_at, ChatInput.id).limit(1))
            if first != item.id:
                continue
            busy = await session.scalar(select(AgentRun.id).where(AgentRun.workspace_id == workspace,
                AgentRun.project_id == project_id, AgentRun.thread_id == item.thread_id,
                AgentRun.parent_run_id.is_(None), AgentRun.status.in_(ACTIVE_STATUSES)).limit(1))
            if busy:
                continue
            member = await MembershipRepository(session).get(workspace, item.owner_id)
            try:
                if (project is None or member is None or not can(member, Permission.CHAT)
                        or await ProjectRepository(session).visible(member, project_id) is None):
                    raise Forbidden("Conversation access changed before delivery")
                previous = await owned_thread(session, ProjectAccess(project, member), item.thread_id)
                if previous.status is not RunStatus.COMPLETED:
                    if previous.error_kind in ("model_limit", "interrupted"):
                        continue
                    raise Conflict("The previous turn stopped; send a new message when ready")
                await AgentService(session, runner).create_run(ProjectAccess(project, member), RunCreate(
                    message=item.message, thread_id=item.thread_id, **item.payload), queued_input=item)
                delivered += 1
            except DomainError as exc:
                # Creation may have committed and published before a later read
                # lost access. Never relabel a committed delivery as rejected.
                if item.status == "delivered":
                    raise
                item.status, item.error, item.updated_at = "rejected", str(exc.detail)[:200], now()
                audit(session, item, "rejected")
                await session.commit()
    return delivered
