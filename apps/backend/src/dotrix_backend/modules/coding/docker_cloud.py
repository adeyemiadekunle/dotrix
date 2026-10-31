"""Kai's sandboxes on Docker Cloud (`DOTRIX_CODING_SANDBOX=docker-cloud`): the Docker Sandboxes API.

Each run gets a sandbox of its own (a microVM) from the coding image, pulled from a registry
(`DOTRIX_CODING_IMAGE`, e.g. `docker.io/acme/dotrix-coding:0.1.0`), under an inline network policy that
denies everything but the tool's model API. Docker enforces it before the first process starts, so no
egress proxy of ours is needed. Through the same `SandboxSession` as the other sandboxes:

- the repo goes in as a tar uploaded through the sandbox's file service, then unpacked;
- a command is a process: its output is read page by page from a cursor (stdout a line at a time to
  `on_line`, stderr's tail kept), stdin is uploaded as a file and becomes the process's standard
  input, Stop sends SIGINT and SIGKILL after a grace, and the time limit SIGKILL;
- the model key is a secret stored in Docker: the sandbox holds a placeholder, and Docker writes the
  real key into the model API's requests only (`key_injection`). If Docker takes no secret, the key
  goes in each process's environment instead (never the sandbox's settings or argv), and then only
  the model API may be reachable: extra hosts an owner allowed are refused rather than given the key;
- extra hosts owners and admins allow (Settings → Network) join the model API in the policy;
- between turns a session's sandbox sleeps (stopped: files kept, no compute) and wakes for the next
  (`handle`, `sleep`, `wake`, `discard`); the sweep deletes what nothing refers to any more;
- the sandbox's own timeout stops it if the worker never does (a crash), renewed by each command.

Like the others, a sandbox never receives a GitHub token: the worker clones and pushes. Management
calls use an access token exchanged from a Docker personal access token with Cloud Sandboxes access
(`DOTRIX_DOCKER_CLOUD_ID`, `DOTRIX_DOCKER_CLOUD_PAT`); file and process calls use short-lived
credentials scoped to one sandbox. Docker labels the API experimental:
https://docs.docker.com/reference/api/sandboxes/latest/
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from dotrix_backend.core.settings import Settings

from .models import CodingAgent
from .sandbox import (
    CAPTURE_LIMIT,
    DOCKER_HOME,
    STDERR_TAIL,
    ExecResult,
    LineHandler,
    SandboxError,
    SandboxSession,
    _tar_of,
)
from .tools import CodingTool

logger = logging.getLogger(__name__)

API_URL = "https://connect.docker.com/sandboxes"
TOKEN_URL = "https://hub.docker.com/v2/auth/token"  # a PAT exchanged for a short-lived access token
TOKEN_LIFETIME = 240.0  # seconds an access token is reused before it's exchanged again
REPO = f"{DOCKER_HOME}/repo"
READY_TIMEOUT = 300.0  # creating (pulling the image) and starting
READY_POLL = 2.0
REQUEST_TIMEOUT = 60.0
RETRIES = 5  # a rate limit or a passing failure (429, 502, 503, 504) on one request
POLL_MIN, POLL_MAX = 0.25, 1.0  # seconds between output reads: quick while a command talks
PAGE_BYTES = 512_000
STOP_GRACE = 5.0  # seconds between SIGINT (finish cleanly) and SIGKILL, as in the other sandboxes
KILL_WAIT = 30.0  # seconds a killed process gets to report its exit before it's given up on
SIZES = (1, 2, 4, 8, 16)  # CPUs; Docker pairs each with 2 GiB of memory per CPU
CREDENTIAL_PERMISSIONS = ["sandboxesExec", "sandboxesFilesRead", "sandboxesFilesWrite"]


PREFIX = "dotrix-run-"
ORPHAN_AGE = 3600.0  # a stopped sandbox (or a secret) no session refers to, this old, is left over


def display_name(run_id: uuid.UUID) -> str:
    return f"{PREFIX}{run_id.hex[-16:]}"


def _id(resource: dict[str, Any]) -> str:
    return str(resource.get("uid") or str(resource["name"]).rsplit("/", 1)[-1])


def _created(value: Any) -> float:
    """An RFC 3339 timestamp as seconds since the epoch; an unknown one counts as now (kept)."""
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return time.time()


def size_for(cpus: float) -> dict[str, int]:
    """The supported CPU and memory pair nearest `cpus` (Docker accepts only these pairs)."""
    chosen = min(SIZES, key=lambda size: (abs(size - cpus), size))
    return {"cpus": chosen, "memoryMib": chosen * 2048}


def _problem(response: httpx.Response) -> str:
    """Docker's error, safe to store: its code and message (never a token; it sends none)."""
    try:
        body = response.json()
    except ValueError:
        return f"HTTP {response.status_code}"
    error = body.get("error", body) if isinstance(body, dict) else {}
    code, message = error.get("code"), error.get("message")
    return f"{code}: {message}"[:300] if code or message else f"HTTP {response.status_code}"


