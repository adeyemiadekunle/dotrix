"""Calendar feeds (FR-32): a secret URL per person with their issue dates as iCalendar."""
from datetime import UTC, date, datetime, timedelta
from typing import Any

from httpx import AsyncClient

from dotrix_backend.core.middleware import loggable_path

TODAY = date.today()


def _feed_path(created: dict[str, Any]) -> str:
    # The URL is on the web app's address (http://app.test/v1/...), which forwards /v1 to the API.
    return created["url"].removeprefix("http://app.test")


async def _project(client: AsyncClient, headers: dict[str, str], ws: dict[str, Any], key: str = "KUN") -> str:
    res = await client.post(f"/v1/workspaces/{ws['id']}/projects", json={"key": key, "name": f"{key} project"}, headers=headers)
    assert res.status_code == 201, res.text
    return f"/v1/workspaces/{ws['id']}/projects/{res.json()['id']}"


async def _issue(client: AsyncClient, base: str, headers: dict[str, str], **fields: Any) -> dict[str, Any]:
    res = await client.post(f"{base}/issues", json={"type": "task", **fields}, headers=headers)
    assert res.status_code == 201, res.text
    return res.json()


async def _feed(client: AsyncClient, headers: dict[str, str], scope: str = "mine") -> str:
    res = await client.post("/v1/me/calendar", json={"scope": scope}, headers=headers)
    assert res.status_code == 201, res.text
    return _feed_path(res.json())


async def test_turning_the_feed_on_gives_a_secret_url(db_client: AsyncClient, signup, create_team) -> None:
    ada = await signup()
    assert (await db_client.get("/v1/me/calendar", headers=ada.headers)).status_code == 404
    team = await create_team(ada.headers)
    base = await _project(db_client, ada.headers, team)
    due = (TODAY + timedelta(days=3)).isoformat()
    await _issue(db_client, base, ada.headers, title="Ship the driver app", due=due, assignee_user_id=ada.id)
    scheduled = datetime.combine(TODAY + timedelta(days=1), datetime.min.time(), UTC).replace(hour=14)
    await _issue(db_client, base, ada.headers, title="Demo to Lagos ops", scheduled=scheduled.isoformat(), assignee_user_id=ada.id)
    await _issue(db_client, base, ada.headers, title="No date", assignee_user_id=ada.id)

    created = await db_client.post("/v1/me/calendar", json={}, headers=ada.headers)
    assert created.status_code == 201 and created.json()["scope"] == "mine"
    assert created.json()["url"].startswith("http://app.test/v1/calendar/") and created.json()["url"].endswith(".ics")
    settings = (await db_client.get("/v1/me/calendar", headers=ada.headers)).json()
    assert "url" not in settings and settings["last_used_at"] is None

    res = await db_client.get(_feed_path(created.json()))  # no Authorization: the URL is the secret
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/calendar")
    body = res.text
    assert body.startswith("BEGIN:VCALENDAR\r\n") and body.endswith("END:VCALENDAR\r\n")
    assert "SUMMARY:Due: KUN-1 Ship the driver app" in body
    assert f"DTSTART;VALUE=DATE:{(TODAY + timedelta(days=3)).strftime('%Y%m%d')}" in body
    assert f"DTSTART:{scheduled.strftime('%Y%m%dT%H%M%SZ')}" in body  # a one-hour slot
    assert "No date" not in body
    assert f"URL:http://app.test/w/{team['slug']}/p/KUN/board?issue=KUN-1" in body
    assert (await db_client.get("/v1/me/calendar", headers=ada.headers)).json()["last_used_at"] is not None
    # Calendar apps subscribed before the web app moved to Vite keep polling /api/v1/calendar/...
    old = await db_client.get("/api" + _feed_path(created.json()))
    assert old.status_code == 200 and old.text == body


