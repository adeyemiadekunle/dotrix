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
        self.deleted: list[tuple[str, str]] = []
        self.renewed = 0
        self.tokens = 0
        self.credentials = 0
        self.rate_limited = 0  # requests to answer 429 before the next is served
        self.reject_token_once = False
        self.program = lambda proc: None  # sets what a command prints and how it ends

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
        path = request.url.path.removeprefix("/sandboxes")
        if path == "/v1/sandboxes" and request.method == "POST":
            assert request.headers.get("Idempotency-Key")
            self.created.append(json.loads(request.content))
            return httpx.Response(202, json={"name": "sandboxes/sbx-1", "uid": "sbx-1", "core": {"status": "creating"}})
        if path == "/v1/sandboxes/sbx-1" and request.method == "GET":
            if self.deleted:
                return httpx.Response(404, json={"error": {"code": "notFound"}})
            return httpx.Response(200, json={"name": "sandboxes/sbx-1", "uid": "sbx-1", "core": {
                "status": "running", "etag": "e-1", "endpoint": {"uri": ENDPOINT, "protocol": "http"}}})
        if path == "/v1/sandboxes/sbx-1" and request.method == "DELETE":
            self.deleted.append((request.headers["If-Match"], request.url.params.get("force", "")))
            return httpx.Response(204)
        if path == "/v1/sandboxes/sbx-1/endpoint-credentials":
            assert set(json.loads(request.content)["permissions"]) == set(docker_cloud.CREDENTIAL_PERMISSIONS)
            self.credentials += 1
            return httpx.Response(200, json={"token": "ep-token", "expireTime": "2026-10-31T00:05:00Z"})
        if path == "/v1/sandboxes/sbx-1/renew-timeout":
            self.renewed += 1
            return httpx.Response(200, json={"name": "sandboxes/sbx-1"})
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
    assert body["features"] == {"timeouts": {"timeout": f"{(30 + 15 + 10) * 60}s", "onTimeout": "delete"}}
    assert body["labels"] == {"dotrix-run": str(run_id)}
    assert KEY not in json.dumps(body)  # the key never goes in the sandbox's own (stored) settings
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
    assert proc.env == {"ANTHROPIC_API_KEY": KEY, "HOME": "/sandbox", "LANG": "C.UTF-8"}
    assert not any(path.startswith("/tmp/dotrix-stdin") for path in fake.files)  # handed over, not left behind

    kept = await session.exec(["git", "diff"], timeout=60)  # not streamed: kept whole
    assert kept.stdout == '{"type":"system"}\n{"type":"result"}\npartial'
    assert fake.renewed >= 3 and fake.credentials == 1  # the sandbox's deadline pushed out by each command

    await session.close()
    await session.close()
    assert fake.deleted == [("e-1", "true")]
    with pytest.raises(SandboxError, match="closed"):
        await session.exec(["true"], timeout=5)


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
    assert len(fake.created) == 1  # the same create retried, not repeated
    assert fake.tokens == 2  # the refused token exchanged again once
    await session.close()


async def test_a_sandbox_that_fails_to_start_is_deleted_and_says_why(fake: FakeDockerCloud, repo: Path) -> None:
    original = fake.handle

    def failing(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path.endswith("/v1/sandboxes/sbx-1") and not fake.deleted:
            return httpx.Response(200, json={"name": "sandboxes/sbx-1", "uid": "sbx-1",
                                             "core": {"status": "failed", "etag": "e-9"},
                                             "failure": {"code": "notFound", "message": "image not found"}})
        return original(request)

    sandbox = DockerCloudSandbox(_settings(), transport=httpx.MockTransport(failing))
    with pytest.raises(SandboxError, match="image not found"):
        await sandbox.open(uuid.uuid4(), repo, ClaudeCode(), KEY)
    assert fake.deleted == [("e-9", "true")]  # nothing left running
