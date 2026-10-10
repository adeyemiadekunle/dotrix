"""The dotrix GitHub App: what it may see, as the app itself or as one installation.

The app signs a short JWT with its private key to act as itself (to read an installation), and
trades it for an installation token to read that installation's repos. Tokens aren't stored:
they last an hour, and each request gets what it needs.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Protocol

import httpx
import jwt
from fastapi import Depends

from dotrix_backend.api.deps import SettingsDep
from dotrix_backend.core.errors import Conflict, Forbidden, NotFound
from dotrix_backend.core.settings import Settings
from dotrix_backend.modules.auth.github import API_URL, GitHubUnavailable

HEADERS = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
MAX_REPOS = 1_000  # per installation, in pages of 100


@dataclass(frozen=True)
class Installation:
    id: int
    account_login: str
    account_type: str  # "User" or "Organization"
    suspended: bool


@dataclass(frozen=True)
class PullRequest:
    number: int
    html_url: str


@dataclass(frozen=True)
class Repo:
    id: int
    full_name: str
    private: bool
    default_branch: str
    html_url: str


def _repo(data: dict) -> Repo:
    return Repo(
        id=int(data["id"]),
        full_name=str(data["full_name"]),
        private=bool(data.get("private")),
        default_branch=str(data.get("default_branch") or "main"),
        html_url=str(data.get("html_url") or f"https://github.com/{data['full_name']}"),
    )


class GitHubApp(Protocol):
    @property
    def configured(self) -> bool: ...
    def install_url(self) -> str: ...
    async def installation(self, installation_id: int) -> Installation: ...
    async def repositories(self, installation_id: int) -> list[Repo]: ...
    async def repository(self, installation_id: int, repo_id: int) -> Repo: ...
    async def access_token(
        self, installation_id: int, *, repository_id: int | None = None, write: bool = False
    ) -> str: ...
    async def create_pull_request(
        self, installation_id: int, full_name: str, *, head: str, base: str, title: str, body: str, token: str
    ) -> PullRequest: ...
    async def create_repository(
        self, installation_id: int, org: str, name: str, *, private: bool, description: str
    ) -> Repo: ...


class GitHubAppClient:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.app_id = settings.github_app_id
        self.slug = settings.github_app_slug
        self.private_key = _private_key(settings)
        self.transport = transport

    @property
    def configured(self) -> bool:
        return bool(self.app_id and self.slug and self.private_key)

    def install_url(self) -> str:
        """GitHub's page to install the app on an account and choose its repos."""
        self._require_config()
        return f"https://github.com/apps/{self.slug}/installations/new"

    async def installation(self, installation_id: int) -> Installation:
        data = await self._get(f"/app/installations/{installation_id}", self._app_token())
        return Installation(
            id=int(data["id"]),
            account_login=str(data["account"]["login"]),
            account_type=str(data["account"].get("type") or "User"),
            suspended=data.get("suspended_at") is not None,
        )

    async def repositories(self, installation_id: int) -> list[Repo]:
        """The repos the account gave the app (all of them, or the ones chosen)."""
        token = await self._installation_token(installation_id)
        repos: list[Repo] = []
        for page in range(1, MAX_REPOS // 100 + 1):
            data = await self._get(f"/installation/repositories?per_page=100&page={page}", token)
            batch = data.get("repositories") or []
            repos += [_repo(r) for r in batch]
            if len(batch) < 100:
                break
        return repos

    async def repository(self, installation_id: int, repo_id: int) -> Repo:
        """One repo, if this installation can see it (else NotFound)."""
        return _repo(await self._get(f"/repositories/{repo_id}", await self._installation_token(installation_id)))

    async def create_repository(
        self, installation_id: int, org: str, name: str, *, private: bool, description: str
    ) -> Repo:
        """A new repo in an organisation the app is installed on (with a README, so it has a
        default branch). Needs the app's Administration (write) permission there."""
        token = await self._installation_token(installation_id)
        async with httpx.AsyncClient(transport=self.transport, timeout=15) as http:
            try:
                res = await http.post(
                    f"{API_URL}/orgs/{org}/repos",
                    headers={**HEADERS, "Authorization": f"Bearer {token}"},
                    json={"name": name, "private": private, "description": description, "auto_init": True},
                )
            except httpx.HTTPError as exc:
                raise GitHubUnavailable("GitHub couldn't be reached; try again shortly") from exc
        if res.status_code == 201:
            return _repo(res.json())
        if res.status_code == 422:
            raise Conflict(f"{org} already has a repository called {name}, or GitHub didn't accept that name")
        if res.status_code in (403, 404):
            raise Forbidden(
                f"The GitHub App can't create repositories in {org}: it needs the Administration (write) "
                "permission there"
            )
        raise GitHubUnavailable(f"GitHub answered {res.status_code}; try again shortly")

    async def access_token(
        self, installation_id: int, *, repository_id: int | None = None, write: bool = False
    ) -> str:
        """An installation token (an hour long) for git; never stored. With `repository_id`, it
        works on that one repo only; `write` adds pushing and opening pull requests there."""
        body: dict | None = None
        if repository_id is not None:
            permissions = {"contents": "write", "pull_requests": "write"} if write else {"contents": "read"}
            body = {"repository_ids": [repository_id], "permissions": {"metadata": "read", **permissions}}
        return await self._installation_token(installation_id, body)

    async def create_pull_request(
        self, installation_id: int, full_name: str, *, head: str, base: str, title: str, body: str, token: str
    ) -> PullRequest:
        """Open a pull request from `head` into `base`, with a token from `access_token(write=True)`."""
        async with httpx.AsyncClient(transport=self.transport, timeout=30) as http:
            try:
                res = await http.post(
                    f"{API_URL}/repos/{full_name}/pulls",
                    headers={**HEADERS, "Authorization": f"Bearer {token}"},
                    json={"title": title, "head": head, "base": base, "body": body, "maintainer_can_modify": True},
                )
            except httpx.HTTPError as exc:
                raise GitHubUnavailable("GitHub couldn't be reached; try again shortly") from exc
        if res.status_code == 201:
            data = res.json()
            return PullRequest(number=int(data["number"]), html_url=str(data["html_url"]))
        if res.status_code in (403, 404):
            raise Forbidden("The GitHub App can't open pull requests there: it needs Pull requests (write)")
        raise GitHubUnavailable(f"GitHub didn't open the pull request ({res.status_code})")

    # -- tokens and requests -----------------------------------------------------------

    def _app_token(self) -> str:
        self._require_config()
        assert self.private_key is not None
        now = datetime.now(UTC)
        claims = {"iat": now - timedelta(seconds=60), "exp": now + timedelta(minutes=9), "iss": self.app_id}
        return jwt.encode(claims, self.private_key, algorithm="RS256")

    async def _installation_token(self, installation_id: int, body: dict | None = None) -> str:
        async with httpx.AsyncClient(transport=self.transport, timeout=15) as http:
            try:
                res = await http.post(
                    f"{API_URL}/app/installations/{installation_id}/access_tokens",
                    headers={**HEADERS, "Authorization": f"Bearer {self._app_token()}"},
                    json=body,
                )
            except httpx.HTTPError as exc:
                raise GitHubUnavailable("GitHub couldn't be reached; try again shortly") from exc
        if res.status_code == 404:
            raise NotFound("The GitHub app isn't installed there any more")
        if res.status_code != 201:
            raise GitHubUnavailable("GitHub didn't give the app access; check its ID and private key")
        return str(res.json()["token"])

    async def _get(self, path: str, token: str) -> dict:
        async with httpx.AsyncClient(transport=self.transport, timeout=15) as http:
            try:
                res = await http.get(f"{API_URL}{path}", headers={**HEADERS, "Authorization": f"Bearer {token}"})
            except httpx.HTTPError as exc:
                raise GitHubUnavailable("GitHub couldn't be reached; try again shortly") from exc
        if res.status_code == 404:
            raise NotFound("GitHub says that isn't there, or the app can't see it")
        if res.status_code != 200:
            raise GitHubUnavailable(f"GitHub answered {res.status_code}; try again shortly")
        return res.json()

    def _require_config(self) -> None:
        if not self.configured:
            raise GitHubUnavailable(
                "Connecting GitHub repos isn't set up (set DOTRIX_GITHUB_APP_ID, DOTRIX_GITHUB_APP_SLUG, "
                "and DOTRIX_GITHUB_APP_PRIVATE_KEY or _PATH in .env)"
            )


def _private_key(settings: Settings) -> str | None:
    if settings.github_app_private_key is not None:
        # Kept on one line in some secret stores: "\n" written out stands for a line break.
        return settings.github_app_private_key.get_secret_value().replace("\\n", "\n")
    if settings.github_app_private_key_path:
        return Path(settings.github_app_private_key_path).read_text()
    return None


def get_github_app(settings: SettingsDep) -> GitHubApp:
    return GitHubAppClient(settings)


GitHubAppDep = Annotated[GitHubApp, Depends(get_github_app)]
