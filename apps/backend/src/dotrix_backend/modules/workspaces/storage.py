"""What a workspace has stored in uploads, and the limit on it.

Counted: document originals and task attachments (both record their `size`). Not counted:
knowledge files' Markdown and history, coding screenshots and saved sessions, profile photos.
Usage is summed from the rows, never kept in a counter, so deletes and moves can't drift it.
"""
from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from dotrix_backend.core.errors import StorageFull
from dotrix_backend.core.settings import Settings
from dotrix_backend.modules.documents.models import Document
from dotrix_backend.modules.issues.models import IssueAttachment
from dotrix_backend.modules.workspaces.models import Workspace


async def usage(session: AsyncSession, workspace_id: uuid.UUID) -> tuple[int, int]:
    """(document originals, task attachments) in bytes."""
    documents = await session.scalar(
        select(func.coalesce(func.sum(Document.size), 0)).where(Document.workspace_id == workspace_id)
    )
    attachments = await session.scalar(
        select(func.coalesce(func.sum(IssueAttachment.size), 0)).where(IssueAttachment.workspace_id == workspace_id)
    )
    return int(documents or 0), int(attachments or 0)


async def used_bytes(session: AsyncSession, workspace_id: uuid.UUID) -> int:
    return sum(await usage(session, workspace_id))


async def project_bytes(session: AsyncSession, project_id: uuid.UUID) -> int:
    """What one project holds in counted uploads (for moving it into another workspace)."""
    documents = await session.scalar(
        select(func.coalesce(func.sum(Document.size), 0)).where(Document.project_id == project_id)
    )
    attachments = await session.scalar(
        select(func.coalesce(func.sum(IssueAttachment.size), 0)).where(IssueAttachment.project_id == project_id)
    )
    return int(documents or 0) + int(attachments or 0)


def limit_bytes(workspace: Workspace, settings: Settings) -> int | None:
    """The workspace's own limit, else the deployment's; 0 means none (returned as None)."""
    mb = workspace.storage_limit_mb if workspace.storage_limit_mb is not None else settings.workspace_storage_limit_mb
    return mb * 1_000_000 if mb else None


def _size(n: int) -> str:
    if n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.1f} GB"
    return f"{n / 1_000_000:.0f} MB" if n >= 1_000_000 else f"{max(n // 1000, 0)} KB"


async def ensure_room(
    session: AsyncSession, workspace_id: uuid.UUID, settings: Settings, incoming: int
) -> None:
    """Refuse (StorageFull) when `incoming` more bytes would pass the limit. Two uploads at once
    can each pass and together exceed the limit by one upload; that is accepted."""
    workspace = await session.get(Workspace, workspace_id)
    limit = limit_bytes(workspace, settings) if workspace is not None else None
    if limit is None:
        return
    used = await used_bytes(session, workspace_id)
    if used + incoming > limit:
        raise StorageFull(
            f"This workspace's storage is full ({_size(used)} of {_size(limit)} used). "
            "Delete files you no longer need, or ask for a higher limit."
        )
