from __future__ import annotations

import asyncio
import dataclasses
import logging
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import health, v1
from .core.crypto import Secrets
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
from .jobs import (
    AUTOMATIONS_INTERVAL_SECONDS,
    CLEANUP_INTERVAL_SECONDS,
    EMAIL_INTERVAL_SECONDS,
    INDEX_INTERVAL_SECONDS,
    JOBS,
)
from .modules.agents.checkpoints import open_checkpointer
from .modules.agents.llm import settings_model_factory
from .modules.agents.queue import RunQueue
from .modules.agents.runner import AgentRunner, mark_interrupted_runs
from .modules.agents.streams import RedisRunStreams
from .modules.code.checkouts import build_checkouts
from .modules.coding.runner import build_coding_worker, end_cut_off_runs
from .modules.documents.service import mark_interrupted_conversions
from .modules.research.service import build_web_research
from .modules.search.embeddings import build_embedder
from .modules.web import router as web_session

API_VERSION = "0.1.0"
logger = logging.getLogger(__name__)


async def _every(jobs: LocalJobs, name: str, seconds: float) -> None:
    """Run a job, wait, run it again: one at a time, however long a run takes."""
    while True:
        await jobs.run(name)  # logs its own failures
        await asyncio.sleep(seconds)


def _log_sign_in_options(settings: Settings) -> None:
    """Say at startup whether "Continue with GitHub" is offered, and why not."""
    has_id, has_secret = bool(settings.github_client_id), bool(settings.github_client_secret)
    if has_id and has_secret:
        logger.info("GitHub sign-in is on (client id %s)", settings.github_client_id)
    elif has_id or has_secret:
        missing = "PMAGENT_GITHUB_CLIENT_SECRET" if has_id else "PMAGENT_GITHUB_CLIENT_ID"
        logger.warning("GitHub sign-in is off: %s is missing from .env", missing)
    else:
        logger.info("GitHub sign-in is off: set PMAGENT_GITHUB_CLIENT_ID and PMAGENT_GITHUB_CLIENT_SECRET in .env")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_json)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        _log_sign_in_options(settings)
        engine = create_engine(settings.database_url, echo=settings.database_echo)
        app.state.engine = engine
        app.state.sessionmaker = sessionmaker = create_sessionmaker(engine)
        async with AsyncExitStack() as stack:
            redis = None
            if settings.jobs == "worker" or settings.rate_limits == "redis":
                redis = await create_pool(RedisSettings.from_dsn(settings.redis_url))
                stack.push_async_callback(redis.aclose)
            app.state.rate_limiter = build_rate_limiter(settings, redis)
            job_context = JobContext(
                sessionmaker, settings, build_email_sender(settings), app.state.storage, app.state.embedder,
                app.state.checkouts,
            )
            queue, streams, local_jobs = None, None, None
            if settings.jobs == "worker":
                # Work executes in the worker; the API enqueues it and serves run streams.
                queue, streams = RunQueue(redis), RedisRunStreams(redis)
                app.state.jobs = QueuedJobs(redis)
            else:
                # Runs execute in this process, so any cut off by the last shutdown are over.
                await mark_interrupted_runs(sessionmaker)
                await mark_interrupted_conversions(sessionmaker)
                async with sessionmaker() as session:
                    await end_cut_off_runs(session, settings, everything=True)
                if settings.jobs == "inline":
                    app.state.jobs = InlineJobs(job_context, JOBS)
                else:
                    app.state.jobs = local_jobs = LocalJobs(job_context, JOBS)
            app.state.email_sender = QueuedEmailSender(app.state.jobs)
            app.state.runner = runner = AgentRunner(
                session_factory=sessionmaker,
                checkpointer=await open_checkpointer(settings.database_url, stack),
                model_factory=settings_model_factory(settings),
                token_budget=settings.run_token_budget,
                embedder=app.state.embedder,
                web=build_web_research(settings),
                checkouts=app.state.checkouts,
                summarize_after_tokens=settings.summarize_after_tokens,
                unattended_limits=(settings.unattended_changes_per_run, settings.unattended_changes_per_day),
                secrets=app.state.secrets,
                inline=settings.jobs == "inline",
                queue=queue,
                streams=streams,
            )
            if isinstance(app.state.jobs, InlineJobs | LocalJobs):
                # Jobs that start agent runs (automations, the Reviewer after a coding run) need the
                # runner, made just above.
                app.state.jobs.ctx = dataclasses.replace(
                    job_context, runner=runner, coding=build_coding_worker(settings, sessionmaker, runner)
                )
            loops: list[asyncio.Task[None]] = []
            if local_jobs is not None:
                # No worker (and so no cron) in local mode: clean up hourly and keep the search
                # index current from here.
                loops = [
                    asyncio.create_task(_every(local_jobs, "cleanup_expired", CLEANUP_INTERVAL_SECONDS)),
                    asyncio.create_task(_every(local_jobs, "index_knowledge", INDEX_INTERVAL_SECONDS)),
                    asyncio.create_task(_every(local_jobs, "run_automations", AUTOMATIONS_INTERVAL_SECONDS)),
                    asyncio.create_task(_every(local_jobs, "email_notifications", EMAIL_INTERVAL_SECONDS)),
                ]
            yield
            for loop in loops:
                loop.cancel()
            await runner.shutdown()
            if local_jobs is not None:
                await local_jobs.drain()
        await engine.dispose()

    docs = settings.docs_enabled
    app = FastAPI(
        title="dotrix API",
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
    # Reads and writes organisations' own model provider keys (encrypted at rest).
    app.state.secrets = Secrets.from_settings(settings)
    # Replaced in lifespan by a sender that queues each email as a job; until then (and in
    # tests that don't run the lifespan) emails go straight to the provider.
    app.state.email_sender = build_email_sender(settings)
    app.state.rate_limiter = build_rate_limiter(settings, None)
    app.state.storage = build_storage(settings)
    app.state.embedder = build_embedder(settings)
    # Checkouts of connected repos: kept where agents run (here in local mode, else the worker).
    app.state.checkouts = build_checkouts(settings)
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
    app.include_router(web_session.router)
    return app

