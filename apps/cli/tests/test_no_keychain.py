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

from pmagent_cli import cli as cli_module  # noqa: E402
from pmagent_cli.platform import (  # noqa: E402
    Credential,
    KeychainUnavailable,
    KeyringStore,
    NotSignedIn,
    PlatformClient,
)


@pytest.fixture
def no_keychain(monkeypatch):
    monkeypatch.delenv("PMAGENT_TOKEN", raising=False)
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
    assert "no OS keychain" in result.output and "PMAGENT_TOKEN" in result.output
    assert "Traceback" not in result.output


def test_login_revokes_the_token_it_could_not_store(no_keychain, monkeypatch) -> None:
    platform = FakePlatform()
    platform.device_polls = ["ok"]
    monkeypatch.setattr(cli_module, "PlatformClient", lambda url, token=None: platform.client(token))
    monkeypatch.setattr("pmagent_cli.platform.time.sleep", lambda s: None)
    result = CliRunner().invoke(cli_module.app, ["login", "--api-url", "http://fake", "--no-browser"])
    assert result.exit_code == 1 and "no OS keychain" in result.output
    revoked = [r for r in platform.requests if r.method == "DELETE"]
    assert [r.url.path for r in revoked] == ["/v1/me/tokens/tok-1"]
