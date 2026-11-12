"""One versioned skill catalog for leaders, specialists and coding workers."""
from __future__ import annotations

import hashlib
import json

from dotrix_backend.core.errors import Unprocessable
from dotrix_backend.modules.knowledge.repository import KnowledgeRepository
from dotrix_backend.modules.rules.service import WorkspaceSkills
from dotrix_engine.skills import SKILLS_FOLDER, default_skills, skill_name, skills_for


async def resolve(session, workspace_id, project_id) -> dict[str, str]:
    rows = await KnowledgeRepository(session).list_files(project_id)
    project_paths = {row.path for row in rows}
    texts = {skill_name(path): text for path, text in default_skills().items() if path not in project_paths}
    texts.update(await WorkspaceSkills(session).texts(workspace_id))
    for row in rows:
        if row.path.startswith(SKILLS_FOLDER) and row.path.endswith(".md"):
            if row.deleted:
                texts.pop(skill_name(row.path), None)
            else:
                texts[skill_name(row.path)] = row.content
    if len(json.dumps(texts).encode()) > 256_000:
        raise Unprocessable("The skill catalog exceeds 256 KB; reduce the configured skills before running an agent")
    return texts


def versioned(texts: dict[str, str]) -> dict:
    return {name: {"content": text, "sha256": hashlib.sha256(text.encode()).hexdigest()}
            for name, text in sorted(texts.items())}


async def pin(session, run, secrets) -> dict[str, str]:
    if run.skill_snapshot is None:
        catalog = versioned(await resolve(session, run.workspace_id, run.project_id))
        run.skill_snapshot = catalog
        await session.commit()
    catalog = run.skill_snapshot
    return {name: item["content"] for name, item in catalog.items()}


def for_role(texts: dict[str, str], role: str) -> dict[str, str]:
    return skills_for(texts, role)
