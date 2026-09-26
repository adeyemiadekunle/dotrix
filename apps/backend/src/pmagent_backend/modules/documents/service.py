"""Document upload (FR-11): keep the original, give agents normalised markdown.

The original goes to object storage; its markdown goes into the project's
knowledge under `docs/normalized/`, as a normal versioned file, so it syncs to
local mirrors and shows up in history. Uploading a file with the same name
again adds a new version of the same markdown file.
"""
from __future__ import annotations

import asyncio
import hashlib
import mimetypes
import re
import uuid
from datetime import UTC, datetime
from pathlib import PurePath

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from uuid_utils.compat import uuid7

from pmagent_backend.core.errors import NotFound, Unprocessable
from pmagent_backend.core.storage import BlobStorage
from pmagent_backend.modules.knowledge.service import Actor, KnowledgeService
from pmagent_backend.modules.projects.deps import ProjectAccess
from pmagent_engine.ingest import SUPPORTED_EXTENSIONS, UnsupportedDocument, to_markdown

from .models import Document
from .schemas import DocumentRead

NORMALIZED_DIR = "docs/normalized"


class UnsupportedFormat(Unprocessable):
    code = "unsupported_format"


class UnreadableDocument(Unprocessable):
    code = "unreadable_document"


class UploadTooLarge(Unprocessable):
    code = "file_too_large"


def safe_filename(name: str) -> str:
    """Last path segment only, with unusual characters replaced; keeps the extension."""
    base = PurePath(name.replace("\\", "/")).name.strip()
    cleaned = re.sub(r"[^A-Za-z0-9._ ()-]+", "_", base).strip(" .")
    return cleaned[-200:] or "document"


def normalized_path(filename: str) -> str:
    stem = PurePath(filename).stem.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", stem).strip("-")[:80] or "document"
    return f"{NORMALIZED_DIR}/{slug}.md"


class DocumentService:
    def __init__(self, session: AsyncSession, storage: BlobStorage) -> None:
        self.session = session
        self.storage = storage

    async def upload(
        self,
        access: ProjectAccess,
        filename: str,
        data: bytes,
        *,
        max_bytes: int,
    ) -> DocumentRead:
        filename = safe_filename(filename)
        # From the extension, never the client's header, so stored types can be trusted.
        content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        suffix = PurePath(filename).suffix.lower()
        if suffix not in SUPPORTED_EXTENSIONS:
            raise UnsupportedFormat(
                f"Can't import {suffix or 'files without an extension'}. "
                f"Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
            )
        if len(data) > max_bytes:
            raise UploadTooLarge(f"Uploads are limited to {max_bytes // 1_000_000} MB")
        if not data:
            raise UnreadableDocument("The file is empty")

        try:
            # Parsing (PDF especially) is CPU-bound; keep it off the event loop.
            markdown = await asyncio.to_thread(to_markdown, filename, data)
        except UnsupportedDocument as exc:
            raise UnreadableDocument(str(exc)) from exc

        project, member = access.project, access.member
        document_id = uuid7()
        now = datetime.now(UTC)
        path = normalized_path(filename)
        header = (
            f"> Imported from `{filename}` on {now:%Y-%m-%d}. "
            f"Original: document `{document_id}`.\n\n"
        )
        storage_key = f"{project.workspace_id}/{project.id}/{document_id}/{filename}"
        await self.storage.put(storage_key, data, content_type)

        try:
            document = Document(
                id=document_id,
                workspace_id=project.workspace_id,
                project_id=project.id,
                filename=filename,
                content_type=content_type,
                size=len(data),
                sha256=hashlib.sha256(data).hexdigest(),
                storage_key=storage_key,
                knowledge_path=path,
                knowledge_version=0,
                uploaded_by_id=member.user_id,
                created_at=now,
            )
            self.session.add(document)
            # Commits the document together with the knowledge change.
            written = await KnowledgeService(self.session).write(
                project,
                path,
                header + markdown,
                Actor.person(member.user_id, member.role),
                message=f"Imported {filename}",
            )
            document.knowledge_version = written.version
            await self.session.commit()
        except BaseException:
            await self.session.rollback()
            await self.storage.delete(storage_key)  # don't leave an orphaned original
            raise
        return DocumentRead.model_validate(document)

    async def list(self, project_id: uuid.UUID) -> list[DocumentRead]:
        result = await self.session.scalars(
            select(Document)
            .where(Document.project_id == project_id)
            .order_by(Document.created_at.desc())
        )
        return [DocumentRead.model_validate(d) for d in result]

    async def get(self, project_id: uuid.UUID, document_id: uuid.UUID) -> Document:
        document = await self.session.scalar(
            select(Document).where(Document.project_id == project_id, Document.id == document_id)
        )
        if document is None:
            raise NotFound("Document not found")
        return document

    async def original(self, document: Document) -> bytes:
        return await self.storage.get(document.storage_key)
