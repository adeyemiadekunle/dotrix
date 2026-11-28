"""Optional real Claude Code check, with a local scripted model (no model keys): a cloud turn's command starts Kai's
workers as subagents, each within its own tools, and loads nothing of the repository's or of its home folder's.

Set DOTRIX_TEST_CLAUDE to the pinned binary (the coding image's version), or put it on PATH.
"""
import json
import os
import shutil
import subprocess
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from dotrix_backend.modules.coding.tools import ClaudeCode, Usage

CLAUDE = os.environ.get("DOTRIX_TEST_CLAUDE") or shutil.which("claude")
PINNED = "2.1.323"


@contextmanager
def _model(requests: list[dict]):
    """The parent asks `explorer` once; the subagent (offered no Agent tool) reports; then the parent ends."""
    called = threading.Event()

    class Model(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if "count_tokens" in self.path:
                body = b'{"input_tokens": 10}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)
                return
            requests.append(request)
            names = [t.get("name") for t in request.get("tools", [])]
            if "Agent" in names and not called.is_set():
                called.set()
                block = {"type": "tool_use", "id": "toolu_1", "name": "Agent", "input": {}}
                delta = {"type": "input_json_delta", "partial_json": json.dumps(
                    {"subagent_type": "explorer", "description": "find the answer", "prompt": "What is the answer?"})}
                stop = "tool_use"
            else:
                block = {"type": "text", "text": ""}
                said = "HELPER-REPORT: 42" if request.get("tools") and "Agent" not in names else "Done."
                delta, stop = {"type": "text_delta", "text": said}, "end_turn"
            events = [
                {"type": "message_start", "message": {"id": f"msg_{len(requests)}", "type": "message", "role": "assistant",
                 "model": request.get("model"), "content": [], "usage": {"input_tokens": 10, "output_tokens": 1}}},
                {"type": "content_block_start", "index": 0, "content_block": block},
                {"type": "content_block_delta", "index": 0, "delta": delta},
                {"type": "content_block_stop", "index": 0},
                {"type": "message_delta", "delta": {"stop_reason": stop}, "usage": {"output_tokens": 5}},
                {"type": "message_stop"},
            ]
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write("".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events).encode())

    server = ThreadingHTTPServer(("127.0.0.1", 0), Model)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.mark.skipif(not CLAUDE, reason="Needs the pinned Claude Code")
def test_a_cloud_turn_starts_kai_s_workers_and_loads_nothing_planted(tmp_path: Path) -> None:
    version = subprocess.run([CLAUDE, "--version"], capture_output=True, text=True, timeout=30)
    if not version.stdout.startswith(PINNED):
        pytest.skip(f"Use the coding image's pinned version ({PINNED})")
    home, repo, ran = tmp_path / "home", tmp_path / "repo", tmp_path / "hook-ran"
    hook = {"hooks": {"UserPromptSubmit": [{"hooks": [{"type": "command", "command": f"touch {ran.as_posix()}"}]}]}}
    for root in (home, repo / ".claude"):  # its home folder's own, and the repository's
        (root / "agents").mkdir(parents=True)
        (root / "skills" / "planted-skill").mkdir(parents=True)
        (root / "settings.json").write_text(json.dumps(hook))
        (root / "agents" / "planted.md").write_text("---\nname: planted-agent\ndescription: PLANTED\n---\nPLANTED\n")
        (root / "skills" / "planted-skill" / "SKILL.md").write_text("---\nname: planted-skill\ndescription: PLANTED\n---\n")
    (repo / "CLAUDE.md").write_text("PLANTED\n")
    (repo / "AGENTS.md").write_text("PLANTED\n")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    argv = ClaudeCode().command(None)
    start = argv.index("claude")
    settings = dict(pair.split("=", 1) for pair in argv[1:start])  # what `env` sets before it
    requests: list[dict] = []
    with _model(requests) as url:
        env = {**os.environ, **settings, "CLAUDE_CONFIG_DIR": str(home), "ANTHROPIC_BASE_URL": url,
               "ANTHROPIC_API_KEY": "sk-ant-test-not-real"}
        done = subprocess.run([CLAUDE, *argv[start + 1:], "--model", "claude-haiku-5-5"], input="Use your helper",
                              cwd=repo, env=env, capture_output=True, text=True, timeout=180)
    assert done.returncode == 0, done.stderr
    tool, usage = ClaudeCode(), Usage()
    steps = [(s.kind, s.text) for line in done.stdout.splitlines() for s in tool.parse(line, usage).steps]
    assert ("background-running", "explorer: find the answer") in steps
    assert ("background-done", "explorer: find the answer") in steps
    helper = [r for r in requests if r.get("tools") and "Agent" not in [t["name"] for t in r["tools"]]]
    assert helper and sorted(t["name"] for t in helper[0]["tools"]) == ["Glob", "Grep", "Read"]
    assert "PLANTED" not in json.dumps(requests) and not ran.exists()
