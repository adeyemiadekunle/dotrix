"""Backend test fixtures.

Integration tests run against a real Postgres database: PMAGENT_TEST_DATABASE_URL
if set, otherwise PMAGENT_DATABASE_URL (from .env) with the database name
swapped to `pmagent_test`. Each run creates its own database named after that one
(`pmagent_test_<random>`) and drops it at the end, so runs in different checkouts (or
side by side in one) never drop each other's database mid-test. The schema is migrated
once per session with Alembic, and each test runs inside a transaction that is rolled
back, so tests never see each other's data. Service code may call commit(): the
session joins the outer transaction via savepoints.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from alembic import command
from alembic.config import Config
from arq import create_pool
from arq.connections import RedisSettings
from httpx import ASGITransport, AsyncClient
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import make_url, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from pmagent_backend.core.email import OutboxEmailSender, get_email_sender
from pmagent_backend.core.jobs import InlineJobs, JobContext
from pmagent_backend.core.settings import Settings, get_database_settings
from pmagent_backend.core.storage import MemoryBlobStorage, get_storage
from pmagent_backend.db.session import get_session
from pmagent_backend.jobs import JOBS
from pmagent_backend.main import create_app
from pmagent_backend.modules.agents.llm import ModelChoice, ModelUnavailable
from pmagent_backend.modules.agents.runner import AgentRunner
from pmagent_backend.modules.code.checkouts import CodeCheckouts
from pmagent_backend.modules.workspaces.models import Membership, Role
from pmagent_engine.testing import ScriptedChatModel

BACKEND_DIR = Path(__file__).resolve().parents[1]
# For tests that never open a connection; no credentials.
UNUSED_DATABASE_URL = "postgresql+asyncpg://localhost/unused"


def resolve_test_database_url() -> str:
    """This run's own database: the configured test database's name plus a random suffix."""
    if url := os.environ.get("PMAGENT_TEST_DATABASE_URL"):
        base = make_url(url)
    else:
        base = make_url(get_database_settings().database_url).set(database="pmagent_test")
    run_database = f"{base.database}_{uuid.uuid4().hex[:8]}"
    return base.set(database=run_database).render_as_string(hide_password=False)


async def _admin(url: str, *statements: str) -> None:
    admin = create_async_engine(make_url(url).set(database="postgres"), isolation_level="AUTOCOMMIT")
    async with admin.connect() as conn:
        for statement in statements:
            await conn.execute(text(statement))
    await admin.dispose()


@pytest.fixture(scope="session")
def migrated_database() -> Iterator[str]:
    """This run's database at Alembic head, dropped afterwards. Sync, so Alembic can run its
    own loop."""
    url = resolve_test_database_url()
    name = make_url(url).database
    asyncio.run(_admin(url, f'CREATE DATABASE "{name}"'))
    try:
        config = Config(str(BACKEND_DIR / "alembic.ini"))
        config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
        # "%" must be escaped for ConfigParser (passwords may contain it).
        config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
        config.attributes["configure_logger"] = False
        command.upgrade(config, "head")
        yield url
    finally:
        # Only this run ever connects to it, so forcing out leftover connections is safe.
        asyncio.run(_admin(url, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


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


def make_settings(database_url: str = UNUSED_DATABASE_URL, **overrides: Any) -> Settings:
    """Explicit test settings, so tests never depend on a developer's .env or CI secrets."""
    return Settings(
        env="test",
        log_json=False,
        database_url=database_url,
        jwt_secret="test-only-jwt-secret-not-used-anywhere-else",  # type: ignore[arg-type]
        app_url="http://app.test",
        email_backend="console",
        default_model="anthropic:claude-sonnet-5",
        # Tests that check limits install a limiter themselves (`rate_limited` fixture).
        rate_limits="off",
        # No real embedding calls; search tests install a fake embedder.
        embedding_model="",
        # Not offered unless a test sets it up (a developer's .env may have it).
        github_client_id=None,
        github_client_secret=None,
        # No real web searches (a developer's .env may have a Tavily key).
        tavily_api_key=None,
        **overrides,
    )


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """HTTP client for endpoints that don't touch the database."""
    app = create_app(make_settings())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


REDIS_URL = os.environ.get("PMAGENT_TEST_REDIS_URL", "redis://127.0.0.1:6379/15")


@pytest.fixture
async def redis() -> AsyncIterator[Any]:
    """An arq Redis pool on $PMAGENT_TEST_REDIS_URL (or local database 15); the test is
    skipped if Redis isn't reachable. Use unique key prefixes / queue names per test."""
    try:
        pool = await create_pool(RedisSettings.from_dsn(REDIS_URL), retry=0)
        await pool.ping()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Redis not reachable at {REDIS_URL}: {exc}")
    yield pool
    await pool.aclose()


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
        self.specialist: ScriptedChatModel | None = None
        self.models_used: list[str | None] = []  # the model each run (or check) asked for

    def say(self, *replies: object) -> ScriptedChatModel:
        self.model = ScriptedChatModel.of(*replies)  # type: ignore[arg-type]
        return self.model

    def specialists_say(self, *replies: object) -> ScriptedChatModel:
        """A separate (cheaper) model for the specialists and summaries."""
        self.specialist = ScriptedChatModel.of(*replies)  # type: ignore[arg-type]
        return self.specialist

    def factory(self, project: object, model: str | None = None) -> ModelChoice:
        self.models_used.append(model)
        if self.model is None:
            raise ModelUnavailable("No API key for the test model")
        return ModelChoice(model=self.model, web_search=None, specialist_model=self.specialist)


@pytest.fixture
def agent_script() -> AgentScript:
    return AgentScript()


@pytest.fixture
def checkouts(tmp_path: Path) -> CodeCheckouts:
    """Connected repos' checkouts, in a folder of the test's own; set `.remote` to fetch."""
    return CodeCheckouts(tmp_path / "code", None, max_bytes=50_000_000)


@pytest.fixture
async def db_client(
    migrated_database: str,
    db_session: AsyncSession,
    outbox: OutboxEmailSender,
    storage: MemoryBlobStorage,
    agent_script: AgentScript,
    checkouts: CodeCheckouts,
) -> AsyncIterator[AsyncClient]:
    """HTTP client whose requests share the test's rolled-back session."""
    app = create_app(make_settings(migrated_database))
    app.dependency_overrides[get_session] = lambda: db_session
    app.dependency_overrides[get_email_sender] = lambda: outbox
    app.dependency_overrides[get_storage] = lambda: storage

    @asynccontextmanager
    async def shared_session() -> AsyncIterator[AsyncSession]:
        # Like production, each unit of agent work gets its own session (so a failed tool
        # call rolls back only its own work), but on the test's connection, inside the
        # test's rolled-back transaction.
        session = AsyncSession(
            bind=db_session.bind, join_transaction_mode="create_savepoint", expire_on_commit=False
        )
        try:
            yield session
        finally:
            await session.close()

    # Inline: jobs and runs finish (or pause) before the request that started them returns.
    app.state.checkouts = checkouts
    app.state.jobs = InlineJobs(
        JobContext(shared_session, app.state.settings, outbox, storage, checkouts=checkouts), JOBS
    )
    app.state.runner = AgentRunner(
        session_factory=shared_session,
        checkpointer=InMemorySaver(),
        model_factory=agent_script.factory,
        inline=True,
        checkouts=checkouts,
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
        """An organisation you own (a workspace that can invite people)."""
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
