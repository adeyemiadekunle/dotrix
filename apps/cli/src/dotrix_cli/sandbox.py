"""The sandbox runtime (`srt`, https://github.com/anthropics/sandbox-runtime) that local turns code in.

It comes with dotrix rather than from the person: a pinned version, installed by `dotrix sandbox
install` into `~/.dotrix/tools` (`dotrix runner` installs it the first time it's missing), and run
with Node directly so no shell shim or global install is involved. The desktop app ships the same
version in its own package and points the runner at it through `DOTRIX_SRT`.

Which copy runs, in order: `DOTRIX_SRT` (a path to srt's `cli.js`, or to an `srt` executable), the
copy dotrix installed, then an `srt` already on PATH.

srt needs Node 22.12 or later; on Linux also bubblewrap and socat (macOS needs nothing more, and
Windows support in srt is still alpha).
"""
from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

PACKAGE = "@anthropic-ai/sandbox-runtime"
VERSION = "0.0.79"  # pinned; the desktop app's package.json pins the same
MIN_NODE = (22, 12)


def tools_dir() -> Path:
    return Path(os.environ.get("DOTRIX_TOOLS_DIR") or Path.home() / ".dotrix" / "tools")


def install_dir() -> Path:
    return tools_dir() / f"sandbox-runtime-{VERSION}"


def installed_cli() -> Path:
    return install_dir() / "node_modules" / "@anthropic-ai" / "sandbox-runtime" / "dist" / "cli.js"


def node() -> str | None:
    return shutil.which("node")


def node_version(binary: str | None = None) -> tuple[int, int] | None:
    binary = binary or node()
    if binary is None:
        return None
    try:
        out = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=10, check=False).stdout
    except OSError:
        return None
    found = re.match(r"v?(\d+)\.(\d+)", out.strip())
    return (int(found.group(1)), int(found.group(2))) if found else None


def command() -> list[str] | None:
    """How to run srt here (its argv prefix), or None when there's none."""
    chosen = os.environ.get("DOTRIX_SRT")
    if chosen:
        return _run(Path(chosen))
    if installed_cli().is_file():
        return _run(installed_cli())
    on_path = shutil.which("srt")
    return [on_path] if on_path else None


def _run(path: Path) -> list[str] | None:
    if path.suffix in (".js", ".mjs", ".cjs"):
        # The desktop app runs it with Electron's own Node (ELECTRON_RUN_AS_NODE), named by DOTRIX_SRT_NODE.
        runtime = os.environ.get("DOTRIX_SRT_NODE") or node()
        return [runtime, str(path)] if runtime and path.is_file() else None
    return [str(path)] if path.is_file() else None


def env() -> dict[str, str]:
    """What srt's own process needs in its environment: run by the desktop app's executable, that
    executable runs as Node only when told to (never set for anything else the app starts)."""
    return {"ELECTRON_RUN_AS_NODE": "1"} if os.environ.get("DOTRIX_SRT_NODE") and os.environ.get("DOTRIX_SRT") else {}


@dataclass
class Check:
    ready: bool
    srt: list[str] | None
    missing: list[str] = field(default_factory=list)  # what to install, said so a person can do it


def check() -> Check:
    """Whether srt can sandbox a tool here, and what's missing when it can't."""
    missing: list[str] = []
    srt = command()
    if srt is None:
        version = node_version()
        if version is None:
            missing.append(f"Node {MIN_NODE[0]}.{MIN_NODE[1]} or later (https://nodejs.org), then `dotrix sandbox install`")
        elif version < MIN_NODE:
            missing.append(f"Node {MIN_NODE[0]}.{MIN_NODE[1]} or later (this is {version[0]}.{version[1]})")
        else:
            missing.append("the sandbox runtime: `dotrix sandbox install`")
    if platform.system() == "Linux":
        for binary, package in (("bwrap", "bubblewrap"), ("socat", "socat")):
            if shutil.which(binary) is None:
                missing.append(f"{package} (e.g. `sudo apt-get install {package}`)")
    return Check(ready=not missing, srt=srt, missing=missing)


def install() -> Path:
    """Install the pinned srt into dotrix's tools folder (again: it's already there, nothing to do)."""
    if installed_cli().is_file():
        return installed_cli()
    npm = shutil.which("npm")
    version = node_version()
    if npm is None or version is None:
        raise RuntimeError(f"Installing the sandbox runtime needs Node {MIN_NODE[0]}.{MIN_NODE[1]} or later "
                           "with npm (https://nodejs.org)")
    if version < MIN_NODE:
        raise RuntimeError(f"The sandbox runtime needs Node {MIN_NODE[0]}.{MIN_NODE[1]} or later (this is "
                           f"{version[0]}.{version[1]})")
    target = install_dir()
    target.mkdir(parents=True, exist_ok=True)
    done = subprocess.run(
        [npm, "install", "--prefix", str(target), "--no-fund", "--no-audit", "--omit=dev", "--save-exact",
         f"{PACKAGE}@{VERSION}"],
        capture_output=True, text=True, timeout=600, check=False,
    )
    if done.returncode != 0 or not installed_cli().is_file():
        raise RuntimeError(f"npm couldn't install {PACKAGE}@{VERSION}: {(done.stderr or done.stdout).strip()[-800:]}")
    return installed_cli()
