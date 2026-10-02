"""Connecting GitHub through the app: installations proven by a GitHub sign-in, each project's
repo, and the webhook keeping them current. GitHub is faked with an httpx MockTransport."""
import hashlib
import hmac
import json
from typing import Any
from urllib.parse import parse_qs

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import AsyncClient
from pydantic import SecretStr

from pmagent_backend.core.settings import Settings
from pmagent_backend.modules.auth.github import GitHubOAuth, get_github
from pmagent_backend.modules.connectors.github_app import GitHubAppClient, get_github_app
from pmagent_backend.modules.workspaces.models import Role

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PEM = KEY.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
WEBHOOK_SECRET = "hook-secret"


def _repo(repo_id: int, full_name: str, private: bool = False) -> dict[str, Any]:
    return {"id": repo_id, "full_name": full_name, "private": private, "default_branch": "main",
            "html_url": f"https://github.com/{full_name}"}


class FakeGitHub:
    """GitHub's App API, its sign-in, and two installations; the person signing in manages 111."""

    def __init__(self) -> None:
        self.installations = {
            111: {"account": {"login": "kunemi", "type": "Organization"},
                  "repos": [_repo(9001, "kunemi/api", private=True), _repo(9002, "kunemi/web")]},
            222: {"account": {"login": "someone-else", "type": "User"}, "repos": [_repo(9100, "someone-else/x")]},
        }
        self.manages = {111}
        self.codes = {"code-1", "code-2", "code-3"}

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        auth = request.headers.get("Authorization", "")
        if path == "/login/oauth/access_token":
            code = parse_qs(request.content.decode())["code"][0]
            if code not in self.codes:
                return httpx.Response(200, json={"error": "bad_verification_code"})
            self.codes.discard(code)
            return httpx.Response(200, json={"access_token": "gho_user"})
        if path == "/user/installations":
            assert auth == "Bearer gho_user"
            return httpx.Response(200, json={"installations": [{"id": i} for i in sorted(self.manages)]})
        if path.startswith("/app/"):
            claims = jwt.decode(auth.removeprefix("Bearer "), KEY.public_key(), algorithms=["RS256"])
            assert claims["iss"] == "4242"
            installation_id = int(path.split("/")[3])
            if installation_id not in self.installations:
                return httpx.Response(404)
            if path.endswith("/access_tokens"):
                return httpx.Response(201, json={"token": f"ghs_{installation_id}"})
            return httpx.Response(200, json={"id": installation_id, **self.installations[installation_id]})
        installation = self.installations.get(int(auth.removeprefix("Bearer ghs_") or 0))
        assert installation is not None, auth
        if path == "/installation/repositories":
            return httpx.Response(200, json={"repositories": installation["repos"]})
        if path.startswith("/repositories/"):
            repo = next((r for r in installation["repos"] if r["id"] == int(path.split("/")[2])), None)
            return httpx.Response(200, json=repo) if repo else httpx.Response(404)
        return httpx.Response(404)


@pytest.fixture
def github(db_client: AsyncClient) -> FakeGitHub:
    fake = FakeGitHub()
    settings = Settings(
        database_url="postgresql+asyncpg://localhost/unused",
        jwt_secret="test-only-jwt-secret-not-used-anywhere-else",  # type: ignore[arg-type]
        github_client_id="gh-client",
        github_client_secret="gh-secret",  # type: ignore[arg-type]
        github_app_id="4242",
        github_app_slug="pmagent-test",
        github_app_private_key=PEM.decode(),  # type: ignore[arg-type]
    )
    transport = httpx.MockTransport(fake.handle)
    app = db_client._transport.app  # type: ignore[attr-defined]
    app.dependency_overrides[get_github_app] = lambda: GitHubAppClient(settings, transport=transport)
    app.dependency_overrides[get_github] = lambda: GitHubOAuth(settings, transport=transport)
    before = app.state.settings.github_webhook_secret
    app.state.settings.github_webhook_secret = SecretStr(WEBHOOK_SECRET)
    yield fake
    app.state.settings.github_webhook_secret = before
    app.dependency_overrides.pop(get_github_app)
    app.dependency_overrides.pop(get_github)


