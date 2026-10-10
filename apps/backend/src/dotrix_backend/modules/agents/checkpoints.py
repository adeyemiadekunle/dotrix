"""The LangGraph checkpointer that makes agent runs resumable (per thread).

Postgres in normal operation, so a run paused for approval survives restarts
and can be resumed by any API process. Its tables (checkpoints, checkpoint_*)
are created and migrated by langgraph itself, not Alembic.

psycopg's async mode can't run on Windows' default (Proactor) event loop, so the
dev server (`dotrix_backend.serve`) uses a selector loop there. If the Postgres
saver still can't start, runs fall back to memory and a warning says so.
"""
from __future__ import annotations

import asyncio
import logging
import sys
from contextlib import AsyncExitStack
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import make_url

logger = logging.getLogger(__name__)


def psycopg_conninfo(database_url: str) -> str:
    """postgresql+asyncpg://... (SQLAlchemy) -> postgresql://... (psycopg)."""
    return make_url(database_url).set(drivername="postgresql").render_as_string(hide_password=False)


def _proactor_loop() -> bool:
    return sys.platform == "win32" and isinstance(
        asyncio.get_running_loop(), getattr(asyncio, "ProactorEventLoop", ())
    )


def _memory_fallback(reason: str) -> InMemorySaver:
    logger.warning(
        "Postgres checkpointer unavailable (%s); agent runs are kept in memory and will NOT "
        "survive a restart.",
        reason,
    )
    return InMemorySaver()


async def open_checkpointer(database_url: str, stack: AsyncExitStack) -> Any:
    if _proactor_loop():
        return _memory_fallback(
            "Windows Proactor event loop; start the API with `pnpm dev:backend` "
            "(python -m dotrix_backend.serve), which uses a selector loop"
        )
    pool = None
    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        from psycopg.rows import dict_row
        from psycopg_pool import AsyncConnectionPool

        pool = AsyncConnectionPool(
            psycopg_conninfo(database_url),
            max_size=10,
            open=False,
            kwargs={
                "autocommit": True,
                "prepare_threshold": 0,
                "row_factory": dict_row,
                "connect_timeout": 5,  # never hang startup on an unreachable address
            },
        )
        await pool.open(wait=True, timeout=10)
        saver = AsyncPostgresSaver(pool)  # type: ignore[arg-type]
        await saver.setup()
    except Exception as exc:
        if pool is not None:
            await pool.close()
        return _memory_fallback(f"{exc.__class__.__name__}: {exc}")
    stack.push_async_callback(pool.close)
    return saver
