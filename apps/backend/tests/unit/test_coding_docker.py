"""The Docker sandbox: where the egress proxy lets a tool go, and (where Docker and the coding image
are on this machine) a real sandbox: the agent edits the repo it was given, reaches nothing else,
can't write the system, and is gone afterwards."""
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

from dotrix_backend.core.settings import Settings
from dotrix_backend.modules.coding.sandbox import DockerSandbox, SandboxError, egress_allow
from dotrix_backend.modules.coding.tools import ClaudeCode, Codex

IMAGE = "dotrix-coding:latest"


def _docker_ready() -> bool:
    if shutil.which("docker") is None:
        return False
    found = subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True, check=False)
    return found.returncode == 0


def test_the_proxy_lets_each_tool_reach_its_model_api(monkeypatch: pytest.MonkeyPatch) -> None:
    assert egress_allow(ClaudeCode()) == "api.anthropic.com:443"
    assert egress_allow(Codex()) == "api.openai.com:443"
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://llm-proxy.internal:8080/v1")  # never followed
    assert egress_allow(ClaudeCode()) == "api.anthropic.com:443"


async def test_the_docker_daemon_does_not_inherit_the_agents_egress_proxy(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DOCKER_HOST", "tcp://docker-proxy:2375")
    sandbox = DockerSandbox(Settings(database_url="postgresql+asyncpg://localhost/unused", jwt_secret="x" * 40))
    calls = []

    async def cli(*args, **kwargs):
        calls.append((args, kwargs))
        if args[0] == "inspect":
            return "172.30.0.2\n" if "NetworkSettings" in args[2] else "runsc\n"
        return ""

    monkeypatch.setattr(sandbox, "cli", cli)
    repo = tmp_path / "repo"
    repo.mkdir()
    box = await sandbox.open(uuid.uuid4(), repo, Codex(), "selected-test-key")
    try:
        args, kwargs = next((args, kwargs) for args, kwargs in calls if "--init" in args)
        client = kwargs["env"]
        assert client["DOCKER_HOST"] == "tcp://docker-proxy:2375"
        assert not any(name in client for name in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"))
        assert "HTTP_PROXY=http://egress:3128" in args
        assert "NO_PROXY=localhost,127.0.0.1,::1" in args
        assert client["OPENAI_API_KEY"] == client["CODEX_API_KEY"] == "selected-test-key"
        assert "selected-test-key" not in " ".join(args)
    finally:
        await box.close()


@pytest.mark.parametrize("container", ["agent", "egress"])
@pytest.mark.parametrize("failure", ["runc", "", "inspect-error", "run-error"])
async def test_unverified_isolation_never_receives_repository_files_or_falls_back(
    tmp_path: Path, monkeypatch, container: str, failure: str,
) -> None:
    sandbox = DockerSandbox(Settings(database_url="postgresql+asyncpg://localhost/unused", jwt_secret="x" * 40,
                                    coding_docker_runtime="runsc"))
    run_id = uuid.uuid4()
    name = f"dotrix-run-{run_id.hex[-16:]}"
    target = name if container == "agent" else f"{name}-egress"
    calls = []

    async def cli(*args, **kwargs):
        calls.append(args)
        if args[0] in ("run", "start") and target in args and failure == "run-error":
            raise SandboxError("The requested isolation runtime could not start")
        if args[0] == "inspect":
            if "NetworkSettings" in args[2]:  # the proxy's address on the run's network
                return "172.30.0.2\n"
            if args[-1] == target:
                if failure == "inspect-error":
                    raise SandboxError("Could not inspect sandbox")
                return failure
            return "runsc\n"
        return ""

    monkeypatch.setattr(sandbox, "cli", cli)
    with pytest.raises(SandboxError):
        await sandbox.open(run_id, tmp_path, Codex(), "selected-test-key")
    assert not any(args[0] == "exec" and name in args for args in calls)  # nothing reached the agent's container
    assert ("rm", "-f", "-v", name, f"{name}-egress") in calls
    assert ("network", "rm", name) in calls
    attempts = [args for args in calls if args[0] in ("create", "run")]
    assert all(args[args.index("--runtime") + 1] == "runsc" for args in attempts)
    assert len(attempts) == (1 if container == "egress" else 2)


async def test_the_agent_reaches_its_proxy_by_address_and_no_address_stops_the_sandbox(tmp_path: Path, monkeypatch) -> None:
    """Under gVisor a container can't use Docker's resolver, so the agent gets the proxy's address (`--add-host`).
    No address, or something that isn't one, and the sandbox doesn't open: no repository goes in."""
    for answer, opens in (("172.30.0.2\n", True), ("\n", False), ("<no value>\n", False)):
        sandbox = DockerSandbox(Settings(database_url="postgresql+asyncpg://localhost/unused", jwt_secret="x" * 40,
                                        coding_docker_runtime="runsc"))
        calls = []

        async def cli(*args, answer=answer, calls=calls, **kwargs):
            calls.append(args)
            if args[0] == "inspect":
                return answer if "NetworkSettings" in args[2] else "runsc\n"
            return ""

        monkeypatch.setattr(sandbox, "cli", cli)
        if opens:
            await sandbox.open(uuid.uuid4(), tmp_path, Codex(), "selected-test-key")
            [run] = [args for args in calls if args[0] == "run"]
            assert run[run.index("--add-host") + 1] == "egress:172.30.0.2"
        else:
            with pytest.raises(SandboxError, match="no address"):
                await sandbox.open(uuid.uuid4(), tmp_path, Codex(), "selected-test-key")
            assert not any(args[0] == "run" for args in calls)


async def test_under_gvisor_the_egress_proxy_gets_named_resolvers_and_is_waited_for(tmp_path: Path, monkeypatch) -> None:
    """Under a runtime the proxy can't reach Docker's resolver either: it's given named ones. The agent starts only
    once the proxy listens; one that never does stops the sandbox."""
    from dotrix_backend.modules.coding import sandbox as module

    for runtime, ready in (("runsc", True), (None, True), ("runsc", False)):
        settings = Settings(database_url="postgresql+asyncpg://localhost/unused", jwt_secret="x" * 40,  # type: ignore[arg-type]
                            coding_docker_runtime=runtime)
        sandbox = DockerSandbox(settings)
        calls = []

        async def cli(*args, calls=calls, ready=ready, **kwargs):
            calls.append(args)
            if args[0] == "inspect":
                return "172.30.0.2\n" if "NetworkSettings" in args[2] else "runsc\n"
            if args[0] == "exec" and "-e" in args and not ready:
                raise SandboxError("connection refused")
            return ""

        monkeypatch.setattr(sandbox, "cli", cli)
        monkeypatch.setattr(module, "EGRESS_READY_TRIES", 2)
        if ready:
            await sandbox.open(uuid.uuid4(), tmp_path, Codex(), "selected-test-key")
        else:
            with pytest.raises(SandboxError, match="didn't start"):
                await sandbox.open(uuid.uuid4(), tmp_path, Codex(), "selected-test-key")
        [create] = [args for args in calls if args[0] == "create"]
        assert ("DOTRIX_EGRESS_DNS=1.1.1.1,8.8.8.8" in create) == (runtime is not None)
        probes = [args for args in calls if args[0] == "exec" and "-e" in args]
        assert probes and all(args[1].endswith("-egress") for args in probes)
        assert any(args[0] == "run" for args in calls) == ready


@pytest.mark.skipif(not _docker_ready(), reason=f"needs Docker and {IMAGE} (docker build -t {IMAGE} infra/coding)")
async def test_a_docker_sandbox_edits_the_repo_and_reaches_nothing_else(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("x = 1\n")
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run([*git, "init", "-q"], check=True)
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run([*git, "commit", "-qm", "base"], check=True)

    settings = Settings(database_url="postgresql+asyncpg://localhost/unused", jwt_secret="x" * 40,  # type: ignore[arg-type]
                        coding_sandbox="docker", coding_image=IMAGE)
    sandbox = DockerSandbox(settings)
    run_id = uuid.uuid4()
    box = await sandbox.open(run_id, repo, ClaudeCode(), "test-key-not-real")
    name = f"dotrix-run-{run_id.hex[-16:]}"
    try:
        # It edits the repo it was given, as its own user, and the change reads back as a patch.
        edit = await box.exec(["sh", "-c", "echo 'y = 2' >> a.py && git add -A && git diff --cached"], timeout=60)
        assert edit.code == 0 and "+y = 2" in edit.stdout
        who = await box.exec(["id", "-u"], timeout=30)
        assert who.stdout.strip() == "1500"
        init = await box.exec(["cat", "/proc/1/comm"], timeout=30)
        assert init.stdout.strip() == "docker-init"  # reaps what a stopped turn leaves behind
        # The key is there for the tool; the proxy is the only way out.
        env = await box.exec(["sh", "-c", "echo $ANTHROPIC_API_KEY $HTTPS_PROXY"], timeout=30)
        assert env.stdout.split() == ["test-key-not-real", "http://egress:3128"]
        # Nothing but the model API: not GitHub through the proxy, nothing around it, no system writes.
        denied = await box.exec(["curl", "-sS", "-m", "10", "-o", "/dev/null", "-w", "%{http_code}",
                                 "https://github.com"], timeout=60)
        assert denied.code != 0
        direct = await box.exec(["curl", "-sS", "-m", "10", "--noproxy", "*", "https://example.com"], timeout=60)
        assert direct.code != 0
        allowed = await box.exec(["curl", "-sS", "-m", "20", "-o", "/dev/null", "-w", "%{http_code}",
                                  "https://api.anthropic.com/v1/messages"], timeout=60)
        assert allowed.code == 0 and allowed.stdout.strip() in {"400", "401", "403", "404", "405"}  # reached, no real key
        system = await box.exec(["sh", "-c", "touch /etc/x || touch /usr/x"], timeout=30)
        assert system.code != 0
    finally:
        await box.close()
    left = subprocess.run(["docker", "ps", "-a", "--filter", f"name={name}", "--format", "{{.Names}}"],
                          capture_output=True, text=True, check=False)
    assert left.stdout.strip() == ""
    nets = subprocess.run(["docker", "network", "ls", "--filter", f"name={name}", "--format", "{{.Name}}"],
                          capture_output=True, text=True, check=False)
    assert nets.stdout.strip() == ""


@pytest.mark.skipif(not _docker_ready(), reason=f"needs Docker and {IMAGE} (docker build -t {IMAGE} infra/coding)")
async def test_stop_reaches_the_command_inside_the_sandbox(tmp_path: Path) -> None:
    """Interrupting `docker exec` would leave the command running in the container: Stop sends
    SIGINT inside, so the command ends cleanly (Claude Code writes its final result), well inside the grace."""
    import asyncio
    import time

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    settings = Settings(database_url="postgresql+asyncpg://localhost/unused", jwt_secret="x" * 40,  # type: ignore[arg-type]
                        coding_sandbox="docker", coding_image=IMAGE)
    box = await DockerSandbox(settings).open(uuid.uuid4(), repo, ClaudeCode(), "not-a-key")
    try:
        lines: list[str] = []

        async def on_line(line: str) -> None:
            lines.append(line.strip())

        cancel = asyncio.Event()
        asyncio.get_running_loop().call_later(2, cancel.set)
        started = time.monotonic()
        result = await box.exec(["sh", "-c", 'trap "echo finished cleanly; exit 0" INT; echo working; while :; do sleep 0.2; done'],
                                on_line=on_line, timeout=60, cancel=cancel)
        took = time.monotonic() - started
        assert result.cancelled and lines == ["working", "finished cleanly"] and took < 5
        left = await box.exec(["sh", "-c", 'ps -eo args | grep -c "[w]hile :" || true'], timeout=30)
        assert left.stdout.strip() == "0"
    finally:
        await box.close()
