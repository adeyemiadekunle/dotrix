"""Explicit human publication of an edited outcome, independent of the chat runtime."""
import hashlib
import re
import uuid
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator
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


class PublicationDocumentRef(BaseModel):
    path: str = Field(min_length=1, max_length=300)
    version: int = Field(ge=1)

    @field_validator("path")
    @classmethod
    def shared_path(cls, value: str) -> str:
        # Keep generated relationship lines unambiguous and outside protected guidance.
        if not re.fullmatch(r"(?:requirements|decisions|research)/[\w./-]+\.md", value) or ".." in value:
            raise ValueError("Choose a requirements, decisions or research Markdown document")
        return value


class ChatPublicationCreate(BaseModel):
    request_id: uuid.UUID
    destination: Literal["requirements", "decisions", "research", "task"]
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=100_000)
    acknowledge_shared: Literal[True]
    related_document: PublicationDocumentRef | None = None
    related_issue: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9]*-[1-9][0-9]*$", max_length=32)
    supersedes: PublicationDocumentRef | None = None

    @model_validator(mode="after")
    def decision_supersession(self):
        if self.supersedes and (self.destination != "decisions" or not self.supersedes.path.startswith("decisions/")):
            raise ValueError("Only a new decision can supersede an existing decision")
        return self


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
        (str(run_id) + data.model_dump_json(exclude={"request_id"}, exclude_none=True)).encode()
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
    knowledge = KnowledgeService(session)
    reviewed = {}
    for ref in (data.related_document, data.supersedes):
        if ref is None:
            continue
        file = await knowledge.read(access.project, ref.path)
        if file.path != ref.path or file.version != ref.version:
            raise Conflict("Linked knowledge changed. Reload it and review the publication again")
        reviewed[ref.path] = file
    if data.related_issue:
        await IssueService(session).get(access.project, data.related_issue)
    relationships = []
    if data.supersedes:
        relationships.append(f"Supersedes: /dotrix/{data.supersedes.path} (reviewed version {data.supersedes.version})")
    if data.related_document:
        relationships.append(f"Shared context: /dotrix/{data.related_document.path} (reviewed version {data.related_document.version})")
    if data.related_issue:
        relationships.append(f"Related task: {data.related_issue}")
    selected = data.content.strip()
    if relationships:
        selected += "\n\n" + "\n\n".join(relationships)
    row = ChatPublication(
        workspace_id=access.project.workspace_id, project_id=access.project.id,
        user_id=access.member.user_id, run_id=run.id, request_id=data.request_id,
        fingerprint=fingerprint, destination=data.destination, target="",
    )
    session.add(row)
    await session.flush()
    content = f"# {data.title.strip()}\n\n{selected}\n"
    if data.destination == "task":
        issue = await IssueService(session)._insert(
            access.project, IssueActor(access.member),
            IssueCreate(title=data.title.strip(), description=selected),
        )
        row.target = issue.key
        await session.commit()
    else:
        row.target = f"{data.destination}/chat-{row.id}.md"
        # The version check prevents overwriting existing human knowledge. This
        # service stages writes; the destination, predecessor annotation and retry
        # record commit together.
        await knowledge.write(
            access.project, row.target, content,
            Actor.person(access.member.user_id, access.member.role), base_version=0,
            message="Selected chat outcome, reviewed and published by a person", commit=False,
        )
        if data.supersedes:
            old = reviewed[data.supersedes.path]
            await knowledge.write(
                access.project, old.path,
                old.content + f"\n\n## Superseded\n\nSuperseded by: /dotrix/{row.target}\n",
                Actor.person(access.member.user_id, access.member.role), base_version=data.supersedes.version,
                message="Explicitly superseded by a reviewed new decision", commit=False,
            )
        await session.commit()
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
