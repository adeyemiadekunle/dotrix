"""The backend for end-to-end (browser) tests: `uv run python apps/backend/scripts/e2e_server.py`.

Recreates a throwaway `pmagent_e2e` database (next to the dev one, or $PMAGENT_E2E_DATABASE_URL),
migrates it, then serves the API on port 8100 with the deterministic "e2e:rules" model, so
agent runs need no API key and always behave the same. Never point this at real data.
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from pmagent_backend.core.settings import get_database_settings

BACKEND = Path(__file__).resolve().parents[1]
PORT = os.environ.get("PMAGENT_E2E_PORT", "8100")
WEB_URL = os.environ.get("PMAGENT_E2E_WEB_URL", "http://localhost:3100")


def e2e_database_url() -> str:
    if url := os.environ.get("PMAGENT_E2E_DATABASE_URL"):
        return url
    dev = make_url(get_database_settings().database_url)
    return dev.set(database="pmagent_e2e").render_as_string(hide_password=False)


async def recreate(url: str) -> None:
    target = make_url(url)
    assert target.database and target.database.endswith("_e2e"), "refusing to reset a non-e2e database"
    admin = create_async_engine(target.set(database="postgres"), isolation_level="AUTOCOMMIT")
    async with admin.connect() as conn:
        await conn.execute(text(f'DROP DATABASE IF EXISTS "{target.database}" WITH (FORCE)'))
        await conn.execute(text(f'CREATE DATABASE "{target.database}"'))
    await admin.dispose()


def main() -> None:
    url = e2e_database_url()
    asyncio.run(recreate(url))
    env = {
        **os.environ,
        "PMAGENT_DATABASE_URL": url,
        "PMAGENT_E2E_MODELS": "true",
        "PMAGENT_DEFAULT_MODEL": "e2e:rules",
        "PMAGENT_APP_URL": WEB_URL,
        "PMAGENT_CORS_ORIGINS": f'["{WEB_URL}"]',
        "PMAGENT_LOG_JSON": "false",
        # Every test signs up a fresh account from the same machine (backend tests cover limits).
        "PMAGENT_RATE_LIMITS": "off",
        # Test sign-ups mustn't reach a real email provider, even if .env configures one.
        "PMAGENT_EMAIL_BACKEND": "console",
        # Only used if no secret is configured (e.g. CI); this server holds throwaway data.
        "PMAGENT_JWT_SECRET": os.environ.get("PMAGENT_JWT_SECRET") or "e2e-only-secret-for-throwaway-test-data",
    }
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, env=env, check=True)
    print(f"e2e backend: {make_url(url).database} on :{PORT}", flush=True)
    raise SystemExit(
        subprocess.call([sys.executable, "-m", "pmagent_backend.serve", "--port", PORT], env=env)
    )


if __name__ == "__main__":
    main()
