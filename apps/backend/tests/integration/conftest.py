"""A fake GitHub for the connector and code tests: its App API and sign-in through an httpx
MockTransport, a workspace with two projects, and signed webhook deliveries."""
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

from dotrix_backend.core.settings import Settings
from dotrix_backend.modules.auth.github import GitHubOAuth, get_github
from dotrix_backend.modules.connectors.github_app import GitHubAppClient, get_github_app
from dotrix_backend.modules.workspaces.models import Role

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PEM = KEY.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
WEBHOOK_SECRET = "hook-secret"


def _repo(repo_id: int, full_name: str, private: bool = False) -> dict[str, Any]:
    return {"id": repo_id, "full_name": full_name, "private": private, "default_branch": "main",
            "html_url": f"https://github.com/{full_name}"}


class FakeGitHub:
    """GitHub's App API, its sign-in, and three installations: the person signing in manages 111 (an
    organisation) and 333 (their own account), not 222."""

    def __init__(self) -> None:
        self.installations = {
            111: {"account": {"login": "kunemi", "type": "Organization"},
                  "repos": [_repo(9001, "kunemi/api", private=True), _repo(9002, "kunemi/web")]},
            222: {"account": {"login": "someone-else", "type": "User"}, "repos": [_repo(9100, "someone-else/x")]},
            333: {"account": {"login": "ada-gh", "type": "User"}, "repos": []},
            444: {"account": {"login": "dotrix-fork", "type": "Organization"}, "repos": []},  # coding runs' forks
        }
        self.manages = {111, 333}
        self.token_requests: list[dict[str, Any]] = []  # what each installation token was scoped to
        self.pulls: list[dict[str, Any]] = []  # pull requests opened
        self.forks: list[dict[str, Any]] = []  # forks asked for
        self.synced: list[tuple[str, str]] = []  # forks' branches brought up to their upstream
        self.codes = {"code-1", "code-2", "code-3"}
        self.branch_heads: Any = None  # (repo, branch) -> the commit it points at, or None; set by a test
        self.fail_pulls = 0  # how many PR requests to answer with a 502 (a reply lost on the way)
        self.reviews: list[dict[str, Any]] = []  # reviews posted on pull requests
        self.comments: list[dict[str, Any]] = []  # comments posted on pull requests
        self.reject_inline = False  # answer reviews with inline comments with a 422 (a line not in the diff)
        self.refuse_actions = False  # the App wasn't given Actions (read)
        self.ci_runs: list[dict[str, Any]] = []  # Actions workflow runs: {"id", "head_sha", "conclusion", "jobs": [...]}

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
        if path.startswith("/orgs/") and path.endswith("/installation"):
            jwt.decode(auth.removeprefix("Bearer "), KEY.public_key(), algorithms=["RS256"])
            org = path.split("/")[2]
            found = [i for i, inst in self.installations.items() if inst["account"]["login"] == org]
            return httpx.Response(200, json={"id": found[0]}) if found else httpx.Response(404)
        if path.startswith("/app/"):
            claims = jwt.decode(auth.removeprefix("Bearer "), KEY.public_key(), algorithms=["RS256"])
            assert claims["iss"] == "4242"
            installation_id = int(path.split("/")[3])
            if installation_id not in self.installations:
                return httpx.Response(404)
            if path.endswith("/access_tokens"):
                self.token_requests.append(json.loads(request.content) if request.content else {})
                return httpx.Response(201, json={"token": f"ghs_{installation_id}"})
            return httpx.Response(200, json={"id": installation_id, **self.installations[installation_id]})
        installation = self.installations.get(int(auth.removeprefix("Bearer ghs_") or 0))
        assert installation is not None, auth
        if path.startswith("/orgs/") and path.endswith("/repos") and request.method == "POST":
            body = json.loads(request.content)
            org = path.split("/")[2]
            if org != installation["account"]["login"]:
                return httpx.Response(404)
            if any(r["full_name"] == f"{org}/{body['name']}" for r in installation["repos"]):
                return httpx.Response(422, json={"message": "name already exists"})
            repo = _repo(9500 + len(installation["repos"]), f"{org}/{body['name']}", private=body["private"])
            installation["repos"].append(repo)
            return httpx.Response(201, json=repo)
        if path.startswith("/repos/") and path.endswith("/forks") and request.method == "POST":
            body = json.loads(request.content)
            if body["organization"] != installation["account"]["login"]:
                return httpx.Response(403)
            self.forks.append({"repo": path.removeprefix("/repos/").removesuffix("/forks"), **body})
            full_name = f"{body['organization']}/{body['name']}"
            repo = next((r for r in installation["repos"] if r["full_name"] == full_name), None)
            if repo is None:
                repo = _repo(9700 + len(installation["repos"]), full_name)
                installation["repos"].append(repo)
            return httpx.Response(202, json=repo)
        if path.startswith("/repos/") and path.endswith("/merge-upstream") and request.method == "POST":
            self.synced.append((path.removeprefix("/repos/").removesuffix("/merge-upstream"),
                                json.loads(request.content)["branch"]))
            return httpx.Response(200, json={"merge_type": "fast-forward"})
        if "/git/ref/heads/" in path and request.method == "GET":
            full_name, branch = path.removeprefix("/repos/").split("/git/ref/heads/", 1)
            sha = self.branch_heads(full_name, branch) if self.branch_heads else None
            return httpx.Response(200, json={"object": {"sha": sha}}) if sha else httpx.Response(404)
        if path.startswith("/repos/") and path.endswith("/pulls") and request.method == "GET":
            full_name = path.removeprefix("/repos/").removesuffix("/pulls")
            owner, _, branch = request.url.params["head"].partition(":")
            found = [{"number": n, "html_url": f"https://github.com/{full_name}/pull/{n}",
                      "head": {"ref": p["head"].split(":")[-1]}, "state": p.get("state", "open"),
                      "merged_at": p.get("merged_at")}
                     for n, p in enumerate(self.pulls, 1) if p["repo"] == full_name]
            return httpx.Response(200, json=found if branch else [])  # GitHub checks the owner; the client the branch
        if path.startswith("/repos/") and path.endswith("/pulls") and request.method == "POST":
            if self.fail_pulls:
                self.fail_pulls -= 1
                return httpx.Response(502)
            full_name = path.removeprefix("/repos/").removesuffix("/pulls")
            self.pulls.append({"repo": full_name, **json.loads(request.content)})
            number = len(self.pulls)
            return httpx.Response(201, json={"number": number, "html_url": f"https://github.com/{full_name}/pull/{number}"})
        if path.startswith("/repos/") and path.endswith("/reviews") and request.method == "POST":
            body = json.loads(request.content)
            if self.reject_inline and body.get("comments"):
                return httpx.Response(422, json={"message": "Line could not be resolved"})
            full_name, _, rest = path.removeprefix("/repos/").partition("/pulls/")
            self.reviews.append({"repo": full_name, "number": int(rest.split("/")[0]), **body})
            return httpx.Response(200, json={"html_url": f"https://github.com/{full_name}/pull/{rest.split('/')[0]}"
                                                         f"#pullrequestreview-{len(self.reviews)}"})
        if path.startswith("/repos/") and path.endswith("/comments") and "/issues/" in path and request.method == "POST":
            full_name, _, rest = path.removeprefix("/repos/").partition("/issues/")
            self.comments.append({"repo": full_name, "number": int(rest.split("/")[0]), **json.loads(request.content)})
            return httpx.Response(201, json={"html_url": f"https://github.com/{full_name}/pull/{rest.split('/')[0]}"
                                                         f"#issuecomment-{len(self.comments)}"})
        if path.startswith("/repos/") and "/actions/" in path and self.refuse_actions:
            return httpx.Response(403)
        if path.startswith("/repos/") and path.endswith("/actions/runs"):
            sha = request.url.params.get("head_sha")
            return httpx.Response(200, json={"workflow_runs": [
                {k: v for k, v in r.items() if k != "jobs"} for r in self.ci_runs if r["head_sha"] == sha]})
        if path.startswith("/repos/") and "/actions/runs/" in path and path.endswith("/jobs"):
            run_id = int(path.split("/actions/runs/")[1].split("/")[0])
            run = next(r for r in self.ci_runs if r["id"] == run_id)
            return httpx.Response(200, json={"jobs": [{k: v for k, v in j.items() if k != "log"} for j in run["jobs"]]})
        if path.startswith("/repos/") and "/actions/jobs/" in path and path.endswith("/logs"):
            job_id = int(path.split("/actions/jobs/")[1].split("/")[0])
            job = next(j for r in self.ci_runs for j in r["jobs"] if j["id"] == job_id)
            return httpx.Response(200, text=job["log"])
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
        github_app_slug="dotrix-test",
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


