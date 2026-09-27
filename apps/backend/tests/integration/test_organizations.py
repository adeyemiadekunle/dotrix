"""Organisations own several workspaces and manage people across them, but an org admin
never sees inside a workspace unless they're a member of it."""
import pytest
from httpx import AsyncClient

ORGS = "/v1/organizations"


@pytest.fixture
def org(db_client: AsyncClient, signup):
    """Ada owns the organisation "Acme"."""

    async def _make():
        ada = await signup()
        created = (await db_client.post(ORGS, json={"name": "Acme Logistics"}, headers=ada.headers)).json()
        return ada, created

    return _make


async def add(db_client: AsyncClient, org: dict, headers, email: str, role: str = "member"):
    return await db_client.post(f"{ORGS}/{org['id']}/members", json={"email": email, "role": role}, headers=headers)


async def test_create_and_list(org, db_client: AsyncClient) -> None:
    ada, acme = await org()
    assert acme["role"] == "owner" and acme["slug"].startswith("acme-logistics-")
    listed = (await db_client.get(ORGS, headers=ada.headers)).json()
    assert [(o["name"], o["role"]) for o in listed] == [("Acme Logistics", "owner")]


async def test_people(org, db_client: AsyncClient, signup) -> None:
    ada, acme = await org()
    bob = await signup(email="bob@example.com", name="Bob")
    cy = await signup(email="cy@example.com", name="Cy")
    assert (await add(db_client, acme, ada.headers, "BOB@example.com", "admin")).status_code == 201
    assert (await add(db_client, acme, ada.headers, "nobody@example.com")).status_code == 404  # no account yet
    assert (await add(db_client, acme, ada.headers, "bob@example.com")).status_code == 409  # already in
    # Admins add people, but only owners add owners.
    assert (await add(db_client, acme, bob.headers, "cy@example.com", "owner")).status_code == 403
    assert (await add(db_client, acme, bob.headers, "cy@example.com")).status_code == 201
    # Members can't manage people; outsiders can't even see the organisation.
    eve = await signup(email="eve@example.com", name="Eve")
    assert (await add(db_client, acme, cy.headers, "eve@example.com")).status_code == 403
    assert (await db_client.get(f"{ORGS}/{acme['id']}", headers=eve.headers)).status_code == 404
    members = (await db_client.get(f"{ORGS}/{acme['id']}/members", headers=cy.headers)).json()
    assert {(m["email"], m["role"]) for m in members} == {
        ("ada@example.com", "owner"), ("bob@example.com", "admin"), ("cy@example.com", "member")
    }


async def test_organisation_keeps_an_owner(org, db_client: AsyncClient) -> None:
    ada, acme = await org()
    res = await db_client.patch(f"{ORGS}/{acme['id']}/members/{ada.id}", json={"role": "admin"}, headers=ada.headers)
    assert res.status_code == 409
    assert (await db_client.delete(f"{ORGS}/{acme['id']}/members/{ada.id}", headers=ada.headers)).status_code == 409