@dataclass
class _Credential:
    token: str
    until: float


class DockerCloudApi:
    """The Sandboxes API: management calls with the account's access token, sandbox calls (files,
    processes) with a credential scoped to that sandbox. Retries rate limits and passing failures."""

    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None) -> None:
        if not settings.docker_cloud_id or settings.docker_cloud_pat is None:
            raise SandboxError("Docker Cloud sandboxes need DOTRIX_DOCKER_CLOUD_ID and DOTRIX_DOCKER_CLOUD_PAT")
        self.base = settings.docker_cloud_url.rstrip("/")
        self.docker_id = settings.docker_cloud_id
        self.pat = settings.docker_cloud_pat
        self.http = httpx.AsyncClient(transport=transport, timeout=REQUEST_TIMEOUT)
        self._access: _Credential | None = None
        self._lock = asyncio.Lock()

    async def access_token(self, *, renew: bool = False) -> str:
        async with self._lock:
            if renew or self._access is None or self._access.until <= time.monotonic():
                try:
                    res = await self.http.post(TOKEN_URL, json={"identifier": self.docker_id,
                                                                "secret": self.pat.get_secret_value()})
                except httpx.HTTPError as exc:
                    raise SandboxError("Docker couldn't be reached to sign in") from exc
                if res.status_code != 200 or not res.json().get("access_token"):
                    raise SandboxError("Docker refused the access token (DOTRIX_DOCKER_CLOUD_PAT needs "
                                       f"Cloud Sandboxes access): HTTP {res.status_code}")
                self._access = _Credential(res.json()["access_token"], time.monotonic() + TOKEN_LIFETIME)
            return self._access.token

    async def call(
        self, method: str, url: str, *, token: str | None = None, ok: tuple[int, ...] = (200, 201, 202, 204),
        **kwargs: Any,
    ) -> httpx.Response:
        """One request: with `token` (a sandbox credential) or the account's, retried on a rate limit
        or a passing failure, the account's token renewed once if it's refused."""
        renewed = False
        headers = kwargs.pop("headers", {})  # kept for every retry (Idempotency-Key, If-Match)
        for attempt in range(RETRIES):
            bearer = token or await self.access_token()
            try:
                res = await self.http.request(method, url, headers={**headers, "Authorization": f"Bearer {bearer}"},
                                              **kwargs)
            except httpx.HTTPError as exc:
                if attempt == RETRIES - 1:
                    raise SandboxError(f"Docker Cloud couldn't be reached: {type(exc).__name__}") from exc
                await asyncio.sleep(2 ** attempt)
                continue
            if res.status_code in ok:
                return res
            if res.status_code == 401 and token is None and not renewed:
                renewed = True
                await self.access_token(renew=True)
                continue
            if res.status_code in (429, 502, 503, 504) and attempt < RETRIES - 1:
                wait = res.headers.get("Retry-After")
                await asyncio.sleep(float(wait) if wait and wait.replace(".", "", 1).isdigit() else 2 ** attempt)
                continue
            raise SandboxError(f"Docker Cloud refused {method} {url.removeprefix(self.base)}: {_problem(res)}")
        raise SandboxError(f"Docker Cloud kept refusing {method} {url.removeprefix(self.base)}")

    async def aclose(self) -> None:
        await self.http.aclose()


