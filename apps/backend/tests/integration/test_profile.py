"""Your profile: name, what you do, photo, sign-in methods; and what colleagues see of it."""
import uuid
from datetime import UTC, datetime

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from dotrix_backend.modules.auth.models import OAuthAccount, User
from dotrix_backend.modules.workspaces.models import Role

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


async def test_change_your_name_and_what_you_do(signup, db_client: AsyncClient) -> None:
    ada = await signup()
    res = await db_client.patch("/v1/me", json={"display_name": " Ada L. ", "title": "Product designer"}, headers=ada.headers)
    assert res.status_code == 200
    assert (res.json()["display_name"], res.json()["title"]) == ("Ada L.", "Product designer")

    # Leaving a field out keeps it; an empty title clears it; an empty name is refused.
    res = await db_client.patch("/v1/me", json={"title": ""}, headers=ada.headers)
    assert (res.json()["display_name"], res.json()["title"]) == ("Ada L.", None)
    assert (await db_client.patch("/v1/me", json={"display_name": "  "}, headers=ada.headers)).status_code == 422
    assert (await db_client.patch("/v1/me", json={"title": "x" * 101}, headers=ada.headers)).status_code == 422
    assert (await db_client.get("/v1/me", headers=ada.headers)).json()["display_name"] == "Ada L."


async def test_a_photo_is_set_served_and_removed(signup, db_client: AsyncClient) -> None:
    ada = await signup()
    assert (await db_client.get("/v1/me", headers=ada.headers)).json()["avatar_updated_at"] is None
    assert (await db_client.get("/v1/me/avatar", headers=ada.headers)).status_code == 404

    res = await db_client.put("/v1/me/avatar", files={"file": ("me.png", PNG, "image/png")}, headers=ada.headers)
    assert res.status_code == 200 and res.json()["avatar_updated_at"] is not None
    photo = await db_client.get("/v1/me/avatar", headers=ada.headers)
    assert photo.status_code == 200 and photo.content == PNG
    assert photo.headers["content-type"] == "image/png"

    removed = await db_client.delete("/v1/me/avatar", headers=ada.headers)
    assert removed.status_code == 200 and removed.json()["avatar_updated_at"] is None
    assert (await db_client.get("/v1/me/avatar", headers=ada.headers)).status_code == 404


async def test_only_small_real_images_are_photos(signup, db_client: AsyncClient) -> None:
    ada = await signup()

    async def put(content: bytes, content_type: str) -> int:
        res = await db_client.put("/v1/me/avatar", files={"file": ("f", content, content_type)}, headers=ada.headers)
        return res.status_code

    assert await put(b"<svg onload=alert(1)>", "image/svg+xml") == 422
    assert await put(b"<html>", "image/png") == 422  # says PNG, isn't
    assert await put(b"\x89PNG\r\n\x1a\n" + b"\x00" * 600_000, "image/png") == 422
    assert await put(b"\xff\xd8\xff" + b"\x00" * 10, "image/jpeg") == 200


async def test_sign_in_methods_and_unlinking_github(signup, db_client: AsyncClient, db_session: AsyncSession) -> None:
    ada = await signup()
    methods = (await db_client.get("/v1/me/sign-in-methods", headers=ada.headers)).json()
    assert methods == {"password": True, "email_link": True, "accounts": []}
    assert (await db_client.delete("/v1/me/sign-in-methods/github", headers=ada.headers)).status_code == 404

    db_session.add(
        OAuthAccount(
            user_id=uuid.UUID(ada.id), provider="github", provider_user_id="42", login="ada-l", created_at=datetime.now(UTC)
        )
    )
    await db_session.commit()
    methods = (await db_client.get("/v1/me/sign-in-methods", headers=ada.headers)).json()
    assert [(a["provider"], a["login"]) for a in methods["accounts"]] == [("github", "ada-l")]

    assert (await db_client.delete("/v1/me/sign-in-methods/github", headers=ada.headers)).status_code == 204
    assert (await db_client.get("/v1/me/sign-in-methods", headers=ada.headers)).json()["accounts"] == []


