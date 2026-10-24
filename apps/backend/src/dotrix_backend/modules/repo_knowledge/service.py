"""Taking a connected repository's inventory, and what its knowledge covers.

`snapshot` lists every tracked path at the checkout's commit (once per commit and classification
rules), keeping "analyzed" for a path whose content (its git blob) is unchanged since the last
snapshot, so the skill rereads only what changed. `coverage` reports path coverage and domain
coverage separately: a domain with no evidence in the repository is a named gap, never silence.
"""
from __future__ import annotations

import asyncio
import logging
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import delete, func, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from uuid_utils.compat import uuid7

from dotrix_backend.core.errors import Conflict, Unprocessable
from dotrix_backend.modules.code.checkouts import CodeCheckouts
from dotrix_backend.modules.code.service import CodeService
from dotrix_backend.modules.knowledge.models import KnowledgeFile
from dotrix_backend.modules.notifications.notify import Notifier
from dotrix_backend.modules.projects.models import Project
from dotrix_engine.dependencies import read_dependencies
from dotrix_engine.inventory import (
    DOMAINS,
    GAP_HINTS,
    POLICY_VERSION,
    CheckoutMoved,
    take_inventory,
)

from .models import PathStatus, RepoPath, RepoSnapshot
from .schemas import (
    DependencyRead,
    DomainCoverage,
    RepoCoverageRead,
    RepoDependenciesRead,
    RepoPageRead,
    RepoPagesRead,
    RepoPathPage,
    RepoPathRead,
    RepoSnapshotRead,
    StaleSource,
    UnreadFile,
)

logger = logging.getLogger(__name__)

WIKI = "docs/wiki/"  # where the skill's pages live
# `path:12` or `path:12-40`, in backticks (the citation format the skill asks for)
CITATION = re.compile(r"`([^`\s:]+):(\d+)(?:-(\d+))?`")
_ALWAYS = (WIKI + "architecture.md", WIKI + "quality.md")  # what a coding brief always wants, when written
KEEP_SNAPSHOTS = 3  # a project's latest few: enough to compare, without a row per path per push forever
PAGE_MAX = 500
_OPEN = (PathStatus.PENDING, PathStatus.UNSUPPORTED, PathStatus.INACCESSIBLE)


