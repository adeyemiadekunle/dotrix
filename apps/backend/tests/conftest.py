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
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import make_url, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from pmagent_backend.core.email import OutboxEmailSender, get_email_sender
from pmagent_backend.core.settings import Settings, get_database_settings
from pmagent_backend.core.storage import MemoryBlobStorage, get_storage
from pmagent_backend.db.session import get_session
from pmagent_backend.main import create_app
from pmagent_backend.modules.agents.llm import ModelChoice, ModelUnavailable
from pmagent_backend.modules.agents.runner import AgentRunner
from pmagent_backend.modules.workspaces.models import Membership, Role
from pmagent_engine.testing import ScriptedChatModel

BACKEND_DIR = Path(__file__).resolve().parents[1]
# For tests that never open a connection; no credentials.
UNUSED_DATABASE_URL = "postgresql+asyncpg://localhost/unused"


def resolve_test_database_url() -> str:
    if url := os.environ.get("PMAGENT_TEST_DATABASE_URL"):
        return url
    dev_url = make_url(get_database_settings().database_url)
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
    url = resolve_test_database_url()
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


def make_settings(database_url: str = UNUSED_DATABASE_URL) -> Settings:
    """Explicit test settings, so tests never depend on a developer's .env or CI secrets."""
    return Settings(
        env="test",
        log_json=False,
        database_url=database_url,
        jwt_secret="test-only-jwt-secret-not-used-anywhere-else",  # type: ignore[arg-type]
        app_url="http://app.test",
        email_backend="console",
        default_model="anthropic:claude-sonnet-5",
    )


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """HTTP client for endpoints that don't touch the database."""
    app = create_app(make_settings())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
def outbox() -> OutboxEmailSender:
    return OutboxEmailSender()


@pytest.fixture
def storage() -> MemoryBlobStorage:
    return MemoryBlobStorage()


class AgentScript:
    """What the agents' model will say in this test: `agent_script.say("hi", tool_call(...))`."""

    def __init__(self) -> None:
        self.model: ScriptedChatModel | None = None

    def say(self, *replies: object) -> ScriptedChatModel:
        self.model = ScriptedChatModel.of(*replies)  # type: ignore[arg-type]
        return self.model

    def factory(self, project: object) -> ModelChoice:
        if self.model is None:
            raise ModelUnavailable("No API key for the test model")
        return ModelChoice(model=self.model, web_search=None)


@pytest.fixture
def agent_script() -> AgentScript:
    return AgentScript()


@pytest.fixture
async def db_client(
    migrated_database: str,
    db_session: AsyncSession,
    outbox: OutboxEmailSender,
    storage: MemoryBlobStorage,
    agent_script: AgentScript,
) -> AsyncIterator[AsyncClient]:
    """HTTP client whose requests share the test's rolled-back session."""
    app = create_app(make_settings(migrated_database))
    app.dependency_overrides[get_session] = lambda: db_session
    app.dependency_overrides[get_email_sender] = lambda: outbox
    app.dependency_overrides[get_storage] = lambda: storage

    @asynccontextmanager
    async def shared_session() -> AsyncIterator[AsyncSession]:
        yield db_session  # agent runs join the test's rolled-back transaction

    # Inline: a run finishes (or pauses) before the request that started it returns.
    app.state.runner = AgentRunner(
        session_factory=shared_session,
        checkpointer=InMemorySaver(),
        model_factory=agent_script.factory,
        inline=True,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


class SignedUp:
    """A user created through the API, with their tokens and auth header."""

    def __init__(self, body: dict[str, Any], password: str) -> None:
        self.user = body["user"]
        self.id: str = body["user"]["id"]
        self.email: str = body["user"]["email"]
        self.password = password
        self.tokens = body["tokens"]
        self.headers = {"Authorization": f"Bearer {self.tokens['access_token']}"}


@pytest.fixture
def signup(db_client: AsyncClient) -> Callable[..., Awaitable[SignedUp]]:
    async def _signup(
        email: str = "ada@example.com", password: str = "correct horse battery", name: str = "Ada"
    ) -> SignedUp:
        res = await db_client.post(
            "/v1/auth/signup", json={"email": email, "password": password, "display_name": name}
        )
        assert res.status_code == 201, res.text
        return SignedUp(res.json(), password)

    return _signup


@pytest.fixture
def email_token(outbox: OutboxEmailSender) -> Callable[[str], str]:
    """Token from the newest emailed link whose path is `path`, e.g. "/verify-email"."""

    def _token(path: str) -> str:
        for message in reversed(outbox.messages):
            for word in message.body.split():
                url = urlparse(word)
                if url.path == path:
                    return parse_qs(url.query)["token"][0]
        raise AssertionError(f"no email with a {path} link")

    return _token


@pytest.fixture
def create_team(db_client: AsyncClient) -> Callable[..., Awaitable[dict[str, Any]]]:
    async def _create(headers: dict[str, str], name: str = "Kunemi") -> dict[str, Any]:
        res = await db_client.post("/v1/workspaces", json={"name": name}, headers=headers)
        assert res.status_code == 201, res.text
        return res.json()

    return _create


@pytest.fixture
def add_member(db_session: AsyncSession) -> Callable[[str, str, Role], Awaitable[None]]:
    """Insert a membership directly, for tests that aren't about invites."""

    async def _add(workspace_id: str, user_id: str, role: Role) -> None:
        db_session.add(
            Membership(workspace_id=uuid.UUID(workspace_id), user_id=uuid.UUID(user_id), role=role)
        )
        await db_session.commit()

    return _add
