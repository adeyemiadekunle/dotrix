from fastapi import APIRouter

from pmagent_backend.modules.agents.router import router as agents
from pmagent_backend.modules.agents.router import workspace_router as workspace_approvals
from pmagent_backend.modules.api_tokens.router import device_router, tokens_router
from pmagent_backend.modules.audit.router import router as audit
from pmagent_backend.modules.auth.router import me_router
from pmagent_backend.modules.auth.router import router as auth
from pmagent_backend.modules.documents.router import router as documents
from pmagent_backend.modules.invites.router import router as invites
from pmagent_backend.modules.invites.router import workspace_router as workspace_invites
from pmagent_backend.modules.issues.router import router as issues
from pmagent_backend.modules.knowledge.router import router as knowledge
from pmagent_backend.modules.organizations.router import router as organizations
from pmagent_backend.modules.projects.router import router as projects
from pmagent_backend.modules.workspaces.router import router as workspaces

router = APIRouter(prefix="/v1")
for module_router in (
    auth,
    device_router,
    me_router,
    tokens_router,
    organizations,
    workspaces,
    workspace_invites,
    invites,
    projects,
    knowledge,
    documents,
    agents,
    workspace_approvals,
    audit,
    issues,
):
    router.include_router(module_router)
