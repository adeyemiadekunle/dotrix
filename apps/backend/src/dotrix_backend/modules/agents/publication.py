"""Explicit human publication of an edited outcome, independent of the chat runtime."""
import hashlib
import uuid
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dotrix_backend.core.errors import Conflict, Forbidden, NotFound
from dotrix_backend.modules.issues.schemas import IssueCreate
from dotrix_backend.modules.issues.service import IssueActor, IssueService
from dotrix_backend.modules.knowledge.service import Actor, KnowledgeService
from dotrix_backend.modules.projects.deps import ProjectAccess
from dotrix_backend.modules.projects.repository import ProjectRepository
from dotrix_backend.modules.workspaces.permissions import Permission, can

from .models import AgentRun, ChatPublication, RunStatus


class ChatPublicationCreate(BaseModel):
    request_id: uuid.UUID
    destination: Literal["requirements", "decisions", "research", "task"]
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=100_000)
    acknowledge_shared: Literal[True]


class ChatPublicationRead(BaseModel):
    destination: Literal["requirements", "decisions", "research", "task"]
    target: str


async def publish(
    session: AsyncSession, access: ProjectAccess, run_id: uuid.UUID, data: ChatPublicationCreate,
) -> ChatPublicationRead:
    permission = Permission.EDIT_ISSUES if data.destination == "task" else Permission.EDIT_KNOWLEDGE
    if not can(access.member, permission):
        raise Forbidden("You cannot publish to this destination")
    # Serialize retries with document/issue writes and project moves. Do not rely on
    # approver access: only the owner may publish from their private conversation.
    await ProjectRepository(session).get(access.project.workspace_id, access.project.id, for_update=True)
    run = await session.scalar(select(AgentRun).where(
        AgentRun.workspace_id == access.project.workspace_id, AgentRun.project_id == access.project.id,
        AgentRun.id == run_id, AgentRun.requested_by_id == access.member.user_id,
        AgentRun.parent_run_id.is_(None),
    ))
    if run is None:
        raise NotFound("Conversation run not found")
    if run.status != RunStatus.COMPLETED:
        raise Conflict("Wait for this reply to finish before publishing an outcome")
    if not data.title.strip() or not data.content.strip():
        raise Conflict("Add a title and selected content before publishing")
    fingerprint = hashlib.sha256(
        (str(run_id) + data.model_dump_json(exclude={"request_id"})).encode()
    ).hexdigest()
    previous = await session.scalar(select(ChatPublication).where(
        ChatPublication.workspace_id == access.project.workspace_id,
        ChatPublication.project_id == access.project.id, ChatPublication.user_id == access.member.user_id,
        ChatPublication.request_id == data.request_id,
    ))
    if previous:
        if previous.fingerprint != fingerprint:
            raise Conflict("This publication request was already used for different content")
        return ChatPublicationRead(destination=previous.destination, target=previous.target)
    row = ChatPublication(
        workspace_id=access.project.workspace_id, project_id=access.project.id,
        user_id=access.member.user_id, run_id=run.id, request_id=data.request_id,
        fingerprint=fingerprint, destination=data.destination, target="",
    )
    session.add(row)
    await session.flush()
    content = f"# {data.title.strip()}\n\n{data.content.strip()}\n"
    if data.destination == "task":
        issue = await IssueService(session)._insert(
            access.project, IssueActor(access.member),
            IssueCreate(title=data.title.strip(), description=data.content.strip()),
        )
        row.target = issue.key
        await session.commit()
    else:
        row.target = f"{data.destination}/chat-{row.id}.md"
        # The version check prevents overwriting existing human knowledge. This
        # service commits the destination and retry record in the same transaction.
        await KnowledgeService(session).write(
            access.project, row.target, content,
            Actor.person(access.member.user_id, access.member.role), base_version=0,
            message="Selected chat outcome, reviewed and published by a person",
        )
    return ChatPublicationRead(destination=data.destination, target=row.target)


async def publications(session: AsyncSession, access: ProjectAccess, run_id: uuid.UUID) -> list[ChatPublicationRead]:
    run = await session.scalar(select(AgentRun.id).where(
        AgentRun.workspace_id == access.project.workspace_id, AgentRun.project_id == access.project.id,
        AgentRun.id == run_id, AgentRun.requested_by_id == access.member.user_id,
    ))
    if run is None:
        raise NotFound("Conversation run not found")
    rows = (await session.scalars(select(ChatPublication).where(
        ChatPublication.workspace_id == access.project.workspace_id,
        ChatPublication.project_id == access.project.id, ChatPublication.user_id == access.member.user_id,
        ChatPublication.run_id == run_id,
    ).order_by(ChatPublication.id))).all()
    return [ChatPublicationRead(destination=row.destination, target=row.target) for row in rows]
