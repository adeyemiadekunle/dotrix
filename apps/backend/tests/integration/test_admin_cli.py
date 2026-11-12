"""Admin accounts made and recovered from the server's command line (admin_cli, modules/admin/accounts)."""
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from dotrix_backend.admin_cli import build_parser
from dotrix_backend.core.errors import Conflict, Unprocessable
from dotrix_backend.modules.admin.accounts import create_admin, list_admins, reset_admin_password

PASSWORD = "a long enough secret"


@pytest.fixture(autouse=True)
def admin_header(db_client: AsyncClient) -> None:
    db_client.headers["X-Requested-With"] = "dotrix-admin"


async def _login(client: AsyncClient, email: str, password: str):
    return await client.post("/v1/admin/login", json={"email": email, "password": password})


async def test_created_admin_signs_in(db_client: AsyncClient, db_session: AsyncSession) -> None:
    await create_admin(db_session, email="Ops@Example.com", name="Ops", password=PASSWORD)
    res = await _login(db_client, "ops@example.com", PASSWORD)
    assert res.status_code == 204
    assert res.cookies.get("dtx_admin_access") and res.cookies.get("dtx_admin_refresh")


async def test_a_second_admin_can_be_created_after_the_first(db_session: AsyncSession) -> None:
    await create_admin(db_session, email="one@example.com", name="One", password=PASSWORD)
    await create_admin(db_session, email="two@example.com", name="Two", password=PASSWORD)
    assert len(await list_admins(db_session)) == 2


async def test_duplicate_email_and_short_password_are_refused(db_session: AsyncSession) -> None:
    await create_admin(db_session, email="one@example.com", name="One", password=PASSWORD)
    with pytest.raises(Conflict):
        await create_admin(db_session, email="ONE@example.com", name="Again", password=PASSWORD)
    with pytest.raises(Unprocessable):
        await create_admin(db_session, email="short@example.com", name="Short", password="too short")


async def test_reset_changes_the_password_and_signs_out_sessions(db_client: AsyncClient, db_session: AsyncSession) -> None:
    await create_admin(db_session, email="one@example.com", name="One", password=PASSWORD)
    assert (await _login(db_client, "one@example.com", PASSWORD)).status_code == 204
    assert (await db_client.get("/v1/admin/me")).status_code == 200
    await reset_admin_password(db_session, email="one@example.com", password="a brand new secret")
    assert (await db_client.get("/v1/admin/me")).status_code == 401
    db_client.cookies.clear()
    assert (await _login(db_client, "one@example.com", PASSWORD)).status_code == 401
    assert (await _login(db_client, "one@example.com", "a brand new secret")).status_code == 204


async def test_list_is_oldest_first(db_session: AsyncSession) -> None:
    await create_admin(db_session, email="one@example.com", name="One", password=PASSWORD)
    await create_admin(db_session, email="two@example.com", name="Two", password=PASSWORD)
    assert [a.email for a in await list_admins(db_session)] == ["one@example.com", "two@example.com"]


def test_parser_lists_its_commands(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as stop:
        build_parser().parse_args(["--help"])
    assert stop.value.code == 0
    out = capsys.readouterr().out
    assert "list" in out and "create" in out and "reset-password" in out
