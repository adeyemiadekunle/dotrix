from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def test_readiness_checks_database(db_client: AsyncClient) -> None:
    res = await db_client.get("/health/ready")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok" and body["database"] == "ok"
    assert body["database_ms"] >= 0 and body["time"].endswith("Z")


async def test_migrations_applied(db_session: AsyncSession) -> None:
    version = await db_session.scalar(text("SELECT version_num FROM alembic_version"))
    assert version is not None


async def test_each_test_is_rolled_back_part_1(db_session: AsyncSession) -> None:
    await db_session.execute(text("CREATE TABLE scratch (id int)"))
    await db_session.commit()  # services commit; the outer transaction still rolls back


async def test_each_test_is_rolled_back_part_2(db_session: AsyncSession) -> None:
    exists = await db_session.scalar(text("SELECT to_regclass('public.scratch')"))
    assert exists is None
