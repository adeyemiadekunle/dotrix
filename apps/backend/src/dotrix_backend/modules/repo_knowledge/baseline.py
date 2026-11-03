"""Human baseline reviews bind to evidence revisions, not a mutable 'understood' flag."""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dotrix_backend.core.errors import Conflict, Unprocessable
from dotrix_backend.modules.audit.models import AuthorType
from dotrix_backend.modules.audit.service import AuditLog
from dotrix_backend.modules.code.checkouts import CodeCheckouts
from dotrix_backend.modules.connectors.models import ConnectedRepo
from dotrix_backend.modules.knowledge.models import KnowledgeFile
from dotrix_backend.modules.projects.deps import ProjectAccess
from dotrix_backend.modules.projects.models import Project

from .models import RepoBaselineReview
from .schemas import (
    BaselineHumanContextRead,
    BaselineReviewCreate,
    BaselineReviewRead,
    RepoBaselineRead,
)
from .service import RepoKnowledgeService


def _digest(evidence: dict) -> str:
    return hashlib.sha256(json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class BaselineService:
    def __init__(self, session: AsyncSession, checkouts: CodeCheckouts | None) -> None:
        self.session, self.checkouts = session, checkouts

    async def human_context(self, project: Project) -> BaselineHumanContextRead | None:
        """Blank attestations don't erase the last explicitly saved human context."""
        row = await self.session.scalar(select(RepoBaselineReview).where(
            RepoBaselineReview.workspace_id == project.workspace_id, RepoBaselineReview.project_id == project.id,
            RepoBaselineReview.notes != "",
        ).order_by(RepoBaselineReview.created_at.desc(), RepoBaselineReview.id.desc()).limit(1))
        return BaselineHumanContextRead(revision=row.id, notes=row.notes, updated_by_id=row.reviewed_by_id,
                                        updated_at=row.created_at) if row else None

    async def state(self, project: Project) -> RepoBaselineRead:
        human_context = await self.human_context(project)
        knowledge = RepoKnowledgeService(self.session, self.checkouts)
        coverage, pages = await knowledge.coverage(project), await knowledge.pages(project)
        repo = await self.session.scalar(select(ConnectedRepo).where(
            ConnectedRepo.workspace_id == project.workspace_id, ConnectedRepo.project_id == project.id))
        documents = list(await self.session.scalars(select(KnowledgeFile).where(
            KnowledgeFile.workspace_id == project.workspace_id, KnowledgeFile.project_id == project.id,
            KnowledgeFile.deleted.is_(False),
            (KnowledgeFile.path.startswith("docs/wiki/", autoescape=True)
             | KnowledgeFile.path.startswith("requirements/", autoescape=True)
             | KnowledgeFile.path.startswith("decisions/", autoescape=True)),
        ).order_by(KnowledgeFile.path)))
        evidence = {
            "repository_id": repo.github_repo_id if repo else None,
            "repository": repo.full_name if repo else None,
            "latest_push": repo.last_push_sha if repo else None,
            "checkout": repo.checkout_sha if repo else None,
            "purpose": project.description,
            "knowledge_revision": project.knowledge_revision,
            "human_context": {"revision": str(human_context.revision), "notes": human_context.notes} if human_context else None,
            "coverage": coverage.model_dump(mode="json"),
            "pages": pages.model_dump(mode="json"),
            "documents": [{"path": f.path, "version": f.version, "revision": f.revision, "hash": f.content_hash} for f in documents],
        }
        digest = _digest(evidence)
        blockers = []
        if not repo:
            blockers.append("Connect a repository before reviewing its baseline.")
        if not coverage.snapshot:
            blockers.append("Take an inventory, then explain the repository.")
        elif repo:
            if not coverage.inventory_complete:
                blockers.append("The inventory is incomplete. Take a fresh inventory before confirming.")
            snap = coverage.snapshot
            if (repo.full_name != snap.repo_full_name
                    or any(sha and sha != snap.commit_sha for sha in (repo.last_push_sha, repo.checkout_sha))):
                blockers.append("The repository changed after this inventory. Sync it and take a fresh inventory first.")
            if repo.checkout_error:
                blockers.append("The repository checkout failed. Restore access and sync it before confirming.")
        if not pages.pages or not any(p.citations for p in pages.pages):
            blockers.append("Explain the repository and save cited wiki pages before confirming a baseline.")
        if any(p.stale for p in pages.pages):
            blockers.append("Review and refresh stale citations before confirming this baseline.")
        review = await self.session.scalar(select(RepoBaselineReview).where(
            RepoBaselineReview.workspace_id == project.workspace_id, RepoBaselineReview.project_id == project.id,
        ).order_by(RepoBaselineReview.created_at.desc(), RepoBaselineReview.id.desc()).limit(1))
        return RepoBaselineRead(digest=digest, can_confirm=not blockers, blockers=blockers, evidence=evidence,
            current=bool(review and review.decision == "confirmed" and review.digest == digest and not blockers),
            review=BaselineReviewRead.model_validate(review) if review else None, human_context=human_context)

    async def review(self, access: ProjectAccess, data: BaselineReviewCreate) -> RepoBaselineRead:
        project = access.project
        project = await self.session.scalar(select(Project).where(
            Project.workspace_id == project.workspace_id, Project.id == project.id).with_for_update()
            .execution_options(populate_existing=True))
        assert project is not None
        previous = await self.session.scalar(select(RepoBaselineReview).where(
            RepoBaselineReview.workspace_id == project.workspace_id, RepoBaselineReview.project_id == project.id,
            RepoBaselineReview.request_id == data.request_id))
        if previous:
            if (previous.reviewed_by_id != access.member.user_id or (previous.request_digest or previous.digest) != data.digest
                    or previous.decision != data.decision or previous.notes != data.notes.strip()):
                raise Conflict("This review request already belongs to a different decision")
            return await self.state(project)
        state = await self.state(project)
        if data.digest != state.digest:
            raise Conflict("The baseline changed while you reviewed it. Reload the evidence and review again.")
        if data.decision == "confirmed" and (not state.can_confirm or not data.acknowledge_limits):
            raise Unprocessable("Resolve the baseline prerequisites and acknowledge its coverage limits first")
        if data.decision == "corrections" and not data.notes.strip():
            raise Unprocessable("Describe the corrections or missing project context")
        review = RepoBaselineReview(workspace_id=project.workspace_id, project_id=project.id,
            request_id=data.request_id, request_digest=data.digest, digest=state.digest, decision=data.decision,
            notes=data.notes.strip(), evidence=state.evidence, reviewed_by_id=access.member.user_id, created_at=datetime.now(UTC))
        self.session.add(review)
        await self.session.flush()
        # New notes become a new context revision in this same project-locked transaction.
        # Bind the attestation to that resulting evidence, keeping its submitted digest
        # separately so a lost-response retry still matches the original request.
        resulting_evidence = dict(state.evidence)
        if review.notes:
            resulting_evidence["human_context"] = {"revision": str(review.id), "notes": review.notes}
        # Don't absorb unrelated repository/document changes during submission into
        # evidence the person did not see. A fresh read will mark those out of date.
        review.digest, review.evidence = _digest(resulting_evidence), resulting_evidence
        AuditLog(self.session).record(workspace_id=project.workspace_id, project_id=project.id,
            action="repository.baseline_reviewed", target=str(project.id), actor_type=AuthorType.USER,
            actor_user_id=access.member.user_id, details={"digest": review.digest, "decision": data.decision})
        await self.session.commit()
        return await self.state(project)
