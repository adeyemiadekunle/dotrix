"""A project's `.dotrix/` files: manifest (sync), read, write, history, restore, export.

File paths are relative to `.dotrix/`, e.g. `requirements/product.md`, and go in
the URL as-is: `/files/requirements/product.md`.
"""
from __future__ import annotations

from fastapi import APIRouter, Query, Response, status

from dotrix_backend.api.deps import SessionDep
from dotrix_backend.core.openapi import errors
from dotrix_backend.modules.projects.deps import (
    KnowledgeEditor,
    KnowledgeExporter,
    ProjectAccess,
    ProjectViewer,
)

from .schemas import (
    FileRead,
    FileWrite,
    Manifest,
    RestoreRequest,
    VersionDiff,
    VersionEntry,
    VersionRead,
)
from .service import Actor, KnowledgeService

router = APIRouter(
    prefix="/workspaces/{workspace_id}/projects/{project_id}/knowledge",
    tags=["knowledge"],
    responses=errors(401, 404),
)


def _person(access: ProjectAccess) -> Actor:
    return Actor.person(access.member.user_id, access.member.role)


@router.get("")
async def get_manifest(
    access: ProjectViewer,
    session: SessionDep,
    since_revision: int | None = Query(
        default=None,
        ge=0,
        description="Only files changed after this revision, including deletions "
        "(`deleted: true`). Omit for every current file.",
    ),
) -> Manifest:
    """The file list and the project's current revision. A local mirror stores `revision`
    and next time asks for `since_revision` to pull only what changed."""
    return await KnowledgeService(session).manifest(access.project, since_revision)


@router.get(
    "/export",
    response_class=Response,
    responses={200: {"content": {"application/zip": {}}, "description": "Zip of `.dotrix/`"}}
    | errors(403),
)
async def export_knowledge(access: KnowledgeExporter, session: SessionDep) -> Response:
    """Download the whole `.dotrix/` as Markdown (zip), with a `config.yaml`. Owners and
    admins. Leaving the platform loses nothing."""
    data = await KnowledgeService(session).export_zip(access.project)
    filename = f"{access.project.key.lower()}-dotrix.zip"
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# More specific file routes first: {path:path} would otherwise swallow the suffix.


@router.get("/files/{path:path}/versions/{version}/diff", responses=errors(422))
async def diff_file_version(
    path: str, version: int, access: ProjectViewer, session: SessionDep
) -> VersionDiff:
    """What a version changed, as a unified diff against the version before it."""
    return await KnowledgeService(session).diff(access.project, path, version)


@router.get("/files/{path:path}/versions/{version}", responses=errors(422))
async def get_file_version(
    path: str, version: int, access: ProjectViewer, session: SessionDep
) -> VersionRead:
    """A past version's content and who wrote, instructed, and approved it."""
    return await KnowledgeService(session).version(access.project, path, version)


@router.get("/files/{path:path}/versions", responses=errors(422))
async def list_file_versions(
    path: str, access: ProjectViewer, session: SessionDep
) -> list[VersionEntry]:
    """Full history of a file, newest first, including deletions."""
    return await KnowledgeService(session).versions(access.project, path)


@router.post("/files/{path:path}/restore", responses=errors(403, 409, 422))
async def restore_file_version(
    path: str, data: RestoreRequest, access: KnowledgeEditor, session: SessionDep
) -> FileRead:
    """Make an old version current again. This adds a new version; history is kept."""
    return await KnowledgeService(session).restore(
        access.project, path, data.version, _person(access), base_version=data.base_version
    )


@router.get("/files/{path:path}", responses=errors(422))
async def read_file(path: str, access: ProjectViewer, session: SessionDep) -> FileRead:
    """A file's current content."""
    return await KnowledgeService(session).read(access.project, path)


@router.put("/files/{path:path}", responses=errors(403, 409, 422))
async def write_file(
    path: str, data: FileWrite, access: KnowledgeEditor, session: SessionDep
) -> FileRead:
    """Create or replace a file (text formats only, up to 1 MB). Send `base_version` to
    avoid overwriting someone else's change (409 `version_conflict`). Writing identical
    content is a no-op. `agent-rules/` needs owner or admin."""
    return await KnowledgeService(session).write(
        access.project,
        path,
        data.content,
        _person(access),
        base_version=data.base_version,
        message=data.message,
    )


@router.delete(
    "/files/{path:path}", status_code=status.HTTP_204_NO_CONTENT, responses=errors(403, 409, 422)
)
async def delete_file(
    path: str,
    access: KnowledgeEditor,
    session: SessionDep,
    base_version: int | None = Query(default=None, ge=1),
) -> None:
    """Delete a file. Recorded as a version, so it can be restored."""
    await KnowledgeService(session).delete(
        access.project, path, _person(access), base_version=base_version
    )
