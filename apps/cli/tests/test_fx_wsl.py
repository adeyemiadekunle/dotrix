"""Kai's fx on Windows through WSL (fx_wsl): what is missing and how to install it, and what a turn keeps."""
from __future__ import annotations

import io
import json
import subprocess
import tarfile
from pathlib import Path, PurePosixPath

import pytest

from dotrix_cli import fx_wsl
from dotrix_cli.fx_bridge import KAI_FX_VERSION
from dotrix_cli.fx_local import allowed


def _completed(stdout: bytes, code: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess([], code, stdout, b"")


def _listing(*rows: str) -> bytes:
    return ("  NAME      STATE           VERSION\r\n" + "".join(f"{row}\r\n" for row in rows)).encode("utf-16-le")


def _facts(**values) -> bytes:
    base = {"missing": "", "namespaces": True, "fx": "/home/k/.local/bin/fx", "version": KAI_FX_VERSION,
            "dirs": " /usr /bin /lib /lib64"}
    return (json.dumps({**base, **values}) + "\n").encode()


@pytest.fixture
def wsl(monkeypatch):
    """Stands in for wsl.exe: `answers` maps the first argument to what it prints."""
    answers: dict[str, subprocess.CompletedProcess] = {}
    calls: list[list[str]] = []

    def run(args, *, input=None, timeout=60):
        calls.append(args)
        return answers["--list" if args[0] == "--list" else "probe"]

    monkeypatch.setattr(fx_wsl, "_wsl_exe", lambda: r"C:\Windows\System32\wsl.exe")
    monkeypatch.setattr(fx_wsl, "_run", run)
    monkeypatch.setattr(fx_wsl, "_ready", None)
    monkeypatch.delenv(fx_wsl.DISTRO_ENV, raising=False)
    monkeypatch.delenv("DOTRIX_WSL_FX", raising=False)
    return answers, calls


def test_without_wsl_the_runner_says_to_install_it(monkeypatch):
    monkeypatch.setattr(fx_wsl, "_wsl_exe", lambda: None)
    monkeypatch.setattr(fx_wsl, "_ready", None)
    found = fx_wsl.status()
    assert not found.ok
    assert "isn't installed" in found.problem and "`wsl --install`" in found.fix


def test_wsl_without_a_distribution_says_to_install_ubuntu(wsl):
    answers, _ = wsl
    answers["--list"] = _completed(_listing("  docker-desktop    Running    2"))
    found = fx_wsl.status()
    assert "no Linux distribution" in found.problem and "wsl --install -d Ubuntu" in found.fix


def test_wsl_1_is_refused_with_how_to_convert_it(wsl):
    answers, _ = wsl
    answers["--list"] = _completed(_listing("* Ubuntu    Stopped    1"))
    found = fx_wsl.status()
    assert found.distro == "Ubuntu" and "WSL 1" in found.problem and "wsl --set-version Ubuntu 2" in found.fix


def test_missing_packages_are_named_with_the_apt_command(wsl):
    answers, _ = wsl
    answers["--list"] = _completed(_listing("* Ubuntu    Running    2"))
    answers["probe"] = _completed(_facts(missing=" bwrap git", namespaces=False))
    found = fx_wsl.status()
    assert "bwrap" in found.problem and "sudo apt install bubblewrap git" in found.fix


def test_another_fx_release_is_refused_naming_the_one_needed(wsl):
    answers, _ = wsl
    answers["--list"] = _completed(_listing("* Ubuntu    Running    2"))
    answers["probe"] = _completed(_facts(version="0.0.17"))
    found = fx_wsl.status()
    assert not found.ok and f"fx {KAI_FX_VERSION} (it has 0.0.17)" in found.problem


def test_a_ready_distribution_is_kept_and_the_chosen_fx_is_passed_in(wsl, monkeypatch):
    answers, calls = wsl
    answers["--list"] = _completed(_listing("* Ubuntu    Running    2", "  Other    Stopped    2"))
    answers["probe"] = _completed(_facts())
    monkeypatch.setenv("DOTRIX_WSL_FX", "/opt/kai/fx")
    found = fx_wsl.status()
    assert found.ok and found.distro == "Ubuntu" and found.system_dirs == ("/usr", "/bin", "/lib", "/lib64")
    assert "DOTRIX_WSL_FX=/opt/kai/fx" in calls[-1]  # wsl.exe passes no Windows variables on its own
    answers.clear()
    assert fx_wsl.status() is found  # kept once ready: no more wsl.exe calls


def test_a_named_distribution_is_used(wsl, monkeypatch):
    answers, _ = wsl
    answers["--list"] = _completed(_listing("* Ubuntu    Running    2", "  Debian    Stopped    2"))
    answers["probe"] = _completed(_facts())
    monkeypatch.setenv(fx_wsl.DISTRO_ENV, "Debian")
    assert fx_wsl.status().distro == "Debian"
    monkeypatch.setattr(fx_wsl, "_ready", None)
    monkeypatch.setenv(fx_wsl.DISTRO_ENV, "Missing")
    assert "'Missing'" in fx_wsl.status().problem


def _archive(entries: dict[str, bytes | None], symlink: tuple[str, str] | None = None) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for name, data in entries.items():
            info = tarfile.TarInfo(name)
            if data is None:
                info.type = tarfile.DIRTYPE
                archive.addfile(info)
            else:
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
        if symlink:
            info = tarfile.TarInfo(symlink[0])
            info.type, info.linkname = tarfile.SYMTYPE, symlink[1]
            archive.addfile(info)
    return buffer.getvalue()


def test_a_turns_profile_comes_back_without_the_files_the_host_owns(tmp_path):
    profile = tmp_path / "profile"
    (profile / ".fx").mkdir(parents=True)
    (profile / ".fx" / "dotrix-session.json").write_text('{"fxSession": "host"}')
    (profile / "auth-source.json").write_text("host")
    archive = _archive({
        "./": None, "./.fx/": None, "./.fx/sessions/": None,
        "./.fx/sessions/s1.json": b"turn",
        "./.fx/dotrix-session.json": b'{"fxSession": "sandbox"}',
        "./auth-source.json": b"sandbox",
        "../outside.txt": b"escape",
    }, symlink=("./.fx/link", "/etc/passwd"))
    fx_wsl.copy_back(archive, profile)
    assert (profile / ".fx" / "sessions" / "s1.json").read_text() == "turn"
    assert json.loads((profile / ".fx" / "dotrix-session.json").read_text())["fxSession"] == "host"
    assert (profile / "auth-source.json").read_text() == "host"
    assert not (tmp_path / "outside.txt").exists() and not (profile / ".fx" / "link").exists()


def test_a_profile_too_large_to_keep_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(fx_wsl, "COPY_BACK_LIMIT", 10)
    with pytest.raises(ValueError, match="too large"):
        fx_wsl.copy_back(_archive({"./big": b"x" * 100}), tmp_path)


def test_the_staged_profile_has_no_links_and_private_modes(tmp_path):
    profile = tmp_path / "profile"
    (profile / ".fx").mkdir(parents=True)
    (profile / ".fx" / "settings.json").write_text("{}")
    with tarfile.open(fileobj=io.BytesIO(fx_wsl._tar({"bridge.py": b"code"}, profile))) as archive:
        members = {member.name: member for member in archive.getmembers()}
    assert members["bridge.py"].mode == 0o600
    assert members["profile/.fx/settings.json"].mode == 0o600 and members["profile/.fx"].mode == 0o700
    assert all(member.uid == 0 and not member.issym() for member in members.values())


def test_tool_paths_in_wsl_are_checked_against_the_worktree_as_fx_sees_it():
    root = PurePosixPath("/mnt/c/Users/k/repo")
    edit = lambda path: {"name": "edit_file", "rawInput": {"path": path}}  # noqa: E731
    assert allowed(edit("/mnt/c/Users/k/repo/src/a.py"), root)
    assert allowed(edit("src/a.py"), root)
    assert not allowed(edit("/mnt/c/Users/k/repo/../other/a.py"), root)
    assert not allowed(edit("../repo-other/a.py"), root)
    assert not allowed(edit("/mnt/c/Users/k/repository/a.py"), root)
    assert allowed({"name": "shell", "rawInput": {}}, root)
    assert isinstance(Path("x"), Path) and not isinstance(root, Path)
