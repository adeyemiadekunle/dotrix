"""Kai's sandbox on Docker Cloud, against a fake of the Docker Sandboxes API (no network, no account)."""
import asyncio
import base64
import email
import email.policy
import io
import json
import tarfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import pytest

from dotrix_backend.core.settings import Settings
from dotrix_backend.modules.coding import docker_cloud
from dotrix_backend.modules.coding.docker_cloud import DockerCloudSandbox, size_for
from dotrix_backend.modules.coding.sandbox import SandboxError, build_sandbox
from dotrix_backend.modules.coding.tools import ClaudeCode

IMAGE = "docker.io/acme/dotrix-coding:0.1.0"
ENDPOINT = "https://sbx-1.endpoint.test/api"
KEY = "sk-ant-test-key"


def _settings(**values) -> Settings:
    base = {"database_url": "postgresql+asyncpg://localhost/unused", "jwt_secret": "x" * 40,
            "anthropic_api_key": None, "openai_api_key": None, "coding_sandbox": "docker-cloud",
            "coding_image": IMAGE, "docker_cloud_id": "acme", "docker_cloud_pat": "dckr_pat_test",
            "coding_timeout_minutes": 30, "coding_idle_minutes": 15}
    return Settings(**{**base, **values})  # type: ignore[arg-type]


@dataclass
class Proc:
    """A process in the fake sandbox: what it prints, then its exit code (None: it runs until signalled)."""
    cmd: list[str]
    env: dict
    stdin: bytes | None
    out: list[tuple[str, bytes]] = field(default_factory=list)
    code: int | None = 0
    exits_on_int: int | None = None  # the exit code SIGINT gives it (None: SIGINT is ignored)
    signals: list[str] = field(default_factory=list)


