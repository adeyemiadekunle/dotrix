"""Talking to the pmagent platform: credentials, the HTTP client, and device login.

Credentials live in the OS keychain (Windows Credential Manager, macOS Keychain,
Secret Service on Linux) via `keyring`, keyed by API URL. They are never written
to a config file. `PMAGENT_TOKEN` overrides the keychain for CI and scripts.
"""
from __future__ import annotations

import json
import logging
import os
import time
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

# The MCP server's logging setup would otherwise print every request to stderr.
logging.getLogger("httpx").setLevel(logging.WARNING)

DEFAULT_API_URL = "http://127.0.0.1:8000"
KEYRING_SERVICE = "pmagent"
CLIENT_NAME = "pmagent CLI"


def api_url(value: str | None = None) -> str:
    return (value or os.environ.get("PMAGENT_API_URL") or DEFAULT_API_URL).rstrip("/")


class PlatformError(Exception):
    """An API error, carrying the problem `type` (e.g. "nothing_ready") and its detail."""

    def __init__(self, status: int, code: str, detail: str) -> None:
        super().__init__(detail)
        self.status, self.code, self.detail = status, code, detail


NO_KEYCHAIN_HINT = (
    "This machine has no OS keychain (common on servers, CI, and containers), so pmagent can't "
    "store a sign-in here. Set PMAGENT_TOKEN to an API token instead (create one in the web app, "
    "or POST /v1/me/tokens), or install a keyring backend such as keyrings.alt."
)


class NotSignedIn(PlatformError):
    def __init__(self, url: str, *, no_keychain: bool = False) -> None:
        detail = f"Not signed in to {url}. Run `pmagent login`."
        if no_keychain:
            detail = f"Not signed in to {url}. {NO_KEYCHAIN_HINT}"
        super().__init__(401, "not_signed_in", detail)


class KeychainUnavailable(PlatformError):
    def __init__(self) -> None:
        super().__init__(0, "no_keychain", NO_KEYCHAIN_HINT)


# -- credentials ---------------------------------------------------------------------


@dataclass(frozen=True)
class Credential:
    token: str
    token_id: str | None = None  # lets `logout` revoke it on the server


class CredentialStore(Protocol):
    def get(self, url: str) -> Credential | None: ...
    def set(self, url: str, credential: Credential) -> None: ...
    def delete(self, url: str) -> None: ...


class KeyringStore:
    """The OS keychain. Machines without one (headless Linux, containers, CI) behave as
    "not signed in" rather than crashing; `unavailable` says why."""

    def __init__(self) -> None:
        self.unavailable = False

    def get(self, url: str) -> Credential | None:
        import keyring
        from keyring.errors import KeyringError

        try:
            raw = keyring.get_password(KEYRING_SERVICE, url)
        except KeyringError:
            self.unavailable = True
            return None
        if not raw:
            return None
        data = json.loads(raw)
        return Credential(data["token"], data.get("token_id"))

    def set(self, url: str, credential: Credential) -> None:
        import keyring
        from keyring.errors import KeyringError

        try:
            keyring.set_password(
                KEYRING_SERVICE, url, json.dumps({"token": credential.token, "token_id": credential.token_id})
            )
        except KeyringError as exc:
            self.unavailable = True
            raise KeychainUnavailable() from exc

    def delete(self, url: str) -> None:
        import keyring
        from keyring.errors import KeyringError

        try:
            keyring.delete_password(KEYRING_SERVICE, url)
        except KeyringError:  # not stored, or no keychain at all: nothing to remove
            pass


class MemoryStore:
    """For tests."""

    def __init__(self) -> None:
        self.items: dict[str, Credential] = {}

    def get(self, url: str) -> Credential | None:
        return self.items.get(url)

    def set(self, url: str, credential: Credential) -> None:
        self.items[url] = credential

    def delete(self, url: str) -> None:
        self.items.pop(url, None)


def load_credential(url: str, store: CredentialStore | None = None) -> Credential | None:
    if token := os.environ.get("PMAGENT_TOKEN"):
        return Credential(token)
    return (store or KeyringStore()).get(url)


# -- HTTP ----------------------------------------------------------------------------


class PlatformClient:
    def __init__(self, url: str, token: str | None = None, *, http: httpx.Client | None = None) -> None:
        self.url = url
        self.http = http or httpx.Client(base_url=url, timeout=30)
        self.token = token

    @classmethod
    def signed_in(cls, url: str | None = None, store: CredentialStore | None = None) -> PlatformClient:
        resolved = api_url(url)
        store = store or KeyringStore()
        credential = load_credential(resolved, store)
        if credential is None:
            raise NotSignedIn(resolved, no_keychain=getattr(store, "unavailable", False))
        return cls(resolved, credential.token)

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        headers = kwargs.pop("headers", {})
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        try:
            response = self.http.request(method, f"/v1{path}", headers=headers, **kwargs)
        except httpx.TransportError as exc:
            raise PlatformError(0, "unreachable", f"Can't reach {self.url}: {exc}") from exc
        if response.status_code >= 400:
            try:
                body = response.json()
                code = str(body.get("type", "")).rsplit("/", 1)[-1] or "error"
                detail = body.get("detail") or response.reason_phrase
            except ValueError:
                code, detail = "error", response.text or response.reason_phrase
            if response.status_code == 401 and self.token:
                detail += " (run `pmagent login` again)"
            raise PlatformError(response.status_code, code, detail)
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    def get(self, path: str, **kw: Any) -> Any:
        return self.request("GET", path, **kw)

    def post(self, path: str, body: Any = None, **kw: Any) -> Any:
        return self.request("POST", path, json=body, **kw)

    def patch(self, path: str, body: Any, **kw: Any) -> Any:
        return self.request("PATCH", path, json=body, **kw)

    def put(self, path: str, body: Any = None, **kw: Any) -> Any:
        return self.request("PUT", path, json=body, **kw)

    def delete(self, path: str, **kw: Any) -> Any:
        return self.request("DELETE", path, **kw)


# -- device login (RFC 8628) -----------------------------------------------------------


def device_login(
    client: PlatformClient,
    *,
    show: Callable[[str, str, str], None],
    open_browser: bool = True,
    sleep: Callable[[float], None] | None = None,
    scopes: list[str] | None = None,
) -> Credential:
    """Start a device login, let the user approve it in the browser, and return the token.

    `show(user_code, verification_uri, verification_uri_complete)` tells the user what to do.
    """
    start = client.post("/auth/device/code", {"client_name": CLIENT_NAME, "scopes": scopes or ["read", "write"]})
    show(start["user_code"], start["verification_uri"], start["verification_uri_complete"])
    if open_browser:
        try:
            webbrowser.open(start["verification_uri_complete"])
        except Exception:  # noqa: BLE001 - no browser is fine; the URL was printed
            pass
    sleep = sleep or time.sleep  # looked up at call time, so tests can patch it
    interval = float(start["interval"])
    deadline = time.monotonic() + float(start["expires_in"])
    while time.monotonic() < deadline:
        sleep(interval)
        try:
            issued = client.post("/auth/device/token", {"device_code": start["device_code"]})
            return Credential(issued["token"], issued["id"])
        except PlatformError as exc:
            if exc.code == "authorization_pending":
                continue
            if exc.code == "slow_down":
                interval += 5
                continue
            raise
    raise PlatformError(400, "expired_token", "The sign-in code expired; run `pmagent login` again.")
