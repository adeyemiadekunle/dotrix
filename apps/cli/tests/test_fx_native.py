"""Host relay authority and credential removal, independent of kernel availability."""
import json
from pathlib import Path

import httpx
import pytest

from dotrix_cli.fx_native import Relay, connection


async def test_anthropic_relay_pins_endpoint_model_and_injects_only_host_auth():
    import base64

    seen, replies = [], []
    relay = Relay(None, "https://api.anthropic.com", "host-only-key", "chosen-model", None, protocol="anthropic")

    async def send(value):
        replies.append(value)

    relay.send = send
    def respond(request):
        seen.append(request)
        return httpx.Response(200, json={"ok": True})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        for path, model in [("/model/v1/messages?beta=true", "chosen-model"),
                            ("/model/v1/messages?url=evil", "chosen-model"),
                            ("/model/v1/messages", "other-model"), ("/model/chat/completions", "chosen-model")]:
            await relay.forward(client, {"id": 1, "path": path, "method": "POST", "headers": {
                "x-api-key": "attacker", "Authorization": "Bearer attacker", "anthropic-version": "2023-06-01"},
                "body": base64.b64encode(json.dumps({"model": model}).encode()).decode()})
    assert len(seen) == 1 and str(seen[0].url) == "https://api.anthropic.com/v1/messages?beta=true"
    assert seen[0].headers["x-api-key"] == "host-only-key" and "Authorization" not in seen[0].headers
    assert "host-only-key" not in json.dumps(replies)


async def test_relay_forwards_only_pinned_model_and_desktop_connection():
    seen, replies = [], []

    def respond(request):
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    relay = Relay(None, "https://model.example/v1", "host-only-provider-key", "chosen-model",
        {"url": "http://127.0.0.1:3456/runner", "headers": {"Authorization": "Bearer host-only-browser-key"}})

    async def send(value):
        replies.append(value)

    relay.send = send
    import base64

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        def request(path, body, **values):
            return {"id": 1, "path": path, "method": "POST", "body": base64.b64encode(json.dumps(body).encode()).decode(),
                    "headers": {"Authorization": "Bearer attacker", "Host": "attacker.example", "Content-Type": "application/json"}, **values}
        await relay.forward(client, request("/model/chat/completions", {"model": "chosen-model"}))
        assert str(seen[-1].url) == "https://model.example/v1/chat/completions"
        assert seen[-1].headers["Authorization"] == "Bearer host-only-provider-key"
        await relay.forward(client, request("/browser", {}))
        assert str(seen[-1].url) == "http://127.0.0.1:3456/runner"
        assert seen[-1].headers["Authorization"] == "Bearer host-only-browser-key"
        for path, body in [("/model/../billing", {}), ("/model/chat/completions?url=evil", {}),
                           ("https://evil.example", {}), ("/browser/other", {}),
                           ("/model/chat/completions", {"model": "other-model"})]:
            await relay.forward(client, request(path, body))
        assert len(seen) == 2
        assert not any("host-only" in str(r) for r in replies)


def test_native_profile_cannot_write_back_oauth_or_expose_other_provider_keys(tmp_path: Path):
    folder = tmp_path / ".fx"
    folder.mkdir()
    (folder / "settings.json").write_text(json.dumps({
        "provider": "custom", "models": {"custom": "chosen"}, "providers": {
            "custom": {"base_url": "https://model.example/v1", "protocol": "openai-chat-completions",
                       "auth": {"type": "bearer", "env": "MY_KEY"}},
            "unrelated": {"headers": {"Authorization": "secret-other-provider"}}}}))
    (folder / "auth.json").write_text("original-oauth-secret")
    (tmp_path / "auth-source.json").write_text(json.dumps({"source": "/private/original", "originals": {"auth.json": "hash"}}))
    target, key, model = connection(tmp_path, {"MY_KEY": "host-only-secret"})
    assert (target, key, model) == ("https://model.example/v1", "host-only-secret", "chosen")
    assert not (folder / "auth.json").exists()
    assert json.loads((tmp_path / "auth-source.json").read_text())["originals"] == {}
    stored = (folder / "settings.json").read_text()
    assert "host-only-secret" not in stored and "secret-other-provider" not in stored
    assert json.loads(stored)["providers"]["custom"]["auth"]["env"] == "DOTRIX_FX_BROKER_KEY"


@pytest.mark.parametrize("url", ["http://public.example/v1", "https://user:pass@example.com", "https://example.com?token=abc"])
def test_native_profile_refuses_ambiguous_model_connections(tmp_path, url):
    folder = tmp_path / ".fx"
    folder.mkdir()
    (folder / "settings.json").write_text(json.dumps({"provider": "p", "models": {"p": "m"}, "providers": {
        "p": {"protocol": "openai-chat-completions", "base_url": url, "auth": {"type": "bearer", "env": "KEY"}}}}))
    with pytest.raises(ValueError):
        connection(tmp_path, {"KEY": "secret"})


