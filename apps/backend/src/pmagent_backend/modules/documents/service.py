"""Document upload (FR-11): keep the original, give agents normalised markdown.

The original goes to object storage; its markdown goes into the project's
knowledge under `docs/normalized/`, as a normal versioned file, so it syncs to
local mirrors and shows up in history. Uploading a file with the same name
again adds a new version of the same markdown file.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import mimetypes
import re
import uuid
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from pathlib import PurePath

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from uuid_utils.compat import uuid7

from pmagent_backend.core.errors import DomainError, NotFound, Unprocessable
from pmagent_backend.core.jobs import Jobs
from pmagent_backend.core.storage import BlobStorage
from pmagent_backend.modules.knowledge.service import Actor, KnowledgeService
from pmagent_backend.modules.projects.deps import ProjectAccess
from pmagent_backend.modules.projects.repository import ProjectRepository
from pmagent_backend.modules.workspaces.repository import MembershipRepository
from pmagent_engine.ingest import SUPPORTED_EXTENSIONS, UnsupportedDocument, to_markdown

from .models import Document, DocumentStatus
from .schemas import DocumentRead

logger = logging.getLogger(__name__)

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
    def __init__(self, session: AsyncSession, storage: BlobStorage, jobs: Jobs | None = None) -> None:
        self.session = session
        self.storage = storage
        self.jobs = jobs  # the API's; None inside the conversion job

    async def upload(
        self,
        access: ProjectAccess,
        filename: str,
        data: bytes,
        *,
        max_bytes: int,
    ) -> DocumentRead:
        """Store the original and queue its conversion: the document is `converting` until
        the job has written its markdown (large PDFs take a while; the request doesn't wait)."""
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

        project, member = access.project, access.member
        document_id = uuid7()
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
                knowledge_path=normalized_path(filename),
                knowledge_version=0,
                status=DocumentStatus.CONVERTING,
                uploaded_by_id=member.user_id,
                created_at=datetime.now(UTC),
            )
            self.session.add(document)
            await self.session.commit()
        except BaseException:
            await self.session.rollback()
            await self.storage.delete(storage_key)  # don't leave an orphaned original
            raise
        assert self.jobs is not None
        await self.jobs.enqueue("convert_document", document_id=str(document_id))
        await self.session.refresh(document)  # (an inline job may have finished already)
        return DocumentRead.model_validate(document)

    async def convert(self, document_id: uuid.UUID) -> None:
        """The conversion job: markdown from the stored original, written to the project's
        knowledge as the person who uploaded it. Failures are recorded on the document."""
        document = await self.session.get(Document, document_id)
        if document is None or document.status is not DocumentStatus.CONVERTING:
            return  # deleted, or already done (a retried job)
        project = await ProjectRepository(self.session).get(document.workspace_id, document.project_id)
        uploader = (
            await MembershipRepository(self.session).get(document.workspace_id, document.uploaded_by_id)
            if document.uploaded_by_id
            else None
        )
        if project is None or uploader is None:
            await self._failed(document_id, "The person who uploaded it no longer has access to this project")
            return
        try:
            data = await self.storage.get(document.storage_key)
            # Parsing (PDF especially) is CPU-bound; keep it off the event loop.
            markdown = await asyncio.to_thread(to_markdown, document.filename, data)
            header = (
                f"> Imported from `{document.filename}` on {document.created_at:%Y-%m-%d}. "
                f"Original: document `{document.id}`.\n\n"
            )
            written = await KnowledgeService(self.session).write(
                project,
                document.knowledge_path,
                header + markdown,
                Actor.person(uploader.user_id, uploader.role),
                message=f"Imported {document.filename}",
            )
        except UnsupportedDocument as exc:
            await self.session.rollback()
            await self._failed(document_id, str(exc))
            return
        except DomainError as exc:  # e.g. the markdown is larger than a knowledge file may be
            await self.session.rollback()
            await self._failed(document_id, exc.detail)
            return
        except Exception:
            logger.exception("converting document %s failed", document_id)
            await self.session.rollback()
            await self._failed(document_id, "Couldn't convert this file; try uploading it again")
            return
        document.status, document.knowledge_version, document.error = DocumentStatus.READY, written.version, None
        await self.session.commit()

    async def _failed(self, document_id: uuid.UUID, error: str) -> None:
        document = await self.session.get(Document, document_id)
        if document is not None:
            document.status, document.error = DocumentStatus.FAILED, error[:2000]
            await self.session.commit()

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


async def mark_interrupted_conversions(session_factory: Callable[[], AbstractAsyncContextManager[AsyncSession]]) -> None:
    """Local mode, at startup: conversions run as tasks in the API process, so any still
    `converting` were cut off by the last shutdown. (The worker's queue keeps its own.)"""
    async with session_factory() as session:
        await session.execute(
            update(Document)
            .where(Document.status == DocumentStatus.CONVERTING)
            .values(status=DocumentStatus.FAILED, error="The server restarted while converting it; upload it again")
        )
        await session.commit()
