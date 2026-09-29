"""Sign in with GitHub: the OAuth web flow against a GitHub App or OAuth App.

The web app sends the person to `authorize_url`; GitHub sends them back with a code, which the
web app hands to the API. The API trades the code for a GitHub token (with the client secret,
which never leaves the backend), reads who they are and their verified emails, and then
forgets the token: signing in needs nothing stored from GitHub but the account's id.
"""
from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus
from typing import Annotated, Protocol
from urllib.parse import urlencode

import httpx
from fastapi import Depends

from pmagent_backend.api.deps import SettingsDep
from pmagent_backend.core.errors import DomainError, Unauthorized
from pmagent_backend.core.settings import Settings

AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
TOKEN_URL = "https://github.com/login/oauth/access_token"
API_URL = "https://api.github.com"
# OAuth Apps need these scopes; a GitHub App ignores them and uses its own permissions
# (Account permissions → Email addresses: read-only).
SCOPE = "read:user user:email"


class GitHubUnavailable(DomainError):
    status_code = HTTPStatus.SERVICE_UNAVAILABLE
    code = "github_unavailable"


@dataclass(frozen=True)
class GitHubProfile:
    id: str  # GitHub's numeric account id: stable, unlike the login or emails
    login: str
    name: str | None
    verified_email: str | None  # the primary email if verified, else another verified one


class GitHubClient(Protocol):
    @property
    def configured(self) -> bool: ...
    def authorize_url(self, state: str) -> str: ...
    async def profile(self, code: str) -> GitHubProfile: ...


class GitHubOAuth:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.client_id = settings.github_client_id
        self.client_secret = settings.github_client_secret
        # Unset: GitHub uses the callback URL registered on the app.
        self.redirect_uri = settings.github_redirect_uri
        self.transport = transport

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    def authorize_url(self, state: str) -> str:
        self._require_config()
        params = {"client_id": self.client_id, "state": state, "scope": SCOPE, "allow_signup": "true"}
        if self.redirect_uri:
            params["redirect_uri"] = self.redirect_uri
        return f"{AUTHORIZE_URL}?{urlencode(params)}"

    async def profile(self, code: str) -> GitHubProfile:
        """Trade the code for a token, then read the account and its verified emails."""
        self._require_config()
        assert self.client_secret is not None
        async with httpx.AsyncClient(transport=self.transport, timeout=15) as http:
            try:
                token = await self._exchange(http, code)
                headers = {
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                }
                user_res = await http.get(f"{API_URL}/user", headers=headers)
                emails_res = await http.get(f"{API_URL}/user/emails", headers=headers)
            except httpx.HTTPError as exc:
                raise GitHubUnavailable("GitHub couldn't be reached; try again shortly") from exc
        if user_res.status_code != 200:
            raise GitHubUnavailable("GitHub didn't return your account; try again shortly")
        if emails_res.status_code in (403, 404):
            raise GitHubUnavailable(
                "The GitHub app can't read email addresses: give it the Email addresses "
                "(read-only) account permission, or the user:email scope"
            )
        if emails_res.status_code != 200:
            raise GitHubUnavailable("GitHub didn't return your email addresses; try again shortly")
        user = user_res.json()
        return GitHubProfile(
            id=str(user["id"]),
            login=user["login"],
            name=user.get("name") or None,
            verified_email=_verified_email(emails_res.json()),
        )

    async def _exchange(self, http: httpx.AsyncClient, code: str) -> str:
        assert self.client_secret is not None
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret.get_secret_value(),
            "code": code,
        }
        if self.redirect_uri:
            data["redirect_uri"] = self.redirect_uri
        res = await http.post(TOKEN_URL, data=data, headers={"Accept": "application/json"})
        if res.status_code != 200:
            raise GitHubUnavailable("GitHub didn't accept the sign-in; try again shortly")
        body = res.json()
        # GitHub answers 200 with an "error" for a bad, used, or expired code.
        token = body.get("access_token")
        if body.get("error") == "incorrect_client_credentials":
            raise GitHubUnavailable("GitHub rejected the app's client ID or secret (check PMAGENT_GITHUB_* in .env)")
        if body.get("error") == "redirect_uri_mismatch":
            raise GitHubUnavailable("PMAGENT_GITHUB_REDIRECT_URI isn't one of the GitHub app's callback URLs")
        if not token:
            raise Unauthorized("The GitHub sign-in expired or was already used; try again")
        return str(token)

    def _require_config(self) -> None:
        if not self.configured:
            raise GitHubUnavailable(
                "Sign-in with GitHub isn't set up (set PMAGENT_GITHUB_CLIENT_ID and "
                "PMAGENT_GITHUB_CLIENT_SECRET in .env)"
            )


def _verified_email(emails: list[dict]) -> str | None:
    verified = [e for e in emails if e.get("verified") and e.get("email")]
    # GitHub's private relay addresses can't receive our email; prefer a real one.
    real = [e for e in verified if not str(e["email"]).endswith("@users.noreply.github.com")]
    for candidates in (real, verified):
        primary = next((e for e in candidates if e.get("primary")), None)
        chosen = primary or (candidates[0] if candidates else None)
        if chosen:
            return str(chosen["email"]).lower()
    return None


def get_github(settings: SettingsDep) -> GitHubClient:
    return GitHubOAuth(settings)


GitHubDep = Annotated[GitHubClient, Depends(get_github)]
