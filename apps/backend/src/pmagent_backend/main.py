from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import health, v1
from .core.email import build_email_sender
from .core.errors import register_exception_handlers
from .core.logging import configure_logging
from .core.middleware import RequestContextMiddleware
from .core.openapi import install_openapi, operation_id
from .core.settings import Settings, get_settings
from .core.storage import build_storage
from .db.session import create_engine, create_sessionmaker
from .modules.agents.checkpoints import open_checkpointer
from .modules.agents.llm import settings_model_factory
from .modules.agents.runner import AgentRunner, mark_interrupted_runs
from .modules.agents.titles import generate_title

API_VERSION = "0.1.0"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_json)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(settings.database_url, echo=settings.database_echo)
        app.state.engine = engine
        app.state.sessionmaker = sessionmaker = create_sessionmaker(engine)
        async with AsyncExitStack() as stack:
            await mark_interrupted_runs(sessionmaker)
            app.state.runner = runner = AgentRunner(
                session_factory=sessionmaker,
                checkpointer=await open_checkpointer(settings.database_url, stack),
                model_factory=settings_model_factory(settings),
                inline=settings.agent_runs_inline,
                titler=generate_title,
            )
            yield
            await runner.shutdown()
        await engine.dispose()

    docs = settings.docs_enabled
    app = FastAPI(
        title="pmagent API",
        version=API_VERSION,
        lifespan=lifespan,
        generate_unique_id_function=operation_id,
        docs_url="/docs" if docs else None,
        redoc_url="/redoc" if docs else None,
        openapi_url="/openapi.json" if docs else None,
        swagger_ui_parameters={"persistAuthorization": True, "displayRequestDuration": True},
    )
    install_openapi(app, API_VERSION)
    app.state.settings = settings
    app.state.email_sender = build_email_sender(settings.email_backend)
    app.state.storage = build_storage(settings)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )
    # Added last so it is outermost: request ID covers CORS and 500s.
    app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(app)

    app.include_router(health.router)
    app.include_router(v1.router)
    return app

