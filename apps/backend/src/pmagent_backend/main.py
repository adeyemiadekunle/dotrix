from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import health, v1
from .core.email import build_email_sender
from .core.errors import register_exception_handlers
from .core.jobs import InlineJobs, JobContext, LocalJobs, QueuedEmailSender, QueuedJobs
from .core.logging import configure_logging
from .core.middleware import RequestContextMiddleware
from .core.openapi import install_openapi, operation_id
from .core.ratelimit import build_rate_limiter
from .core.settings import Settings, get_settings
from .core.storage import build_storage
from .db.session import create_engine, create_sessionmaker
from .jobs import CLEANUP_INTERVAL_SECONDS, JOBS
from .modules.agents.checkpoints import open_checkpointer
from .modules.agents.llm import settings_model_factory
from .modules.agents.queue import RunQueue
from .modules.agents.runner import AgentRunner, mark_interrupted_runs
from .modules.agents.streams import RedisRunStreams

API_VERSION = "0.1.0"
logger = logging.getLogger(__name__)


async def _clean_up_hourly(jobs: LocalJobs) -> None:
    while True:
        try:
            await jobs.enqueue("cleanup_expired")
        except Exception:
            logger.exception("scheduling cleanup failed")
        await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_json)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(settings.database_url, echo=settings.database_echo)
        app.state.engine = engine
        app.state.sessionmaker = sessionmaker = create_sessionmaker(engine)
        async with AsyncExitStack() as stack:
            redis = None
            if settings.jobs == "worker" or settings.rate_limits == "redis":
                redis = await create_pool(RedisSettings.from_dsn(settings.redis_url))
                stack.push_async_callback(redis.aclose)
            app.state.rate_limiter = build_rate_limiter(settings, redis)
            job_context = JobContext(sessionmaker, settings, build_email_sender(settings.email_backend))
            queue, streams, local_jobs = None, None, None
            if settings.jobs == "worker":
                # Work executes in the worker; the API enqueues it and serves run streams.
                queue, streams = RunQueue(redis), RedisRunStreams(redis)
                app.state.jobs = QueuedJobs(redis)
            else:
                # Runs execute in this process, so any cut off by the last shutdown are over.
                await mark_interrupted_runs(sessionmaker)
                if settings.jobs == "inline":
                    app.state.jobs = InlineJobs(job_context, JOBS)
                else:
                    app.state.jobs = local_jobs = LocalJobs(job_context, JOBS)
            app.state.email_sender = QueuedEmailSender(app.state.jobs)
            app.state.runner = runner = AgentRunner(
                session_factory=sessionmaker,
                checkpointer=await open_checkpointer(settings.database_url, stack),
                model_factory=settings_model_factory(settings),
                inline=settings.jobs == "inline",
                queue=queue,
                streams=streams,
            )
            cleanup = None
            if local_jobs is not None:
                # No worker (and so no cron) in local mode: clean up from here, hourly.
                cleanup = asyncio.create_task(_clean_up_hourly(local_jobs))
            yield
            if cleanup is not None:
                cleanup.cancel()
            await runner.shutdown()
            if local_jobs is not None:
                await local_jobs.drain()
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
    # Replaced in lifespan by a sender that queues each email as a job; until then (and in
    # tests that don't run the lifespan) emails go straight to the provider.
    app.state.email_sender = build_email_sender(settings.email_backend)
    app.state.rate_limiter = build_rate_limiter(settings, None)
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

