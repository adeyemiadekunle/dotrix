"""Layered guidance shared by project chat runtimes."""
from dotrix_backend.modules.knowledge.repository import KnowledgeRepository
from dotrix_backend.modules.knowledge.service import Actor, KnowledgeService
from dotrix_backend.modules.lessons.service import lessons_path
from dotrix_backend.modules.projects.models import Project
from dotrix_backend.modules.rules.service import WorkspaceRules, WorkspaceSkills, layered
from dotrix_engine.layout import AGENTS
from dotrix_engine.skills import SKILLS_FOLDER, default_skills, skill_name, skills_guide
from dotrix_engine.templates import TEMPLATES_GUIDE, default_templates


async def project_rules(session, project_id, handles=None, workspace_id=None) -> dict[str, str]:
    files = await KnowledgeRepository(session).list_files(project_id)
    names = ("base", *AGENTS, *(handles or []))
    live = {f.path: f.content for f in files if not f.deleted}
    ever = {f.path for f in files}  # a deleted template or skill stays deleted
    missing = {path: text for path, text in {**default_templates(), **default_skills()}.items() if path not in ever}
    if missing:
        project = await session.get(Project, project_id)
        knowledge = KnowledgeService(session)
        for path, text in missing.items():
            await knowledge.write(project, path, text, Actor.system(), message="Default template or skill")
            live[path] = text
    rules = {name: live[f"agent-rules/{name}.md"] for name in names if f"agent-rules/{name}.md" in live}
    for name in names:
        lessons = live.get(lessons_path(name), "").strip()
        if lessons:
            # Owners accepted these; the file's own heading is replaced by ours.
            body = "\n".join(line for line in lessons.splitlines() if not line.startswith("# "))
            rules[name] = f"{rules.get(name, '').rstrip()}\n\n## Lessons from this project\n{body.strip()}".strip()
    skills: dict[str, str] = {}
    if workspace_id is not None:
        workspace_rules = await WorkspaceRules(session).texts(workspace_id)
        rules = layered({h: t for h, t in workspace_rules.items() if h in names}, rules)
        skills = await WorkspaceSkills(session).texts(workspace_id)
    # The project's own skills win over the workspace's of the same name.
    skills |= {skill_name(p): c for p, c in live.items() if p.startswith(SKILLS_FOLDER) and p.endswith(".md")}
    skills = skills_guide(skills)
    rules["base"] = "\n\n".join(part for part in (rules.get("base", "").rstrip(), TEMPLATES_GUIDE, skills) if part)
    return rules
