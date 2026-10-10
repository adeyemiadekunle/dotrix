from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import KnowledgeFile, KnowledgeVersion


class KnowledgeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add(self, row: KnowledgeFile | KnowledgeVersion) -> None:
        self.session.add(row)

    async def get_file(self, project_id: uuid.UUID, path: str) -> KnowledgeFile | None:
        return await self.session.scalar(
            select(KnowledgeFile).where(
                KnowledgeFile.project_id == project_id, KnowledgeFile.path == path
            )
        )

    async def list_files(
        self, project_id: uuid.UUID, *, since_revision: int | None = None
    ) -> list[KnowledgeFile]:
        stmt = select(KnowledgeFile).where(KnowledgeFile.project_id == project_id)
        if since_revision is None:
            stmt = stmt.where(KnowledgeFile.deleted.is_(False))
        else:
            # Include deletions, so a mirror can remove files it still has.
            stmt = stmt.where(KnowledgeFile.revision > since_revision)
        return list(await self.session.scalars(stmt.order_by(KnowledgeFile.path)))

    async def list_versions(self, file_id: uuid.UUID) -> list[KnowledgeVersion]:
        result = await self.session.scalars(
            select(KnowledgeVersion)
            .where(KnowledgeVersion.file_id == file_id)
            .order_by(KnowledgeVersion.version.desc())
        )
        return list(result)

    async def get_version(self, file_id: uuid.UUID, version: int) -> KnowledgeVersion | None:
        return await self.session.scalar(
            select(KnowledgeVersion).where(
                KnowledgeVersion.file_id == file_id, KnowledgeVersion.version == version
            )
        )
