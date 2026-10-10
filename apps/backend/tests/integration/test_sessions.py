"""Where you're signed in: browsers and the desktop app, each one signed out on its own."""
from httpx import AsyncClient

CHROME_MAC = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/140.0.0.0 Safari/537.36"
)
DESKTOP_MAC = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
    "dotrix/0.1.0 Chrome/138.0.0.0 Electron/37.2.0 Safari/537.36"
)


async def _login(db_client: AsyncClient, email: str, password: str, user_agent: str) -> dict:
    res = await db_client.post(
        "/v1/auth/login", json={"email": email, "password": password}, headers={"User-Agent": user_agent}
    )
    assert res.status_code == 200, res.text
    return res.json()


def _auth(tokens: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


async def test_sessions_are_listed_and_signed_out(signup, db_client: AsyncClient) -> None:
    ada = await signup()
    browser = await _login(db_client, ada.email, ada.password, CHROME_MAC)
    desktop = await _login(db_client, ada.email, ada.password, DESKTOP_MAC)

    listed = (await db_client.get("/v1/me/sessions", headers=_auth(browser))).json()
    # The one asking first; then the others, latest used first (sign-up made one too).
    assert [(s["client"], s["device"], s["current"]) for s in listed] == [
        ("web", "Chrome on macOS", True),
        ("desktop", "Desktop app on macOS", False),
        ("other", "Unknown app", False),
    ]
    assert listed[0]["ip"]

    # Refreshing keeps the same session.
    refreshed = (await db_client.post("/v1/auth/refresh", json={"refresh_token": desktop["refresh_token"]})).json()
    again = (await db_client.get("/v1/me/sessions", headers=_auth(refreshed))).json()
    assert len(again) == 3 and [s["device"] for s in again if s["current"]] == ["Desktop app on macOS"]

    # Sign the desktop app out from the browser: its access stops at once, and it can't refresh.
    desktop_id = listed[1]["id"]
    assert (await db_client.delete(f"/v1/me/sessions/{desktop_id}", headers=_auth(browser))).status_code == 204
    assert (await db_client.get("/v1/me", headers=_auth(refreshed))).status_code == 401
    gone = await db_client.post("/v1/auth/refresh", json={"refresh_token": refreshed["refresh_token"]})
    assert gone.status_code == 401
    assert (await db_client.delete(f"/v1/me/sessions/{desktop_id}", headers=_auth(browser))).status_code == 404

    # Everyone else: the sign-up session goes; the browser stays.
    res = await db_client.post("/v1/me/sessions/sign-out-others", headers=_auth(browser))
    assert res.json() == {"signed_out": 1}
    assert (await db_client.get("/v1/me", headers=ada.headers)).status_code == 401
    assert [s["device"] for s in (await db_client.get("/v1/me/sessions", headers=_auth(browser))).json()] == [
        "Chrome on macOS"
    ]

    # Signing out ends the session too.
    await db_client.post("/v1/auth/logout", json={"refresh_token": browser["refresh_token"]})
    assert (await db_client.get("/v1/me", headers=_auth(browser))).status_code == 401


async def test_only_your_own_sessions(signup, db_client: AsyncClient) -> None:
    ada = await signup()
    bob = await signup(email="bob@example.com")
    [bobs] = (await db_client.get("/v1/me/sessions", headers=bob.headers)).json()
    assert (await db_client.delete(f"/v1/me/sessions/{bobs['id']}", headers=ada.headers)).status_code == 404
    assert (await db_client.get("/v1/me", headers=bob.headers)).status_code == 200

    # API tokens (the CLI) can't sign browsers out.
    token = (await db_client.post("/v1/me/tokens", json={"name": "cli"}, headers=ada.headers)).json()
    cli = {"Authorization": f"Bearer {token['token']}"}
    [adas] = (await db_client.get("/v1/me/sessions", headers=cli)).json()
    assert not adas["current"]
    assert (await db_client.delete(f"/v1/me/sessions/{adas['id']}", headers=cli)).status_code == 403
    assert (await db_client.post("/v1/me/sessions/sign-out-others", headers=cli)).status_code == 403


async def test_change_password_signs_out_the_others(signup, db_client: AsyncClient) -> None:
    ada = await signup()
    browser = await _login(db_client, ada.email, ada.password, CHROME_MAC)

    wrong = await db_client.put(
        "/v1/me/password", json={"current_password": "not it", "new_password": "a brand new secret"},
        headers=_auth(browser),
    )
    assert wrong.status_code == 422 and wrong.json()["type"].endswith("/wrong_password")
    res = await db_client.put(
        "/v1/me/password", json={"current_password": ada.password, "new_password": "a brand new secret"},
        headers=_auth(browser),
    )
    assert res.json() == {"signed_out": 1}  # the sign-up's session; this browser stays
    assert (await db_client.get("/v1/me", headers=ada.headers)).status_code == 401
    assert (await db_client.get("/v1/me", headers=_auth(browser))).status_code == 200
    old = await db_client.post("/v1/auth/login", json={"email": ada.email, "password": ada.password})
    assert old.status_code == 401
    await _login(db_client, ada.email, "a brand new secret", CHROME_MAC)


async def test_set_a_first_password(db_client: AsyncClient, signup, db_session) -> None:
    from dotrix_backend.modules.auth.models import User

    ada = await signup()
    user = await db_session.get(User, __import__("uuid").UUID(ada.id))
    user.password_hash = None  # as if she'd signed up with GitHub or an email link
    await db_session.flush()
    res = await db_client.put("/v1/me/password", json={"new_password": "my first password"}, headers=ada.headers)
    assert res.status_code == 200, res.text
    methods = (await db_client.get("/v1/me/sign-in-methods", headers=ada.headers)).json()
    assert methods["password"] is True
