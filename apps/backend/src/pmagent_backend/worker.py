"""The background worker: `python -m pmagent_backend.worker` (`pnpm dev:worker`).

Executes what the API enqueues when PMAGENT_JOBS=worker (arq on Redis): agent runs, and the
jobs in `pmagent_backend.jobs` (emails, password-reset requests). Work survives API restarts.
If the worker stops mid-run, the run is retried and continues from its last checkpoint; a
job that fails is retried with backoff. Stop (from the API) aborts a run. Run as many
workers as you like: each job goes to one of them.
"""
from __future__ import annotations

import asyncio
import logging
import sys
import uuid
from contextlib import AsyncExitStack
from typing import Any

from arq import cron, func
from arq.connections import RedisSettings
from arq.worker import Function, Retry, run_worker

from .core.email import build_email_sender
from .core.jobs import QUEUE_NAME, JobContext, JobFunction
from .core.logging import configure_logging
from .core.settings import get_settings
from .core.storage import build_storage
from .db.session import create_engine, create_sessionmaker
from .jobs import JOBS, cleanup_expired, email_notifications, index_knowledge, run_automations
from .modules.agents.checkpoints import open_checkpointer
from .modules.agents.llm import settings_model_factory
from .modules.agents.queue import RunQueue
from .modules.agents.runner import AgentRunner
from .modules.agents.streams import RedisRunStreams
from .modules.code.checkouts import build_checkouts
from .modules.research.service import build_web_research
from .modules.search.embeddings import build_embedder

logger = logging.getLogger(__name__)

RUN_TIMEOUT_SECONDS = 60 * 60  # an agent run can take a while (research, many approvals' worth of work)
RUN_MAX_TRIES = 3  # a run cut off by a worker restart is retried from its last checkpoint
JOB_TIMEOUT = 60
JOB_MAX_TRIES = 5  # e.g. the email provider is briefly down: retried after 10s, 20s, 30s, 40s


async def startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    stack = ctx["stack"] = AsyncExitStack()
    engine = ctx["engine"] = create_engine(settings.database_url, echo=settings.database_echo)
    redis = ctx["redis"]
    sessionmaker = create_sessionmaker(engine)
    embedder = build_embedder(settings)
    checkouts = build_checkouts(settings)
    checkpointer = await open_checkpointer(settings.database_url, stack)
    # Jobs that start runs (automations) queue them, as the API does, rather than running them
    # inside a job that has to finish within a minute.
    dispatcher = AgentRunner(
        session_factory=sessionmaker, checkpointer=checkpointer, model_factory=settings_model_factory(settings),
        queue=RunQueue(redis),
    )
    ctx["jobs"] = JobContext(
        sessionmaker, settings, build_email_sender(settings), build_storage(settings), embedder, checkouts,
        runner=dispatcher,
    )
    ctx["runner"] = AgentRunner(
        session_factory=sessionmaker,
        checkpointer=checkpointer,
        model_factory=settings_model_factory(settings),
        token_budget=settings.run_token_budget,
        embedder=embedder,
        web=build_web_research(settings),
        checkouts=checkouts,
        summarize_after_tokens=settings.summarize_after_tokens,
        inline=True,  # this process executes the runs
        stop_reasons=RunQueue(redis),
        streams=RedisRunStreams(redis),
    )
    logger.info("worker ready (queue %s)", QUEUE_NAME)


async def shutdown(ctx: dict[str, Any]) -> None:
    await ctx["stack"].aclose()
    await ctx["engine"].dispose()


async def run_agent(ctx: dict[str, Any], run_id: str, payload: dict[str, Any]) -> None:
    runner: AgentRunner = ctx["runner"]
    await runner.execute(uuid.UUID(run_id), payload)


def job_function(name: str, job: JobFunction, backoff_seconds: float = 10) -> Function:
    async def run(ctx: dict[str, Any], **kwargs: Any) -> None:
        try:
            await job(ctx["jobs"], **kwargs)
        except Exception as exc:
            tries = ctx.get("job_try", 1)
            if tries >= JOB_MAX_TRIES:
                raise
            logger.warning("job %s failed (try %s), retrying: %s", name, tries, exc)
            raise Retry(defer=backoff_seconds * tries) from exc

    return func(run, name=name, timeout=JOB_TIMEOUT, max_tries=JOB_MAX_TRIES)


async def cleanup(ctx: dict[str, Any]) -> None:
    await cleanup_expired(ctx["jobs"])


async def index(ctx: dict[str, Any]) -> None:
    await index_knowledge(ctx["jobs"])


async def automations(ctx: dict[str, Any]) -> None:
    await run_automations(ctx["jobs"])


async def emails(ctx: dict[str, Any]) -> None:
    await email_notifications(ctx["jobs"])


class WorkerSettings:
    functions = [
        func(run_agent, timeout=RUN_TIMEOUT_SECONDS, max_tries=RUN_MAX_TRIES),
        *(job_function(name, job) for name, job in JOBS.items()),
    ]
    # Hourly; arq gives each run a unique job ID, so with several workers only one does it.
    # The search index every minute (only what changed is re-chunked or embedded).
    cron_jobs = [
        cron(cleanup, minute={17}, run_at_startup=True),
        cron(index, run_at_startup=True, timeout=10 * 60),
        cron(automations, timeout=2 * 60),
        cron(emails, timeout=2 * 60),
    ]
    queue_name = QUEUE_NAME
    on_startup = startup
    on_shutdown = shutdown
    allow_abort_jobs = True
    # redis_settings is passed in main(): reading settings at import would need a full environment.


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        # arq's job log lines use arrows and bullets that Windows' console codepage can't encode.
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")  # type: ignore[union-attr]
    if sys.platform == "win32":
        # psycopg (the Postgres checkpointer) can't run on Windows' default Proactor loop.
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    run_worker(WorkerSettings, redis_settings=RedisSettings.from_dsn(get_settings().redis_url))  # type: ignore[arg-type]


if __name__ == "__main__":
    main()
