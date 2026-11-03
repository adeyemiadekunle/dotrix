"""Saved project evidence and private next-step guidance; no external calls or writes."""
import hashlib
from datetime import datetime
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from dotrix_backend.core.settings import Settings
from dotrix_backend.modules.agents.llm import available_models
from dotrix_backend.modules.agents.models import AgentRun, RunStatus
from dotrix_backend.modules.auth.models import User
from dotrix_backend.modules.connectors.models import ConnectedRepo, GitHubInstallation
from dotrix_backend.modules.issues.models import Issue, IssueStatus
from dotrix_backend.modules.knowledge.models import KnowledgeFile
from dotrix_backend.modules.model_keys.models import UserModelKey
from dotrix_backend.modules.repo_knowledge.baseline import BaselineService
from dotrix_backend.modules.workspaces.permissions import Permission, can
from dotrix_engine.layout import skeleton

from .deps import ProjectAccess
from .models import ProjectSource

Action = Literal["purpose", "knowledge", "repository", "models", "tasks", "discuss", "plan"]


class ReadinessCheck(BaseModel):
    key: str
    title: str
    state: Literal["ready", "missing", "optional", "review", "unverified", "blocked"]
    detail: str
    action: Action
    allowed: bool = True
    restriction: str | None = None


class ProjectReadiness(BaseModel):
    source: ProjectSource
    checks: list[ReadinessCheck]
    next_action: Action
    next_title: str
    next_detail: str
    next_allowed: bool
    next_restriction: str | None
    model_success_at: datetime | None


