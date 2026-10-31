"""The dotrix GitHub App: what it may see, as the app itself or as one installation.

The app signs a short JWT with its private key to act as itself (to read an installation), and
trades it for an installation token to read that installation's repos. Tokens aren't stored:
they last an hour, and each request gets what it needs.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any, Protocol
from urllib.parse import quote

import httpx
import jwt
from fastapi import Depends

from dotrix_backend.api.deps import SettingsDep
from dotrix_backend.core.errors import Conflict, Forbidden, NotFound
from dotrix_backend.core.settings import Settings
from dotrix_backend.modules.auth.github import API_URL, GitHubUnavailable

HEADERS = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
MAX_REPOS = 1_000  # per installation, in pages of 100
FORK_READY_TRIES = 5
FAILED = ("failure", "timed_out")  # a CI run's or job's conclusion that means it failed
MAX_FAILED_JOBS = 3
LOG_TAIL = 8_000  # characters of a failed job's log


@dataclass(frozen=True)
class FailedJob:
    """A CI job that failed on a commit: its name, page, and the end of its log (or why there's none)."""

    name: str
    html_url: str
    log: str


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
    state: str = "open"  # "open", "closed", or "merged"


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
        self, installation_id: int, *, repository_id: int | None = None, write: bool = False,
        pull_requests: bool = False,
    ) -> str: ...
    async def create_pull_request(
        self, installation_id: int, full_name: str, *, head: str, base: str, title: str, body: str, token: str
    ) -> PullRequest: ...
    async def create_repository(
        self, installation_id: int, org: str, name: str, *, private: bool, description: str
    ) -> Repo: ...
    async def branch_head(self, full_name: str, branch: str, *, token: str) -> str | None: ...
    async def find_pull_request(self, full_name: str, head: str, *, token: str) -> PullRequest | None: ...
    async def org_installation(self, org: str) -> int: ...
    async def fork(self, installation_id: int, full_name: str, *, org: str, name: str) -> Repo: ...
    async def sync_fork(self, full_name: str, branch: str, *, token: str) -> None: ...
    async def post_review(
        self, full_name: str, number: int, *, token: str, body: str, comments: list[dict[str, Any]], commit_id: str | None,
    ) -> str: ...
    async def comment(self, full_name: str, number: int, *, token: str, body: str) -> str: ...
    async def failed_job_logs(self, full_name: str, sha: str, *, token: str) -> list[FailedJob]: ...

    async def create_issue(self, full_name: str, *, token: str, title: str, body: str) -> PullRequest: ...


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
        self, installation_id: int, *, repository_id: int | None = None, write: bool = False,
        pull_requests: bool = False, actions: bool = False, issues: bool = False,
    ) -> str:
        """An installation token (an hour long) for git; never stored. With `repository_id`, it
        works on that one repo only; `write` adds pushing and opening pull requests there,
        `pull_requests` only opening them (from a fork) or commenting on them, and `actions` reading
        its CI runs and their logs, `issues` opening issues there."""
        body: dict | None = None
        if repository_id is not None:
            permissions: dict[str, str] = {"contents": "read"}
            if write:
                permissions = {"contents": "write", "pull_requests": "write"}
            elif pull_requests:
                permissions["pull_requests"] = "write"
            if actions:
                permissions["actions"] = "read"
            if issues:
                permissions["issues"] = "write"
            body = {"repository_ids": [repository_id], "permissions": {"metadata": "read", **permissions}}
        return await self._installation_token(installation_id, body)

    async def create_pull_request(
        self, installation_id: int, full_name: str, *, head: str, base: str, title: str, body: str, token: str
    ) -> PullRequest:
        """Open a pull request from `head` ("owner:branch" from a fork) into `base`, with a token from
        `access_token` that may open pull requests."""
        async with httpx.AsyncClient(transport=self.transport, timeout=30) as http:
            try:
                res = await http.post(
                    f"{API_URL}/repos/{full_name}/pulls",
                    headers={**HEADERS, "Authorization": f"Bearer {token}"},
                    json={"title": title, "head": head, "base": base, "body": body,
                          # GitHub refuses it for a fork an organisation owns.
                          "maintainer_can_modify": ":" not in head},
                )
            except httpx.HTTPError as exc:
                raise GitHubUnavailable("GitHub couldn't be reached; try again shortly") from exc
        if res.status_code == 201:
            data = res.json()
            return PullRequest(number=int(data["number"]), html_url=str(data["html_url"]))
        if res.status_code in (403, 404):
            raise Forbidden("The GitHub App can't open pull requests there: it needs Pull requests (write)")
        raise GitHubUnavailable(f"GitHub didn't open the pull request ({res.status_code})")

    async def branch_head(self, full_name: str, branch: str, *, token: str) -> str | None:
        """The commit `branch` points at in `full_name`, or None when there's no such branch."""
        try:
            data = await self._get(f"/repos/{full_name}/git/ref/heads/{quote(branch, safe='/')}", token)
        except NotFound:
            return None
        return str(data["object"]["sha"])

    async def find_pull_request(self, full_name: str, head: str, *, token: str) -> PullRequest | None:
        """The latest pull request into `full_name` from `head` ("owner:branch", the owner even for the
        same repo: GitHub ignores a bare branch name), open or not."""
        branch = head.split(":", 1)[1]
        found = await self._get(f"/repos/{full_name}/pulls?state=all&head={quote(head, safe='')}", token)
        pulls = sorted((p for p in found if (p.get("head") or {}).get("ref") == branch),
                       key=lambda p: int(p["number"])) if isinstance(found, list) else []
        if not pulls:
            return None
        latest = pulls[-1]
        state = "merged" if latest.get("merged_at") else ("closed" if latest.get("state") == "closed" else "open")
        return PullRequest(number=int(latest["number"]), html_url=str(latest["html_url"]), state=state)

    async def org_installation(self, org: str) -> int:
        """The app's installation on an organisation (where coding runs' forks live)."""
        async with httpx.AsyncClient(transport=self.transport, timeout=15) as http:
            try:
                res = await http.get(f"{API_URL}/orgs/{org}/installation",
                                     headers={**HEADERS, "Authorization": f"Bearer {self._app_token()}"})
            except httpx.HTTPError as exc:
                raise GitHubUnavailable("GitHub couldn't be reached; try again shortly") from exc
        if res.status_code == 404:
            raise Forbidden(f"The GitHub App isn't installed on {org}, where coding runs push their branches")
        if res.status_code != 200:
            raise GitHubUnavailable(f"GitHub answered {res.status_code}; try again shortly")
        return int(res.json()["id"])

    async def fork(self, installation_id: int, full_name: str, *, org: str, name: str) -> Repo:
        """The app's fork of `full_name` in `org` (GitHub returns the existing one if it's there).
        Needs Administration (write) on `org`, and the repo readable from there."""
        token = await self._installation_token(installation_id)
        async with httpx.AsyncClient(transport=self.transport, timeout=30) as http:
            try:
                res = await http.post(
                    f"{API_URL}/repos/{full_name}/forks",
                    headers={**HEADERS, "Authorization": f"Bearer {token}"},
                    json={"organization": org, "name": name, "default_branch_only": True},
                )
            except httpx.HTTPError as exc:
                raise GitHubUnavailable("GitHub couldn't be reached; try again shortly") from exc
        if res.status_code in (200, 202):
            return _repo(res.json())
        if res.status_code in (403, 404, 422):
            raise Forbidden(
                f"The GitHub App can't fork {full_name} into {org}: it needs Administration (write) on {org}, "
                "and a private repo's owner must allow forking"
            )
        raise GitHubUnavailable(f"GitHub didn't fork the repository ({res.status_code})")

    async def sync_fork(self, full_name: str, branch: str, *, token: str) -> None:
        """Bring a fork's `branch` up to its upstream (a new fork may take a few seconds to be ready)."""
        for attempt in range(FORK_READY_TRIES):
            async with httpx.AsyncClient(transport=self.transport, timeout=30) as http:
                try:
                    res = await http.post(f"{API_URL}/repos/{full_name}/merge-upstream",
                                          headers={**HEADERS, "Authorization": f"Bearer {token}"},
                                          json={"branch": branch})
                except httpx.HTTPError as exc:
                    raise GitHubUnavailable("GitHub couldn't be reached; try again shortly") from exc
            if res.status_code == 200:
                return
            if res.status_code == 409:
                raise Conflict(f"{full_name}'s {branch} has commits its upstream doesn't: reset it to the upstream")
            if res.status_code not in (404, 422) or attempt == FORK_READY_TRIES - 1:
                raise GitHubUnavailable(f"GitHub didn't update the fork {full_name} ({res.status_code})")
            await asyncio.sleep(2 * (attempt + 1))

    # -- tokens and requests -----------------------------------------------------------

    async def post_review(
        self, full_name: str, number: int, *, token: str, body: str, comments: list[dict[str, Any]], commit_id: str | None,
    ) -> str:
        """A review on pull request `number`, as a comment (never an approval: merging is a person's), with
        `comments` on lines of its diff ({path, line, body}, on the new side). GitHub refuses the whole
        review when one line isn't in the diff, so it's posted again without them, their text in `body`.
        Returns the review's page."""
        payload: dict[str, Any] = {"event": "COMMENT", "body": body}
        if commit_id:
            payload["commit_id"] = commit_id
        if comments:
            payload["comments"] = [{"path": c["path"], "line": c["line"], "side": "RIGHT", "body": c["body"]}
                                   for c in comments]
        res = await self._post(f"/repos/{full_name}/pulls/{number}/reviews", token, payload)
        if res.status_code == 422 and comments:
            folded = body + "\n\n" + "\n\n".join(f"**`{c['path']}:{c['line']}`**: {c['body']}" for c in comments)
            res = await self._post(f"/repos/{full_name}/pulls/{number}/reviews", token,
                                   {k: v for k, v in payload.items() if k != "comments"} | {"body": folded})
        if res.status_code in (403, 404):
            raise Forbidden("The GitHub App can't review pull requests there: it needs Pull requests (write)")
        if res.status_code != 200:
            raise GitHubUnavailable(f"GitHub didn't take the review ({res.status_code})")
        return str(res.json().get("html_url") or "")

    async def comment(self, full_name: str, number: int, *, token: str, body: str) -> str:
        """A comment on pull request (or issue) `number`'s conversation; returns its page."""
        res = await self._post(f"/repos/{full_name}/issues/{number}/comments", token, {"body": body})
        if res.status_code in (403, 404):
            raise Forbidden("The GitHub App can't comment there: it needs Pull requests (write)")
        if res.status_code != 201:
            raise GitHubUnavailable(f"GitHub didn't take the comment ({res.status_code})")
        return str(res.json().get("html_url") or "")

    async def create_issue(self, full_name: str, *, token: str, title: str, body: str) -> PullRequest:
        """An issue in `full_name`, with a token from `access_token(issues=True)`; its number and page."""
        res = await self._post(f"/repos/{full_name}/issues", token, {"title": title[:250], "body": body})
        if res.status_code in (403, 404):
            raise Forbidden("The GitHub App can't open issues there: it needs Issues (write)")
        if res.status_code == 410:
            raise Conflict(f"Issues are turned off in {full_name}")
        if res.status_code != 201:
            raise GitHubUnavailable(f"GitHub didn't open the issue ({res.status_code})")
        data = res.json()
        return PullRequest(number=int(data["number"]), html_url=str(data["html_url"]))

    async def failed_job_logs(self, full_name: str, sha: str, *, token: str) -> list[FailedJob]:
        """The GitHub Actions jobs that failed on `sha` (the latest attempt of each run), with the end of
        each one's log: at most `MAX_FAILED_JOBS`, `LOG_TAIL` characters each. Without the Actions (read)
        permission GitHub refuses, which is raised as Forbidden for the caller to say."""
        try:
            runs = await self._get(f"/repos/{full_name}/actions/runs?head_sha={sha}&per_page=20", token)
        except GitHubUnavailable as exc:
            if "403" in str(exc):
                raise Forbidden("The GitHub App can't read CI here: it needs Actions (read)") from exc
            raise
        failed: list[FailedJob] = []
        for run in runs.get("workflow_runs") or []:
            if run.get("conclusion") not in FAILED or len(failed) >= MAX_FAILED_JOBS:
                continue
            jobs = await self._get(f"/repos/{full_name}/actions/runs/{run['id']}/jobs?filter=latest", token)
            for job in jobs.get("jobs") or []:
                if job.get("conclusion") not in FAILED or len(failed) >= MAX_FAILED_JOBS:
                    continue
                log = await self._log(f"/repos/{full_name}/actions/jobs/{job['id']}/logs", token)
                failed.append(FailedJob(name=f"{run.get('name') or 'CI'} / {job.get('name') or job['id']}",
                                        html_url=str(job.get("html_url") or run.get("html_url") or ""), log=log))
        return failed

    async def _log(self, path: str, token: str) -> str:
        """A job's log, its end only (the failure is near the end); GitHub answers with a redirect to it."""
        async with httpx.AsyncClient(transport=self.transport, timeout=30, follow_redirects=True) as http:
            try:
                res = await http.get(f"{API_URL}{path}", headers={**HEADERS, "Authorization": f"Bearer {token}"})
            except httpx.HTTPError:
                return "(the log couldn't be fetched)"
        if res.status_code != 200:
            return f"(the log couldn't be fetched: {res.status_code})"
        text = res.text
        return text if len(text) <= LOG_TAIL else "…" + text[-LOG_TAIL:]

    async def _post(self, path: str, token: str, payload: dict[str, Any]) -> httpx.Response:
        async with httpx.AsyncClient(transport=self.transport, timeout=30) as http:
            try:
                return await http.post(f"{API_URL}{path}", headers={**HEADERS, "Authorization": f"Bearer {token}"},
                                       json=payload)
            except httpx.HTTPError as exc:
                raise GitHubUnavailable("GitHub couldn't be reached; try again shortly") from exc

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

    async def _get(self, path: str, token: str) -> Any:
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