class FakeDockerCloud:
    def __init__(self) -> None:
        self.created: list[dict] = []
        self.files: dict[str, bytes] = {}
        self.unpacked: list[str] = []
        self.procs: list[Proc] = []
        self.deleted: list[tuple[str, str]] = []  # (If-Match, force) of each sandbox deleted
        self.sandboxes: dict[str, dict] = {}  # id -> {"status", "displayName", "createdAt"}
        self.secrets: dict[str, dict] = {}  # id -> what was asked for, and its placeholder
        self.secrets_deleted: list[str] = []
        self.managed: set[str] = set()  # hosts Docker serves itself: a custom secret for them is refused
        self.refuse_secrets = False  # no secrets at all
        self.stops = self.starts = 0
        self.blocked: list[dict] = []  # policy log entries
        self.renewed = 0
        self.tokens = 0
        self.credentials = 0
        self.rate_limited = 0  # requests to answer 429 before the next is served
        self.reject_token_once = False
        self.program = lambda proc: None  # sets what a command prints and how it ends

    def sandbox(self, sid: str) -> dict:
        found = self.sandboxes[sid]
        return {"name": f"sandboxes/{sid}", "uid": sid, "displayName": found["displayName"], "core": {
            "status": found["status"], "etag": f"e-{sid}", "createdAt": found["createdAt"],
            "endpoint": {"uri": ENDPOINT, "protocol": "http"}}}

    def handle(self, request: httpx.Request) -> httpx.Response:
        url, auth = str(request.url), request.headers.get("Authorization", "")
        if url == docker_cloud.TOKEN_URL:
            assert json.loads(request.content) == {"identifier": "acme", "secret": "dckr_pat_test"}
            self.tokens += 1
            return httpx.Response(200, json={"access_token": f"at-{self.tokens}"})
        if self.rate_limited:
            self.rate_limited -= 1
            return httpx.Response(429, headers={"Retry-After": "0"}, json={"error": {"code": "resourceExhausted"}})
        if url.startswith(ENDPOINT):
            assert auth == "Bearer ep-token", auth  # file and process calls: the sandbox's credential only
            return self.endpoint(request, request.url.path.removeprefix("/api"))
        assert auth.startswith("Bearer at-"), auth
        if self.reject_token_once:
            self.reject_token_once = False
            return httpx.Response(401, json={"error": {"code": "unauthenticated"}})
        path, method = request.url.path.removeprefix("/sandboxes"), request.method
        parts = path.split("/")  # ["", "v1", "sandboxes", id, action]
        if path == "/v1/secrets" and method == "POST":
            body = json.loads(request.content)
            host = (body.get("custom") or {}).get("injection", {}).get("hosts", [None])[0]
            if self.refuse_secrets or (host in self.managed):
                return httpx.Response(400, json={"error": {"code": "invalidArgument", "message": "host is managed"}})
            sid = f"sec-{len(self.secrets) + 1}"
            self.secrets[sid] = {**body, "placeholder": "sk-ant-api03-PLACEHOLDER"}
            return httpx.Response(201, json={"name": f"secrets/{sid}", "uid": sid, "displayName": body["displayName"],
                                             "placeholder": "sk-ant-api03-PLACEHOLDER", "createdAt": "2026-10-01T00:00:00Z"})
        if path == "/v1/secrets" and method == "GET":
            return httpx.Response(200, json={"secrets": [
                {"name": f"secrets/{k}", "uid": k, "displayName": v["displayName"], "createdAt": "2026-10-01T00:00:00Z"}
                for k, v in self.secrets.items()]})
        if parts[1:3] == ["v1", "secrets"] and len(parts) == 4:
            if parts[3] not in self.secrets:
                return httpx.Response(404, json={"error": {"code": "notFound"}})
            if method == "DELETE":
                del self.secrets[parts[3]]
                self.secrets_deleted.append(parts[3])
                return httpx.Response(204)
            return httpx.Response(200, json={"name": f"secrets/{parts[3]}", "etag": "s-etag"})
        if path == "/v1/sandboxes" and method == "POST":
            assert request.headers.get("Idempotency-Key")
            body = json.loads(request.content)
            self.created.append(body)
            sid = f"sbx-{len(self.created)}"
            self.sandboxes[sid] = {"status": "running", "displayName": body["displayName"],
                                   "createdAt": "2026-10-31T00:00:00Z"}
            return httpx.Response(202, json={"name": f"sandboxes/{sid}", "uid": sid, "core": {"status": "creating"}})
        if path == "/v1/sandboxes" and method == "GET":
            return httpx.Response(200, json={"sandboxes": [self.sandbox(k) for k in self.sandboxes]})
        if parts[1:3] == ["v1", "sandboxes"]:
            sid = parts[3]
            if sid not in self.sandboxes:
                return httpx.Response(404, json={"error": {"code": "notFound"}})
            action = parts[4] if len(parts) > 4 else ""
            if action == "" and method == "GET":
                return httpx.Response(200, json=self.sandbox(sid))
            if action == "" and method == "DELETE":
                self.deleted.append((request.headers["If-Match"], request.url.params.get("force", "")))
                del self.sandboxes[sid]
                return httpx.Response(204)
            if action == "stop":
                assert request.headers["If-Match"] == f"e-{sid}"
                self.stops += 1
                self.sandboxes[sid]["status"] = "stopped"
                return httpx.Response(200, json=self.sandbox(sid))
            if action == "start":
                self.starts += 1
                self.sandboxes[sid]["status"] = "running"
                return httpx.Response(202, json={**self.sandbox(sid), "core": {"status": "starting"}})
            if action == "endpoint-credentials":
                assert set(json.loads(request.content)["permissions"]) == set(docker_cloud.CREDENTIAL_PERMISSIONS)
                self.credentials += 1
                return httpx.Response(200, json={"token": "ep-token", "expireTime": "2026-10-31T00:05:00Z"})
            if action == "renew-timeout":
                self.renewed += 1
                return httpx.Response(200, json=self.sandbox(sid))
            if action == "policy-logs":
                assert request.url.params["filter"] == "domain=network"
                return httpx.Response(200, json={"entries": self.blocked})
        return httpx.Response(404, json={"error": {"code": "notFound", "message": path}})

    def endpoint(self, request: httpx.Request, path: str) -> httpx.Response:
        if path == "/v1/files/upload":
            message = email.message_from_bytes(
                b"Content-Type: " + request.headers["Content-Type"].encode() + b"\r\n\r\n" + request.content,
                policy=email.policy.HTTP)
            parts = list(message.iter_parts())  # type: ignore[attr-defined]
            assert [p.get_param("name", header="content-disposition") for p in parts] == ["metadata", "content"]
            meta, content = json.loads(parts[0].get_payload(decode=True)), parts[1].get_payload(decode=True)
            self.files[meta["path"]] = content
            return httpx.Response(200, json={"filesWritten": 1})
        if path == "/v1/processes" and request.method == "POST":
            body = json.loads(request.content)
            cmd, stdin = body["cmd"], None
            if cmd[:2] == ["sh", "-c"] and "tar -x" in cmd[2]:  # unpacking the repo
                with tarfile.open(fileobj=io.BytesIO(self.files.pop("/tmp/dotrix-repo.tar"))) as tar:
                    self.unpacked = sorted(tar.getnames())
                assert body["workingDir"] == "/sandbox"
                proc = Proc(cmd, body["env"], None)
            else:
                if cmd[:2] == ["sh", "-c"] and 'exec 0<"$f"' in cmd[2]:  # stdin, uploaded as a file
                    stdin, cmd = self.files.pop(cmd[4]), cmd[5:]
                assert body["workingDir"] == "/sandbox/repo"
                proc = Proc(cmd, body["env"], stdin)
                self.program(proc)
            self.procs.append(proc)
            return httpx.Response(201, json={"uid": f"p{len(self.procs)}", "name": f"processes/p{len(self.procs)}",
                                             "state": "running"})
        pid = path.split("/")[3]
        proc = self.procs[int(pid[1:]) - 1]
        if path.endswith("/signal"):
            sig = json.loads(request.content)["signal"]
            proc.signals.append(sig)
            if sig == "kill":
                proc.code = 137
            elif sig == "int" and proc.exits_on_int is not None:
                proc.code = proc.exits_on_int
            return httpx.Response(200, json={})
        if path.endswith("/output"):
            after = int(request.url.params.get("resumeFrom", 0))
            chunks = [{"stream": s, "data": base64.b64encode(d).decode(), "streamSequence": i}
                      for i, (s, d) in enumerate(proc.out, 1) if i > after]
            page = {"chunks": chunks, "nextResumeFrom": len(proc.out)}
            if proc.code is not None:
                page["exited"] = {"exitCode": proc.code}
            return httpx.Response(200, json=page)
        return httpx.Response(404)


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeDockerCloud:
    for name in ("POLL_MIN", "POLL_MAX", "READY_POLL"):  # no waiting between reads here
        monkeypatch.setattr(docker_cloud, name, 0.0)
    return FakeDockerCloud()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "repo" / "src").mkdir(parents=True)
    (tmp_path / "repo" / "src" / "payments.py").write_text("class PaymentProvider:\n    pass\n")
    return tmp_path / "repo"


