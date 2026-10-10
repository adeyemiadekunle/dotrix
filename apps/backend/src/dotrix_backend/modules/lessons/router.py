"""Lessons the agents could learn from people's decisions, for owners and admins to accept or decline."""
from __future__ import annotations

import uuid

from fastapi import APIRouter

from dotrix_backend.api.deps import SessionDep
from dotrix_backend.core.openapi import errors
from dotrix_backend.modules.projects.deps import ProjectManager

from .models import LessonStatus
from .schemas import LessonAccept, LessonRead
from .service import LessonService

router = APIRouter(
    prefix="/workspaces/{workspace_id}/projects/{project_id}/lessons", tags=["lessons"], responses=errors(401, 403, 404)
)


@router.get("")
async def list_lessons(access: ProjectManager, session: SessionDep, status: LessonStatus | None = None) -> list[LessonRead]:
    """Lessons proposed from rejected changes and dismissed results (with their reasons), and what
    became of them; newest first. Owners and admins."""
    return await LessonService(session).list(access.project, status)


@router.post("/{lesson_id}/accept", responses=errors(409, 422))
async def accept_lesson(
    lesson_id: uuid.UUID, data: LessonAccept, access: ProjectManager, session: SessionDep
) -> LessonRead:
    """Add it to the agent's rules (`agent-rules/lessons/<agent>.md`, a new version you can
    edit or restore like any file), in your words if you give `text`. Owners and admins."""
    return await LessonService(session).accept(access, lesson_id, data)


@router.post("/{lesson_id}/decline", responses=errors(409))
async def decline_lesson(lesson_id: uuid.UUID, access: ProjectManager, session: SessionDep) -> LessonRead:
    """Don't teach it; it stays listed as declined. Owners and admins."""
    return await LessonService(session).decline(access, lesson_id)
