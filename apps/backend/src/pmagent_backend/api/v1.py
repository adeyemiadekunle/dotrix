from fastapi import APIRouter

from pmagent_backend.modules.activity.router import router as activity
from pmagent_backend.modules.activity.router import workspace_router as workspace_activity
from pmagent_backend.modules.agent_definitions.router import (
    project_router as project_agent_definitions,
)
from pmagent_backend.modules.agent_definitions.router import router as agent_definitions
from pmagent_backend.modules.agents.router import models_router as models
from pmagent_backend.modules.agents.router import router as agents
from pmagent_backend.modules.agents.router import threads_router as workspace_threads
from pmagent_backend.modules.agents.router import usage_router as workspace_agent_usage
from pmagent_backend.modules.agents.router import workspace_router as workspace_approvals
from pmagent_backend.modules.api_tokens.router import device_router, tokens_router
from pmagent_backend.modules.audit.router import router as audit
from pmagent_backend.modules.auth.router import me_router
from pmagent_backend.modules.auth.router import router as auth
from pmagent_backend.modules.automations.router import router as automations
from pmagent_backend.modules.calendar.router import feed_router as calendar_feed
from pmagent_backend.modules.calendar.router import me_router as calendar_settings
from pmagent_backend.modules.connectors.router import project_router as project_repository
from pmagent_backend.modules.connectors.router import webhook_router as github_webhook
from pmagent_backend.modules.connectors.router import workspace_router as workspace_github
from pmagent_backend.modules.documents.router import router as documents
from pmagent_backend.modules.invites.router import router as invites
from pmagent_backend.modules.invites.router import workspace_router as workspace_invites
from pmagent_backend.modules.issues.router import router as issues
from pmagent_backend.modules.issues.router import workspace_router as workspace_issues
from pmagent_backend.modules.knowledge.router import router as knowledge
from pmagent_backend.modules.notifications.router import router as notifications
from pmagent_backend.modules.notifications.router import settings_router as notification_settings
from pmagent_backend.modules.projects.router import router as projects
from pmagent_backend.modules.search.router import router as search
from pmagent_backend.modules.search.router import workspace_router as workspace_search
from pmagent_backend.modules.workspaces.router import router as workspaces

router = APIRouter(prefix="/v1")
for module_router in (
    auth,
    device_router,
    me_router,
    tokens_router,
    calendar_settings,
    calendar_feed,
    workspaces,
    workspace_invites,
    invites,
    projects,
    knowledge,
    documents,
    agent_definitions,
    project_agent_definitions,
    agents,
    models,
    workspace_approvals,
    workspace_threads,
    workspace_agent_usage,
    automations,
    audit,
    issues,
    workspace_issues,
    activity,
    workspace_activity,
    notifications,
    notification_settings,
    workspace_github,
    project_repository,
    github_webhook,
    search,
    workspace_search,
):
    router.include_router(module_router)
