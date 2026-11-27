"""The programs a release bundles for native local Code, and the pins its build fetches them by."""
import json
import re
import sys
from pathlib import Path

import pytest

from dotrix_cli import bundled

ROOT = Path(__file__).resolve().parents[3]
PINS = json.loads((ROOT / "apps/cli/scripts/bundled-tools.json").read_text())


def _release(tmp_path: Path, monkeypatch, names: list[str]) -> Path:
    """A frozen standalone CLI at tmp_path/dotrix with these programs in its bin/."""
    (tmp_path / "bin").mkdir()
    for name in names:
        program = tmp_path / "bin" / name
        program.write_text("#!/bin/sh\n")
        program.chmod(0o755)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "dotrix"))
    return tmp_path / "bin"


@pytest.mark.skipif(sys.platform == "win32", reason="Kai's fx and Bubblewrap are bundled on Linux and macOS")
def test_a_release_s_own_fx_and_bwrap_win_over_path(tmp_path, monkeypatch):
    folder = _release(tmp_path, monkeypatch, ["fx", "bwrap"])
    monkeypatch.setattr(bundled.shutil, "which", lambda name: f"/usr/bin/{name}")
    assert bundled.fx() == str(folder / "fx")
    # The system's Bubblewrap is tried first: Ubuntu 24.04 lets only its own make user namespaces.
    assert bundled.bwrap_candidates() == ["/usr/bin/bwrap", str(folder / "bwrap")]


def test_without_a_bundle_path_is_used(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.setattr(bundled.shutil, "which", lambda name: f"/usr/bin/{name}")
    assert bundled.fx() == "/usr/bin/fx"
    assert bundled.bwrap_candidates() == ["/usr/bin/bwrap"]


@pytest.mark.skipif(sys.platform == "win32", reason="Kai's fx and Bubblewrap are bundled on Linux and macOS")
def test_a_release_without_one_program_falls_back_to_path_for_it(tmp_path, monkeypatch):
    folder = _release(tmp_path, monkeypatch, ["fx"])  # macOS: no bwrap is bundled
    monkeypatch.setattr(bundled.shutil, "which", lambda name: None)
    assert bundled.fx() == str(folder / "fx")
    assert bundled.bwrap_candidates() == []


@pytest.mark.skipif(sys.platform == "win32", reason="Bubblewrap is Linux only")
def test_native_code_uses_the_first_bubblewrap_that_makes_the_sandbox(tmp_path, monkeypatch):
    from dotrix_cli import fx_native

    tried = []

    def run(argv, **_):
        tried.append(argv[0])
        return type("Done", (), {"returncode": 0 if argv[0] == "/bundle/bwrap" else 1})()

    monkeypatch.setattr(fx_native.bundled, "bwrap_candidates", lambda: ["/usr/bin/bwrap", "/bundle/bwrap"])
    monkeypatch.setattr(fx_native.subprocess, "run", run)
    monkeypatch.setattr(fx_native.Path, "is_file", lambda self: True)
    fx_native._linux_bwrap.cache_clear()
    try:
        assert fx_native._linux_bwrap() == "/bundle/bwrap"
        assert tried == ["/usr/bin/bwrap", "/bundle/bwrap"]
    finally:
        fx_native._linux_bwrap.cache_clear()


def test_the_bundled_fx_is_the_kai_release_native_code_and_the_coding_image_pin():
    from dotrix_cli.fx_bridge import KAI_FX_VERSION

    pin = PINS["kai_fx"]
    assert pin["version"] == KAI_FX_VERSION
    assert set(pin["sha256"]) == {"linux-x64", "linux-arm64", "darwin-arm64", "darwin-x64"}
    assert all(re.fullmatch(r"[0-9a-f]{64}", value) for value in pin["sha256"].values())
    dockerfile = (ROOT / "infra/coding/Dockerfile").read_text()
    for cpu, arg in (("x64", "KAI_CLI_SHA256_X64"), ("arm64", "KAI_CLI_SHA256_ARM64")):
        image = re.search(rf"^ARG {arg}=(\S+)$", dockerfile, re.M)
        assert image is not None and image.group(1) == pin["sha256"][f"linux-{cpu}"]


def test_bubblewrap_is_built_from_a_pinned_source_in_a_pinned_image():
    pin = PINS["bubblewrap"]
    assert pin["url"].endswith(f"/v{pin['version']}/bubblewrap-{pin['version']}.tar.xz")
    assert re.fullmatch(r"[0-9a-f]{64}", pin["sha256"])
    assert re.fullmatch(r"alpine:[\d.]+@sha256:[0-9a-f]{64}", pin["builder_image"])
