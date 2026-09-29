"""Keeping the search index current, and searching it.

- `sync(project)` re-chunks the documents and issues that changed since they were indexed
  (a document by version, an issue by its last change) and drops what's gone. It's only
  database work, so a search runs it first and keyword results are always current.
- `embed_pending(project)` gives chunks without a vector (or from another model) one, in
  batches; the `index_knowledge` job does it in the background, and chunks whose text didn't
  change keep their vector.
- `search(project, query)` merges full-text and vector rankings (reciprocal rank fusion).

Every query is scoped by project (and so by workspace).
"""
from __future__ import annotations

import hashlib
import logging
import math
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import and_, case, delete, func, literal_column, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from pmagent_backend.modules.issues.models import Issue, IssueEvent, IssueEventKind
from pmagent_backend.modules.knowledge.models import KnowledgeFile
from pmagent_backend.modules.projects.models import Project
from pmagent_engine.knowledge_index import sections

from .embeddings import CHARS_PER_TOKEN, Embedder
from .models import ChunkSource, KnowledgeChunk

logger = logging.getLogger(__name__)

NOT_INDEXED = ("agent-rules/",)  # instructions for the agents, not project knowledge
MAX_CHUNK_CHARS = 1_500
RECENT_COMMENTS = 3
EMBED_BATCH = 64
CANDIDATES = 30  # from each ranking, before merging
RRF_K = 60
SNIPPET_CHARS = 500
MAX_QUERY_WORDS = 16


@dataclass(frozen=True)
class Hit:
    source: ChunkSource
    ref: str  # the document's path or the issue's key
    heading: str | None
    snippet: str
    version: int
    score: float


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _split(text_: str, limit: int = MAX_CHUNK_CHARS) -> list[str]:
    """Long sections split between paragraphs (a paragraph longer than the limit is cut)."""
    if len(text_) <= limit:
        return [text_]
    parts: list[str] = []
    current = ""
    for paragraph in text_.split("\n\n"):
        while len(paragraph) > limit:
            parts.append(paragraph[:limit])
            paragraph = paragraph[limit:]
        if current and len(current) + len(paragraph) + 2 > limit:
            parts.append(current)
            current = paragraph
        else:
            current = f"{current}\n\n{paragraph}" if current else paragraph
    if current.strip():
        parts.append(current)
    return parts


def document_chunks(path: str, content: str) -> list[tuple[str | None, str]]:
    """(heading trail, text) for each chunk of a document; at least one, so a document is
    never re-indexed for lack of chunks."""
    found: list[tuple[str | None, str]] = []
    for section in sections(content, nested=False):
        for part in _split(section.text.strip()):
            if part.strip():
                found.append((section.trail or None, part))
    return found or [(None, content.strip() or path)]


def embedding_text(ref: str, heading: str | None, content: str) -> str:
    return f"{ref}{f' — {heading}' if heading else ''}\n{content}"


