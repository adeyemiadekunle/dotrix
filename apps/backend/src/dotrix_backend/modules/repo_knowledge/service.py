"""Taking a connected repository's inventory, and what its knowledge covers.

`snapshot` lists every tracked path at the checkout's commit (once per commit and classification
rules), keeping "analyzed" for a path whose content (its git blob) is unchanged since the last
snapshot, so the skill rereads only what changed. `coverage` reports path coverage and domain
coverage separately: a domain with no evidence in the repository is a named gap, never silence.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import delete, func, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from uuid_utils.compat import uuid7

from dotrix_backend.core.errors import Unprocessable
from dotrix_backend.modules.code.checkouts import CodeCheckouts
from dotrix_backend.modules.code.service import CodeService
from dotrix_backend.modules.projects.models import Project
from dotrix_engine.inventory import DOMAINS, GAP_HINTS, POLICY_VERSION, take_inventory

from .models import PathStatus, RepoPath, RepoSnapshot
from .schemas import DomainCoverage, RepoCoverageRead, RepoPathPage, RepoPathRead, RepoSnapshotRead

logger = logging.getLogger(__name__)

KEEP_SNAPSHOTS = 3  # a project's latest few: enough to compare, without a row per path per push forever
PAGE_MAX = 500
_OPEN = (PathStatus.PENDING, PathStatus.UNSUPPORTED, PathStatus.INACCESSIBLE)


class RepoKnowledgeService:
    def __init__(self, session: AsyncSession, checkouts: CodeCheckouts | None) -> None:
        self.session, self.checkouts = session, checkouts

    async def snapshot(self, project: Project) -> RepoSnapshotRead:
        """The inventory at the repository's current commit: taken now, or the one already taken."""
        if self.checkouts is None:
            raise Unprocessable("Reading code isn't set up on this server")
        checkout = await CodeService(self.session, self.checkouts).ensure(project.workspace_id, project.id)
        if checkout is None:
            raise Unprocessable("Connect the project's GitHub repository first (or its checkout failed: see its settings)")
        existing = await self._at(project, checkout.sha)
        if existing is not None:
            return RepoSnapshotRead.model_validate(existing)
        inventory = await take_inventory(checkout.root)
        previous = await self._latest(project)
        # Content the skill already read, unchanged since: still read.
        kept: dict[tuple[str, str], tuple[datetime | None, object]] = {}
        if previous is not None:
            kept = {(path, blob): (at, run) for path, blob, at, run in await self.session.execute(
                select(RepoPath.path, RepoPath.blob, RepoPath.analyzed_at, RepoPath.analyzed_run_id).where(
                    RepoPath.workspace_id == project.workspace_id, RepoPath.snapshot_id == previous.id,
                    RepoPath.status == PathStatus.ANALYZED,
                ))}
        row = RepoSnapshot(
            id=uuid7(), workspace_id=project.workspace_id, project_id=project.id, repo_full_name=checkout.full_name,
            commit_sha=inventory.commit, policy_version=inventory.policy_version, path_count=len(inventory.paths),
            created_at=datetime.now(UTC),
        )
        self.session.add(row)
        try:
            await self.session.flush()
        except IntegrityError:  # taken meanwhile (a push and a person at once): that one stands
            await self.session.rollback()
            found = await self._at(project, checkout.sha)
            assert found is not None
            return RepoSnapshotRead.model_validate(found)
        rows = []
        for p in inventory.paths:
            was = kept.get((p.path, p.blob)) if p.status == "pending" else None
            rows.append({
                "id": uuid7(), "workspace_id": project.workspace_id, "snapshot_id": row.id, "path": p.path,
                "size": min(p.size, 2**31 - 1), "blob": p.blob, "language": p.language, "kinds": list(p.kinds),
                "domains": list(p.domains), "status": PathStatus.ANALYZED if was else PathStatus(p.status),
                "reason": p.reason, "analyzed_at": was[0] if was else None, "analyzed_run_id": was[1] if was else None,
            })
        for start in range(0, len(rows), 1000):
            await self.session.execute(insert(RepoPath), rows[start:start + 1000])
        await self._prune(project)
        await self.session.commit()
        logger.info("inventory of %s at %s: %d paths", checkout.full_name, inventory.commit[:7], len(rows))
        return RepoSnapshotRead.model_validate(row)

    async def coverage(self, project: Project) -> RepoCoverageRead:
        snap = await self._latest(project)
        if snap is None:
            return RepoCoverageRead(snapshot=None, inventory_complete=False, discovery_complete=False, domains=[])
        statuses = {PathStatus(s): n for s, n in await self.session.execute(
            select(RepoPath.status, func.count()).where(
                RepoPath.workspace_id == project.workspace_id, RepoPath.snapshot_id == snap.id,
            ).group_by(RepoPath.status))}
        domain = func.unnest(RepoPath.domains).label("domain")
        counts: dict[str, dict[PathStatus, int]] = {}
        per_domain = select(domain, RepoPath.status, func.count()).where(
            RepoPath.workspace_id == project.workspace_id, RepoPath.snapshot_id == snap.id,
        ).group_by(domain, RepoPath.status)
        for name, status, n in await self.session.execute(per_domain):
            counts.setdefault(name, {})[PathStatus(status)] = n
        domains = []
        for name, title in DOMAINS.items():
            by = counts.get(name, {})
            excluded = by.get(PathStatus.EXCLUDED, 0)
            analyzed = by.get(PathStatus.ANALYZED, 0)
            readable = sum(n for s, n in by.items() if s is not PathStatus.EXCLUDED)
            state = ("gap" if readable == 0 else "covered" if analyzed == readable
                     else "partial" if analyzed else "pending")
            domains.append(DomainCoverage(
                domain=name, title=title, status=state, paths=readable, analyzed=analyzed, excluded=excluded,
                gap=GAP_HINTS[name] if state == "gap" else None,
            ))
        return RepoCoverageRead(
            snapshot=RepoSnapshotRead.model_validate(snap), statuses=statuses,
            inventory_complete=sum(statuses.values()) == snap.path_count,
            discovery_complete=not any(statuses.get(s) for s in _OPEN),
            domains=domains,
        )

    async def paths(self, project: Project, *, status: PathStatus | None, domain: str | None, prefix: str | None,
                    after: str | None, limit: int) -> RepoPathPage:
        """The latest snapshot's paths, in path order, a page at a time."""
        snap = await self._latest(project)
        if snap is None:
            return RepoPathPage(paths=[], next=None)
        query = select(RepoPath).where(RepoPath.workspace_id == project.workspace_id, RepoPath.snapshot_id == snap.id)
        if status is not None:
            query = query.where(RepoPath.status == status)
        if domain is not None:
            query = query.where(RepoPath.domains.contains([domain]))
        if prefix:
            query = query.where(RepoPath.path.startswith(prefix, autoescape=True))
        if after:
            query = query.where(RepoPath.path > after)
        rows = list(await self.session.scalars(query.order_by(RepoPath.path).limit(min(limit, PAGE_MAX) + 1)))
        page = rows[:min(limit, PAGE_MAX)]
        return RepoPathPage(paths=[RepoPathRead.model_validate(r) for r in page],
                        next=page[-1].path if len(rows) > len(page) else None)

    async def _latest(self, project: Project) -> RepoSnapshot | None:
        return await self.session.scalar(select(RepoSnapshot).where(
            RepoSnapshot.workspace_id == project.workspace_id, RepoSnapshot.project_id == project.id,
        ).order_by(RepoSnapshot.created_at.desc()).limit(1))

    async def _at(self, project: Project, commit: str) -> RepoSnapshot | None:
        return await self.session.scalar(select(RepoSnapshot).where(
            RepoSnapshot.workspace_id == project.workspace_id, RepoSnapshot.project_id == project.id,
            RepoSnapshot.commit_sha == commit, RepoSnapshot.policy_version == POLICY_VERSION,
        ))

    async def _prune(self, project: Project) -> None:
        keep = select(RepoSnapshot.id).where(
            RepoSnapshot.workspace_id == project.workspace_id, RepoSnapshot.project_id == project.id,
        ).order_by(RepoSnapshot.created_at.desc()).limit(KEEP_SNAPSHOTS)
        await self.session.execute(delete(RepoSnapshot).where(
            RepoSnapshot.workspace_id == project.workspace_id, RepoSnapshot.project_id == project.id,
            RepoSnapshot.id.not_in(keep.scalar_subquery()),
        ))
