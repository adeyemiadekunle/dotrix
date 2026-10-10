"""Reads and writes of a project's `.dotrix/` files, with full version history.

Every write goes through `write()` and is checked against who is writing:

- People need `knowledge:write`; `agent-rules/` also needs owner or admin.
- Agents may only write where the engine's folder matrix allows (FR-41), and
  only with both an instructing and an approving person recorded.

Writes lock the project row, so each change gets the next project revision
and concurrent writers to the same project serialise.
"""
from __future__ import annotations

import difflib
import hashlib
import io
import uuid
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime

import yaml
from sqlalchemy.ext.asyncio import AsyncSession
from uuid_utils.compat import uuid7

from dotrix_backend.core.errors import Conflict, Forbidden, NotFound, Unprocessable
from dotrix_backend.modules.audit.service import AuditLog
from dotrix_backend.modules.automations.events import record_event
from dotrix_backend.modules.automations.models import AutomationEvent
from dotrix_backend.modules.projects.models import Project
from dotrix_backend.modules.projects.repository import ProjectRepository
from dotrix_backend.modules.workspaces.models import Role
from dotrix_engine.contracts import AgentPolicy
from dotrix_engine.knowledge_index import describe
from dotrix_engine.layout import MAX_FILE_BYTES, InvalidPath, normalize_path

from .models import AuthorType, KnowledgeFile, KnowledgeVersion
from .repository import KnowledgeRepository
from .schemas import FileEntry, FileRead, Manifest, VersionDiff, VersionEntry, VersionRead

RULES_PREFIX = "agent-rules/"
_BUILTIN_POLICY = AgentPolicy()


class InvalidKnowledgePath(Unprocessable):
    code = "invalid_path"


class FileTooLarge(Unprocessable):
    code = "file_too_large"


class VersionConflict(Conflict):
    code = "version_conflict"


@dataclass(frozen=True)
class Actor:
    """Who is changing `.dotrix/`, for permission checks and the version record."""

    kind: AuthorType
    user_id: uuid.UUID | None = None  # the person, when kind is USER
    role: Role | None = None  # their workspace role, when kind is USER
    agent: str | None = None  # when kind is AGENT
    instructed_by_id: uuid.UUID | None = None
    approved_by_id: uuid.UUID | None = None
    # The run's agent contracts (built-ins when None): what each agent may write.
    policy: AgentPolicy | None = None

    @classmethod
    def person(cls, user_id: uuid.UUID, role: Role) -> Actor:
        # A person editing directly both instructs and approves their own change.
        return cls(AuthorType.USER, user_id, role, None, user_id, user_id)

    @classmethod
    def agent_run(
        cls, agent: str, instructed_by_id: uuid.UUID, approved_by_id: uuid.UUID, policy: AgentPolicy | None = None
    ) -> Actor:
        return cls(AuthorType.AGENT, None, None, agent, instructed_by_id, approved_by_id, policy)

    @classmethod
    def system(cls) -> Actor:
        return cls(AuthorType.SYSTEM)


def _now() -> datetime:
    return datetime.now(UTC)


def _hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _clean_path(path: str) -> str:
    try:
        return normalize_path(path)
    except InvalidPath as exc:
        raise InvalidKnowledgePath(str(exc)) from exc


