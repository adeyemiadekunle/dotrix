"""Sign in with GitHub: the API trades GitHub's code for the account, then links or creates ours.
GitHub itself is faked with an httpx MockTransport."""
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from httpx import AsyncClient

from pmagent_backend.core.settings import Settings
from pmagent_backend.modules.auth.github import GitHubOAuth, get_github


class FakeGitHub:
    """GitHub's token endpoint and API, for one account."""

    def __init__(self) -> None:
        self.user: dict[str, Any] = {"id": 4242, "login": "ada-l", "name": "Ada Lovelace"}
        self.emails: list[dict[str, Any]] = [{"email": "Ada@Example.com", "primary": True, "verified": True}]
        self.codes = {"good-code"}
        self.emails_status = 200

    def handle(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/login/oauth/access_token":
            form = parse_qs(request.content.decode())
            assert form["client_id"] == ["gh-client"] and form["client_secret"] == ["gh-secret"]
            code = form["code"][0]
            if code not in self.codes:
                return httpx.Response(200, json={"error": "bad_verification_code"})
            self.codes.discard(code)  # a code works once
            return httpx.Response(200, json={"access_token": "gho_test", "token_type": "bearer"})
        assert request.headers["Authorization"] == "Bearer gho_test"
        if request.url.path == "/user":
            return httpx.Response(200, json=self.user)
        if request.url.path == "/user/emails":
            return httpx.Response(self.emails_status, json=self.emails if self.emails_status == 200 else {})
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


async def finish(db_client: AsyncClient, code: str = "good-code") -> httpx.Response:
    return await db_client.post("/v1/auth/oauth/github/finish", json={"code": code})


async def me(db_client: AsyncClient, res: httpx.Response) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {res.json()['access_token']}"}
    return (await db_client.get("/v1/me", headers=headers)).json()


async def test_not_offered_until_configured(db_client: AsyncClient) -> None:
    assert (await db_client.get("/v1/auth/providers")).json() == {"github": False}
    res = await db_client.post("/v1/auth/oauth/github/start")
    assert res.status_code == 503 and "PMAGENT_GITHUB_CLIENT_ID" in res.json()["detail"]


async def test_start_gives_the_authorize_url_and_state(db_client: AsyncClient, github: FakeGitHub) -> None:
    assert (await db_client.get("/v1/auth/providers")).json() == {"github": True}
    body = (await db_client.post("/v1/auth/oauth/github/start")).json()
    url = urlparse(body["authorize_url"])
    query = parse_qs(url.query)
    assert url.netloc == "github.com" and url.path == "/login/oauth/authorize"
    assert query["client_id"] == ["gh-client"] and query["state"] == [body["state"]]
    assert "redirect_uri" not in query  # GitHub uses the app's registered callback
    assert "gh-secret" not in body["authorize_url"]


async def test_a_new_person_gets_an_account(db_client: AsyncClient, github: FakeGitHub) -> None:
    res = await finish(db_client)
    assert res.status_code == 200, res.text
    user = await me(db_client, res)
    assert user["email"] == "ada@example.com" and user["display_name"] == "Ada Lovelace"
    assert user["email_verified"] is True
    headers = {"Authorization": f"Bearer {res.json()['access_token']}"}
    workspaces = (await db_client.get("/v1/workspaces", headers=headers)).json()
    assert [w["kind"] for w in workspaces] == ["personal"]

    # Next time the same GitHub account signs in to the same account, even with a new email there.
    github.codes.add("second-code")
    github.emails = [{"email": "ada@new.example", "primary": True, "verified": True}]
    again = await finish(db_client, "second-code")
    assert again.status_code == 200 and (await me(db_client, again))["id"] == user["id"]


async def test_links_an_existing_account_by_verified_email(db_client: AsyncClient, signup, github: FakeGitHub) -> None:
    ada = await signup()
    assert ada.user["email_verified"] is False
    res = await finish(db_client)
    assert res.status_code == 200
    user = await me(db_client, res)
    assert user["id"] == ada.id and user["email_verified"] is True
    # The password still works too.
    login = await db_client.post("/v1/auth/login", json={"email": ada.email, "password": ada.password})
    assert login.status_code == 200


async def test_unverified_emails_never_link(db_client: AsyncClient, signup, github: FakeGitHub) -> None:
    await signup()
    github.emails = [
        {"email": "ada@example.com", "primary": True, "verified": False},
        {"email": "ada-l@users.noreply.github.com", "primary": False, "verified": True},
    ]
    res = await finish(db_client)
    # Only the private relay address is verified: a new account on it, not Ada's.
    assert res.status_code == 200
    assert (await me(db_client, res))["email"] == "ada-l@users.noreply.github.com"

    github.user = {"id": 7, "login": "mallory", "name": None}
    github.emails = [{"email": "ada@example.com", "primary": True, "verified": False}]
    github.codes.add("other-code")
    refused = await finish(db_client, "other-code")
    assert refused.status_code == 401 and "no verified email" in refused.json()["detail"]


async def test_a_bad_or_used_code_is_refused(db_client: AsyncClient, github: FakeGitHub) -> None:
    assert (await finish(db_client)).status_code == 200
    assert (await finish(db_client)).status_code == 401
    assert (await finish(db_client, "made-up")).status_code == 401


async def test_missing_email_permission_is_explained(db_client: AsyncClient, github: FakeGitHub) -> None:
    github.emails_status = 403
    res = await finish(db_client)
    assert res.status_code == 503 and "Email addresses" in res.json()["detail"]


async def test_the_api_callback_forwards_to_the_web_app(db_client: AsyncClient) -> None:
    res = await db_client.get("/v1/auth/oauth/github/callback?code=abc&state=xyz&other=1")
    assert res.status_code == 303
    assert res.headers["location"] == "http://app.test/api/auth/github/callback?code=abc&state=xyz"


async def test_link_github_from_settings(db_client: AsyncClient, signup, github: FakeGitHub) -> None:
    # Signed in, so GitHub's email needn't match: Bob links Ada-the-GitHub-login's account.
    bob = await signup(email="bob@example.com", name="Bob")
    github.codes |= {"link-code", "again-code", "other-code"}
    res = await db_client.put("/v1/me/sign-in-methods/github", json={"code": "link-code"}, headers=bob.headers)
    assert res.status_code == 200, res.text
    assert [a["login"] for a in res.json()["accounts"]] == ["ada-l"]
    # From now on, that GitHub account signs in as Bob.
    assert (await me(db_client, await finish(db_client)))["email"] == "bob@example.com"
    # Linking it again is fine; a second GitHub account isn't.
    assert (await db_client.put("/v1/me/sign-in-methods/github", json={"code": "again-code"}, headers=bob.headers)).status_code == 200
    github.user = {"id": 777, "login": "bob-gh", "name": "Bob"}
    second = await db_client.put("/v1/me/sign-in-methods/github", json={"code": "other-code"}, headers=bob.headers)
    assert second.status_code == 409 and "Unlink @ada-l first" in second.json()["detail"]


async def test_a_github_account_links_to_one_person(db_client: AsyncClient, signup, github: FakeGitHub) -> None:
    ada = await signup()
    bob = await signup(email="bob@example.com", name="Bob")
    github.codes |= {"ada-code", "bob-code"}
    assert (await db_client.put("/v1/me/sign-in-methods/github", json={"code": "ada-code"}, headers=ada.headers)).status_code == 200
    taken = await db_client.put("/v1/me/sign-in-methods/github", json={"code": "bob-code"}, headers=bob.headers)
    assert taken.status_code == 409 and "another dotrix account" in taken.json()["detail"]
    # Not with an API token.
    token = (await db_client.post("/v1/me/tokens", json={"name": "cli"}, headers=bob.headers)).json()["token"]
    cli = await db_client.put(
        "/v1/me/sign-in-methods/github", json={"code": "x"}, headers={"Authorization": f"Bearer {token}"}
    )
    assert cli.status_code == 403