async def test_github_cant_be_unlinked_without_a_password(
    signup, db_client: AsyncClient, db_session: AsyncSession
) -> None:
    ada = await signup()
    user = await db_session.get(User, uuid.UUID(ada.id))
    assert user is not None
    user.password_hash = None
    db_session.add(
        OAuthAccount(user_id=user.id, provider="github", provider_user_id="42", login="ada-l", created_at=datetime.now(UTC))
    )
    await db_session.commit()
    res = await db_client.delete("/v1/me/sign-in-methods/github", headers=ada.headers)
    assert res.status_code == 409
    assert (await db_client.get("/v1/me/sign-in-methods", headers=ada.headers)).json()["password"] is False


async def test_members_show_what_they_do_their_photo_and_the_projects_they_see(
    signup, create_team, add_member, db_client: AsyncClient
) -> None:
    ada = await signup()
    bob = await signup(email="bob@example.com", name="Bob")
    gus = await signup(email="gus@example.com", name="Gus")
    team = await create_team(ada.headers)
    ws = f"/v1/workspaces/{team['id']}"
    await add_member(team["id"], bob.id, Role.MEMBER)
    await add_member(team["id"], gus.id, Role.GUEST)
    await db_client.patch("/v1/me", json={"title": "Founder"}, headers=ada.headers)
    await db_client.put("/v1/me/avatar", files={"file": ("me.png", PNG, "image/png")}, headers=ada.headers)

    open_ = (await db_client.post(f"{ws}/projects", json={"key": "OPN", "name": "Open"}, headers=ada.headers)).json()
    secret = (await db_client.post(f"{ws}/projects", json={"key": "SEC", "name": "Secret"}, headers=ada.headers)).json()
    await db_client.patch(f"{ws}/projects/{secret['id']}", json={"access": "restricted"}, headers=ada.headers)

    def by_email(members: list[dict]) -> dict[str, dict]:
        return {m["email"]: m for m in members}

    seen_by_ada = by_email((await db_client.get(f"{ws}/members", headers=ada.headers)).json())
    assert seen_by_ada["ada@example.com"]["title"] == "Founder"
    assert seen_by_ada["ada@example.com"]["avatar_updated_at"] is not None
    assert seen_by_ada["ada@example.com"]["sees_all_projects"] is True
    assert set(seen_by_ada["ada@example.com"]["project_ids"]) == {open_["id"], secret["id"]}
    assert seen_by_ada["bob@example.com"]["project_ids"] == [open_["id"]]
    assert seen_by_ada["gus@example.com"]["project_ids"] == []

    # Bob sees only what he can see, even about Ada: the restricted project stays hidden.
    seen_by_bob = by_email((await db_client.get(f"{ws}/members", headers=bob.headers)).json())
    assert seen_by_bob["ada@example.com"]["project_ids"] == [open_["id"]]

    # Added to it, Bob sees it in his own list.
    await db_client.put(f"{ws}/projects/{secret['id']}/members/{bob.id}", headers=ada.headers)
    seen_by_bob = by_email((await db_client.get(f"{ws}/members", headers=bob.headers)).json())
    assert set(seen_by_bob["bob@example.com"]["project_ids"]) == {open_["id"], secret["id"]}

    # Colleagues' photos, only within the workspace.
    photo = await db_client.get(f"{ws}/members/{ada.id}/avatar", headers=bob.headers)
    assert photo.status_code == 200 and photo.content == PNG
    assert (await db_client.get(f"{ws}/members/{bob.id}/avatar", headers=ada.headers)).status_code == 404
    stranger = await signup(email="eve@example.com", name="Eve")
    assert (await db_client.get(f"{ws}/members/{ada.id}/avatar", headers=stranger.headers)).status_code == 404
