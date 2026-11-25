"""Personal workspaces launch first: with teams turned off (`DOTRIX_TEAMS`), none
can be created, opened, joined or moved into, and they aren't listed. Their data stays, so
turning them back on brings them back as they were."""
from urllib.parse import parse_qs, urlparse

import pytest
from httpx import AsyncClient

from dotrix_backend.core.settings import Settings


def _settings(client: AsyncClient) -> Settings:
    return client._transport.app.state.settings  # type: ignore[attr-defined]


def _token(url: str) -> str:
    return parse_qs(urlparse(url).query)["token"][0]


@pytest.mark.parametrize(
    ("env", "value", "enabled"),
    [
        ("development", None, True),
        ("test", None, True),
        ("staging", None, False),
        ("production", None, False),
        ("production", True, True),
        ("development", False, False),
    ],
)
def test_teams_are_off_on_a_deployed_server_unless_turned_on(env: str, value: bool | None, enabled: bool) -> None:
    assert Settings.model_construct(env=env, teams=value).teams_enabled is enabled


def test_team_setting_prefers_new_name_and_accepts_legacy_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DOTRIX_TEAMS", raising=False)
    monkeypatch.setenv("DOTRIX_ORGANISATIONS", "false")
    settings = {"env": "test", "database_url": "postgresql+asyncpg://localhost/unused",
                "jwt_secret": "test-only-jwt-secret-not-used-anywhere-else"}
    assert not Settings(_env_file=None, **settings).teams_enabled
    monkeypatch.setenv("DOTRIX_TEAMS", "true")
    assert Settings(_env_file=None, **settings).teams_enabled


async def test_features_say_whether_teams_are_available(db_client: AsyncClient) -> None:
    assert (await db_client.get("/v1/features")).json() == {"teams": True}
    _settings(db_client).teams = False
    assert (await db_client.get("/v1/features")).json() == {"teams": False}


async def test_with_teams_off_only_the_personal_workspace_works(signup, create_team, db_client: AsyncClient) -> None:
    ada = await signup()
    bob = await signup(email="bob@example.com", name="Bob")
    team = await create_team(ada.headers, "Acme")
    link = await db_client.post(f"/v1/workspaces/{team['id']}/invites/links", json={"role": "member"}, headers=ada.headers)
    token = _token(link.json()["url"])
    team_project = await db_client.post(f"/v1/workspaces/{team['id']}/projects", json={"key": "ACM", "name": "Acme"}, headers=ada.headers)
    assert team_project.status_code == 201

    _settings(db_client).teams = False

    listed = (await db_client.get("/v1/workspaces", headers=ada.headers)).json()
    assert [w["kind"] for w in listed] == ["personal"]
    personal = listed[0]

    # Hidden like a workspace you don't belong to.
    assert (await db_client.get(f"/v1/workspaces/{team['id']}", headers=ada.headers)).status_code == 404
    assert (await db_client.get(f"/v1/workspaces/{team['id']}/projects", headers=ada.headers)).status_code == 404
    assert (await db_client.get(f"/v1/workspaces/{team['id']}/invites", headers=ada.headers)).status_code == 404

    created = await db_client.post("/v1/workspaces", json={"name": "Another"}, headers=ada.headers)
    assert created.status_code == 403 and created.json()["type"].endswith("/teams_unavailable")

    chosen = await db_client.post("/v1/me/onboarding-workspace", json={"kind": "team", "name": "Team"}, headers=bob.headers)
    assert chosen.status_code == 403 and chosen.json()["type"].endswith("/teams_unavailable")

    for path in ("/v1/invites/preview", "/v1/invites/accept"):
        res = await db_client.post(path, json={"token": token}, headers=bob.headers)
        assert res.status_code == 403 and res.json()["type"].endswith("/teams_unavailable"), path

    # The personal workspace is untouched, but its projects can't move into the hidden team.
    project = await db_client.post(f"/v1/workspaces/{personal['id']}/projects", json={"key": "SOLO", "name": "Solo"}, headers=ada.headers)
    assert project.status_code == 201, project.text
    moved = await db_client.post(
        f"/v1/workspaces/{personal['id']}/projects/{project.json()['id']}/move", json={"workspace_id": team["id"]}, headers=ada.headers
    )
    assert moved.status_code == 404

    # Turned back on, the team and its project are as they were.
    _settings(db_client).teams = True
    assert {w["id"] for w in (await db_client.get("/v1/workspaces", headers=ada.headers)).json()} == {personal["id"], team["id"]}
    keys = [p["key"] for p in (await db_client.get(f"/v1/workspaces/{team['id']}/projects", headers=ada.headers)).json()]
    assert keys == ["ACM"]
    assert (await db_client.post("/v1/invites/accept", json={"token": token}, headers=bob.headers)).status_code == 200


async def test_a_saved_team_workspace_choice_gives_way_to_personal_when_teams_are_off(signup, db_client: AsyncClient) -> None:
    ada = await signup()
    team = await db_client.post("/v1/me/onboarding-workspace", json={"kind": "team", "name": "Acme"}, headers=ada.headers)
    assert team.status_code == 200, team.text

    _settings(db_client).teams = False

    chosen = await db_client.post("/v1/me/onboarding-workspace", json={"kind": "personal"}, headers=ada.headers)
    assert chosen.status_code == 200, chosen.text
    assert chosen.json()["kind"] == "personal"
    me = (await db_client.get("/v1/me", headers=ada.headers)).json()
    assert me["onboarding_workspace_id"] == chosen.json()["id"]
