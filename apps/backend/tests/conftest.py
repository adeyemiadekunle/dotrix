"""Backend test fixtures.

Integration tests run against a real Postgres database: PMAGENT_TEST_DATABASE_URL
if set, otherwise PMAGENT_DATABASE_URL (from .env) with the database name
swapped to `pmagent_test`. That database is dropped and recreated each run. The schema is migrated once per session with
Alembic, and each test runs inside a transaction that is rolled back, so
tests never see each other's data. Service code may call commit(): the
session joins the outer transaction via savepoints.
"""
from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import make_url, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from pmagent_backend.core.settings import Settings, get_settings
from pmagent_backend.db.session import get_session
from pmagent_backend.main import create_app

BACKEND_DIR = Path(__file__).resolve().parents[1]
# For tests that never open a connection; no credentials.
UNUSED_DATABASE_URL = "postgresql+asyncpg://localhost/unused"


def test_database_url() -> str:
    if url := os.environ.get("PMAGENT_TEST_DATABASE_URL"):
        return url
    dev_url = make_url(get_settings().database_url)
    return dev_url.set(database="pmagent_test").render_as_string(hide_password=False)


async def _recreate_database(url: str) -> None:
    target = make_url(url)
    admin = create_async_engine(target.set(database="postgres"), isolation_level="AUTOCOMMIT")
    async with admin.connect() as conn:
        await conn.execute(text(f'DROP DATABASE IF EXISTS "{target.database}" WITH (FORCE)'))
        await conn.execute(text(f'CREATE DATABASE "{target.database}"'))
    await admin.dispose()


@pytest.fixture(scope="session")
def migrated_database() -> str:
    """Fresh test database at Alembic head. Sync, so Alembic can run its own loop."""
    url = test_database_url()
    asyncio.run(_recreate_database(url))
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    # "%" must be escaped for ConfigParser (passwords may contain it).
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    config.attributes["configure_logger"] = False
    command.upgrade(config, "head")
    return url


@pytest.fixture(scope="session")
async def engine(migrated_database: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(migrated_database)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    async with engine.connect() as conn:
        outer = await conn.begin()
        session = AsyncSession(
            bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False
        )
        try:
            yield session
        finally:
            await session.close()
            await outer.rollback()


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """HTTP client for endpoints that don't touch the database."""
    app = create_app(Settings(env="test", log_json=False, database_url=UNUSED_DATABASE_URL))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
async def db_client(
    migrated_database: str, db_session: AsyncSession
) -> AsyncIterator[AsyncClient]:
    """HTTP client whose requests share the test's rolled-back session."""
    app = create_app(Settings(env="test", log_json=False, database_url=migrated_database))
    app.dependency_overrides[get_session] = lambda: db_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