async def project_readiness(
    session: AsyncSession, access: ProjectAccess, user: User, settings: Settings, *, secrets_configured: bool,
) -> ProjectReadiness:
    project, member = access.project, access.member
    checks = []

    def add(key, title, state, detail, action, permission=None):
        permitted = permission is None or can(member, permission)
        checks.append(ReadinessCheck(key=key, title=title, state=state, detail=detail, action=action,
            allowed=permitted, restriction=None if permitted else "Your role cannot perform this action. Ask a project owner or admin."))

    purpose = bool(project.description.strip())
    add("purpose", "Project purpose", "ready" if purpose else "missing",
        "A project goal is saved." if purpose else "Capture the problem, intended users and goal; the project name alone is not a brief.",
        "purpose", Permission.MANAGE_PROJECTS)
    count = await session.scalar(select(func.count()).select_from(KnowledgeFile).where(
        KnowledgeFile.workspace_id == project.workspace_id, KnowledgeFile.project_id == project.id,
        KnowledgeFile.deleted.is_(False), func.length(func.trim(KnowledgeFile.content)) > 0,
        KnowledgeFile.content_hash.notin_([hashlib.sha256(content.encode()).hexdigest()
                                         for content in skeleton(project.name, project.description).values()]),
        (KnowledgeFile.path.startswith("requirements/", autoescape=True)
         | KnowledgeFile.path.startswith("decisions/", autoescape=True)
         | KnowledgeFile.path.startswith("research/", autoescape=True)
         | KnowledgeFile.path.startswith("architecture/", autoescape=True)
         | KnowledgeFile.path.startswith("design/", autoescape=True)
         | KnowledgeFile.path.startswith("docs/wiki/", autoescape=True)),
    ))
    add("knowledge", "Project knowledge", "ready" if count else "missing",
        f"{count} saved scope, decision, research or repository documents. Review their relevance before using them."
        if count else "Save useful scope, decisions or research in Knowledge. Default agent guidance does not count as project knowledge.", "knowledge")
    row = (await session.execute(select(ConnectedRepo, GitHubInstallation).join(
        GitHubInstallation, GitHubInstallation.id == ConnectedRepo.installation_ref,
    ).where(ConnectedRepo.workspace_id == project.workspace_id, ConnectedRepo.project_id == project.id,
            GitHubInstallation.workspace_id == project.workspace_id))).first()
    repo, installation = row if row else (None, None)
    repository_ok = bool(repo and not installation.suspended_at and not repo.checkout_error)
    repository_state = "unverified" if repository_ok else "blocked" if repo else "optional" if project.source == ProjectSource.DOCS_ONLY else "missing"
    add("repository", "Repository connection", repository_state,
        "A connection is saved. Live access and a committed default branch are checked when coding starts."
        if repository_ok else "The saved installation is suspended or its checkout failed. Restore access before coding."
        if repo else "GitHub is optional while exploring an idea or managing tasks. Connect it when code is needed."
        if project.source == ProjectSource.DOCS_ONLY else "Connect a GitHub repository before implementation. Planning and task management can continue.",
        "repository", Permission.MANAGE_PROJECTS)
    baseline = await BaselineService(session, None).state(project) if repo else None
    needs_baseline = project.source == ProjectSource.EXISTING_REPO
    baseline_relevant = bool(repo and (needs_baseline or baseline.review))
    add("baseline", "Repository baseline", "ready" if baseline and baseline.current else "review" if baseline_relevant else "optional",
        "A person confirmed the current saved evidence and shared context. Unreported remote changes still need a fresh check."
        if baseline and baseline.current else "Review repository evidence, goals and corrections; stale or changed evidence needs renewed confirmation."
        if baseline_relevant else "A reviewed baseline is useful for existing code. An idea or first implementation can begin with agreed scope.", "knowledge")

    # This evidence is private to the current person, project and current key revision.
    model = user.default_model or project.model
    provider = model.partition(":")[0]
    key = await session.scalar(select(UserModelKey).where(UserModelKey.user_id == user.id, UserModelKey.provider == provider))
    available = bool(key and secrets_configured and model in available_models(settings, connected={provider}))
    success = None
    if available:
        success = await session.scalar(select(func.max(AgentRun.finished_at)).where(
            AgentRun.workspace_id == project.workspace_id, AgentRun.project_id == project.id,
            AgentRun.requested_by_id == user.id, AgentRun.model == model, AgentRun.status == RunStatus.COMPLETED,
            AgentRun.created_at >= key.updated_at, AgentRun.model_calls > 0,
            AgentRun.input_tokens + AgentRun.output_tokens > 0,
        ))
    model_state = "blocked" if key and (key.limit_reached_at or not available) else "ready" if success else "unverified" if available else "missing"
    add("model", "Your model access (private)", model_state,
        f"Selected model: {model}. " + ("A provider limit is recorded. Review your personal model settings before using agents."
        if key and key.limit_reached_at else "A successful chat run using this model is recorded after the current key was saved. This is saved evidence, not a live provider check."
        if success else "A personal key is stored for the selected model; a successful call has not been verified here. No test call is made by this page."
        if available else "The selected model has no usable personal connection here. Task and knowledge work do not require a model key."), "models")
    tasks = await session.scalar(select(func.count()).select_from(Issue).where(
        Issue.workspace_id == project.workspace_id, Issue.project_id == project.id,
        Issue.archived_at.is_(None), Issue.status == IssueStatus.TODO,
    ))
    prerequisites = purpose and repository_ok and available and not key.limit_reached_at and bool(tasks) and (not needs_baseline or baseline and baseline.current)
    add("implementation", "Implementation preparation", "ready" if prerequisites else "missing",
        "A To do task and saved prerequisites are available. Review scope first; starting Kai still requires live repository checks and the usual approvals."
        if prerequisites else "Prepare a clear goal and To do task, connect repository and personal model access, and review an existing repository's baseline. These prerequisites do not block manual project work.",
        "plan", Permission.INSTRUCT_CODING_AGENT)
    if not purpose:
        action, title, detail = "purpose", "Clarify the project goal", "Save the problem and intended outcome before deciding scope."
    elif needs_baseline and not repo:
        action, title, detail = "repository", "Connect the existing repository", "Keep planning or managing tasks while repository access is arranged."
    elif repo and not repository_ok:
        action, title, detail = "repository", "Restore repository access", "The saved connection needs attention before code work; manual project work remains available."
    elif needs_baseline and not baseline.current:
        action, title, detail = "knowledge", "Understand and review the repository", "Review cited evidence and shared human context before planning substantial changes."
    elif not count:
        if available and not key.limit_reached_at and can(member, Permission.CHAT):
            action, title, detail = "discuss", "Explore the idea" if project.source == ProjectSource.DOCS_ONLY else "Clarify the project scope", "Open an editable Nova discussion starter. Nothing is sent or implemented automatically."
        else:
            action, title, detail = "knowledge", "Capture the first useful scope", "Write or publish requirements, a decision or research. Chat is optional."
    elif not tasks:
        action, title, detail = "tasks", "Create or review a To do task", "Agree a small task and acceptance criteria. Creating it does not start coding."
    elif project.source == ProjectSource.NEW_REPO and not repo:
        action, title, detail = "repository", "Prepare a repository for implementation", "Your saved scope and tasks remain available while GitHub is set up."
    elif prerequisites and can(member, Permission.INSTRUCT_CODING_AGENT):
        action, title, detail = "plan", "Review the implementation plan", "Open an editable Plan draft. Kai starts only after an explicit implementation request."
    else:
        action, title, detail = "tasks", "Review the next task", "Continue organising scope and acceptance criteria; use your personal model connection when you choose agent work."
    permission = {"purpose": Permission.MANAGE_PROJECTS, "repository": Permission.MANAGE_PROJECTS,
                  "tasks": Permission.EDIT_ISSUES, "plan": Permission.INSTRUCT_CODING_AGENT}.get(action)
    allowed = permission is None or can(member, permission)
    return ProjectReadiness(source=project.source, checks=checks, next_action=action, next_title=title,
        next_detail=detail, next_allowed=allowed,
        next_restriction=None if allowed else "Your role cannot perform this action. Ask a project owner or admin; you can still read project knowledge and tasks.",
        model_success_at=success)
