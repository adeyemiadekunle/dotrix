from urllib.parse import parse_qs, urlparse

from httpx import AsyncClient

from pmagent_backend.core.email import OutboxEmailSender
from pmagent_backend.modules.workspaces.models import Role


def ws(team: dict) -> str:
    return f"/v1/workspaces/{team['id']}"


async def accept(client: AsyncClient, token: str, headers: dict[str, str]):
    return await client.post("/v1/invites/accept", json={"token": token}, headers=headers)


# -- email invites --------------------------------------------------------------------


async def test_email_invite_flow(
    signup, create_team, db_client: AsyncClient, outbox: OutboxEmailSender, email_token
) -> None:
    ada = await signup()
    team = await create_team(ada.headers, "Kunemi", in_org=True)
    res = await db_client.post(
        f"{ws(team)}/invites", json={"email": "Bob@Example.com", "role": "admin"}, headers=ada.headers
    )
    assert res.status_code == 201
    assert res.json()["email"] == "bob@example.com"
    assert outbox.messages[-1].to == "bob@example.com"
    assert "Ada invited you to Kunemi" in outbox.messages[-1].subject
    token = email_token("/invites/accept")

    listed = (await db_client.get(f"{ws(team)}/invites", headers=ada.headers)).json()
    assert [i["email"] for i in listed] == ["bob@example.com"]

    # The accept page can show details before the invitee signs in.
    preview = await db_client.post("/v1/invites/preview", json={"token": token})
    assert preview.status_code == 200
    assert preview.json() | {"expires_at": None} == {
        "workspace_name": "Kunemi",
        "workspace_kind": "team",
        "role": "admin",
        "invited_by": "Ada",
        "email": "bob@example.com",
        "expires_at": None,
    }

    bob = await signup(email="bob@example.com", name="Bob")
    res = await accept(db_client, token, bob.headers)
    assert res.status_code == 200
    assert res.json()["id"] == team["id"] and res.json()["role"] == "admin"
    # Accepting via the emailed link proves the address.
    assert (await db_client.get("/v1/me", headers=bob.headers)).json()["email_verified"] is True

    assert (await db_client.get(f"{ws(team)}/invites", headers=ada.headers)).json() == []
    reused = await accept(db_client, token, bob.headers)
    assert reused.status_code == 400 and reused.json()["type"].endswith("/invalid_link")


async def test_email_invite_only_works_for_that_address(
    signup, create_team, db_client: AsyncClient, email_token
) -> None:
    ada = await signup()
    team = await create_team(ada.headers, in_org=True)
    await db_client.post(f"{ws(team)}/invites", json={"email": "bob@example.com"}, headers=ada.headers)
    carol = await signup(email="carol@example.com", name="Carol")
    res = await accept(db_client, email_token("/invites/accept"), carol.headers)
    assert res.status_code == 403
    assert (await db_client.get(ws(team), headers=carol.headers)).status_code == 404


async def test_reinvite_replaces_the_previous_invite(
    signup, create_team, db_client: AsyncClient, email_token
) -> None:
    ada = await signup()
    team = await create_team(ada.headers, in_org=True)
    body = {"email": "bob@example.com"}
    await db_client.post(f"{ws(team)}/invites", json=body, headers=ada.headers)
    first = email_token("/invites/accept")
    await db_client.post(f"{ws(team)}/invites", json=body, headers=ada.headers)
    second = email_token("/invites/accept")

    assert len((await db_client.get(f"{ws(team)}/invites", headers=ada.headers)).json()) == 1
    bob = await signup(email="bob@example.com", name="Bob")
    assert (await accept(db_client, first, bob.headers)).status_code == 400
    assert (await accept(db_client, second, bob.headers)).status_code == 200


async def test_cannot_invite_an_existing_member(signup, create_team, db_client: AsyncClient) -> None:
    ada = await signup()
    team = await create_team(ada.headers, in_org=True)
    res = await db_client.post(
        f"{ws(team)}/invites", json={"email": "ada@example.com"}, headers=ada.headers
    )
    assert res.status_code == 409