@dataclass
class DockerCloudSession:
    api: DockerCloudApi
    sandbox_id: str
    endpoint: str  # where its file and process services are
    env: dict[str, str]  # each process's: the tool's key, HOME, LANG
    ttl: int  # seconds the sandbox outlives the worker's last command
    secret: str | None = None  # the key, stored in Docker (deleted with the sandbox)
    placeholder: str | None = None  # what the tool holds instead of the key, when it's a secret
    _credential: _Credential | None = None
    _closed: bool = False
    _uploads: int = 0

    # -- the sandbox's own services ------------------------------------------------------

    async def _token(self) -> str:
        if self._credential is None or self._credential.until <= time.monotonic():
            res = await self.api.call("POST", f"{self.api.base}/v1/sandboxes/{self.sandbox_id}/endpoint-credentials",
                                      json={"permissions": CREDENTIAL_PERMISSIONS, "ttl": "300s"})
            body = res.json()
            # Renewed a minute early: a credential lasts at most five minutes.
            self._credential = _Credential(body["token"], time.monotonic() + 240)
        return self._credential.token

    async def _endpoint(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            return await self.api.call(method, f"{self.endpoint}{path}", token=await self._token(), **kwargs)
        except SandboxError:
            self._credential = None  # refused (expired early?): the next call asks for a new one
            raise

    async def upload(self, path: str, data: bytes, mode: int = 0o600) -> None:
        """One file into the sandbox: a metadata part, then its bytes."""
        files = [("metadata", (None, json.dumps({"path": path, "mode": mode}), "application/json")),
                 ("content", ("content", data, "application/octet-stream"))]
        await self._endpoint("POST", "/v1/files/upload", files=files)

    async def renew(self) -> None:
        """Push the sandbox's own deadline out: a crashed worker's sandbox still goes away."""
        try:
            await self.api.call("POST", f"{self.api.base}/v1/sandboxes/{self.sandbox_id}/renew-timeout",
                                json={"timeout": f"{self.ttl}s"})
        except SandboxError as exc:
            logger.warning("docker cloud sandbox %s: couldn't renew its timeout: %s", self.sandbox_id, exc)

    # -- SandboxSession --------------------------------------------------------------------

    async def exec(
        self, argv: list[str], *, stdin: bytes | None = None, on_line: LineHandler | None = None,
        timeout: float, cancel: asyncio.Event | None = None, cwd: str = REPO,
    ) -> ExecResult:
        if self._closed:
            raise SandboxError("The sandbox is closed")
        await self.renew()
        if stdin is not None:
            self._uploads += 1
            feed = f"/tmp/dotrix-stdin-{self._uploads}"
            await self.upload(feed, stdin)
            # Opened as standard input, then removed, then the command itself (so signals reach it).
            argv = ["sh", "-c", 'f=$1; shift; exec 0<"$f"; rm -f "$f"; exec "$@"', "sh", feed, *argv]
        res = await self._endpoint("POST", "/v1/processes", json={"cmd": argv, "env": self.env, "workingDir": cwd},
                                   headers={"Idempotency-Key": str(uuid.uuid4())})
        process = res.json()
        pid = str(process.get("uid") or process["name"].rsplit("/", 1)[-1])
        return await self._follow(pid, on_line=on_line, timeout=timeout, cancel=cancel)

    async def _signal(self, pid: str, sig: str) -> None:
        try:
            await self._endpoint("POST", f"/v1/processes/{pid}/signal", json={"signal": sig})
        except SandboxError as exc:
            logger.warning("docker cloud sandbox %s: couldn't send %s: %s", self.sandbox_id, sig, exc)

    async def _follow(
        self, pid: str, *, on_line: LineHandler | None, timeout: float, cancel: asyncio.Event | None,
    ) -> ExecResult:
        """Read a process's output until it exits: stdout a line at a time to `on_line` (or kept, up to
        a limit), stderr's tail kept. Stop: SIGINT, SIGKILL after the grace; the time limit: SIGKILL."""
        cursor, poll = 0, POLL_MIN
        pending, kept, err = bytearray(), bytearray(), bytearray()
        truncated = timed_out = cancelled = False
        deadline = time.monotonic() + timeout
        stop_by: float | None = None  # when a stopped process is killed, if it hasn't ended by then
        killed_at: float | None = None

        async def emit(raw: bytes) -> None:
            nonlocal truncated
            if on_line is not None:
                await on_line(raw.decode(errors="replace"))
            elif len(kept) + len(raw) <= CAPTURE_LIMIT:
                kept.extend(raw)
            else:
                truncated = True

        while True:
            res = await self._endpoint("GET", f"/v1/processes/{pid}/output",
                                       params={"resumeFrom": cursor, "maxBytes": PAGE_BYTES})
            page = res.json()
            chunks = page.get("chunks") or []
            for chunk in chunks:
                data = base64.b64decode(chunk.get("data") or "")
                if chunk.get("stream") == "stderr":
                    err.extend(data)
                    del err[: max(0, len(err) - STDERR_TAIL)]
                    continue
                pending.extend(data)
                while (end := pending.find(b"\n")) >= 0:
                    line = bytes(pending[: end + 1])
                    del pending[: end + 1]
                    await emit(line)
            cursor = int(page.get("nextResumeFrom") or cursor)
            exited = page.get("exited")
            if exited is not None:
                if pending:
                    await emit(bytes(pending))
                code = exited.get("exitCode")
                return ExecResult(
                    code=None if timed_out else (int(code) if code is not None else None),
                    stdout=kept.decode(errors="replace"), stderr=err.decode(errors="replace"),
                    timed_out=timed_out, cancelled=cancelled, truncated=truncated,
                )
            now = time.monotonic()
            if killed_at is not None and now >= killed_at + KILL_WAIT:
                logger.warning("docker cloud sandbox %s: process %s didn't report its exit", self.sandbox_id, pid)
                return ExecResult(code=None, stdout=kept.decode(errors="replace"), stderr=err.decode(errors="replace"),
                                  timed_out=timed_out, cancelled=cancelled, truncated=truncated)
            if killed_at is None and not timed_out and now >= deadline:
                timed_out, killed_at = True, now
                await self._signal(pid, "kill")
            elif cancel is not None and cancel.is_set() and not cancelled:
                cancelled, stop_by = True, now + STOP_GRACE
                await self._signal(pid, "int")  # Claude Code ends its turn cleanly, with its result
            elif stop_by is not None and killed_at is None and now >= stop_by:
                killed_at = now
                await self._signal(pid, "kill")
            poll = POLL_MIN if chunks else min(POLL_MAX, poll * 2)
            await asyncio.sleep(poll)

    async def blocked_hosts(self, since: datetime) -> list[str]:
        """The hosts the network policy refused since `since` (Docker's policy log), most attempted first."""
        res = await self.api.call("GET", f"{self.api.base}/v1/sandboxes/{self.sandbox_id}/policy-logs", params={
            "filter": "domain=network", "since": since.astimezone(UTC).isoformat().replace("+00:00", "Z"), "pageSize": 100})
        counts: dict[str, int] = {}
        for entry in res.json().get("entries") or []:
            if entry.get("decision") == "blocked" and entry.get("resource"):
                host = str(entry["resource"]).split("://")[-1].split("/")[0].rsplit(":", 1)[0]
                counts[host] = counts.get(host, 0) + int(entry.get("count") or 1)
        return sorted(counts, key=lambda h: -counts[h])

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await delete_sandbox(self.api, self.sandbox_id)
        if self.secret:
            await delete_secret(self.api, self.secret)


async def _etag(api: DockerCloudApi, url: str) -> str | None:
    """A resource's current ETag (what a change to it must send), or None when it's gone."""
    current = await api.call("GET", url, ok=(200, 404))
    if current.status_code == 404:
        return None
    body = current.json()
    return (body.get("core") or {}).get("etag") or body.get("etag") or current.headers.get("ETag") or "*"


async def delete_sandbox(api: DockerCloudApi, sandbox_id: str) -> None:
    url = f"{api.base}/v1/sandboxes/{sandbox_id}"
    try:
        etag = await _etag(api, url)
        if etag is not None:
            await api.call("DELETE", url, params={"force": "true"}, ok=(200, 202, 204, 404),
                           headers={"If-Match": etag, "Idempotency-Key": str(uuid.uuid4())})
    except SandboxError as exc:  # its own timeout stops it; the sweep deletes it
        logger.warning("docker cloud sandbox %s: couldn't delete it: %s", sandbox_id, exc)


async def delete_secret(api: DockerCloudApi, secret: str) -> None:
    url = f"{api.base}/v1/secrets/{secret.rsplit('/', 1)[-1]}"
    try:
        etag = await _etag(api, url)
        if etag is not None:
            await api.call("DELETE", url, ok=(200, 202, 204, 404), headers={"If-Match": etag})
    except SandboxError as exc:  # the sweep deletes it
        logger.warning("docker cloud secret %s: couldn't delete it: %s", secret, exc)


def key_injection(tool: CodingTool) -> dict[str, str]:
    """How the tool sends its key to its model API: the header Docker writes the real key into, and the
    shape of the placeholder the tool holds instead (some check a key's prefix before sending it)."""
    host = tool.api_host
    if tool.agent is CodingAgent.FX:  # fx speaks the OpenAI-compatible API to every provider
        header, value = "Authorization", "Bearer %s"
    elif host == "api.anthropic.com":
        header, value = "x-api-key", "%s"
    elif host == "generativelanguage.googleapis.com":
        header, value = "x-goog-api-key", "%s"
    else:
        header, value = "Authorization", "Bearer %s"
    template = {"api.anthropic.com": "sk-ant-api03-{rand}", "api.openai.com": "sk-proj-{rand}"}.get(host, "sk-{rand}")
    return {"header": header, "format": value, "placeholderTemplate": template}


# Hosts Docker serves itself (its managed integrations): a custom secret for them is refused, so the key
# goes in as that service's token instead. Which hosts these are isn't documented; these are expected.
MANAGED = {"api.anthropic.com": "anthropic", "api.openai.com": "openai"}
PLACEHOLDER = "sk-dotrix-placeholder"  # what the tool holds when Docker's own integration writes the key


class DockerCloudSandbox:
    kind = "docker-cloud"
    sleeps = True  # a session's sandbox can sleep between turns (stopped, files kept) and wake for the next

    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.api = DockerCloudApi(settings, transport)
        self.image = settings.coding_image
        self.resources = size_for(settings.coding_cpus)
        self.inject = settings.docker_cloud_key_injection
        # A turn, then up to the idle time kept warm between turns, with room to spare. At that deadline
        # Docker stops it (a crashed worker's sandbox stops billing); the sweep deletes what's left.
        self.ttl = int((settings.coding_timeout_minutes + max(settings.coding_idle_minutes, 0) + 10) * 60)

    def create_body(self, run_id: uuid.UUID, tool: CodingTool, allow: list[str], secret: str | None) -> dict[str, Any]:
        """The sandbox: our image, sleeping until commands come; only the model API (and the hosts an owner
        allowed) reachable; stopped by its own timeout if nobody stops it. The key is a stored secret
        Docker writes into the model API's requests, or (without one) goes with each process."""
        features: dict[str, Any] = {"timeouts": {"timeout": f"{self.ttl}s", "onTimeout": "stop"}}
        if secret:
            features["storedSecrets"] = {"secrets": [secret]}
        return {
            "displayName": display_name(run_id),
            "imageRef": self.image,
            "resources": self.resources,
            "labels": {"dotrix-run": str(run_id)},
            "networkPolicies": [{"mode": "denyAll", "allowNetworks": [tool.api_host, *[h for h in allow if h != tool.api_host]]}],
            "startupExecution": {"rawImage": {"start": {"argv": ["sleep", "infinity"]}}},
            "features": features,
        }

    async def _secret(self, run_id: uuid.UUID, tool: CodingTool, model_key: str) -> tuple[str, str] | None:
        """The key as a Docker secret: (its resource name, the placeholder the tool holds), or None when
        Docker takes neither form (the caller decides whether the key may go in the sandbox instead)."""
        injection = key_injection(tool)
        body: dict[str, Any] = {"displayName": display_name(run_id), "custom": {
            "value": model_key, "injection": {"hosts": [tool.api_host], "header": injection["header"],
                                             "format": injection["format"], "envVar": tool.key_env,
                                             "placeholderTemplate": injection["placeholderTemplate"]}}}
        try:
            res = await self.api.call("POST", f"{self.api.base}/v1/secrets", json=body,
                                      headers={"Idempotency-Key": str(uuid.uuid4())})
            created = res.json()
            return str(created["name"]), str(created.get("placeholder") or PLACEHOLDER)
        except SandboxError as exc:
            service = MANAGED.get(tool.api_host)
            if service is None:
                logger.warning("docker cloud: the key couldn't be stored as a secret: %s", exc)
                return None
        try:  # a host Docker serves itself: its token
            res = await self.api.call("POST", f"{self.api.base}/v1/secrets", json={
                "displayName": display_name(run_id), "serviceType": service, "token": {"value": model_key}},
                headers={"Idempotency-Key": str(uuid.uuid4())})
            created = res.json()
            return str(created["name"]), str(created.get("placeholder") or PLACEHOLDER)
        except SandboxError as exc:
            logger.warning("docker cloud: the key couldn't be stored as a secret: %s", exc)
            return None

    async def _ready(self, sandbox: dict[str, Any]) -> dict[str, Any]:
        """Wait for a sandbox Docker accepted (202) to be running."""
        sandbox_id = _id(sandbox)
        deadline = time.monotonic() + READY_TIMEOUT
        while True:
            status = (sandbox.get("core") or {}).get("status")
            if status == "running":
                return sandbox
            if status in ("failed", "deleting", "stopped"):
                failure = (sandbox.get("failure") or {}).get("message") or status
                raise SandboxError(f"The Docker Cloud sandbox didn't start: {str(failure)[:300]}")
            if time.monotonic() >= deadline:
                raise SandboxError("The Docker Cloud sandbox took too long to start")
            await asyncio.sleep(READY_POLL)
            sandbox = (await self.api.call("GET", f"{self.api.base}/v1/sandboxes/{sandbox_id}")).json()

    def _env(self, tool: CodingTool, key_or_placeholder: str) -> dict[str, str]:
        return {**tool.sandbox_env(key_or_placeholder), "HOME": DOCKER_HOME, "LANG": "C.UTF-8"}

    async def open(
        self, run_id: uuid.UUID, source: Path, tool: CodingTool, model_key: str, *, allow: list[str] | tuple = (),
    ) -> SandboxSession:
        allow = list(allow)
        stored = await self._secret(run_id, tool, model_key) if self.inject else None
        if stored is None and [h for h in allow if h != tool.api_host]:
            # Another reachable host would be somewhere the key could be sent: never with the key inside.
            raise SandboxError("The model key couldn't be kept out of the sandbox, so it can't reach the extra "
                               "hosts allowed in Settings → Network; remove them, or try again")
        secret, placeholder = stored if stored else (None, None)
        try:
            created = await self.api.call("POST", f"{self.api.base}/v1/sandboxes",
                                          json=self.create_body(run_id, tool, allow, secret),
                                          headers={"Idempotency-Key": str(uuid.uuid4())})
        except BaseException:
            if secret:
                await delete_secret(self.api, secret)
            raise
        sandbox = created.json()
        session = DockerCloudSession(self.api, _id(sandbox), endpoint="", env=self._env(tool, placeholder or model_key),
                                     ttl=self.ttl, secret=secret, placeholder=placeholder)
        try:
            await self._connect(session, sandbox)
            await session.upload("/tmp/dotrix-repo.tar", await asyncio.to_thread(_tar_of, source))
            unpacked = await session.exec(
                ["sh", "-c", f"tar -x -f /tmp/dotrix-repo.tar -C {DOCKER_HOME} && rm -f /tmp/dotrix-repo.tar"],
                timeout=READY_TIMEOUT, cwd=DOCKER_HOME,
            )
            if unpacked.code != 0:
                raise SandboxError(f"The repo couldn't be unpacked in the sandbox: {unpacked.stderr[-300:]}")
        except BaseException:
            await session.close()
            raise
        return session

    async def _connect(self, session: DockerCloudSession, sandbox: dict[str, Any]) -> None:
        sandbox = await self._ready(sandbox)
        endpoint = ((sandbox.get("core") or {}).get("endpoint") or {}).get("uri")
        if not endpoint:
            raise SandboxError("The Docker Cloud sandbox has no endpoint for files and commands")
        session.endpoint, session._credential = str(endpoint).rstrip("/"), None

    # -- sleeping between turns ---------------------------------------------------------------

    def handle(self, box: SandboxSession) -> dict[str, Any] | None:
        """What it takes to wake `box` later, from any worker (stored on its coding session; no key in it)."""
        if not isinstance(box, DockerCloudSession):
            return None
        return {"kind": self.kind, "sandbox": box.sandbox_id, "secret": box.secret, "placeholder": box.placeholder}

    async def sleep(self, box: SandboxSession) -> None:
        """Stop the sandbox: its files (and installed dependencies) kept, no compute billed until it wakes."""
        if not isinstance(box, DockerCloudSession):
            await box.close()
            return
        url = f"{self.api.base}/v1/sandboxes/{box.sandbox_id}"
        box._closed = True  # this object is done; waking makes a new one
        try:
            etag = await _etag(self.api, url)
            if etag is not None:
                await self.api.call("POST", f"{url}/stop", json={}, headers={"If-Match": etag,
                                                                            "Idempotency-Key": str(uuid.uuid4())})
        except SandboxError as exc:  # left running, its own timeout stops it
            logger.warning("docker cloud sandbox %s: couldn't stop it: %s", box.sandbox_id, exc)

    async def wake(self, handle: dict[str, Any], tool: CodingTool, model_key: str) -> SandboxSession | None:
        """The sleeping sandbox, started again; None when it's gone or won't start (it's then deleted)."""
        sandbox_id = str(handle.get("sandbox") or "")
        if not sandbox_id:
            return None
        url = f"{self.api.base}/v1/sandboxes/{sandbox_id}"
        placeholder = handle.get("placeholder")
        session = DockerCloudSession(self.api, sandbox_id, endpoint="", env=self._env(tool, placeholder or model_key),
                                     ttl=self.ttl, secret=handle.get("secret"), placeholder=placeholder)
        try:
            current = await self.api.call("GET", url, ok=(200, 404))
            if current.status_code == 404:
                if session.secret:
                    await delete_secret(self.api, session.secret)
                return None
            sandbox = current.json()
            if (sandbox.get("core") or {}).get("status") != "running":
                etag = (sandbox.get("core") or {}).get("etag") or "*"
                sandbox = (await self.api.call("POST", f"{url}/start", json={}, headers={
                    "If-Match": etag, "Idempotency-Key": str(uuid.uuid4())})).json()
            await self._connect(session, sandbox)
            await session.renew()
            return session
        except SandboxError as exc:
            logger.warning("docker cloud sandbox %s: couldn't wake it: %s", sandbox_id, exc)
            await session.close()
            return None

    async def discard(self, handle: dict[str, Any]) -> None:
        """Delete a sleeping sandbox and its key."""
        if handle.get("sandbox"):
            await delete_sandbox(self.api, str(handle["sandbox"]))
        if handle.get("secret"):
            await delete_secret(self.api, str(handle["secret"]))

    async def sweep(self, keep: set[str], min_age: float = ORPHAN_AGE) -> int:
        """Delete dotrix's stopped sandboxes no session refers to (`keep`: the sandbox ids sessions hold),
        and dotrix's secrets whose sandbox is gone, all older than `min_age` seconds: what a crash or a
        deleted session left behind. Running sandboxes are never touched (a turn may be using one).
        Returns how many sandboxes were deleted."""
        cutoff = time.time() - min_age
        sandboxes = await self._all("/v1/sandboxes", "sandboxes")
        names = {s.get("displayName") for s in sandboxes}
        deleted = 0
        for sandbox in sandboxes:
            core = sandbox.get("core") or {}
            if (not str(sandbox.get("displayName") or "").startswith(PREFIX) or _id(sandbox) in keep
                    or core.get("status") != "stopped" or _created(core.get("createdAt")) > cutoff):
                continue
            await delete_sandbox(self.api, _id(sandbox))
            names.discard(sandbox.get("displayName"))
            deleted += 1
        for secret in await self._all("/v1/secrets", "secrets"):
            name = str(secret.get("displayName") or "")
            if name.startswith(PREFIX) and name not in names and _created(secret.get("createdAt")) <= cutoff:
                await delete_secret(self.api, str(secret.get("name") or ""))
        return deleted

    async def _all(self, path: str, field: str) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []
        token = ""
        for _ in range(50):
            res = await self.api.call("GET", f"{self.api.base}{path}",
                                      params={"pageSize": 100, **({"pageToken": token} if token else {})})
            body = res.json()
            found += body.get(field) or []
            token = body.get("nextPageToken") or ""
            if not token:
                break
        return found

