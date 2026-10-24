"""Machines without an OS keychain (headless Linux, containers, CI) must not crash."""
from __future__ import annotations

import sys
from pathlib import Path

import keyring
import pytest
from keyring.backends import fail
from typer.testing import CliRunner

sys.path.insert(0, str(Path(__file__).parent))

from fake_platform import FakePlatform  # noqa: E402

from dotrix_cli import cli as cli_module  # noqa: E402
from dotrix_cli.platform import (  # noqa: E402
    Credential,
    KeychainUnavailable,
    KeyringStore,
    NotSignedIn,
    PlatformClient,
)


@pytest.fixture
def no_keychain(monkeypatch):
    monkeypatch.delenv("DOTRIX_TOKEN", raising=False)
    previous = keyring.get_keyring()
    keyring.set_keyring(fail.Keyring())
    yield
    keyring.set_keyring(previous)


def test_reads_mean_not_signed_in(no_keychain) -> None:
    store = KeyringStore()
    assert store.get("http://x") is None and store.unavailable
    store.delete("http://x")  # nothing to remove: no error
    with pytest.raises(KeychainUnavailable):
        store.set("http://x", Credential("t"))
    with pytest.raises(NotSignedIn, match="no OS keychain"):
        PlatformClient.signed_in("http://x")


def test_whoami_explains_instead_of_crashing(no_keychain) -> None:
    result = CliRunner().invoke(cli_module.app, ["whoami", "--api-url", "http://x"])
    assert result.exit_code == 1
    assert "no OS keychain" in result.output and "DOTRIX_TOKEN" in result.output
    assert "Traceback" not in result.output


def test_login_revokes_the_token_it_could_not_store(no_keychain, monkeypatch) -> None:
    platform = FakePlatform()
    platform.device_polls = ["ok"]
    monkeypatch.setattr(cli_module, "PlatformClient", lambda url, token=None: platform.client(token))
    monkeypatch.setattr("dotrix_cli.platform.time.sleep", lambda s: None)
    result = CliRunner().invoke(cli_module.app, ["login", "--api-url", "http://fake", "--no-browser"])
    assert result.exit_code == 1 and "no OS keychain" in result.output
    revoked = [r for r in platform.requests if r.method == "DELETE"]
    assert [r.url.path for r in revoked] == ["/v1/me/tokens/tok-1"]


def test_login_and_whoami_speak_json_for_the_desktop_app(monkeypatch) -> None:
    """The desktop app signs its runner in with `login --json`: the code to approve, then who."""
    import json

    from keyring.backend import KeyringBackend

    class Memory(KeyringBackend):
        priority = 1
        kept: dict[tuple[str, str], str] = {}

        def get_password(self, service, username):
            return self.kept.get((service, username))

        def set_password(self, service, username, password):
            self.kept[(service, username)] = password

        def delete_password(self, service, username):
            self.kept.pop((service, username), None)

    monkeypatch.delenv("DOTRIX_TOKEN", raising=False)
    previous = keyring.get_keyring()
    keyring.set_keyring(Memory())
    try:
        platform = FakePlatform()
        platform.device_polls = ["ok"]
        monkeypatch.setattr(cli_module, "PlatformClient", lambda url, token=None: platform.client(token))
        monkeypatch.setattr("dotrix_cli.platform.time.sleep", lambda s: None)
        monkeypatch.setattr("dotrix_cli.platform.webbrowser.open", lambda url: pytest.fail("no browser with --json"))
        result = CliRunner().invoke(cli_module.app, ["login", "--api-url", "http://fake", "--json",
                                                     "--client-name", "dotrix desktop"])
        assert result.exit_code == 0, result.output
        lines = [json.loads(line) for line in result.output.splitlines()]
        assert lines[0]["event"] == "code" and lines[0]["user_code"] and lines[0]["verification_uri_complete"]
        assert lines[1] == {"event": "signed_in", "api_url": "http://fake", "email": "ada@example.com"}
        started = next(r for r in platform.requests if r.url.path == "/v1/auth/device/code")
        assert json.loads(started.content)["client_name"] == "dotrix desktop"

        who = CliRunner().invoke(cli_module.app, ["whoami", "--api-url", "http://fake", "--json"])
        assert json.loads(who.output) == {"api_url": "http://fake", "signed_in": True, "email": "ada@example.com"}
    finally:
        keyring.set_keyring(previous)


def test_whoami_json_says_signed_out_rather_than_failing(no_keychain) -> None:
    import json

    result = CliRunner().invoke(cli_module.app, ["whoami", "--api-url", "http://x", "--json"])
    assert result.exit_code == 0 and json.loads(result.output)["signed_in"] is False
