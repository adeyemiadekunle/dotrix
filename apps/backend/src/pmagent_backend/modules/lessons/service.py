"""Proposing lessons from people's decisions, and accepting them into the agents' rules."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pmagent_backend.core.errors import Conflict, NotFound
from pmagent_backend.modules.audit.service import AuditLog
from pmagent_backend.modules.knowledge.models import AuthorType
from pmagent_backend.modules.knowledge.repository import KnowledgeRepository
from pmagent_backend.modules.knowledge.service import Actor, KnowledgeService
from pmagent_backend.modules.projects.deps import ProjectAccess
from pmagent_backend.modules.projects.models import Project

from .models import AgentLesson, LessonSource, LessonStatus
from .schemas import LessonAccept, LessonRead

PM_HANDLE = "project-manager"
MAX_PROPOSED = 50  # per project: beyond this, older proposals are still there to decide first


def lessons_path(agent: str) -> str:
    return f"agent-rules/lessons/{agent}.md"


def propose(
    session: AsyncSession, project: Project, *, agent: str | None, source: LessonSource, subject: str,
    reason: str | None, run_id: uuid.UUID | None, by: uuid.UUID,
) -> None:
    """A rejection or dismissal with a reason becomes a lesson to decide. Without a reason
    there's nothing to learn. (Added to the caller's transaction.)"""
    reason = (reason or "").strip()
    if not reason:
        return
    verb = "was rejected" if source is LessonSource.REJECTION else "was dismissed"
    session.add(AgentLesson(
        workspace_id=project.workspace_id, project_id=project.id, agent=agent or PM_HANDLE,
        text=f'{subject} {verb}: "{reason[:400]}". Take this into account from now on.'[:600],
        source=source, reason=reason[:500], run_id=run_id, status=LessonStatus.PROPOSED, proposed_by_id=by,
        created_at=datetime.now(UTC),
    ))


class LessonService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list(self, project: Project, status: LessonStatus | None) -> list[LessonRead]:
        stmt = select(AgentLesson).where(AgentLesson.project_id == project.id)
        if status is not None:
            stmt = stmt.where(AgentLesson.status == status)
        rows = await self.session.scalars(stmt.order_by(AgentLesson.created_at.desc()).limit(200))
        return [LessonRead.model_validate(r) for r in rows]

    async def accept(self, access: ProjectAccess, lesson_id: uuid.UUID, data: LessonAccept) -> LessonRead:
        """Add the lesson to the agent's lessons file (a new version of an agent rule)."""
        lesson = await self._proposed(access.project, lesson_id)
        text = (data.text or lesson.text).replace("\n", " ").strip()
        path = lessons_path(lesson.agent)
        existing = await KnowledgeRepository(self.session).get_file(access.project.id, path)
        version = 0 if existing is None or existing.deleted else existing.version
        if version:
            content = existing.content.rstrip() + f"\n- {text}\n"
        else:
            content = (
                f"# Lessons for the {lesson.agent} agent\n\n"
                "Learned from this project's decisions and approved by its owners and admins. Edit or remove "
                "any line here.\n\n"
                f"- {text}\n"
            )
        lesson.text, lesson.status = text, LessonStatus.ACCEPTED
        lesson.decided_by_id, lesson.decided_at = access.member.user_id, datetime.now(UTC)
        self._audit(access, lesson, "lesson.accepted")
        # Commits the file and the lesson together.
        await KnowledgeService(self.session).write(
            access.project, path, content, Actor.person(access.member.user_id, access.member.role),
            base_version=version, message=f"Lesson: {text[:80]}",
        )
        return LessonRead.model_validate(lesson)

    async def decline(self, access: ProjectAccess, lesson_id: uuid.UUID) -> LessonRead:
        lesson = await self._proposed(access.project, lesson_id)
        lesson.status = LessonStatus.DECLINED
        lesson.decided_by_id, lesson.decided_at = access.member.user_id, datetime.now(UTC)
        self._audit(access, lesson, "lesson.declined")
        await self.session.commit()
        return LessonRead.model_validate(lesson)

    async def _proposed(self, project: Project, lesson_id: uuid.UUID) -> AgentLesson:
        lesson = await self.session.scalar(
            select(AgentLesson).where(AgentLesson.project_id == project.id, AgentLesson.id == lesson_id)
        )
        if lesson is None:
            raise NotFound("No such lesson in this project")
        if lesson.status is not LessonStatus.PROPOSED:
            raise Conflict(f"This lesson was already {lesson.status.value}")
        return lesson

    def _audit(self, access: ProjectAccess, lesson: AgentLesson, action: str) -> None:
        AuditLog(self.session).record(
            workspace_id=access.project.workspace_id, project_id=access.project.id, action=action,
            target=lessons_path(lesson.agent), actor_type=AuthorType.USER, actor_user_id=access.member.user_id,
            details={"agent": lesson.agent, "source": lesson.source.value, "text": lesson.text},
        )
