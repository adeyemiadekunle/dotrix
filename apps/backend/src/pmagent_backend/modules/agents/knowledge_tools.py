"""Tools for reading less (plan Phase 2): a document's outline, one section of it, and search
over the project's documents and issues. Read-only, for the PM and every specialist.

A file read with `read_file` is sent to the model in full and re-sent with every later call;
these let an agent find the part that matters first.
"""
from __future__ import annotations

import uuid
from collections.abc import Callable

from pmagent_backend.modules.knowledge.repository import KnowledgeRepository
from pmagent_backend.modules.projects.repository import ProjectRepository
from pmagent_backend.modules.rules.service import WorkspaceSkills
from pmagent_backend.modules.search.embeddings import Embedder
from pmagent_backend.modules.search.models import ChunkSource
from pmagent_backend.modules.search.service import KnowledgeIndex
from pmagent_engine.knowledge_index import describe, find_section, sections
from pmagent_engine.skills import SKILLS_FOLDER

from .storage_backend import SessionFactory

ROOT = "/pmagent/"
CHARS_PER_TOKEN = 4
MAX_SECTIONS_LISTED = 60

KNOWLEDGE_TOOLS_GUIDE = """
## Reading less
Every file you read is re-sent with each later step, so read only what you need:
- `search_knowledge(query)` finds the passages about something across all documents and
  issues (exact terms and paraphrases), with their paths and sections.
- `document_outline(file_path)` lists a document's sections with their sizes.
- `read_section(file_path, heading)` reads one section (with its subsections).
Use `read_file` for short documents or when you need the whole thing.
"""


def _relative(file_path: str) -> str:
    path = file_path.strip()
    if path.startswith(ROOT):
        path = path[len(ROOT):]
    return path.lstrip("/")


def build_knowledge_tools(
    session_factory: SessionFactory,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    embedder: Embedder | None,
) -> list[Callable]:
    async def _file(file_path: str) -> tuple[object | None, str]:
        path = _relative(file_path)
        async with session_factory() as session:
            file = await KnowledgeRepository(session).get_file(project_id, path)
        if file is None or file.deleted:
            return None, f"Error: {ROOT}{path} not found (see the documents list in the project context)"
        return file, path

    async def document_outline(file_path: str) -> str:
        """A document's title, summary, and sections (heading, lines, and about how many tokens
        each), without its text. Use it to decide what to read in a long document.

        Args:
            file_path: e.g. "/pmagent/requirements/product.md".
        """
        file, path = await _file(file_path)
        if file is None:
            return path
        about = describe(path, file.content)
        found = sections(file.content)
        lines = [
            f"{ROOT}{path} (v{file.version}, about {len(file.content) // CHARS_PER_TOKEN:,} tokens): "
            f"{about.title}",
            f"Summary: {about.summary}",
            "Sections:",
        ]
        for section in found[:MAX_SECTIONS_LISTED]:
            indent = "  " * max(section.level - 2, 0)
            label = section.heading or "(before the first heading)"
            lines.append(
                f"{indent}- {label} (lines {section.start_line}-{section.end_line}, "
                f"about {len(section.text) // CHARS_PER_TOKEN:,} tokens)"
            )
        if len(found) > MAX_SECTIONS_LISTED:
            lines.append(f"…and {len(found) - MAX_SECTIONS_LISTED} more sections")
        return "\n".join(lines)

    async def read_section(file_path: str, heading: str) -> str:
        """Read one section of a document: from its heading to the next heading of the same
        level, subsections included.

        Args:
            file_path: e.g. "/pmagent/requirements/product.md".
            heading: The section's heading as the outline shows it, e.g. "## Goals" or "Goals",
                or a trail like "Requirements > Goals".
        """
        file, path = await _file(file_path)
        if file is None:
            return path
        section = find_section(file.content, heading)
        if section is None:
            headings = [s.heading for s in sections(file.content) if s.heading][:MAX_SECTIONS_LISTED]
            return f"No section {heading!r} in {ROOT}{path}. Its sections: " + "; ".join(headings)
        return (
            f"{ROOT}{path} v{file.version}, {section.heading} (lines {section.start_line}-{section.end_line}):\n\n"
            f"{section.text}"
        )

    async def search_knowledge(query: str, only: str | None = None, limit: int = 6) -> str:
        """Search the project's documents (by section) and issues for a topic, in any words:
        exact terms (issue keys, names, error text) and paraphrases both match. Returns the best
        passages with where they are, so you can read just those sections.

        Args:
            query: What you're looking for, e.g. "driver payouts across states".
            only: "documents" or "issues" to search just one kind.
            limit: How many results (1-10).
        """
        source = {"documents": ChunkSource.DOCUMENT, "issues": ChunkSource.ISSUE}.get((only or "").strip().lower())
        async with session_factory() as session:
            project = await ProjectRepository(session).get(workspace_id, project_id)
            if project is None:
                return "Error: the project is gone"
            hits = await KnowledgeIndex(session, embedder).search(
                project, query, limit=max(1, min(int(limit), 10)), source=source
            )
        if not hits:
            return f"Nothing found for {query!r}."
        lines = []
        for number, hit in enumerate(hits, 1):
            if hit.source is ChunkSource.ISSUE:
                where = f"{hit.ref} (issue): {hit.heading}"
            else:
                where = f"{ROOT}{hit.ref} v{hit.version}" + (f", {hit.heading}" if hit.heading else "")
            snippet = "\n   ".join(hit.snippet.splitlines())
            lines.append(f"{number}. {where}\n   {snippet}")
        return "\n".join(lines)

    async def read_skill(skill: str) -> str:
        """Read one of the skills listed under "Skills" in your instructions: the steps to
        follow for that kind of work. The project's own skill wins over the workspace's.

        Args:
            skill: The skill's name as listed, e.g. "write-an-adr".
        """
        clean = skill.strip().removesuffix(".md").rsplit("/", 1)[-1]
        async with session_factory() as session:
            file = await KnowledgeRepository(session).get_file(project_id, f"{SKILLS_FOLDER}{clean}.md")
            if file is not None and not file.deleted:
                return f"Skill {clean} (this project's):\n\n{file.content}"
            shared = await WorkspaceSkills(session).get(workspace_id, clean)
        if shared:
            return f"Skill {clean} (the workspace's):\n\n{shared}"
        return f"No skill called {clean!r}; the skills you have are listed in your instructions."

    return [search_knowledge, document_outline, read_section, read_skill]
