from fastapi import APIRouter

from pmagent_backend.modules.approvals.router import router as approvals
from pmagent_backend.modules.issues.router import router as issues
from pmagent_backend.modules.projects.router import router as projects
from pmagent_backend.modules.workspaces.router import router as workspaces

router = APIRouter(prefix="/v1")
for module_router in (workspaces, projects, issues, approvals):
    router.include_router(module_router)