class KnowledgeService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.files = KnowledgeRepository(session)
        self.projects = ProjectRepository(session)

    # -- reads -------------------------------------------------------------------------

    async def manifest(self, project: Project, since_revision: int | None = None) -> Manifest:
        files = await self.files.list_files(project.id, since_revision=since_revision)
        return Manifest(
            revision=project.knowledge_revision,
            files=[FileEntry.model_validate(f) for f in files],
        )

    async def read(self, project: Project, path: str) -> FileRead:
        return FileRead.model_validate(await self._existing(project, path))

    async def versions(self, project: Project, path: str) -> list[VersionEntry]:
        file = await self._any(project, path)
        return [VersionEntry.model_validate(v) for v in await self.files.list_versions(file.id)]

    async def version(self, project: Project, path: str, version: int) -> VersionRead:
        return VersionRead.model_validate(await self._version(project, path, version))

    async def diff(self, project: Project, path: str, version: int) -> VersionDiff:
        """What `version` changed, compared with the version before it."""
        clean = _clean_path(path)
        after = await self._version(project, clean, version)
        before = await self.files.get_version(after.file_id, version - 1) if version > 1 else None
        old = "" if before is None or before.deleted else before.content
        new = "" if after.deleted else after.content
        diff = "".join(
            difflib.unified_diff(
                old.splitlines(keepends=True),
                new.splitlines(keepends=True),
                fromfile=f"a/{clean}" if before else "/dev/null",
                tofile=f"b/{clean}" if not after.deleted else "/dev/null",
            )
        )
        return VersionDiff(path=clean, from_version=version - 1, to_version=version, diff=diff)

    async def export_zip(self, project: Project) -> bytes:
        """Every current file under `.dotrix/`, plus a rendered config.yaml and one Markdown
        file per issue (`issues/KUN-1.md`), so leaving the platform loses nothing."""
        from dotrix_backend.modules.issues.render import (
            render_project_issues,  # avoid import cycle
        )

        buffer = io.BytesIO()
        config = {
            "key": project.key,
            "name": project.name,
            "description": project.description,
            "model": project.model,
        }
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(".dotrix/config.yaml", yaml.safe_dump(config, sort_keys=False))
            for file in await self.files.list_files(project.id):
                archive.writestr(f".dotrix/{file.path}", file.content)
            for path, content in (await render_project_issues(self.session, project.id)).items():
                archive.writestr(f".dotrix/{path}", content)
        return buffer.getvalue()

    # -- writes ------------------------------------------------------------------------

    async def scaffold(self, project: Project, files: dict[str, str]) -> None:
        """Create a new project's skeleton in one revision; the caller commits."""
        project.knowledge_revision += 1
        actor = Actor.system()
        for path, content in files.items():
            self._create(project, _clean_path(path), content, actor, "Project created")

    async def write(
        self,
        project: Project,
        path: str,
        content: str,
        actor: Actor,
        *,
        base_version: int | None = None,
        message: str | None = None,
    ) -> FileRead:
        clean = _clean_path(path)
        if len(content.encode("utf-8")) > MAX_FILE_BYTES:
            raise FileTooLarge(f"Files are limited to {MAX_FILE_BYTES // 1_000_000} MB")
        self._check_write(actor, clean)

        locked = await self._lock(project)
        file = await self.files.get_file(locked.id, clean)
        current = 0 if file is None or file.deleted else file.version
        if base_version is not None and base_version != current:
            raise VersionConflict(
                f"{clean} is at version {current}, not {base_version}. "
                "Reload it and apply your change again."
            )
        if file is not None and not file.deleted and file.content_hash == _hash(content):
            return FileRead.model_validate(file)  # unchanged: no new version

        locked.knowledge_revision += 1
        if file is None:
            file = self._create(locked, clean, content, actor, message)
        else:
            self._update(locked, file, content, actor, message, deleted=False)
        self._audit(locked, "knowledge.write", file, actor, message)
        if actor.kind is AuthorType.USER and not clean.startswith("agent-rules/"):
            # A person's edit (or an upload's text) sets automations off; an agent's never does.
            await record_event(
                self.session, workspace_id=locked.workspace_id, project_id=locked.id,
                event=AutomationEvent.DOCUMENT_CHANGED,
                summary=f"{clean} {'added' if file.version == 1 else f'edited (version {file.version})'}"
                + (f": {message}" if message else ""),
                details={"path": clean, "version": file.version},
            )
        await self.session.commit()
        return FileRead.model_validate(file)

    async def delete(
        self, project: Project, path: str, actor: Actor, *, base_version: int | None = None
    ) -> None:
        clean = _clean_path(path)
        self._check_write(actor, clean)
        locked = await self._lock(project)
        file = await self.files.get_file(locked.id, clean)
        if file is None or file.deleted:
            raise NotFound(f"{clean} not found")
        if base_version is not None and base_version != file.version:
            raise VersionConflict(f"{clean} is at version {file.version}, not {base_version}")
        locked.knowledge_revision += 1
        self._update(locked, file, "", actor, "Deleted", deleted=True)
        self._audit(locked, "knowledge.delete", file, actor, None)
        await self.session.commit()

    async def restore(
        self, project: Project, path: str, version: int, actor: Actor, *, base_version: int | None
    ) -> FileRead:
        old = await self._version(project, path, version)
        if old.deleted:
            raise Unprocessable(f"Version {version} is a deletion; restore an earlier version")
        return await self.write(
            project,
            path,
            old.content,
            actor,
            base_version=base_version,
            message=f"Restored version {version}",
        )

    # -- helpers -----------------------------------------------------------------------

    def _check_write(self, actor: Actor, path: str) -> None:
        if actor.kind is AuthorType.SYSTEM:
            return
        if actor.kind is AuthorType.AGENT:
            if actor.instructed_by_id is None or actor.approved_by_id is None:
                raise Forbidden("Agent writes need an instructing and an approving person")
            policy = actor.policy or _BUILTIN_POLICY
            if not policy.can_write(actor.agent or "", path):
                owner = policy.access(actor.agent or "", path)
                raise Forbidden(
                    f"The {actor.agent} agent can't write {path} (its access there is "
                    f"'{owner}'); ask the Project Manager to route the change to the owner"
                )
            return
        if path.startswith(RULES_PREFIX) and actor.role not in (Role.OWNER, Role.ADMIN):
            raise Forbidden("Only owners and admins can edit agent rules")

    def _create(
        self, project: Project, path: str, content: str, actor: Actor, message: str | None
    ) -> KnowledgeFile:
        now = _now()
        file = KnowledgeFile(
            id=uuid7(),  # needed before flush: versions reference it
            workspace_id=project.workspace_id,
            project_id=project.id,
            path=path,
            version=1,
            revision=project.knowledge_revision,
            content=content,
            content_hash=_hash(content),
            size=len(content.encode("utf-8")),
            deleted=False,
            created_at=now,
            updated_at=now,
        )
        describe_file(file)
        self.files.add(file)
        self._record(project, file, actor, message)
        return file

    def _update(
        self,
        project: Project,
        file: KnowledgeFile,
        content: str,
        actor: Actor,
        message: str | None,
        *,
        deleted: bool,
    ) -> None:
        file.version += 1
        file.revision = project.knowledge_revision
        file.content = content
        file.content_hash = _hash(content)
        file.size = len(content.encode("utf-8"))
        file.deleted = deleted
        file.updated_at = _now()
        describe_file(file)
        self._record(project, file, actor, message)

    def _record(
        self, project: Project, file: KnowledgeFile, actor: Actor, message: str | None
    ) -> None:
        self.files.add(
            KnowledgeVersion(
                workspace_id=project.workspace_id,
                file_id=file.id,
                project_id=project.id,
                version=file.version,
                revision=file.revision,
                content=file.content,
                content_hash=file.content_hash,
                deleted=file.deleted,
                author_type=actor.kind,
                author_id=actor.user_id,
                agent=actor.agent,
                instructed_by_id=actor.instructed_by_id,
                approved_by_id=actor.approved_by_id,
                message=message,
                created_at=file.updated_at,
            )
        )

    def _audit(
        self, project: Project, action: str, file: KnowledgeFile, actor: Actor, message: str | None
    ) -> None:
        AuditLog(self.session).record(
            workspace_id=project.workspace_id,
            project_id=project.id,
            action=action,
            target=file.path,
            actor_type=actor.kind,
            actor_user_id=actor.user_id,
            agent=actor.agent,
            instructed_by_id=actor.instructed_by_id,
            approved_by_id=actor.approved_by_id,
            details={"version": file.version, "revision": file.revision, "message": message},
        )

    async def _lock(self, project: Project) -> Project:
        locked = await self.projects.get(project.workspace_id, project.id, for_update=True)
        if locked is None:
            raise NotFound("Project not found")
        return locked

    async def _any(self, project: Project, path: str) -> KnowledgeFile:
        clean = _clean_path(path)
        file = await self.files.get_file(project.id, clean)
        if file is None:
            raise NotFound(f"{clean} not found")
        return file

    async def _existing(self, project: Project, path: str) -> KnowledgeFile:
        file = await self._any(project, path)
        if file.deleted:
            raise NotFound(f"{file.path} not found")
        return file

    async def _version(self, project: Project, path: str, version: int) -> KnowledgeVersion:
        file = await self._any(project, path)
        found = await self.files.get_version(file.id, version)
        if found is None:
            raise NotFound(f"{file.path} has no version {version}")
        return found


def describe_file(file: KnowledgeFile) -> None:
    """Keep the file's title, summary, and outline in step with its content."""
    described = describe(file.path, file.content)
    file.title, file.summary, file.outline = described.title, described.summary, described.outline
    file.described_version = file.version
