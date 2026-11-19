"""Local Codex/fx setup, credential boundaries, browser events and permission decisions."""
import json
import os
from pathlib import Path

import pytest

from dotrix_cli.fx_local import allowed, prepare_profile, save_refreshed_auth
from dotrix_cli.runner import (
    Outcome,
    Tool,
    browser_tools,
    found_tools,
    parse_line,
    write_browser_config,
)
from dotrix_cli.toolenv import tool_environment


def test_codex_is_detected_and_unsafe_native_fx_is_not_advertised(monkeypatch, tmp_path):
    monkeypatch.setattr("dotrix_cli.fx_native.available", lambda: False)
    monkeypatch.setattr("shutil.which", lambda name: f"/bin/{name}" if name in ("codex", "fx") else None)
    assert found_tools() == ["codex"]
    monkeypatch.setattr("dotrix_cli.fx_native.available", lambda: True)
    assert found_tools() == ["codex", "fx"]
    config = write_browser_config("http://127.0.0.1:4411/mcp", "browser-secret")
    try:
        argv = Tool.named("codex", browser=config, native=True, disabled_mcp=("other",)).argv
    finally:
        config.unlink()
    assert argv[argv.index("--sandbox") + 1] == "workspace-write"
    assert argv[argv.index("--ask-for-approval") + 1] == "never"
    assert "browser-secret" not in " ".join(argv)
    assert 'bearer_token_env_var = "DOTRIX_BROWSER_MCP_TOKEN"' in " ".join(argv)
    assert '"other" = { enabled = false }' in " ".join(argv)
    assert "features.hooks=false" in argv and "features.plugins=false" in argv
    assert "project_doc_max_bytes=0" in argv and "network_access = false" in " ".join(argv)
    assert "exclude_slash_tmp = true" in " ".join(argv)
    isolated = Tool.named("codex", isolated=True).argv
    assert isolated[isolated.index("--sandbox") + 1] == "danger-full-access"
    assert "mcp_servers.browser.url" not in " ".join(isolated)
    assert browser_tools({"DOTRIX_BROWSER_MCP_URL": "http://127.0.0.1:123@evil.example/mcp", "DOTRIX_BROWSER_MCP_TOKEN": "secret"}) is None


def test_fx_copies_only_its_connection_and_auth_not_saved_full_access(tmp_path):
    source = tmp_path / "person" / ".fx"
    source.mkdir(parents=True)
    saved = {"provider": "custom", "providers": {"custom": {"auth": {"type": "bearer", "env": "MY_TEST_KEY"}}},
             "models": {"custom": "test"}, "permission_mode": "yolo", "permission": {"*": "allow"},
             "workspaces": {"/": {"permission_mode": "yolo"}}, "context": True}
    original = json.dumps(saved)
    (source / "settings.json").write_text(original)
    (source / "auth.json").write_text('{"token":"synthetic-login"}')
    profile = tmp_path / "private"
    prepare_profile(profile, {"HOME": str(source.parent)})
    configured = json.loads((profile / ".fx/settings.json").read_text())
    assert configured["provider"] == "custom" and configured["models"] == saved["models"]
    assert configured["permission_mode"] == "ask" and configured["permission"]["*"] == "deny"
    assert configured["permission"]["edit"] == "ask" and not configured["context"]
    assert configured["project_config"] is False  # the repository is data, never configuration
    assert "workspaces" not in configured and (source / "settings.json").read_text() == original
    assert (profile / ".fx/auth.json").read_text() == '{"token":"synthetic-login"}'
    if os.name != "nt":
        assert (profile / ".fx/auth.json").stat().st_mode & 0o077 == 0
    env = tool_environment("fx", {"HOME": str(source.parent), "PATH": "/bin", "MY_TEST_KEY": "own-provider-key",
                                  "OPENAI_API_KEY": "other-provider-key", "GITHUB_TOKEN": "host-token", "NODE_OPTIONS": "host-hook"})
    assert env == {"HOME": str(source.parent), "PATH": "/bin", "MY_TEST_KEY": "own-provider-key"}
    argv = Tool.named("fx", profile=profile).argv
    assert "dotrix_cli.fx_local" in argv and "--profile" in argv and "own-provider-key" not in " ".join(argv)
    with pytest.raises(ValueError, match="template"):
        Tool.named("fx", isolated=True, profile=profile)
    with pytest.raises(ValueError, match="model does not match"):
        prepare_profile(tmp_path / "mismatch", {"HOME": str(source.parent)}, expected_model="nvidia:different-model")
    assert not (tmp_path / "mismatch").exists()


