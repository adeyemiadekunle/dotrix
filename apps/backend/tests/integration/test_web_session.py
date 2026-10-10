"""The web app's session (modules/web): httpOnly cookies, refreshing them, CSRF, GitHub redirects."""
import asyncio
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from httpx import AsyncClient

from dotrix_backend.core.settings import Settings
from dotrix_backend.modules.auth.github import GitHubOAuth, get_github
from dotrix_backend.modules.web.session import SharedRefresh

WEB = {"X-Requested-With": "dotrix-web"}
PASSWORD = "correct horse battery"


async def sign_up(client: AsyncClient, email: str = "ada@example.com") -> httpx.Response:
    res = await client.post(
        "/api/auth/signup", json={"email": email, "password": PASSWORD, "display_name": "Ada"}, headers=WEB
    )
    assert res.status_code == 201, res.text
    return res


def set_cookies(res: httpx.Response) -> dict[str, str]:
    """Each Set-Cookie header by cookie name (the whole header, attributes included). Where a
    response sets a cookie and deletes one of the same name at another path, the one it sets."""
    found: dict[str, str] = {}
    for header in res.headers.get_list("set-cookie"):
        name = header.split("=", 1)[0]
        if name not in found or "Max-Age=0" in found[name]:
            found[name] = header
    return found


async def test_signing_up_puts_the_session_into_httponly_cookies(db_client: AsyncClient) -> None:
    res = await sign_up(db_client)
    assert res.json()["email"] == "ada@example.com"
    assert "access_token" not in res.text and "refresh_token" not in res.text
    cookies = set_cookies(res)
    assert "HttpOnly" in cookies["dx_access"] and "Path=/;" in cookies["dx_access"] + ";"
    assert "HttpOnly" in cookies["dx_refresh"] and "Path=/api/auth" in cookies["dx_refresh"]
    assert "HttpOnly" not in cookies["dx_session"]  # only says someone is signed in
    assert "SameSite=lax" in cookies["dx_access"]
    # The API takes the access cookie, with no Authorization header.
    me = await db_client.get("/v1/me")
    assert me.status_code == 200 and me.json()["email"] == "ada@example.com"