async def _world(db_client: AsyncClient, signup, create_team, add_member):
    ada = await signup()
    cat = await signup(email="cat@example.com", name="Cat")
    team = await create_team(ada.headers)
    await add_member(team["id"], cat.id, Role.MEMBER)
    ws = f"/v1/workspaces/{team['id']}"
    kun = (await db_client.post(f"{ws}/projects", json={"key": "KUN", "name": "K"}, headers=ada.headers)).json()
    mob = (await db_client.post(f"{ws}/projects", json={"key": "MOB", "name": "M"}, headers=ada.headers)).json()
    return ada, cat, ws, kun, mob


async def _deliver(db_client: AsyncClient, event: str, payload: dict, secret: str = WEBHOOK_SECRET) -> httpx.Response:
    body = json.dumps(payload).encode()
    signature = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return await db_client.post(
        "/v1/github/webhook", content=body,
        headers={"X-GitHub-Event": event, "X-Hub-Signature-256": signature, "Content-Type": "application/json"},
    )


async def test_not_set_up(db_client: AsyncClient, signup, create_team, add_member) -> None:
    ada, _, ws, _, _ = await _world(db_client, signup, create_team, add_member)
    assert (await db_client.get(f"{ws}/github", headers=ada.headers)).json() == {
        "configured": False, "install_url": None, "installations": []
    }


async def test_install_then_connect_a_repo(db_client: AsyncClient, signup, create_team, add_member, github) -> None:
    ada, cat, ws, kun, mob = await _world(db_client, signup, create_team, add_member)
    status = (await db_client.get(f"{ws}/github", headers=ada.headers)).json()
    assert status["configured"] and status["install_url"] == "https://github.com/apps/pmagent-test/installations/new"
    # Members don't set up projects' code.
    assert (await db_client.get(f"{ws}/github", headers=cat.headers)).status_code == 403

    # Only an installation GitHub says you manage.
    theirs = await db_client.post(f"{ws}/github/installations", json={"installation_id": 222, "code": "code-1"},
                                  headers=ada.headers)
    assert theirs.status_code == 403
    added = await db_client.post(f"{ws}/github/installations", json={"installation_id": 111, "code": "code-2"},
                                 headers=ada.headers)
    assert added.status_code == 200, added.text
    installation = added.json()
    assert installation["account_login"] == "kunemi" and installation["account_type"] == "Organization"

    repos = (await db_client.get(f"{ws}/github/repos", headers=ada.headers)).json()
    assert [(r["full_name"], r["private"], r["project_key"]) for r in repos] == [
        ("kunemi/api", True, None), ("kunemi/web", False, None)
    ]

    base = f"{ws}/projects/{kun['id']}/repository"
    connect = {"installation_ref": installation["id"], "github_repo_id": 9001}
    res = await db_client.put(base, json=connect, headers=ada.headers)
    assert res.status_code == 200, res.text
    assert res.json()["full_name"] == "kunemi/api" and res.json()["account_login"] == "kunemi"
    project = (await db_client.get(f"{ws}/projects/{kun['id']}", headers=ada.headers)).json()
    assert project["repo_url"] == "https://github.com/kunemi/api"
    # Anyone who sees the project sees its repo; another project can't take it.
    assert (await db_client.get(base, headers=cat.headers)).json()["full_name"] == "kunemi/api"
    taken = await db_client.put(f"{ws}/projects/{mob['id']}/repository", json=connect, headers=ada.headers)
    assert taken.status_code == 409 and "KUN already uses kunemi/api" in taken.json()["detail"]
    # A repo the installation can't see isn't there.
    hidden = await db_client.put(f"{ws}/projects/{mob['id']}/repository",
                                 json={**connect, "github_repo_id": 9100}, headers=ada.headers)
    assert hidden.status_code == 404
    assert [r["project_key"] for r in (await db_client.get(f"{ws}/github/repos", headers=ada.headers)).json()] == [
        "KUN", None
    ]

    # Disconnecting keeps the repo's address (for the CLI).
    assert (await db_client.delete(base, headers=ada.headers)).status_code == 204
    assert (await db_client.get(base, headers=ada.headers)).json() is None
    assert (await db_client.delete(base, headers=ada.headers)).status_code == 404


