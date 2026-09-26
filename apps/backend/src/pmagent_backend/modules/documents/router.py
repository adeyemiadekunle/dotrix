"""Document upload and originals (FR-11)."""
from __future__ import annotations

import uuid
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Response, UploadFile, status

from pmagent_backend.api.deps import SessionDep, SettingsDep
from pmagent_backend.core.openapi import errors
from pmagent_backend.core.storage import BlobStorage, get_storage
from pmagent_backend.modules.projects.deps import KnowledgeEditor, ProjectViewer

from .schemas import DocumentRead
from .service import DocumentService

router = APIRouter(
    prefix="/workspaces/{workspace_id}/projects/{project_id}/documents",
    tags=["documents"],
    responses=errors(401, 404),
)


def get_document_service(
    session: SessionDep, storage: Annotated[BlobStorage, Depends(get_storage)]
) -> DocumentService:
    return DocumentService(session, storage)


Documents = Annotated[DocumentService, Depends(get_document_service)]


@router.post("", status_code=status.HTTP_201_CREATED, responses=errors(403, 409, 422, 503))
async def upload_document(
    access: KnowledgeEditor,
    documents: Documents,
    settings: SettingsDep,
    file: Annotated[UploadFile, File(description="PDF, DOCX, PPTX, XLSX, XLS, HTML, CSV, JSON, XML, MD, TXT")],
) -> DocumentRead:
    """Upload a document. The original is kept in storage, and its content is converted
    to markdown at `docs/normalized/<name>.md` in the project's knowledge, where agents
    read it. Uploading the same filename again adds a new version of that markdown."""
    limit = settings.max_upload_mb * 1_000_000
    data = await file.read(limit + 1)  # read one byte past the limit to detect oversize
    return await documents.upload(access, file.filename or "document", data, max_bytes=limit)


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