async def test_org_admin_manages_but_does_not_see(org, db_client: AsyncClient, signup) -> None:
    ada, acme = await org()
    bob = await signup(email="bob@example.com", name="Bob")  # org admin
    fe = await signup(email="fe@example.com", name="Frontend Dev")
    for person, role in ((bob, "admin"), (fe, "member")):
        await add(db_client, acme, ada.headers, person.email, role)

    # Ada creates a division workspace, owned by herself, with a project in it.
    ws = (await db_client.post(f"{ORGS}/{acme['id']}/workspaces", json={"name": "Kunemi"}, headers=ada.headers)).json()
    assert ws["your_role"] == "owner" and ws["kind"] == "business"
    await db_client.post(f"/v1/workspaces/{ws['id']}/projects", json={"key": "KUN", "name": "Kunemi"}, headers=ada.headers)

    # Bob (org admin) sees the workspace's name and size...
    seen = {w["name"]: w for w in (await db_client.get(f"{ORGS}/{acme['id']}/workspaces", headers=bob.headers)).json()}
    assert seen["Kunemi"]["projects"] == 1 and seen["Kunemi"]["your_role"] is None
    # ...but not its content: he isn't in the workspace.
    assert (await db_client.get(f"/v1/workspaces/{ws['id']}/projects", headers=bob.headers)).status_code == 404
    assert (await db_client.get(f"/v1/workspaces/{ws['id']}", headers=bob.headers)).status_code == 404

    # He can place people into it without joining it himself.
    placed = await db_client.put(
        f"{ORGS}/{acme['id']}/workspaces/{ws['id']}/members/{fe.id}", json={"role": "member"}, headers=bob.headers
    )
    assert placed.status_code == 200 and {m["email"] for m in placed.json()} == {"ada@example.com", "fe@example.com"}
    assert [p["key"] for p in (await db_client.get(f"/v1/workspaces/{ws['id']}/projects", headers=fe.headers)).json()] == ["KUN"]
    assert (await db_client.get(f"/v1/workspaces/{ws['id']}/projects", headers=bob.headers)).status_code == 404

    # Members of the organisation only see the workspaces they're in.
    fe_view = (await db_client.get(f"{ORGS}/{acme['id']}/workspaces", headers=fe.headers)).json()
    assert [w["name"] for w in fe_view] == ["Kunemi"]


async def test_workspace_owner_is_changed_in_the_workspace_not_by_the_org(org, db_client: AsyncClient, signup) -> None:
    ada, acme = await org()
    bob = await signup(email="bob@example.com", name="Bob")
    await add(db_client, acme, ada.headers, bob.email, "admin")
    ws = (await db_client.post(f"{ORGS}/{acme['id']}/workspaces", json={"name": "Kunemi", "owner_user_id": ada.id},
                               headers=bob.headers)).json()
    url = f"{ORGS}/{acme['id']}/workspaces/{ws['id']}/members/{ada.id}"
    assert (await db_client.put(url, json={"role": "member"}, headers=bob.headers)).status_code == 409
    assert (await db_client.delete(url, headers=bob.headers)).status_code == 409
    owner_placement = await db_client.put(url, json={"role": "owner"}, headers=bob.headers)
    assert owner_placement.status_code == 422


async def test_attach_an_existing_workspace(org, db_client: AsyncClient, signup, create_team, add_member) -> None:
    from pmagent_backend.modules.workspaces.models import Role

    ada, acme = await org()
    dev = await signup(email="dev@example.com", name="Dev")
    team = await create_team(ada.headers, "Kumove")
    await add_member(team["id"], dev.id, Role.MEMBER)
    personal = (await db_client.get("/v1/workspaces", headers=ada.headers)).json()[0]

    res = await db_client.post(f"{ORGS}/{acme['id']}/workspaces/attach", json={"workspace_id": team["id"]}, headers=ada.headers)
    assert res.status_code == 200 and res.json()["name"] == "Kumove"
    # Its people joined the organisation.
    emails = {m["email"] for m in (await db_client.get(f"{ORGS}/{acme['id']}/members", headers=ada.headers)).json()}
    assert emails == {"ada@example.com", "dev@example.com"}
    workspace = (await db_client.get(f"/v1/workspaces/{team['id']}", headers=ada.headers)).json()
    assert workspace["organization_id"] == acme["id"]

    again = await db_client.post(f"{ORGS}/{acme['id']}/workspaces/attach", json={"workspace_id": team["id"]}, headers=ada.headers)
    assert again.status_code == 409
    mine = await db_client.post(f"{ORGS}/{acme['id']}/workspaces/attach", json={"workspace_id": personal["id"]}, headers=ada.headers)
    assert mine.status_code == 409  # personal workspaces stay personal