async def test_signing_in_and_out(db_client: AsyncClient) -> None:
    await sign_up(db_client)
    db_client.cookies.clear()
    assert (await db_client.get("/v1/me")).status_code == 401
    wrong = await db_client.post("/api/auth/login", json={"email": "ada@example.com", "password": "nope"}, headers=WEB)
    assert wrong.status_code == 401 and "dx_access" not in set_cookies(wrong)
    res = await db_client.post("/api/auth/login", json={"email": "ada@example.com", "password": PASSWORD}, headers=WEB)
    assert res.status_code == 204
    assert (await db_client.get("/v1/me")).status_code == 200

    refresh_token = db_client.cookies.get("dx_refresh")
    out = await db_client.post("/api/auth/logout", headers=WEB)
    assert out.status_code == 204
    assert (await db_client.get("/v1/me")).status_code == 401
    # The session is revoked on the server too, not only forgotten by the browser.
    again = await db_client.post("/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert again.status_code == 401


async def test_changes_with_the_cookie_need_the_web_header(db_client: AsyncClient) -> None:
    await sign_up(db_client)
    forged = await db_client.post("/v1/workspaces", json={"name": "Forged"})
    assert forged.status_code == 403 and "X-Requested-With" in forged.json()["detail"]
    ok = await db_client.post("/v1/workspaces", json={"name": "Kunemi"}, headers=WEB)
    assert ok.status_code == 201, ok.text
    # Reading needs no header; a bearer token needs none either way.
    assert (await db_client.get("/v1/workspaces")).status_code == 200


async def test_session_routes_refuse_a_request_from_another_site(db_client: AsyncClient) -> None:
    res = await db_client.post("/api/auth/login", json={"email": "ada@example.com", "password": PASSWORD})
    assert res.status_code == 403
    await sign_up(db_client)
    assert (await db_client.post("/api/auth/logout")).status_code == 403
    assert (await db_client.get("/v1/me")).status_code == 200  # still signed in


async def test_a_bearer_token_works_without_the_header(db_client: AsyncClient, signup: Callable[..., Any]) -> None:
    ada = await signup()
    db_client.cookies.clear()
    res = await db_client.post("/v1/workspaces", json={"name": "Kunemi"}, headers=ada.headers)
    assert res.status_code == 201


async def test_refresh_rotates_the_cookies(db_client: AsyncClient) -> None:
    await sign_up(db_client)
    before = db_client.cookies.get("dx_refresh")
    res = await db_client.post("/api/auth/refresh", headers=WEB)
    assert res.status_code == 204
    after = db_client.cookies.get("dx_refresh")
    assert after and after != before
    assert (await db_client.get("/v1/me")).status_code == 200


async def test_a_session_that_cant_refresh_is_cleared(db_client: AsyncClient) -> None:
    res = await db_client.post("/api/auth/refresh", headers=WEB)
    assert res.status_code == 401
    db_client.cookies.set("dx_refresh", "not-a-real-token", domain="test", path="/api/auth")
    res = await db_client.post("/api/auth/refresh", headers=WEB)
    assert res.status_code == 401
    cleared = set_cookies(res)
    assert 'dx_access=""' in cleared["dx_access"] and "Max-Age=0" in cleared["dx_access"]


async def test_requests_refreshing_at_once_share_one_refresh() -> None:
    shared = SharedRefresh()
    calls = 0

    async def do(token: str) -> Any:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.01)
        return f"pair-for-{token}"

    results = await asyncio.gather(*(shared.refresh("r1", do) for _ in range(5)))
    assert calls == 1 and set(results) == {"pair-for-r1"}
    # Remembered briefly: a request that was in flight with the old cookie gets the same pair.
    assert await shared.refresh("r1", do) == "pair-for-r1" and calls == 1


async def test_magic_link_and_sign_up_link_sign_in(
    db_client: AsyncClient, email_token: Callable[[str], str]
) -> None:
    await db_client.post("/v1/auth/magic-link/request", json={"email": "new@example.com"})
    res = await db_client.post(
        "/api/auth/signup-link", json={"token": email_token("/signup/finish"), "display_name": "Grace"}, headers=WEB
    )
    assert res.status_code == 201 and res.json()["display_name"] == "Grace"
    assert (await db_client.get("/v1/me")).json()["email"] == "new@example.com"

    db_client.cookies.clear()
    await db_client.post("/v1/auth/magic-link/request", json={"email": "new@example.com"})
    res = await db_client.post("/api/auth/magic-link", json={"token": email_token("/magic-link")}, headers=WEB)
    assert res.status_code == 204
    assert (await db_client.get("/v1/me")).json()["email"] == "new@example.com"


# -- GitHub --------------------------------------------------------------------------------