def _sandbox(fake: FakeDockerCloud, **values) -> DockerCloudSandbox:
    return DockerCloudSandbox(_settings(**values), transport=httpx.MockTransport(fake.handle))


def test_settings_need_the_account_and_a_registry_image() -> None:
    assert isinstance(build_sandbox(_settings()), DockerCloudSandbox)
    with pytest.raises(ValueError, match="DOCKER_CLOUD_PAT"):
        _settings(docker_cloud_pat=None)
    with pytest.raises(ValueError, match="registry"):
        _settings(coding_image="dotrix-coding:latest")  # a local tag Docker Cloud can't pull
    assert size_for(2) == {"cpus": 2, "memoryMib": 4096} and size_for(3) == {"cpus": 2, "memoryMib": 4096}
    assert size_for(0.5) == {"cpus": 1, "memoryMib": 2048}


async def test_a_sandbox_holds_the_repo_reaches_only_the_model_api_and_streams_commands(
    fake: FakeDockerCloud, repo: Path,
) -> None:
    def program(proc: Proc) -> None:
        proc.out = [("stdout", b'{"type":"system"}\n{"type":"res'), ("stderr", b"warming up\n"),
                    ("stdout", b'ult"}\npartial')]

    fake.program = program
    sandbox = _sandbox(fake)
    run_id = uuid.uuid4()
    session = await sandbox.open(run_id, repo, ClaudeCode(), KEY)
    [body] = fake.created
    assert body["imageRef"] == IMAGE and body["resources"] == {"cpus": 2, "memoryMib": 4096}
    assert body["networkPolicies"] == [{"mode": "denyAll", "allowNetworks": ["api.anthropic.com"]}]
    assert body["features"]["timeouts"] == {"timeout": f"{(30 + 15 + 10) * 60}s", "onTimeout": "stop"}
    assert body["labels"] == {"dotrix-run": str(run_id)}
    # The key is a secret Docker writes into the model API's requests: the sandbox holds a placeholder.
    [secret] = fake.secrets.values()
    assert secret["custom"]["value"] == KEY and secret["custom"]["injection"] == {
        "hosts": ["api.anthropic.com"], "header": "x-api-key", "format": "%s", "envVar": "ANTHROPIC_API_KEY",
        "placeholderTemplate": "sk-ant-api03-{rand}"}
    assert body["features"]["storedSecrets"] == {"secrets": ["secrets/sec-1"]}
    assert KEY not in json.dumps(body)
    assert fake.unpacked == ["repo", "repo/src", "repo/src/payments.py"]

    lines: list[str] = []

    async def on_line(line: str) -> None:
        lines.append(line)

    result = await session.exec(["claude", "-p"], stdin=b"the brief", on_line=on_line, timeout=60)
    assert result.code == 0 and not result.timed_out and not result.cancelled
    assert lines == ['{"type":"system"}\n', '{"type":"result"}\n', "partial"]  # whole lines, the rest at the end
    assert result.stderr == "warming up\n" and result.stdout == ""
    proc = fake.procs[-1]
    assert proc.cmd == ["claude", "-p"] and proc.stdin == b"the brief"
    assert proc.env == {"ANTHROPIC_API_KEY": "sk-ant-api03-PLACEHOLDER", "HOME": "/sandbox", "LANG": "C.UTF-8"}
    assert all(KEY not in json.dumps(p.env) for p in fake.procs)  # never inside the sandbox
    assert not any(path.startswith("/tmp/dotrix-stdin") for path in fake.files)  # handed over, not left behind

    kept = await session.exec(["git", "diff"], timeout=60)  # not streamed: kept whole
    assert kept.stdout == '{"type":"system"}\n{"type":"result"}\npartial'
    assert fake.renewed >= 3 and fake.credentials == 1  # the sandbox's deadline pushed out by each command

    await session.close()
    await session.close()
    assert fake.deleted == [("e-sbx-1", "true")] and fake.secrets_deleted == ["sec-1"]
    with pytest.raises(SandboxError, match="closed"):
        await session.exec(["true"], timeout=5)


