from fastapi import APIRouter

from pmagent_backend.modules.api_tokens.router import device_router, tokens_router
from pmagent_backend.modules.approvals.router import router as approvals
from pmagent_backend.modules.auth.router import me_router
from pmagent_backend.modules.auth.router import router as auth
from pmagent_backend.modules.invites.router import router as invites
from pmagent_backend.modules.invites.router import workspace_router as workspace_invites
from pmagent_backend.modules.issues.router import router as issues
from pmagent_backend.modules.projects.router import router as projects
from pmagent_backend.modules.workspaces.router import router as workspaces

router = APIRouter(prefix="/v1")
for module_router in (
    auth,
    device_router,
    me_router,
    tokens_router,
    workspaces,
    workspace_invites,
    invites,
    projects,
    issues,
    approvals,
):
    router.include_router(module_router)