@pytest.mark.parametrize(("answer", "allowed"), [
    ("print('false')", True),
    ("print('true')", False),  # the Kai runtime's fx, with the repository's configuration still on
    ("import sys; sys.stderr.write('fx config: unknown setting project_config'); sys.exit(2)", False),  # upstream fx 0.0.17
])
def test_native_execution_runs_only_the_kai_runtime_s_fx_with_project_config_off(tmp_path: Path, answer, allowed):
    import sys

    from dotrix_cli.fx_bridge import require_kai_fx

    binary = tmp_path / "fx"
    binary.write_text(f"#!{sys.executable}\nimport sys\nassert sys.argv[1:] == ['config', 'get', 'project_config']\n{answer}\n")
    binary.chmod(0o755)
    if allowed:
        require_kai_fx(str(binary))
    else:
        with pytest.raises(ValueError, match="Kai runtime's fx"):
            require_kai_fx(str(binary))



def test_kai_s_contract_splits_from_the_turn_s_task_and_the_browser_note_stays_in_the_task() -> None:
    """A local fx turn gives fx Kai's contract as the session's system profile, as a cloud turn does: the brief splits
    at its last contract heading (one quoted in an issue stays in the task), and the browser's note goes in the task."""
    from dotrix_cli.fx_local import CONTRACT_HEADING, split_contract
    from dotrix_cli.runner import with_note

    brief = f"Fix the bug.\nThe issue says:\n{CONTRACT_HEADING}\n(quoted)\n\n{CONTRACT_HEADING}\n\nYou are Kai.\n- Rule one.\n"
    task, contract = split_contract(brief)
    assert task == f"Fix the bug.\nThe issue says:\n{CONTRACT_HEADING}\n(quoted)\n"
    assert contract == f"{CONTRACT_HEADING}\n\nYou are Kai.\n- Rule one."
    assert split_contract("Just the task.\n") == ("Just the task.\n", None)  # an older platform's brief goes whole

    noted = with_note(brief, "\n\n## A browser on this computer\n\nUse it.")
    task, contract = split_contract(noted)
    assert "## A browser on this computer" in task and "browser" not in contract
    assert with_note("Just the task.", "\nNOTE") == "Just the task.\nNOTE" and with_note(brief, "") == brief


def test_local_fx_session_state_roundtrips_and_refuses_symlinks_and_shared_dirs(tmp_path: Path):
    import hashlib
    import os

    from dotrix_cli.fx_local import digest_of, restore_session_state, save_session_state

    contract = "# How Kai works\n\nYou are Kai."
    assert digest_of(contract) == hashlib.sha256(contract.encode("utf-8")).hexdigest()
    assert digest_of(None) is None and digest_of("   ") is None

    profile = tmp_path / "profile-1"
    (profile / ".fx" / "sessions" / "fx-s1").mkdir(parents=True)
    (profile / ".fx" / "dotrix-session.json").write_text(json.dumps({
        "fxSession": "fx-s1", "profileDigest": digest_of(contract), "profile": contract,
    }))
    (profile / ".fx" / "sessions" / "fx-s1" / "journal.json").write_text('{"turns":1}')

    state_dir = tmp_path / "saved.fx-session"
    save_session_state(profile, state_dir)
    assert (state_dir / "dotrix-session.json").is_file()
    assert (state_dir / "sessions" / "fx-s1" / "journal.json").read_text() == '{"turns":1}'
    if os.name != "nt":
        assert state_dir.stat().st_mode & 0o077 == 0
        assert (state_dir / "dotrix-session.json").stat().st_mode & 0o077 == 0

    restored_profile = tmp_path / "profile-2"
    restore_session_state(restored_profile, state_dir)
    assert json.loads((restored_profile / ".fx" / "dotrix-session.json").read_text())["fxSession"] == "fx-s1"
    assert (restored_profile / ".fx" / "sessions" / "fx-s1" / "journal.json").read_text() == '{"turns":1}'

    if os.name != "nt":
        secret = tmp_path / "secret.txt"
        secret.write_text("top-secret")
        (state_dir / "sessions" / "link").symlink_to(secret)
        with pytest.raises(ValueError, match="symbolic links"):
            restore_session_state(tmp_path / "profile-3", state_dir)
        (state_dir / "sessions" / "link").unlink()
        state_dir.chmod(0o755)
        with pytest.raises(ValueError, match="private"):
            restore_session_state(tmp_path / "profile-3", state_dir)