async def test_invite_permissions(signup, create_team, add_member, db_client: AsyncClient) -> None:
    ada = await signup()
    bob = await signup(email="bob@example.com", name="Bob")
    outsider = await signup(email="eve@example.com", name="Eve")
    team = await create_team(ada.headers, in_org=True)
    await add_member(team["id"], bob.id, Role.MEMBER)
    body = {"email": "new@example.com"}

    # Members can't invite or see invites; outsiders can't tell the workspace exists.
    assert (await db_client.post(f"{ws(team)}/invites", json=body, headers=bob.headers)).status_code == 403
    assert (await db_client.get(f"{ws(team)}/invites", headers=bob.headers)).status_code == 403
    assert (await db_client.post(f"{ws(team)}/invites", json=body, headers=outsider.headers)).status_code == 404
    assert (await db_client.get(f"{ws(team)}/invites", headers=outsider.headers)).status_code == 404


async def test_nobody_is_invited_as_owner(signup, create_team, db_client: AsyncClient) -> None:
    ada = await signup()
    team = await create_team(ada.headers, in_org=True)
    res = await db_client.post(
        f"{ws(team)}/invites", json={"email": "bob@example.com", "role": "owner"}, headers=ada.headers
    )
    assert res.status_code == 422


async def test_a_personal_workspace_invites_nobody(signup, db_client: AsyncClient) -> None:
    ada = await signup()
    personal = (await db_client.get("/v1/workspaces", headers=ada.headers)).json()[0]
    for role in ("member", "guest"):
        res = await db_client.post(
            f"{ws(personal)}/invites", json={"email": "bob@example.com", "role": role}, headers=ada.headers
        )
        assert res.status_code == 409 and res.json()["type"].endswith("/invites_need_organization")
        assert "just for you" in res.json()["detail"]
    link = await db_client.post(f"{ws(personal)}/invites/links", json={"role": "guest"}, headers=ada.headers)
    assert link.status_code == 409


async def test_only_organisation_workspaces_invite(signup, create_team, db_client: AsyncClient) -> None:
    ada = await signup()
    standalone = await create_team(ada.headers, "Solo team")
    res = await db_client.post(f"{ws(standalone)}/invites", json={"email": "bob@example.com"}, headers=ada.headers)
    assert res.status_code == 409 and "Add this workspace to an organisation" in res.json()["detail"]
    assert (await db_client.post(f"{ws(standalone)}/invites/links", json={}, headers=ada.headers)).status_code == 409
    # In an organisation, it can.
    org = (await db_client.post("/v1/organizations", json={"name": "Kunemi Ltd"}, headers=ada.headers)).json()
    attach = await db_client.post(
        f"/v1/organizations/{org['id']}/workspaces/attach", json={"workspace_id": standalone["id"]}, headers=ada.headers
    )
    assert attach.status_code == 200
    assert (
        await db_client.post(f"{ws(standalone)}/invites", json={"email": "bob@example.com"}, headers=ada.headers)
    ).status_code == 201


async def test_an_invite_stops_working_when_its_workspace_leaves_the_organisation(
    signup, create_team, db_client: AsyncClient, email_token
) -> None:
    ada = await signup()
    team = await create_team(ada.headers, in_org=True)
    res = await db_client.post(f"{ws(team)}/invites", json={"email": "bob@example.com"}, headers=ada.headers)
    assert res.status_code == 201
    token = email_token("/invites/accept")
    detached = await db_client.post(
        f"/v1/organizations/{team['organization_id']}/workspaces/{team['id']}/detach", headers=ada.headers
    )
    assert detached.status_code == 204
    bob = await signup(email="bob@example.com", name="Bob")
    accepted = await db_client.post("/v1/invites/accept", json={"token": token}, headers=bob.headers)
    assert accepted.status_code == 409 and accepted.json()["type"].endswith("/invites_need_organization")


# -- link invites ---------------------------------------------------------------------


def token_from(url: str) -> str:
    return parse_qs(urlparse(url).query)["token"][0]


async def test_link_invite_with_use_limit(signup, create_team, db_client: AsyncClient) -> None:
    ada = await signup()
    team = await create_team(ada.headers, in_org=True)
    res = await db_client.post(
        f"{ws(team)}/invites/links", json={"role": "guest", "max_uses": 1}, headers=ada.headers
    )
    assert res.status_code == 201
    link = res.json()
    assert link["kind"] == "link" and link["url"].startswith("http://app.test/invites/accept?token=")
    token = token_from(link["url"])

    bob = await signup(email="bob@example.com", name="Bob")
    joined = await accept(db_client, token, bob.headers)
    assert joined.status_code == 200 and joined.json()["role"] == "guest"

    carol = await signup(email="carol@example.com", name="Carol")
    assert (await accept(db_client, token, carol.headers)).status_code == 400  # used up