class KnowledgeIndex:
    def __init__(self, session: AsyncSession, embedder: Embedder | None = None) -> None:
        self.session = session
        self.embedder = embedder

    # -- keeping it current ----------------------------------------------------------------

    async def sync(self, project: Project) -> int:
        """Re-chunk what changed; returns how many documents and issues were re-indexed.

        One sync per project at a time (a search and the background job may both start one):
        the second waits for the first to commit, then finds nothing left to do."""
        await self.session.execute(
            select(func.pg_advisory_xact_lock(func.hashtextextended(f"knowledge_index:{project.id}", 0)))
        )
        changed = await self._sync_documents(project) + await self._sync_issues(project)
        if changed:
            await self.session.commit()
        return changed

    async def _sync_documents(self, project: Project) -> int:
        indexed = (
            select(KnowledgeChunk.file_id, func.max(KnowledgeChunk.version).label("version"))
            .where(KnowledgeChunk.project_id == project.id, KnowledgeChunk.source == ChunkSource.DOCUMENT)
            .group_by(KnowledgeChunk.file_id)
            .subquery()
        )
        live = and_(KnowledgeFile.deleted.is_(False), *(~KnowledgeFile.path.startswith(p) for p in NOT_INDEXED))
        stale = list(
            await self.session.scalars(
                select(KnowledgeFile)
                .outerjoin(indexed, indexed.c.file_id == KnowledgeFile.id)
                .where(
                    KnowledgeFile.project_id == project.id,
                    or_(
                        and_(live, or_(indexed.c.version.is_(None), indexed.c.version != KnowledgeFile.version)),
                        and_(~live, indexed.c.version.is_not(None)),
                    ),
                )
            )
        )
        for file in stale:
            gone = file.deleted or file.path.startswith(NOT_INDEXED)
            chunks = [] if gone else document_chunks(file.path, file.content)
            await self._replace(
                project,
                KnowledgeChunk.file_id == file.id,
                [
                    KnowledgeChunk(
                        workspace_id=project.workspace_id,
                        project_id=project.id,
                        source=ChunkSource.DOCUMENT,
                        file_id=file.id,
                        ref=file.path,
                        heading=heading[:300] if heading else None,
                        position=position,
                        content=content,
                        content_hash=_hash(embedding_text(file.path, heading, content)),
                        version=file.version,
                        source_updated_at=file.updated_at,
                    )
                    for position, (heading, content) in enumerate(chunks)
                ],
            )
        return len(stale)

    async def _sync_issues(self, project: Project) -> int:
        indexed = (
            select(KnowledgeChunk.issue_id, func.max(KnowledgeChunk.source_updated_at).label("at"))
            .where(KnowledgeChunk.project_id == project.id, KnowledgeChunk.source == ChunkSource.ISSUE)
            .group_by(KnowledgeChunk.issue_id)
            .subquery()
        )
        stale = list(
            await self.session.scalars(
                select(Issue)
                .outerjoin(indexed, indexed.c.issue_id == Issue.id)
                .where(Issue.project_id == project.id, or_(indexed.c.at.is_(None), indexed.c.at < Issue.updated_at))
            )
        )
        comments: dict[uuid.UUID, list[str]] = {}
        if stale:
            rows = await self.session.execute(
                select(IssueEvent.issue_id, IssueEvent.body)
                .where(
                    IssueEvent.issue_id.in_([i.id for i in stale]),
                    IssueEvent.kind == IssueEventKind.COMMENTED,
                    IssueEvent.body.is_not(None),
                )
                .order_by(IssueEvent.created_at.desc())
            )
            for issue_id, body in rows:
                listed = comments.setdefault(issue_id, [])
                if len(listed) < RECENT_COMMENTS:
                    listed.append(body[:300])
        for issue in stale:
            content = self._issue_text(issue, comments.get(issue.id, []))
            await self._replace(
                project,
                KnowledgeChunk.issue_id == issue.id,
                [
                    KnowledgeChunk(
                        workspace_id=project.workspace_id,
                        project_id=project.id,
                        source=ChunkSource.ISSUE,
                        issue_id=issue.id,
                        ref=issue.key,
                        heading=issue.title[:300],
                        position=0,
                        content=content,
                        content_hash=_hash(embedding_text(issue.key, issue.title, content)),
                        version=0,
                        source_updated_at=issue.updated_at,
                    )
                ],
            )
        return len(stale)

    @staticmethod
    def _issue_text(issue: Issue, comments: list[str]) -> str:
        lines = [f"{issue.type.value.replace('_', ' ').capitalize()}, {issue.status.value.replace('_', ' ')}, "
                 f"{issue.priority.value} priority"]
        if issue.labels:
            lines.append("Labels: " + ", ".join(issue.labels))
        if issue.description.strip():
            lines += ["", issue.description.strip()[:MAX_CHUNK_CHARS * 2]]
        if comments:
            lines += ["", "Recent comments:", *(f"- {c}" for c in reversed(comments))]
        return "\n".join(lines)

    async def _replace(self, project: Project, which: object, chunks: list[KnowledgeChunk]) -> None:
        """Swap a document's or issue's chunks, keeping the vectors of text that didn't change."""
        old = {
            (c.content_hash, c.embedding_model): c.embedding
            for c in await self.session.scalars(
                select(KnowledgeChunk).where(KnowledgeChunk.project_id == project.id, which)  # type: ignore[arg-type]
            )
            if c.embedding is not None
        }
        await self.session.execute(
            delete(KnowledgeChunk).where(KnowledgeChunk.project_id == project.id, which)  # type: ignore[arg-type]
        )
        model = self.embedder.model if self.embedder else None
        for chunk in chunks:
            if model and (vector := old.get((chunk.content_hash, model))) is not None:
                chunk.embedding, chunk.embedding_model = vector, model
            self.session.add(chunk)
        await self.session.flush()

    async def embed_pending(self, project: Project, limit: int = 500) -> int:
        """Give up to `limit` chunks a vector from the current model; returns how many."""
        if self.embedder is None:
            return 0
        model = self.embedder.model
        pending = list(
            await self.session.scalars(
                select(KnowledgeChunk)
                .where(
                    KnowledgeChunk.project_id == project.id,
                    or_(KnowledgeChunk.embedding.is_(None), KnowledgeChunk.embedding_model != model),
                )
                .order_by(KnowledgeChunk.id)
                .limit(limit)
            )
        )
        done = 0
        for start in range(0, len(pending), EMBED_BATCH):
            batch = pending[start:start + EMBED_BATCH]
            texts = [embedding_text(c.ref, c.heading, c.content) for c in batch]
            vectors = await self.embedder.embed_documents(texts)
            for chunk, vector in zip(batch, vectors, strict=True):
                chunk.embedding, chunk.embedding_model = vector, model
            await self.session.commit()
            done += len(batch)
            logger.info(
                "search: embedded %d chunks for project %s (about %d tokens, %s)",
                len(batch), project.id, sum(len(t) for t in texts) // CHARS_PER_TOKEN, model,
            )
        return done

    async def stale_projects(self) -> list[uuid.UUID]:
        """Projects whose index is behind: changed documents or issues, or chunks without a
        vector from the current model (the background job's to-do list)."""
        indexed_files = (
            select(KnowledgeChunk.file_id, func.max(KnowledgeChunk.version).label("version"))
            .where(KnowledgeChunk.source == ChunkSource.DOCUMENT)
            .group_by(KnowledgeChunk.file_id)
            .subquery()
        )
        live = and_(KnowledgeFile.deleted.is_(False), *(~KnowledgeFile.path.startswith(p) for p in NOT_INDEXED))
        documents = (
            select(KnowledgeFile.project_id)
            .outerjoin(indexed_files, indexed_files.c.file_id == KnowledgeFile.id)
            .where(
                or_(
                    and_(live, or_(indexed_files.c.version.is_(None), indexed_files.c.version != KnowledgeFile.version)),
                    and_(~live, indexed_files.c.version.is_not(None)),
                )
            )
        )
        indexed_issues = (
            select(KnowledgeChunk.issue_id, func.max(KnowledgeChunk.source_updated_at).label("at"))
            .where(KnowledgeChunk.source == ChunkSource.ISSUE)
            .group_by(KnowledgeChunk.issue_id)
            .subquery()
        )
        issues = (
            select(Issue.project_id)
            .outerjoin(indexed_issues, indexed_issues.c.issue_id == Issue.id)
            .where(or_(indexed_issues.c.at.is_(None), indexed_issues.c.at < Issue.updated_at))
        )
        queries = [documents, issues]
        if self.embedder is not None:
            queries.append(
                select(KnowledgeChunk.project_id).where(
                    or_(KnowledgeChunk.embedding.is_(None), KnowledgeChunk.embedding_model != self.embedder.model)
                )
            )
        found: set[uuid.UUID] = set()
        for query in queries:
            found.update(await self.session.scalars(query.distinct()))
        return sorted(found)

    # -- searching -------------------------------------------------------------------------

    async def _keyword(self, scope: list[Any], query: str) -> list[uuid.UUID]:
        """Full-text ranking: chunks with every word first (web-search syntax: "quoted phrases",
        -excluded), then chunks with most of them (at least half, and two), so a near-duplicate
        title still matches without an embedding model."""
        english = literal_column("'english'::regconfig")
        every = func.websearch_to_tsquery(english, query)
        found = list(
            await self.session.scalars(
                select(KnowledgeChunk.id)
                .where(*scope, KnowledgeChunk.tsv.op("@@")(every))
                .order_by(func.ts_rank_cd(KnowledgeChunk.tsv, every).desc())
                .limit(CANDIDATES)
            )
        )
        words = list(
            (await self.session.execute(select(func.tsvector_to_array(func.to_tsvector(english, query))))).scalar()
            or []
        )[:MAX_QUERY_WORDS]
        if len(found) >= CANDIDATES or len(words) < 2:
            return found
        simple = literal_column("'simple'::regconfig")  # the words are already stemmed
        matched = sum(
            (case((KnowledgeChunk.tsv.op("@@")(func.plainto_tsquery(simple, word)), 1), else_=0) for word in words),
            start=literal_column("0"),
        )
        most = await self.session.scalars(
            select(KnowledgeChunk.id)
            .where(*scope, KnowledgeChunk.id.not_in(found) if found else literal_column("true"))
            .where(matched >= max(2, math.ceil(len(words) / 2)))
            .order_by(matched.desc())
            .limit(CANDIDATES - len(found))
        )
        return found + list(most)

    async def search(
        self, project: Project, query: str, *, limit: int = 8, source: ChunkSource | None = None
    ) -> list[Hit]:
        """The best chunks for a query: full-text and meaning rankings merged, one hit per
        section (the best-scoring chunk of each document section or issue)."""
        query = query.strip()
        if not query:
            return []
        await self.sync(project)
        scope = [KnowledgeChunk.project_id == project.id]
        if source is not None:
            scope.append(KnowledgeChunk.source == source)

        ranked: dict[uuid.UUID, float] = {}
        for rank, chunk_id in enumerate(await self._keyword(scope, query)):
            ranked[chunk_id] = ranked.get(chunk_id, 0) + 1 / (RRF_K + rank + 1)

        if self.embedder is not None:
            try:
                vector = await self.embedder.embed_query(query)
            except Exception:  # the provider is down or out of quota: keywords still work
                logger.exception("search: embedding the query failed; keyword results only")
            else:
                semantic = await self.session.scalars(
                    select(KnowledgeChunk.id)
                    .where(
                        *scope,
                        KnowledgeChunk.embedding_model == self.embedder.model,
                        # The nearest chunks of an unrelated query are still "nearest":
                        # only close enough ones count.
                        KnowledgeChunk.embedding.cosine_distance(vector) < 1 - self.embedder.min_similarity,
                    )
                    .order_by(KnowledgeChunk.embedding.cosine_distance(vector))
                    .limit(CANDIDATES)
                )
                for rank, chunk_id in enumerate(semantic):
                    ranked[chunk_id] = ranked.get(chunk_id, 0) + 1 / (RRF_K + rank + 1)

        if not ranked:
            return []
        chunks = {
            c.id: c
            for c in await self.session.scalars(select(KnowledgeChunk).where(KnowledgeChunk.id.in_(list(ranked))))
        }
        hits: list[Hit] = []
        seen: set[tuple[str, str | None]] = set()
        for chunk_id in sorted(ranked, key=lambda i: -ranked[i]):
            chunk = chunks.get(chunk_id)
            if chunk is None or (chunk.ref, chunk.heading) in seen:
                continue
            seen.add((chunk.ref, chunk.heading))
            snippet = chunk.content if len(chunk.content) <= SNIPPET_CHARS else chunk.content[:SNIPPET_CHARS] + "…"
            hits.append(Hit(chunk.source, chunk.ref, chunk.heading, snippet, chunk.version, round(ranked[chunk_id], 5)))
            if len(hits) >= limit:
                break
        return hits