def _stale_sources(pages: RepoPagesRead) -> dict[str, set[tuple[str, str]]]:
    """Each page's cited paths that changed or left the repository (never read isn't a push's doing)."""
    return {p.path: {(s.path, s.why) for s in p.stale if s.why != "unread"} for p in pages.pages}


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
        workspace_id, project_id = project.workspace_id, project.id  # (a rollback below expires `project`)
        existing = await self._at(workspace_id, project_id, checkout.sha)
        if existing is not None:
            return RepoSnapshotRead.model_validate(existing)
        async with self.checkouts.held(project_id):  # one commit's files throughout, never a sync's swap halfway
            try:
                inventory = await take_inventory(checkout.root)
            except CheckoutMoved as exc:
                raise Conflict("The repository changed while it was read; try again in a moment") from exc
        if inventory.commit != checkout.sha and (existing := await self._at(workspace_id, project_id, inventory.commit)):
            return RepoSnapshotRead.model_validate(existing)  # a push landed meanwhile, and its sync took it
        previous = await self._latest(project)
        stale_before = _stale_sources(await self.pages(project)) if previous is not None else {}
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
            found = await self._at(workspace_id, project_id, inventory.commit)
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
        if previous is not None:  # pages the new commit made stale (not ones that already were)
            stale_now = _stale_sources(await self.pages(project))
            newly = [page for page, sources in stale_now.items() if sources - stale_before.get(page, set())]
            if newly:
                await Notifier(self.session).stale_pages(project, newly, checkout.full_name, datetime.now(UTC))
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

    async def pages(self, project: Project) -> RepoPagesRead:
        """Each wiki page, stale when a path it cites changed since it was read, left the repository,
        or was never read. Read when asked, from the pages as they are now: a person's edit counts."""
        snap = await self._latest(project)
        files = await self._wiki(project)
        cited = {f.path: list(dict.fromkeys(m.group(1) for m in CITATION.finditer(f.content))) for f in files}
        wanted = {p for paths in cited.values() for p in paths}
        status: dict[str, PathStatus] = {}
        read_before: set[str] = set()
        if snap is not None and wanted:
            status = {path: PathStatus(s) for path, s in await self.session.execute(
                select(RepoPath.path, RepoPath.status).where(
                    RepoPath.workspace_id == project.workspace_id, RepoPath.snapshot_id == snap.id,
                    RepoPath.path.in_(wanted)))}
            # Read in an earlier inventory and not since: its content changed.
            read_before = set(await self.session.scalars(select(RepoPath.path).join(
                RepoSnapshot, RepoSnapshot.id == RepoPath.snapshot_id).where(
                RepoPath.workspace_id == project.workspace_id, RepoSnapshot.project_id == project.id,
                RepoSnapshot.id != snap.id, RepoPath.status == PathStatus.ANALYZED, RepoPath.path.in_(wanted))))
        pages = []
        for f in files:
            stale = []
            for path in cited[f.path] if snap is not None else []:
                state = status.get(path)
                if state is None:
                    stale.append(StaleSource(path=path, why="removed"))
                elif state is not PathStatus.ANALYZED:
                    stale.append(StaleSource(path=path, why="changed" if path in read_before else "unread"))
            pages.append(RepoPageRead(path=f.path, version=f.version, updated_at=f.updated_at,
                                      citations=len(CITATION.findall(f.content)), stale=stale))
        return RepoPagesRead(commit_sha=snap.commit_sha if snap else None, pages=pages)

    async def relevant(self, project: Project, text: str, *, limit: int = 3) -> list[tuple[str, str, list[str]]]:
        """The wiki pages that bear on `text` (an issue, a question): (path, content, why it's stale).
        Pages sharing the text's words first; the architecture and quality pages break ties, so a
        coding brief always says how the code is laid out and tested when the wiki does."""
        files = {f.path: f for f in await self._wiki(project)}
        if not files:
            return []
        words = {w for w in re.findall(r"[a-z][a-z0-9_]{3,}", text.lower())}
        def score(f: KnowledgeFile) -> tuple[int, int]:
            body = f.content.lower()
            return (sum(1 for w in words if w in body), int(f.path in _ALWAYS))
        ranked = sorted(files.values(), key=score, reverse=True)
        chosen = [f for f in ranked if score(f) != (0, 0)][:limit]
        stale = {p.path: [f"{s.path} {s.why}" for s in p.stale if s.why != "unread"] for p in (await self.pages(project)).pages}
        return [(f.path, f.content, stale.get(f.path, [])) for f in chosen]

    async def summary(self, project: Project) -> str:
        """What the repository's knowledge covers, in a few lines, for an agent run's context pack."""
        coverage = await self.coverage(project)
        if coverage.snapshot is None:
            return ""
        by: dict[str, list[str]] = {}
        for d in coverage.domains:
            by.setdefault(d.status, []).append(d.title.split(":")[0].lower())
        words = {"covered": "read", "partial": "partly read", "pending": "not read yet", "gap": "no evidence in the code"}
        lines = [
            f"## Repository knowledge ({coverage.snapshot.repo_full_name} at {coverage.snapshot.commit_sha[:7]})",
            "Pages under docs/wiki/ explain the code, each claim with its source (`path:line`): read the one "
            "you need before exploring the code, and check its sources when it's stale.",
            "Domains: " + "; ".join(f"{words[k]}: {', '.join(v)}" for k, v in by.items() if k in words) + ".",
        ]
        stale = [p for p in (await self.pages(project)).pages if p.stale]
        if stale:
            lines.append("Stale pages: " + "; ".join(
                f"{p.path} ({', '.join(f'{s.path} {s.why}' for s in p.stale[:3])})" for p in stale[:5]))
        return "\n".join(lines)

    async def dependencies(self, project: Project, root: Path | None = None) -> RepoDependenciesRead:
        """The manifests' direct dependencies and their locked versions, at the checkout's commit
        (`root`: a run's checkout; else this server's, synced if needed)."""
        snap = await self._latest(project)
        if snap is None:
            return RepoDependenciesRead(commit_sha=None, dependencies=[], unread=[])
        if root is None:
            if self.checkouts is None:
                raise Unprocessable("Reading code isn't set up on this server")
            checkout = await CodeService(self.session, self.checkouts).ensure(project.workspace_id, project.id)
            if checkout is None:
                raise Unprocessable("Connect the project's GitHub repository first (or its checkout failed: see its settings)")
            root = Path(checkout.root)
        paths = list(await self.session.scalars(select(RepoPath.path).where(
            RepoPath.workspace_id == project.workspace_id, RepoPath.snapshot_id == snap.id,
            RepoPath.kinds.overlap(["manifest", "lockfile"]),
        )))
        found = await asyncio.to_thread(read_dependencies, root, paths)
        commit = (await self.checkouts.head(project.workspace_id, project.id)) if self.checkouts else None
        return RepoDependenciesRead(
            commit_sha=commit or snap.commit_sha,
            dependencies=[DependencyRead(**vars(d)) for d in found.dependencies],
            unread=[UnreadFile(path=p, reason=r) for p, r in found.unread],
        )

    async def _wiki(self, project: Project) -> list[KnowledgeFile]:
        return list(await self.session.scalars(select(KnowledgeFile).where(
            KnowledgeFile.workspace_id == project.workspace_id, KnowledgeFile.project_id == project.id,
            KnowledgeFile.path.startswith(WIKI, autoescape=True), KnowledgeFile.deleted.is_(False),
        ).order_by(KnowledgeFile.path)))

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

    async def _at(self, workspace_id: uuid.UUID, project_id: uuid.UUID, commit: str) -> RepoSnapshot | None:
        return await self.session.scalar(select(RepoSnapshot).where(
            RepoSnapshot.workspace_id == workspace_id, RepoSnapshot.project_id == project_id,
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