async def test_a_host_docker_serves_itself_gets_its_token_and_without_a_secret_only_the_model_api(
    fake: FakeDockerCloud, repo: Path,
) -> None:
    fake.managed = {"api.anthropic.com"}
    session = await _sandbox(fake).open(uuid.uuid4(), repo, ClaudeCode(), KEY, allow=["registry.npmjs.org"])
    [secret] = fake.secrets.values()
    assert secret["serviceType"] == "anthropic" and secret["token"] == {"value": KEY}
    assert fake.created[-1]["networkPolicies"][0]["allowNetworks"] == ["api.anthropic.com", "registry.npmjs.org"]
    await session.close()

    # No secret at all: the key may go in each process's environment only while nothing else is reachable.
    fake.refuse_secrets = True
    with pytest.raises(SandboxError, match="Sandbox network"):
        await _sandbox(fake).open(uuid.uuid4(), repo, ClaudeCode(), KEY, allow=["registry.npmjs.org"])
    assert len(fake.created) == 1  # refused before a sandbox was made
    session = await _sandbox(fake).open(uuid.uuid4(), repo, ClaudeCode(), KEY)
    await session.exec(["claude", "-p"], timeout=60)
    assert fake.procs[-1].env["ANTHROPIC_API_KEY"] == KEY and "storedSecrets" not in fake.created[-1]["features"]
    await session.close()


async def test_a_sandbox_sleeps_between_turns_and_wakes_with_its_files(fake: FakeDockerCloud, repo: Path) -> None:
    sandbox = _sandbox(fake)
    session = await sandbox.open(uuid.uuid4(), repo, ClaudeCode(), KEY)
    handle = sandbox.handle(session)
    assert handle == {"kind": "docker-cloud", "sandbox": "sbx-1", "secret": "secrets/sec-1",
                      "placeholder": "sk-ant-api03-PLACEHOLDER"}
    assert KEY not in json.dumps(handle)  # stored on the session: never the key
    await sandbox.sleep(session)
    assert fake.sandboxes["sbx-1"]["status"] == "stopped" and fake.stops == 1 and not fake.deleted

    woken = await sandbox.wake(handle, ClaudeCode(), KEY)
    assert woken is not None and fake.starts == 1 and fake.sandboxes["sbx-1"]["status"] == "running"
    await woken.exec(["git", "status"], timeout=60)  # the same sandbox, its files as they were
    assert fake.procs[-1].env["ANTHROPIC_API_KEY"] == "sk-ant-api03-PLACEHOLDER"
    await sandbox.discard(handle)
    assert "sbx-1" not in fake.sandboxes and fake.secrets_deleted == ["sec-1"]
    assert await sandbox.wake(handle, ClaudeCode(), KEY) is None  # gone