async def test_only_the_workspace_owner_can_attach_it(org, db_client: AsyncClient, signup, create_team) -> None:
    ada, acme = await org()
    bob = await signup(email="bob@example.com", name="Bob")
    await add(db_client, acme, ada.headers, bob.email, "admin")
    bobs_team = await create_team(bob.headers, "Bob's team")
    adas_view = await db_client.post(f"{ORGS}/{acme['id']}/workspaces/attach", json={"workspace_id": bobs_team["id"]},
                                     headers=ada.headers)
    assert adas_view.status_code == 404  # Ada isn't in it
    assert (await db_client.post(f"{ORGS}/{acme['id']}/workspaces/attach", json={"workspace_id": bobs_team["id"]},
                                 headers=bob.headers)).status_code == 200


async def test_leaving_the_org_leaves_its_workspaces(org, db_client: AsyncClient, signup) -> None:
    ada, acme = await org()
    fe = await signup(email="fe@example.com", name="Frontend Dev")
    await add(db_client, acme, ada.headers, fe.email)
    ws = (await db_client.post(f"{ORGS}/{acme['id']}/workspaces", json={"name": "Kunemi"}, headers=ada.headers)).json()
    await db_client.put(f"{ORGS}/{acme['id']}/workspaces/{ws['id']}/members/{fe.id}", json={"role": "member"}, headers=ada.headers)
    assert (await db_client.get(f"/v1/workspaces/{ws['id']}", headers=fe.headers)).status_code == 200

    assert (await db_client.delete(f"{ORGS}/{acme['id']}/members/{fe.id}", headers=ada.headers)).status_code == 204
    assert (await db_client.get(f"/v1/workspaces/{ws['id']}", headers=fe.headers)).status_code == 404


async def test_workspace_owners_must_hand_over_before_leaving(org, db_client: AsyncClient, signup) -> None:
    ada, acme = await org()
    bob = await signup(email="bob@example.com", name="Bob")
    await add(db_client, acme, ada.headers, bob.email)
    await db_client.post(f"{ORGS}/{acme['id']}/workspaces", json={"name": "Bob's", "owner_user_id": bob.id}, headers=ada.headers)
    res = await db_client.delete(f"{ORGS}/{acme['id']}/members/{bob.id}", headers=ada.headers)
    assert res.status_code == 409 and "transfer ownership" in res.json()["detail"]


async def test_invite_into_an_org_workspace_joins_the_org(org, db_client: AsyncClient, signup, email_token) -> None:
    ada, acme = await org()
    ws = (await db_client.post(f"{ORGS}/{acme['id']}/workspaces", json={"name": "Kunemi"}, headers=ada.headers)).json()
    await db_client.post(f"/v1/workspaces/{ws['id']}/invites", json={"email": "new@example.com"}, headers=ada.headers)
    newbie = await signup(email="new@example.com", name="New")
    await db_client.post("/v1/invites/accept", json={"token": email_token("/invites/accept")}, headers=newbie.headers)
    orgs = (await db_client.get(ORGS, headers=newbie.headers)).json()
    assert [(o["name"], o["role"]) for o in orgs] == [("Acme Logistics", "member")]


async def test_organisations_are_isolated(org, db_client: AsyncClient, signup) -> None:
    ada, acme = await org()
    zed = await signup(email="zed@example.com", name="Zed")
    other = (await db_client.post(ORGS, json={"name": "Other Co"}, headers=zed.headers)).json()
    acme_ws = (await db_client.post(f"{ORGS}/{acme['id']}/workspaces", json={"name": "Kunemi"}, headers=ada.headers)).json()
    # Zed runs another organisation: he can't see or manage Acme's workspaces through his own.
    assert (await db_client.get(f"{ORGS}/{acme['id']}/workspaces", headers=zed.headers)).status_code == 404
    res = await db_client.get(f"{ORGS}/{other['id']}/workspaces/{acme_ws['id']}/members", headers=zed.headers)
    assert res.status_code == 404