async def test_link_cannot_grant_admin(signup, create_team, db_client: AsyncClient) -> None:
    ada = await signup()
    team = await create_team(ada.headers, in_org=True)
    res = await db_client.post(f"{ws(team)}/invites/links", json={"role": "admin"}, headers=ada.headers)
    assert res.status_code == 422


async def test_revoked_link_stops_working(signup, create_team, db_client: AsyncClient) -> None:
    ada = await signup()
    team = await create_team(ada.headers, in_org=True)
    link = (await db_client.post(f"{ws(team)}/invites/links", json={}, headers=ada.headers)).json()
    res = await db_client.delete(f"{ws(team)}/invites/{link['id']}", headers=ada.headers)
    assert res.status_code == 204

    bob = await signup(email="bob@example.com", name="Bob")
    assert (await accept(db_client, token_from(link["url"]), bob.headers)).status_code == 400
    preview = await db_client.post("/v1/invites/preview", json={"token": token_from(link["url"])})
    assert preview.status_code == 400


async def test_existing_member_keeps_role_and_does_not_use_the_link(
    signup, create_team, db_client: AsyncClient
) -> None:
    ada = await signup()
    team = await create_team(ada.headers, in_org=True)
    link = (
        await db_client.post(f"{ws(team)}/invites/links", json={"max_uses": 1}, headers=ada.headers)
    ).json()
    res = await accept(db_client, token_from(link["url"]), ada.headers)
    assert res.status_code == 200 and res.json()["role"] == "owner"  # not demoted to member
    listed = (await db_client.get(f"{ws(team)}/invites", headers=ada.headers)).json()
    assert listed[0]["use_count"] == 0


async def test_accept_requires_sign_in(signup, create_team, db_client: AsyncClient) -> None:
    ada = await signup()
    team = await create_team(ada.headers, in_org=True)
    link = (await db_client.post(f"{ws(team)}/invites/links", json={}, headers=ada.headers)).json()
    res = await db_client.post("/v1/invites/accept", json={"token": token_from(link["url"])})
    assert res.status_code == 401


# -- ownership transfer ---------------------------------------------------------------


async def test_transfer_ownership(signup, create_team, add_member, db_client: AsyncClient) -> None:
    ada = await signup()
    bob = await signup(email="bob@example.com", name="Bob")
    team = await create_team(ada.headers, in_org=True)
    await add_member(team["id"], bob.id, Role.ADMIN)

    # An admin can't take ownership.
    res = await db_client.post(
        f"{ws(team)}/transfer-ownership", json={"user_id": bob.id}, headers=bob.headers
    )
    assert res.status_code == 403

    res = await db_client.post(
        f"{ws(team)}/transfer-ownership", json={"user_id": bob.id}, headers=ada.headers
    )
    assert res.status_code == 200 and res.json()["role"] == "owner"
    roles = {
        m["email"]: m["role"]
        for m in (await db_client.get(f"{ws(team)}/members", headers=bob.headers)).json()
    }
    assert roles == {"ada@example.com": "admin", "bob@example.com": "owner"}


async def test_transfer_ownership_rules(signup, create_team, add_member, db_client: AsyncClient) -> None:
    ada = await signup()
    guest = await signup(email="guest@example.com", name="Guest")
    team = await create_team(ada.headers, in_org=True)
    await add_member(team["id"], guest.id, Role.GUEST)
    personal = (await db_client.get("/v1/workspaces", headers=ada.headers)).json()[0]

    to_guest = await db_client.post(
        f"{ws(team)}/transfer-ownership", json={"user_id": guest.id}, headers=ada.headers
    )
    assert to_guest.status_code == 409
    from_personal = await db_client.post(
        f"{ws(personal)}/transfer-ownership", json={"user_id": guest.id}, headers=ada.headers
    )
    assert from_personal.status_code == 409
