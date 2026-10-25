"""Run the API: `python -m dotrix_backend.serve [--reload] [--port 8000]` (`pnpm dev:backend`).

Same as `uvicorn --factory dotrix_backend.main:create_app`, except that on Windows it
uses a selector event loop: psycopg (the Postgres checkpointer that makes agent runs
resumable) can't run on Windows' default Proactor loop. uvicorn's --loop flag only
takes its built-in names, so the loop factory is passed programmatically.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import uvicorn


def selector_loop() -> asyncio.AbstractEventLoop:
    return asyncio.SelectorEventLoop()


def source_dirs() -> list[str]:
    """What --reload watches: the API's own code and the engine it runs (never the folder it
    starts in, where worktrees, node_modules, or a virtualenv would restart it for nothing)."""
    import dotrix_backend
    import dotrix_engine

    return [str(Path(module.__file__).parent) for module in (dotrix_backend, dotrix_engine)]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the dotrix API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true", help="Restart on code changes")
    args = parser.parse_args()
    uvicorn.run(
        "dotrix_backend.main:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        reload=args.reload,
        reload_dirs=source_dirs() if args.reload else None,
        loop="dotrix_backend.serve:selector_loop" if sys.platform == "win32" else "auto",
    )


if __name__ == "__main__":
    main()