def test_refreshed_login_survives_cleanup_without_overwriting_a_new_sign_in(tmp_path):
    source = tmp_path / "home/.fx"
    source.mkdir(parents=True)
    auth = source / "auth.json"
    auth.write_text('{"token":"original"}')
    profile = tmp_path / "private"
    prepare_profile(profile, {"HOME": str(source.parent)})
    (profile / ".fx/auth.json").write_text('{"token":"refreshed"}')
    save_refreshed_auth(profile)
    assert auth.read_text() == '{"token":"refreshed"}'
    if os.name != "nt":
        assert auth.stat().st_mode & 0o077 == 0
    auth.write_text('{"token":"new-sign-in"}')
    (profile / ".fx/auth.json").write_text('{"token":"stale-refresh"}')
    save_refreshed_auth(profile)
    assert auth.read_text() == '{"token":"new-sign-in"}'


def test_fx_permissions_require_observed_identity_and_bound_paths(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    assert allowed({"name": "write_file", "rawInput": {"path": "inside.md"}}, root)
    assert not allowed({"name": "write_file", "rawInput": {"path": "../outside.md"}}, root)
    assert allowed({"name": "shell", "rawInput": {"command": "touch inside"}}, root)
    assert not allowed({"name": "web_fetch", "rawInput": {"url": "http://localhost"}}, root)
    assert not allowed({"name": "mcp_browser_browser_click"}, root)
    assert allowed({"name": "mcp_browser_browser_click", "_meta": {"fx": {"toolCall": {"mcp": {"server": "browser"}}}}}, root)
    if os.name != "nt":
        (root / "escape").symlink_to(tmp_path, target_is_directory=True)
        assert not allowed({"name": "edit_file", "rawInput": {"path": "escape/outside.md"}}, root)


def test_new_engine_streams_keep_browser_steps_failures_and_usage():
    codex = Outcome(root=Path("/repo"))
    browser_call = {"id": "b1", "type": "mcp_tool_call", "server": "browser", "tool": "browser_navigate", "arguments": {"url": "http://localhost:3000"}}
    for event in ({"type": "item.started", "item": browser_call}, {"type": "item.completed", "item": browser_call},
                  {"type": "item.completed", "item": {"id": "text", "type": "agent_message", "text": "Verified."}},
                  {"type": "turn.completed", "usage": {"input_tokens": 100, "output_tokens": 20}}):
        parse_line(json.dumps(event), codex)
    assert [e["text"] for e in codex.events].count("Opened http://localhost:3000 in the browser") == 1
    assert codex.summary == "Verified." and codex.usage == {"input_tokens": 100, "output_tokens": 20}
    fx = Outcome()
    for event in ({"type": "tool", "id": "b1", "name": "mcp_browser_browser_click", "input": {"ref": "e2"}},
                  {"type": "tool_result", "id": "b1", "status": "failed", "output": "Kai browser access is off"},
                  {"type": "done", "final": "Could not check.", "stopReason": "end_turn", "usage": {"inputTokens": 80, "outputTokens": 10}}):
        parse_line(json.dumps(event), fx)
    assert [e["kind"] for e in fx.events] == ["tool", "error"]
    assert fx.summary == "Could not check." and fx.usage == {"input_tokens": 80, "output_tokens": 10}


async def test_native_fx_is_refused_before_any_engine_or_model_process(monkeypatch, tmp_path, capsys):
    from dotrix_cli.fx_local import run

    monkeypatch.setattr("dotrix_cli.fx_native.available", lambda: False)

    async def forbidden(*args, **kwargs):
        raise AssertionError("No engine process may start while the native network boundary is unverified")

    monkeypatch.setenv("NATIVE_FX_POLICY_VALIDATED", "true")
    monkeypatch.setenv("DOTRIX_NATIVE_FX_POLICY_VALIDATED", "true")
    monkeypatch.setattr("asyncio.create_subprocess_exec", forbidden)
    assert await run(tmp_path / "not-created") == 1
    output = capsys.readouterr().out
    assert "requires Linux Bubblewrap" in output and "Use cloud coding" in output