async def test_the_webhook_keeps_it_current(db_client: AsyncClient, signup, create_team, add_member, github) -> None:
    ada, _, ws, kun, mob = await _world(db_client, signup, create_team, add_member)
    installation = (await db_client.post(f"{ws}/github/installations", json={"installation_id": 111, "code": "code-1"},
                                          headers=ada.headers)).json()
    for project, repo_id in ((kun, 9001), (mob, 9002)):
        await db_client.put(f"{ws}/projects/{project['id']}/repository",
                            json={"installation_ref": installation["id"], "github_repo_id": repo_id}, headers=ada.headers)

    push = {"ref": "refs/heads/main", "after": "a" * 40,
            "repository": {"id": 9001, "full_name": "kunemi/api-renamed", "default_branch": "main"}}
    assert (await _deliver(db_client, "push", push, secret="wrong")).status_code == 401
    assert (await _deliver(db_client, "push", push)).status_code == 202
    repo = (await db_client.get(f"{ws}/projects/{kun['id']}/repository", headers=ada.headers)).json()
    assert repo["last_push_sha"] == "a" * 40 and repo["full_name"] == "kunemi/api-renamed"
    # Pushes to other branches don't count.
    await _deliver(db_client, "push", {**push, "ref": "refs/heads/feature", "after": "b" * 40})
    assert (await db_client.get(f"{ws}/projects/{kun['id']}/repository", headers=ada.headers)).json()["last_push_sha"] == "a" * 40

    # A repo taken away from the app: its project is disconnected.
    removed = {"action": "removed", "installation": {"id": 111}, "repositories_removed": [{"id": 9002}]}
    await _deliver(db_client, "installation_repositories", removed)
    assert (await db_client.get(f"{ws}/projects/{mob['id']}/repository", headers=ada.headers)).json() is None
    # Uninstalled: forgotten, and its projects disconnected.
    await _deliver(db_client, "installation", {"action": "deleted", "installation": {"id": 111}})
    assert (await db_client.get(f"{ws}/github", headers=ada.headers)).json()["installations"] == []
    assert (await db_client.get(f"{ws}/projects/{kun['id']}/repository", headers=ada.headers)).json() is None


async def test_forget_an_installation(db_client: AsyncClient, signup, create_team, add_member, github) -> None:
    ada, _, ws, kun, _ = await _world(db_client, signup, create_team, add_member)
    installation = (await db_client.post(f"{ws}/github/installations", json={"installation_id": 111, "code": "code-1"},
                                          headers=ada.headers)).json()
    await db_client.put(f"{ws}/projects/{kun['id']}/repository",
                        json={"installation_ref": installation["id"], "github_repo_id": 9001}, headers=ada.headers)
    gone = await db_client.delete(f"{ws}/github/installations/{installation['id']}", headers=ada.headers)
    assert gone.status_code == 204
    assert (await db_client.get(f"{ws}/projects/{kun['id']}/repository", headers=ada.headers)).json() is None
    audit = (await db_client.get(f"{ws}/audit", headers=ada.headers)).json()
    actions = {e["action"] for e in (audit["items"] if isinstance(audit, dict) else audit)}
    assert {"github.installation_added", "project.repo_connected", "github.installation_removed"} <= actions


async def test_moving_a_project_drops_its_connection(db_client: AsyncClient, signup, create_team, add_member, github) -> None:
    ada, _, ws, kun, _ = await _world(db_client, signup, create_team, add_member)
    installation = (await db_client.post(f"{ws}/github/installations", json={"installation_id": 111, "code": "code-1"},
                                          headers=ada.headers)).json()
    await db_client.put(f"{ws}/projects/{kun['id']}/repository",
                        json={"installation_ref": installation["id"], "github_repo_id": 9001}, headers=ada.headers)
    other = await create_team(ada.headers, "Other")
    moved = await db_client.post(f"{ws}/projects/{kun['id']}/move", json={"workspace_id": other["id"]}, headers=ada.headers)
    assert moved.status_code == 200, moved.text
    # The installation belongs to the old workspace: the project keeps its address, not the connection.
    there = f"/v1/workspaces/{other['id']}/projects/{kun['id']}"
    assert (await db_client.get(f"{there}/repository", headers=ada.headers)).json() is None
    assert (await db_client.get(there, headers=ada.headers)).json()["repo_url"] == "https://github.com/kunemi/api"
    assert [r["project_key"] for r in (await db_client.get(f"{ws}/github/repos", headers=ada.headers)).json()] == [None, None]
