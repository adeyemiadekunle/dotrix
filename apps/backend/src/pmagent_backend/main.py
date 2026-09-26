from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routers import approvals, health, issues, projects, workspaces
from .settings import settings


def create_app() -> FastAPI:
    app = FastAPI(title="pmagent API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router)
    for module in (workspaces, projects, issues, approvals):
        app.include_router(module.router, prefix="/v1")
    return app


app = create_app()