class FakeGitHub:
    def __init__(self) -> None:
        self.codes = {"good-code"}

    def handle(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/login/oauth/access_token":
            code = parse_qs(request.content.decode())["code"][0]
            if code not in self.codes:
                return httpx.Response(200, json={"error": "bad_verification_code"})
            self.codes.discard(code)
            return httpx.Response(200, json={"access_token": "gho_test", "token_type": "bearer"})
        if request.url.path == "/user":
            return httpx.Response(200, json={"id": 4242, "login": "ada-l", "name": "Ada Lovelace"})
        if request.url.path == "/user/emails":
            return httpx.Response(200, json=[{"email": "ada@example.com", "primary": True, "verified": True}])
        return httpx.Response(404)


@pytest.fixture
def github(db_client: AsyncClient) -> FakeGitHub:
    fake = FakeGitHub()
    settings = Settings(
        database_url="postgresql+asyncpg://localhost/unused",
        jwt_secret="test-only-jwt-secret-not-used-anywhere-else",  # type: ignore[arg-type]
        github_client_id="gh-client",
        github_client_secret="gh-secret",  # type: ignore[arg-type]
    )
    app = db_client._transport.app  # type: ignore[attr-defined]
    app.dependency_overrides[get_github] = lambda: GitHubOAuth(settings, transport=httpx.MockTransport(fake.handle))
    return fake


async def start(db_client: AsyncClient, query: str = "next=/w/x") -> str:
    """Begin a GitHub sign-in; the `state` GitHub would send back."""
    res = await db_client.get(f"/api/auth/github?{query}")
    assert res.status_code == 303
    location = urlparse(res.headers["location"])
    assert location.netloc == "github.com"
    assert "HttpOnly" in set_cookies(res)["pm_github_state"]
    return parse_qs(location.query)["state"][0]


async def test_github_sign_in_sets_the_session(db_client: AsyncClient, github: FakeGitHub) -> None:
    state = await start(db_client)
    res = await db_client.get(f"/api/auth/github/callback?code=good-code&state={state}")
    assert res.status_code == 303 and res.headers["location"] == "/w/x"
    assert "dx_access" in set_cookies(res)
    assert (await db_client.get("/v1/me")).json()["email"] == "ada@example.com"


async def test_github_sign_in_refuses_another_browsers_state(db_client: AsyncClient, github: FakeGitHub) -> None:
    await start(db_client)
    res = await db_client.get("/api/auth/github/callback?code=good-code&state=forged")
    assert res.status_code == 303
    location = urlparse(res.headers["location"])
    assert location.path == "/login" and "another browser" in parse_qs(location.query)["error"][0]
    assert (await db_client.get("/v1/me")).status_code == 401


async def test_github_unavailable_goes_back_to_sign_in(db_client: AsyncClient) -> None:
    res = await db_client.get("/api/auth/github?next=/w/x")
    location = urlparse(res.headers["location"])
    assert location.path == "/login" and parse_qs(location.query)["next"] == ["/w/x"]


async def test_linking_github_from_settings(db_client: AsyncClient, github: FakeGitHub) -> None:
    await sign_up(db_client, email="someone@example.com")
    state = await start(db_client, "link=1&next=/w/x/settings/profile")
    res = await db_client.get(f"/api/auth/github/callback?code=good-code&state={state}")
    assert res.headers["location"] == "/w/x/settings/profile?github=linked"
    methods = (await db_client.get("/v1/me/sign-in-methods")).json()
    assert [(a["provider"], a["login"]) for a in methods["accounts"]] == [("github", "ada-l")]


async def test_linking_github_needs_a_session(db_client: AsyncClient, github: FakeGitHub) -> None:
    state = await start(db_client, "link=1&next=/w/x/settings/profile")
    res = await db_client.get(f"/api/auth/github/callback?code=good-code&state={state}")
    location = urlparse(res.headers["location"])
    assert location.path == "/w/x/settings/profile" and "github_error" in parse_qs(location.query)


async def test_installing_the_app_checks_the_state_and_the_install_link(db_client: AsyncClient) -> None:
    forged = await db_client.get("/api/github/setup?installation_id=1&setup_action=install&state=forged")
    assert forged.status_code == 303 and "github_error" in forged.headers["location"]
    bad = await db_client.get("/api/github/install?workspace=x&install_url=https://evil.example/apps/x/installations/new")
    assert "github_error" in bad.headers["location"] and "evil" not in bad.headers["location"]

    workspace = "0190f5b8-0000-7000-8000-000000000001"
    url = "https://github.com/apps/dotrix/installations/new"
    res = await db_client.get(f"/api/github/install?workspace={workspace}&install_url={url}&next=/w/x/settings/github")
    location = urlparse(res.headers["location"])
    assert f"{location.scheme}://{location.netloc}{location.path}" == url
    state = parse_qs(location.query)["state"][0]
    setup = await db_client.get(f"/api/github/setup?installation_id=77&setup_action=install&state={state}")
    location = urlparse(setup.headers["location"])
    assert location.path == "/api/auth/github"
    assert parse_qs(location.query) == {"install": [f"{workspace}:77"], "next": ["/w/x/settings/github"]}