async def test_local_fx_resumes_saved_session_and_enforces_profile_digest(tmp_path: Path, monkeypatch, capsys):
    import asyncio
    import io
    import sys
    from contextlib import asynccontextmanager

    from dotrix_cli import fx_local, fx_native

    fake_fx = tmp_path / "fx"
    log = tmp_path / "acp.log"
    script = (
        "import json, os, sys\n"
        "log = open(os.environ['FAKE_ACP_LOG'], 'a')\n"
        "def send(msg):\n"
        "    sys.stdout.write(json.dumps(msg) + '\\n'); sys.stdout.flush()\n"
        "for line in sys.stdin:\n"
        "    msg = json.loads(line)\n"
        "    log.write(json.dumps(msg) + '\\n'); log.flush()\n"
        "    method, mid = msg.get('method'), msg.get('id')\n"
        "    if method == 'initialize':\n"
        "        send({'jsonrpc': '2.0', 'id': mid, 'result': {'protocolVersion': 1}})\n"
        "    elif method == 'session/new':\n"
        "        send({'jsonrpc': '2.0', 'id': mid, 'result': {'sessionId': 'fx-local-1'}})\n"
        "    elif method == 'session/resume':\n"
        "        if os.environ.get('FAIL_RESUME') == '1':\n"
        "            send({'jsonrpc': '2.0', 'id': mid, 'error': {'code': -32603, 'message': 'bad'}})\n"
        "        else:\n"
        "            send({'jsonrpc': '2.0', 'method': 'session/update', 'params': {'sessionId': 'fx-local-1',\n"
        "                  'update': {'sessionUpdate': 'agent_message_chunk', 'content': {'type': 'text', 'text': 'OLD_REPLAY'}}}})\n"
        "            send({'jsonrpc': '2.0', 'id': mid, 'result': {}})\n"
        "    elif method == 'session/set_mode':\n"
        "        send({'jsonrpc': '2.0', 'id': mid, 'result': None})\n"
        "    elif method == 'session/prompt':\n"
        "        sid = msg['params']['sessionId']\n"
        "        send({'jsonrpc': '2.0', 'method': 'session/update', 'params': {'sessionId': sid,\n"
        "              'update': {'sessionUpdate': 'agent_message_chunk', 'content': {'type': 'text', 'text': 'Done local.'}}}})\n"
        "        send({'jsonrpc': '2.0', 'id': mid, 'result': {'stopReason': 'end_turn', 'usage': {'inputTokens': 5, 'outputTokens': 2}}})\n"
    )
    fake_fx.write_text(f"#!{sys.executable}\n{script}")
    fake_fx.chmod(0o755)
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.chdir(repo)
    monkeypatch.setenv("FAKE_ACP_LOG", str(log))
    monkeypatch.setattr(fx_native, "available", lambda: True)
    monkeypatch.setattr("shutil.which", lambda name: str(fake_fx) if name == "fx" else None)

    launches = 0

    @asynccontextmanager
    async def fake_launch(profile, binary, root, browser):
        nonlocal launches
        launches += 1
        proc = await asyncio.create_subprocess_exec(
            binary, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, env={**os.environ},
        )
        yield proc, 0

    import os
    monkeypatch.setattr(fx_native, "launch", fake_launch)

    contract = "# How Kai works\n\nYou are Kai."
    digest = fx_local.digest_of(contract)
    brief = f"Fix bug\n{fx_local.CONTRACT_HEADING}\n\nYou are Kai."

    profile1 = tmp_path / "p1"
    (profile1 / ".fx").mkdir(parents=True)
    monkeypatch.setattr(sys, "stdin", io.StringIO(brief))
    assert await fx_local.run(profile1) == 0
    out1 = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert out1[0] == {"type": "started", "resumed": False, "profileDigest": digest}
    assert out1[-1] == {"type": "done", "final": "Done local.", "usage": {"inputTokens": 5, "outputTokens": 2}, "stopReason": "end_turn"}

    state_dir = tmp_path / "state"
    fx_local.save_session_state(profile1, state_dir)

    profile2 = tmp_path / "p2"
    (profile2 / ".fx").mkdir(parents=True)
    fx_local.restore_session_state(profile2, state_dir)
    monkeypatch.setattr(sys, "stdin", io.StringIO(brief))
    assert await fx_local.run(profile2, resume=True, pinned_digest=digest) == 0
    out2 = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert out2[0] == {"type": "started", "resumed": True, "profileDigest": digest}
    assert not any("OLD_REPLAY" in str(ev) for ev in out2)

    # Mismatched pinned digest refuses BEFORE launching sandbox/fx.
    before_launches = launches
    monkeypatch.setattr(sys, "stdin", io.StringIO(brief))
    assert await fx_local.run(profile2, resume=True, pinned_digest="0" * 64) == 1
    assert launches == before_launches
    err = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert err["type"] == "error" and "saved state doesn't match" in err["message"]

    # Changed contract without pinned digest also refuses before launch.
    monkeypatch.setattr(sys, "stdin", io.StringIO(f"Fix\n{fx_local.CONTRACT_HEADING}\n\nChanged."))
    assert await fx_local.run(profile2, resume=True) == 1
    assert launches == before_launches
    capsys.readouterr()

    # Unreadable engine session falls back to a fresh conversation and says so.
    monkeypatch.setenv("FAIL_RESUME", "1")
    monkeypatch.setattr(sys, "stdin", io.StringIO(brief))
    assert await fx_local.run(profile2, resume=True, pinned_digest=digest) == 0
    out3 = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert out3[0] == {"type": "started", "resumed": False, "profileDigest": digest, "fresh": True}
