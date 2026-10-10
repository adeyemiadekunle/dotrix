"""The Docker sandbox: where the egress proxy lets a tool go, and (where Docker and the coding image
are on this machine) a real sandbox: the agent edits the repo it was given, reaches nothing else,
can't write the system, and is gone afterwards."""
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

from dotrix_backend.core.settings import Settings
from dotrix_backend.modules.coding.sandbox import DockerSandbox, egress_allow
from dotrix_backend.modules.coding.tools import ClaudeCode, Codex

IMAGE = "dotrix-coding:latest"


def _docker_ready() -> bool:
    if shutil.which("docker") is None:
        return False
    found = subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True, check=False)
    return found.returncode == 0


def test_the_proxy_lets_each_tool_reach_its_model_api(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    assert egress_allow(ClaudeCode()) == "api.anthropic.com:443"
    assert egress_allow(Codex()) == "api.openai.com:443"
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://llm-proxy.internal:8080/v1")
    assert egress_allow(ClaudeCode()) == "llm-proxy.internal:8080"


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
