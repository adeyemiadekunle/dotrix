"""Document upload and originals (FR-11)."""
from __future__ import annotations

import uuid
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Response, UploadFile, status

from dotrix_backend.api.deps import JobsDep, SessionDep, SettingsDep
from dotrix_backend.core.openapi import errors
from dotrix_backend.core.storage import BlobStorage, get_storage
from dotrix_backend.modules.projects.deps import ProjectManager, ProjectViewer

from .schemas import DocumentRead, DocumentRename
from .service import DocumentService

router = APIRouter(
    prefix="/workspaces/{workspace_id}/projects/{project_id}/documents",
    tags=["documents"],
    responses=errors(401, 404),
)


def get_document_service(
    session: SessionDep, storage: Annotated[BlobStorage, Depends(get_storage)], jobs: JobsDep
) -> DocumentService:
    return DocumentService(session, storage, jobs)


Documents = Annotated[DocumentService, Depends(get_document_service)]


@router.post("", status_code=status.HTTP_201_CREATED, responses=errors(403, 409, 422, 503))
async def upload_document(
    access: ProjectManager,
    documents: Documents,
    settings: SettingsDep,
    file: Annotated[UploadFile, File(description="PDF, DOCX, PPTX, XLSX, XLS, HTML, CSV, JSON, XML, MD, TXT")],
) -> DocumentRead:
    """Upload a document. The original is kept in storage, and a background job converts
    it to markdown at `docs/normalized/<name>.md` in the project's knowledge, where agents
    read it: the document is `converting` until then (poll it), then `ready` or `failed`.
    Uploading the same filename again adds a new version of that markdown. Adding a
    project's external docs is setup work: owners and admins."""
    limit = settings.max_upload_mb * 1_000_000
    data = await file.read(limit + 1)  # read one byte past the limit to detect oversize
    return await documents.upload(access, file.filename or "document", data, max_bytes=limit)


@router.post("/{document_id}/retry", responses=errors(403, 409, 503))
async def retry_document_conversion(
    document_id: uuid.UUID, access: ProjectManager, documents: Documents
) -> DocumentRead:
    """Convert a document that failed again, from its stored original: it's `converting`
    until the job finishes, then `ready` or `failed` with a new `error`. 409 unless it failed.
    Owners and admins (the people who add documents)."""
    return await documents.retry(access.project.id, document_id)


@router.patch("/{document_id}", responses=errors(403, 422))
async def rename_document(
    document_id: uuid.UUID, data: DocumentRename, access: ProjectManager, documents: Documents
) -> DocumentRead:
    """Rename a document, keeping its extension. Its markdown in the project's knowledge stays
    where it is. Owners and admins (the people who add documents)."""
    return await documents.rename(access, document_id, data.filename)


@router.post("/{document_id}/duplicate", status_code=status.HTTP_201_CREATED, responses=errors(403, 503))
async def duplicate_document(document_id: uuid.UUID, access: ProjectManager, documents: Documents) -> DocumentRead:
    """Copy a document under a free name ("spec copy.pdf"); the copy is converted like an
    upload (`converting`, then `ready` or `failed`). Owners and admins."""
    return await documents.duplicate(access, document_id)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT, responses=errors(403, 503))
async def delete_document(document_id: uuid.UUID, access: ProjectManager, documents: Documents) -> None:
    """Delete a document: its original, and its markdown in the project's knowledge unless another
    upload made the same file (that delete is versioned, so it can be restored from the file's
    history). Owners and admins."""
    await documents.delete(access, document_id)


@router.get("")
async def list_documents(access: ProjectViewer, documents: Documents) -> list[DocumentRead]:
    """Uploaded documents, newest first."""
    return await documents.list(access.project.id)


@router.get("/{document_id}")
async def get_document(
    document_id: uuid.UUID, access: ProjectViewer, documents: Documents
) -> DocumentRead:
    """An uploaded document's details."""
    return DocumentRead.model_validate(await documents.get(access.project.id, document_id))


@router.get(
    "/{document_id}/original",
    response_class=Response,
    responses={200: {"content": {"application/octet-stream": {}}, "description": "The original file"}}
    | errors(503),
)
async def download_original(
    document_id: uuid.UUID, access: ProjectViewer, documents: Documents
) -> Response:
    """Download the original file, exactly as uploaded."""
    document = await documents.get(access.project.id, document_id)
    data = await documents.original(document)
    return Response(
        content=data,
        media_type=document.content_type,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(document.filename)}",
            "X-Content-Type-Options": "nosniff",
        },
    )
