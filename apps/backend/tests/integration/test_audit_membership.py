"""People and settings changes are recorded in the workspace's audit log, with who did them."""
from httpx import AsyncClient

from pmagent_backend.modules.workspaces.models import Role


async def audit(client: AsyncClient, workspace_id: str, headers) -> list[dict]:
    res = await client.get(f"/v1/workspaces/{workspace_id}/audit", headers=headers)
    assert res.status_code == 200, res.text
    return list(reversed(res.json()))  # oldest first, easier to read


async def test_member_changes_are_audited(signup, create_team, add_member, db_client: AsyncClient) -> None:
    ada = await signup()
    bob = await signup(email="bob@example.com", name="Bob")
    team = await create_team(ada.headers)
    ws = f"/v1/workspaces/{team['id']}"
    await add_member(team["id"], bob.id, Role.MEMBER)

    assert (await db_client.patch(ws, json={"name": "Kunemi HQ"}, headers=ada.headers)).status_code == 200
    assert (await db_client.patch(f"{ws}/members/{bob.id}", json={"role": "admin"}, headers=ada.headers)).status_code == 200
    # Setting the same role again isn't a change.
    assert (await db_client.patch(f"{ws}/members/{bob.id}", json={"role": "admin"}, headers=ada.headers)).status_code == 200
    assert (
        await db_client.post(f"{ws}/transfer-ownership", json={"user_id": bob.id}, headers=ada.headers)
    ).status_code == 200
    assert (await db_client.delete(f"{ws}/members/{ada.id}", headers=ada.headers)).status_code == 204  # Ada leaves

    events = await audit(db_client, team["id"], bob.headers)
    summary = [(e["action"], e["target"], e["actor_user_id"]) for e in events]
    assert summary == [
        ("workspace.renamed", None, ada.id),
        ("member.role_changed", "bob@example.com", ada.id),
        ("workspace.ownership_transferred", "bob@example.com", ada.id),
        ("member.left", "ada@example.com", ada.id),
    ]
    assert events[0]["details"] == {"from": "Kunemi", "to": "Kunemi HQ"}
    assert events[1]["details"] == {"from": "member", "to": "admin", "user_id": bob.id}


async def test_removals_and_invites_are_audited(signup, create_team, add_member, db_client: AsyncClient) -> None:
    ada = await signup()
    bob = await signup(email="bob@example.com", name="Bob")
    carol = await signup(email="carol@example.com", name="Carol")
    team = await create_team(ada.headers)
    ws = f"/v1/workspaces/{team['id']}"
    await add_member(team["id"], bob.id, Role.MEMBER)

    assert (await db_client.delete(f"{ws}/members/{bob.id}", headers=ada.headers)).status_code == 204
    sent = await db_client.post(f"{ws}/invites", json={"email": "dan@example.com", "role": "guest"}, headers=ada.headers)
    assert sent.status_code == 201
    assert (await db_client.delete(f"{ws}/invites/{sent.json()['id']}", headers=ada.headers)).status_code == 204
    link = (await db_client.post(f"{ws}/invites/links", json={"role": "member", "max_uses": 3}, headers=ada.headers)).json()
    token = link["url"].split("token=")[1]
    assert (await db_client.post("/v1/invites/accept", json={"token": token}, headers=carol.headers)).status_code == 200

    events = await audit(db_client, team["id"], ada.headers)
    summary = [(e["action"], e["target"], e["actor_user_id"]) for e in events]
    assert summary == [
        ("member.removed", "bob@example.com", ada.id),
        ("invite.sent", "dan@example.com", ada.id),
        ("invite.revoked", "dan@example.com", ada.id),
        ("invite.link_created", None, ada.id),
        ("member.joined", "carol@example.com", carol.id),
    ]
    assert events[3]["details"] == {"role": "member", "max_uses": 3, "expires_in_days": 7}
    assert events[4]["details"] == {"role": "member", "via": "link invite"}
    # Tokens never reach the log.
    assert token not in str(events)


async def test_organisation_placements_land_in_the_workspace_log(
    signup, create_team, db_client: AsyncClient
) -> None:
    ada = await signup()
    bob = await signup(email="bob@example.com", name="Bob")
    team = await create_team(ada.headers)
    org = (await db_client.post("/v1/organizations", json={"name": "Kunemi Ltd"}, headers=ada.headers)).json()
    base = f"/v1/organizations/{org['id']}"
    assert (await db_client.post(f"{base}/workspaces/attach", json={"workspace_id": team["id"]}, headers=ada.headers)).status_code == 200
    assert (await db_client.post(f"{base}/members", json={"email": "bob@example.com"}, headers=ada.headers)).status_code == 201
    place = f"{base}/workspaces/{team['id']}/members/{bob.id}"
    assert (await db_client.put(place, json={"role": "member"}, headers=ada.headers)).status_code == 200
    assert (await db_client.put(place, json={"role": "guest"}, headers=ada.headers)).status_code == 200
    assert (await db_client.delete(place, headers=ada.headers)).status_code == 204

    events = await audit(db_client, team["id"], ada.headers)
    assert [(e["action"], e["target"]) for e in events] == [
        ("member.placed", "bob@example.com"),
        ("member.role_changed", "bob@example.com"),
        ("member.removed", "bob@example.com"),
    ]
    assert all(e["details"]["by_organization"] == org["id"] for e in events)