@pytest.fixture
def github_world(db_client: AsyncClient, signup, create_team, add_member):
    """Ada (owner) and Cat (member) in a team with projects KUN and MOB."""

    async def _world():
        return await _make_world(db_client, signup, create_team, add_member)

    return _world


async def _make_world(db_client: AsyncClient, signup, create_team, add_member):
    ada = await signup()
    cat = await signup(email="cat@example.com", name="Cat")
    team = await create_team(ada.headers)
    await add_member(team["id"], cat.id, Role.MEMBER)
    ws = f"/v1/workspaces/{team['id']}"
    kun = (await db_client.post(f"{ws}/projects", json={"key": "KUN", "name": "K"}, headers=ada.headers)).json()
    mob = (await db_client.post(f"{ws}/projects", json={"key": "MOB", "name": "M"}, headers=ada.headers)).json()
    return ada, cat, ws, kun, mob


@pytest.fixture
def deliver(db_client: AsyncClient):
    """Send GitHub's webhook delivery, signed (with `secret`, the right one by default)."""

    async def _send(event: str, payload: dict, secret: str = WEBHOOK_SECRET, delivery: str | None = None) -> httpx.Response:
        return await _deliver(db_client, event, payload, secret, delivery)

    return _send


async def _deliver(
    db_client: AsyncClient, event: str, payload: dict, secret: str = WEBHOOK_SECRET, delivery: str | None = None
) -> httpx.Response:
    body = json.dumps(payload).encode()
    signature = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    headers = {"X-GitHub-Event": event, "X-Hub-Signature-256": signature, "Content-Type": "application/json"}
    if delivery:
        headers["X-GitHub-Delivery"] = delivery
    return await db_client.post("/v1/github/webhook", content=body, headers=headers)


