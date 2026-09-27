"""The agent-run worker: `python -m pmagent_backend.worker` (`pnpm dev:worker`).

Executes the runs the API enqueues when PMAGENT_AGENT_RUNS=worker (arq on Redis). Runs
survive API restarts; if the worker itself stops mid-run, the job is retried and continues
from its last checkpoint. Stop (from the API) aborts the job. Run as many workers as you
like: each run step goes to one of them.
"""
from __future__ import annotations

import asyncio
import logging
import sys
import uuid
from contextlib import AsyncExitStack
from typing import Any

from arq import func
from arq.connections import RedisSettings
from arq.worker import run_worker

from .core.logging import configure_logging
from .core.settings import get_settings
from .db.session import create_engine, create_sessionmaker
from .modules.agents.checkpoints import open_checkpointer
from .modules.agents.llm import settings_model_factory
from .modules.agents.queue import QUEUE_NAME, RunQueue
from .modules.agents.runner import AgentRunner
from .modules.agents.streams import RedisRunStreams
from .modules.agents.titles import generate_title

logger = logging.getLogger(__name__)

JOB_TIMEOUT_SECONDS = 60 * 60  # an agent run can take a while (research, many approvals' worth of work)
MAX_TRIES = 3  # a run cut off by a worker restart is retried from its last checkpoint


async def startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    stack = ctx["stack"] = AsyncExitStack()
    engine = ctx["engine"] = create_engine(settings.database_url, echo=settings.database_echo)
    redis = ctx["redis"]
    ctx["runner"] = AgentRunner(
        session_factory=create_sessionmaker(engine),
        checkpointer=await open_checkpointer(settings.database_url, stack),
        model_factory=settings_model_factory(settings),
        inline=True,  # this process executes the runs
        titler=generate_title,
        stop_reasons=RunQueue(redis),
        streams=RedisRunStreams(redis),
    )
    logger.info("agent worker ready (queue %s)", QUEUE_NAME)


async def shutdown(ctx: dict[str, Any]) -> None:
    await ctx["stack"].aclose()
    await ctx["engine"].dispose()


async def run_agent(ctx: dict[str, Any], run_id: str, payload: dict[str, Any]) -> None:
    runner: AgentRunner = ctx["runner"]
    await runner.execute(uuid.UUID(run_id), payload)


class WorkerSettings:
    functions = [func(run_agent, timeout=JOB_TIMEOUT_SECONDS, max_tries=MAX_TRIES)]
    queue_name = QUEUE_NAME
    on_startup = startup
    on_shutdown = shutdown
    allow_abort_jobs = True
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        # arq's job log lines use arrows and bullets that Windows' console codepage can't encode.
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")  # type: ignore[union-attr]
    if sys.platform == "win32":
        # psycopg (the Postgres checkpointer) can't run on Windows' default Proactor loop.
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    run_worker(WorkerSettings)  # type: ignore[arg-type]


if __name__ == "__main__":
    main()
