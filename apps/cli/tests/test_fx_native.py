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