async def test_the_sweep_deletes_leftovers_only(fake: FakeDockerCloud, repo: Path) -> None:
    sandbox = _sandbox(fake)
    kept = await sandbox.open(uuid.uuid4(), repo, ClaudeCode(), KEY)
    left = await sandbox.open(uuid.uuid4(), repo, ClaudeCode(), KEY)
    running = await sandbox.open(uuid.uuid4(), repo, ClaudeCode(), KEY)
    await sandbox.sleep(kept)
    await sandbox.sleep(left)
    fake.sandboxes["other"] = {"status": "stopped", "displayName": "someone-elses", "createdAt": "2026-10-01T00:00:00Z"}
    deleted = await sandbox.sweep({"sbx-1"}, min_age=0)
    assert deleted == 1 and set(fake.sandboxes) == {"sbx-1", "sbx-3", "other"}  # not a session's, running, or not ours
    assert fake.secrets_deleted == ["sec-2"]  # the deleted sandbox's key went with it
    assert running is not None


async def test_blocked_hosts_are_reported(fake: FakeDockerCloud, repo: Path) -> None:
    session = await _sandbox(fake).open(uuid.uuid4(), repo, ClaudeCode(), KEY)
    fake.blocked = [
        {"resource": "registry.npmjs.org:443", "decision": "blocked", "count": "3"},
        {"resource": "api.anthropic.com:443", "decision": "allowed", "count": "40"},
        {"resource": "https://pypi.org/simple", "decision": "blocked", "count": 5},
    ]
    from datetime import UTC, datetime
    assert await session.blocked_hosts(datetime.now(UTC)) == ["pypi.org", "registry.npmjs.org"]


async def test_stop_interrupts_then_kills_and_the_time_limit_kills(
    fake: FakeDockerCloud, repo: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    sandbox = _sandbox(fake)
    session = await sandbox.open(uuid.uuid4(), repo, ClaudeCode(), KEY)

    def obedient(proc: Proc) -> None:
        proc.code, proc.exits_on_int = None, 130

    fake.program = obedient
    cancel = asyncio.Event()
    cancel.set()
    stopped = await session.exec(["claude", "-p"], timeout=60, cancel=cancel)
    assert stopped.cancelled and stopped.code == 130 and fake.procs[-1].signals == ["int"]

    def stubborn(proc: Proc) -> None:
        proc.code = None  # ignores SIGINT

    fake.program = stubborn
    monkeypatch.setattr(docker_cloud, "STOP_GRACE", 0.0)
    killed = await session.exec(["claude", "-p"], timeout=60, cancel=cancel)
    assert killed.cancelled and fake.procs[-1].signals == ["int", "kill"]

    late = await session.exec(["sleep", "999"], timeout=0)
    assert late.timed_out and late.code is None and fake.procs[-1].signals == ["kill"]
    await session.close()


async def test_rate_limits_are_waited_out_and_a_refused_token_is_renewed(fake: FakeDockerCloud, repo: Path) -> None:
    fake.rate_limited, fake.reject_token_once = 2, True
    sandbox = _sandbox(fake)
    session = await sandbox.open(uuid.uuid4(), repo, ClaudeCode(), KEY)
    assert len(fake.created) == 1 and len(fake.secrets) == 1  # each retried, not repeated
    assert fake.tokens == 2  # the refused token exchanged again once
    await session.close()


async def test_a_sandbox_that_fails_to_start_is_deleted_and_says_why(fake: FakeDockerCloud, repo: Path) -> None:
    original = fake.handle

    def failing(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path.endswith("/v1/sandboxes/sbx-1") and "sbx-1" in fake.sandboxes:
            if fake.sandboxes["sbx-1"]["status"] == "running":
                fake.sandboxes["sbx-1"]["status"] = "failed"
            return httpx.Response(200, json={**fake.sandbox("sbx-1"),
                                             "failure": {"code": "notFound", "message": "image not found"}})
        return original(request)

    sandbox = DockerCloudSandbox(_settings(), transport=httpx.MockTransport(failing))
    with pytest.raises(SandboxError, match="image not found"):
        await sandbox.open(uuid.uuid4(), repo, ClaudeCode(), KEY)
    assert fake.deleted == [("e-sbx-1", "true")] and fake.secrets_deleted == ["sec-1"]  # nothing left behind