async def test_mine_is_assigned_or_watched_and_all_is_every_dated_issue(
    db_client: AsyncClient, signup, create_team, add_member
) -> None:
    ada = await signup()
    bob = await signup(email="bob@example.com", name="Bob")
    team = await create_team(ada.headers)
    await add_member(team["id"], bob.id, "member")
    base = await _project(db_client, ada.headers, team)
    due = (TODAY + timedelta(days=2)).isoformat()
    await _issue(db_client, base, ada.headers, title="Bob's task", due=due, assignee_user_id=bob.id)
    watched = await _issue(db_client, base, ada.headers, title="Watched by Bob", due=due)
    await _issue(db_client, base, ada.headers, title="Someone else's", due=due)
    old = (TODAY - timedelta(days=200)).isoformat()
    await _issue(db_client, base, ada.headers, title="Long ago", due=old, assignee_user_id=bob.id)
    assert (await db_client.put(f"{base}/issues/{watched['key']}/watch", headers=bob.headers)).status_code in (200, 204)

    mine = (await db_client.get(await _feed(db_client, bob.headers))).text
    assert "Bob's task" in mine and "Watched by Bob" in mine
    assert "Someone else's" not in mine and "Long ago" not in mine

    everything = (await db_client.get(await _feed(db_client, bob.headers, scope="all"))).text
    assert all(title in everything for title in ("Bob's task", "Watched by Bob", "Someone else's"))
    assert "Long ago" not in everything  # more than 90 days back


async def test_a_new_url_replaces_the_old_and_off_means_off(db_client: AsyncClient, signup) -> None:
    ada = await signup()
    first = await _feed(db_client, ada.headers)
    second = await _feed(db_client, ada.headers)
    assert (await db_client.get(first)).status_code == 404
    assert (await db_client.get(second)).status_code == 200
    changed = await db_client.patch("/v1/me/calendar", json={"scope": "all"}, headers=ada.headers)
    assert changed.status_code == 200 and changed.json()["scope"] == "all"
    assert (await db_client.get(second)).status_code == 200  # same URL
    assert (await db_client.delete("/v1/me/calendar", headers=ada.headers)).status_code == 204
    assert (await db_client.get(second)).status_code == 404
    assert (await db_client.get("/v1/calendar/not-a-feed.ics")).status_code == 404
    assert (await db_client.get("/api/v1/calendar/not-a-feed.ics")).status_code == 404
    assert (await db_client.get("/v1/calendar/whatever")).status_code == 404


async def test_the_feed_only_shows_workspaces_you_can_see_now(
    db_client: AsyncClient, signup, create_team, add_member
) -> None:
    ada = await signup()
    bob = await signup(email="bob@example.com", name="Bob")
    mallory = await signup(email="mallory@example.com", name="Mallory")
    team = await create_team(ada.headers)
    await add_member(team["id"], bob.id, "member")
    base = await _project(db_client, ada.headers, team)
    await _issue(db_client, base, ada.headers, title="Kunemi launch", due=(TODAY + timedelta(days=5)).isoformat())

    assert "Kunemi launch" not in (await db_client.get(await _feed(db_client, mallory.headers, "all"))).text
    bobs = await _feed(db_client, bob.headers, "all")
    assert "Kunemi launch" in (await db_client.get(bobs)).text

    # Guests see no projects, so no issues either.
    ws = f"/v1/workspaces/{team['id']}"
    assert (await db_client.patch(f"{ws}/members/{bob.id}", json={"role": "guest"}, headers=ada.headers)).status_code == 200
    assert "Kunemi launch" not in (await db_client.get(bobs)).text
    # And once removed, nothing: checked on every fetch, not when the feed was made.
    assert (await db_client.patch(f"{ws}/members/{bob.id}", json={"role": "member"}, headers=ada.headers)).status_code == 200
    assert "Kunemi launch" in (await db_client.get(bobs)).text
    assert (await db_client.delete(f"{ws}/members/{bob.id}", headers=ada.headers)).status_code == 204
    assert "Kunemi launch" not in (await db_client.get(bobs)).text


async def test_api_tokens_cant_create_a_feed(db_client: AsyncClient, signup) -> None:
    ada = await signup()
    token = (await db_client.post("/v1/me/tokens", json={"name": "script"}, headers=ada.headers)).json()["token"]
    res = await db_client.post("/v1/me/calendar", json={}, headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 403


def test_feed_secrets_stay_out_of_the_access_log() -> None:
    assert loggable_path("/v1/calendar/abc123.ics") == "/v1/calendar/[secret]"
    assert loggable_path("/v1/me/calendar") == "/v1/me/calendar"
