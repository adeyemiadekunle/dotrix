from fastapi import APIRouter

from dotrix_backend.modules.activity.router import router as activity
from dotrix_backend.modules.activity.router import workspace_router as workspace_activity
from dotrix_backend.modules.agent_definitions.router import mine_router as my_agents
from dotrix_backend.modules.agent_definitions.router import (
    project_router as project_agent_definitions,
)
from dotrix_backend.modules.agent_definitions.router import router as agent_definitions
from dotrix_backend.modules.agents.router import conversations_router as conversations
from dotrix_backend.modules.agents.router import models_router as models
from dotrix_backend.modules.agents.router import router as agents
from dotrix_backend.modules.agents.router import threads_router as workspace_threads
from dotrix_backend.modules.agents.router import usage_router as workspace_agent_usage
from dotrix_backend.modules.agents.router import workspace_router as workspace_approvals
from dotrix_backend.modules.api_tokens.router import device_router, tokens_router
from dotrix_backend.modules.audit.router import router as audit
from dotrix_backend.modules.auth.router import me_router
from dotrix_backend.modules.auth.router import router as auth
from dotrix_backend.modules.automations.router import router as automations
from dotrix_backend.modules.calendar.router import feed_router as calendar_feed
from dotrix_backend.modules.calendar.router import me_router as calendar_settings
from dotrix_backend.modules.coding.router import router as coding
from dotrix_backend.modules.coding.router import workspace_router as workspace_coding
from dotrix_backend.modules.connectors.router import project_router as project_repository
from dotrix_backend.modules.connectors.router import webhook_router as github_webhook
from dotrix_backend.modules.connectors.router import workspace_router as workspace_github
from dotrix_backend.modules.documents.router import router as documents
from dotrix_backend.modules.graph.router import router as graph
from dotrix_backend.modules.invites.router import router as invites
from dotrix_backend.modules.invites.router import workspace_router as workspace_invites
from dotrix_backend.modules.issues.router import router as issues
from dotrix_backend.modules.issues.router import workspace_router as workspace_issues
from dotrix_backend.modules.knowledge.router import router as knowledge
from dotrix_backend.modules.lessons.router import router as lessons
from dotrix_backend.modules.model_keys.router import me_router as my_models
from dotrix_backend.modules.model_keys.router import router as model_keys
from dotrix_backend.modules.notifications.router import router as notifications
from dotrix_backend.modules.notifications.router import settings_router as notification_settings
from dotrix_backend.modules.projects.router import router as projects
from dotrix_backend.modules.rules.router import router as rules
from dotrix_backend.modules.search.router import router as search
from dotrix_backend.modules.search.router import workspace_router as workspace_search
from dotrix_backend.modules.teams.router import router as teams
from dotrix_backend.modules.workspaces.router import router as workspaces

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
    my_agents,
    agents,
    conversations,
    models,
    workspace_approvals,
    workspace_threads,
    workspace_agent_usage,
    automations,
    lessons,
    graph,
    rules,
    audit,
    issues,
    workspace_issues,
    activity,
    workspace_activity,
    notifications,
    notification_settings,
    workspace_github,
    project_repository,
    coding,
    workspace_coding,
    github_webhook,
    teams,
    model_keys,
    my_models,
    search,
    workspace_search,
):
    router.include_router(module_router)
