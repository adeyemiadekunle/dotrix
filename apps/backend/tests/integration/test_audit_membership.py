"""People and settings changes are recorded in the workspace's audit log, with who did them."""
from httpx import AsyncClient

from dotrix_backend.modules.workspaces.models import Role


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


async def test_turning_personal_into_an_organisation_is_audited(signup, db_client: AsyncClient) -> None:
    ada = await signup()
    personal = (await db_client.get("/v1/workspaces", headers=ada.headers)).json()[0]
    res = await db_client.post(
        f"/v1/workspaces/{personal['id']}/convert-to-organization", json={"name": "Kunemi"}, headers=ada.headers
    )
    assert res.status_code == 200
    events = await audit(db_client, personal["id"], ada.headers)
    assert [(e["action"], e["details"]) for e in events] == [
        ("workspace.converted_to_organization", {"from": "Personal", "to": "Kunemi"})
    ]
