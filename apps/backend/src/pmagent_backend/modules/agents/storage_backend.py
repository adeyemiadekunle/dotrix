"""The deepagents storage backend for a project's `.pmagent/` on the platform.

Agent file tools (ls, read_file, glob, grep, write_file, edit_file) land here.
Reads come from the knowledge store. Writes go through KnowledgeService, so the
per-agent folder permissions (FR-41), version history, and audit log all apply:
each write records which agent made it, who instructed the run, and who
approved the action.

Which agent is writing comes from LangGraph's run config: deepagents tags each
subagent's calls with `metadata.lc_agent_name`; anything else is the Project
Manager. Mounted at `/pmagent/` behind a CompositeBackend, so paths arrive here
as `/requirements/product.md`.

Built against deepagents 0.7.19 (pinned <0.8): the read/glob/grep helpers are
the same ones its StateBackend uses, so behaviour matches its other backends.
"""
from __future__ import annotations

import uuid
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Any

from deepagents.backends.protocol import (
    BackendProtocol,
    DeleteResult,
    EditResult,
    FileData,
    FileDownloadResponse,
    FileInfo,
    FileUploadResponse,
    GlobResult,
    GrepResult,
    LsResult,
    ReadResult,
    WriteResult,
)
from deepagents.backends.utils import (
    InvalidGlobPatternError,
    _glob_search_files,
    grep_matches_from_files,
    perform_string_replacement,
    slice_read_response,
)
from langgraph.config import get_config
from sqlalchemy.ext.asyncio import AsyncSession

from pmagent_backend.core.errors import DomainError
from pmagent_backend.modules.knowledge.repository import KnowledgeRepository
from pmagent_backend.modules.knowledge.service import Actor, KnowledgeService
from pmagent_backend.modules.projects.repository import ProjectRepository
from pmagent_engine.agent import role_for_agent_name

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


def current_agent_role() -> str:
    try:
        metadata = get_config().get("metadata") or {}
    except RuntimeError:  # not inside a graph run
        metadata = {}
    return role_for_agent_name(metadata.get("lc_agent_name"))


class PlatformKnowledgeBackend(BackendProtocol):
    def __init__(
        self,
        session_factory: SessionFactory,
        *,
        workspace_id: uuid.UUID,
        project_id: uuid.UUID,
        instructed_by_id: uuid.UUID | None,
        approved_by_id: uuid.UUID | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.workspace_id = workspace_id
        self.project_id = project_id
        self.instructed_by_id = instructed_by_id
        # Set only when a run resumes after a person approved its pending writes.
        self.approved_by_id = approved_by_id

    # -- reads -------------------------------------------------------------------------

    async def _files(self) -> dict[str, FileData]:
        async with self.session_factory() as session:
            files = await KnowledgeRepository(session).list_files(self.project_id)
        return {
            f"/{f.path}": {
                "content": f.content,
                "encoding": "utf-8",
                "created_at": f.created_at.isoformat(),
                "modified_at": f.updated_at.isoformat(),
            }
            for f in files
        }

    async def aread(self, file_path: str, offset: int = 0, limit: int = 2000) -> ReadResult:
        file = (await self._files()).get(file_path)
        if file is None:
            return ReadResult(error=f"File '{file_path}' not found")
        return slice_read_response(file, offset, limit)

    async def als(self, path: str) -> LsResult:
        files = await self._files()
        prefix = path if path.endswith("/") else path + "/"
        entries: list[FileInfo] = []
        subdirs: set[str] = set()
        for key, data in files.items():
            if not key.startswith(prefix):
                continue
            rest = key[len(prefix):]
            if "/" in rest:
                subdirs.add(prefix + rest.split("/")[0] + "/")
                continue
            entries.append(
                {
                    "path": key,
                    "is_dir": False,
                    "size": len(data["content"].encode("utf-8")),
                    "modified_at": data.get("modified_at", ""),
                }
            )
        entries.extend({"path": d, "is_dir": True, "size": 0} for d in sorted(subdirs))
        return LsResult(entries=sorted(entries, key=lambda e: e["path"]))

    async def aglob(self, pattern: str, path: str | None = None) -> GlobResult:
        files = await self._files()
        try:
            result = _glob_search_files(files, pattern, path)
        except InvalidGlobPatternError as exc:
            return GlobResult(error=str(exc))
        if result == "No files found":
            return GlobResult(matches=[])
        return GlobResult(
            matches=[
                {"path": p, "is_dir": False, "size": len(files[p]["content"].encode("utf-8"))}
                for p in result.split("\n")
                if p in files
            ]
        )

    async def agrep(
        self, pattern: str, path: str | None = None, glob: str | None = None, *, max_count: int | None = None
    ) -> GrepResult:
        files = await self._files()
        return grep_matches_from_files(files, pattern, path if path is not None else "/", glob, max_count=max_count)

    # -- writes ------------------------------------------------------------------------

    async def awrite(self, file_path: str, content: str) -> WriteResult:
        error = await self._write(file_path, content)
        return WriteResult(error=error) if error else WriteResult(path=file_path)

    async def aedit(
        self, file_path: str, old_string: str, new_string: str, replace_all: bool = False
    ) -> EditResult:
        file = (await self._files()).get(file_path)
        if file is None:
            return EditResult(error=f"Error: File '{file_path}' not found")
        replaced = perform_string_replacement(file["content"], old_string, new_string, replace_all)
        if isinstance(replaced, str):
            return EditResult(error=replaced)
        new_content, occurrences = replaced
        error = await self._write(file_path, new_content)
        return EditResult(error=error) if error else EditResult(path=file_path, occurrences=int(occurrences))

    async def _write(self, file_path: str, content: str) -> str | None:
        """Write through KnowledgeService; returns an error message for the agent, or None."""
        if self.approved_by_id is None or self.instructed_by_id is None:
            return "Permission denied: writes need a person's instruction and approval"
        actor = Actor.agent_run(current_agent_role(), self.instructed_by_id, self.approved_by_id)
        async with self.session_factory() as session:
            project = await ProjectRepository(session).get(self.workspace_id, self.project_id)
            if project is None:
                return "Project not found"
            try:
                await KnowledgeService(session).write(project, file_path.lstrip("/"), content, actor)
            except DomainError as exc:
                return f"Error: {exc.detail}"
        return None

    # -- not offered to agents -----------------------------------------------------------

    async def adelete(self, file_path: str) -> DeleteResult:
        return DeleteResult(error="Agents can't delete project knowledge; ask a person")

    async def aupload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        return [FileUploadResponse(path=p, error="permission_denied") for p, _ in files]

    async def adownload_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        return [FileDownloadResponse(path=p, error="permission_denied") for p in paths]

    def _sync_unsupported(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("PlatformKnowledgeBackend is async-only; run agents with ainvoke")

    ls = read = write = edit = glob = grep = delete = upload_files = download_files = _sync_unsupported
