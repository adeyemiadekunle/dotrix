"""The sandbox runtime (`srt`, https://github.com/anthropics/sandbox-runtime) that local turns code in.

It comes with dotrix rather than from the person: a pinned version, installed by `dotrix sandbox
install` into `~/.dotrix/tools` (`dotrix runner` installs it the first time it's missing), and run
with Node directly so no shell shim or global install is involved. The desktop app ships the same
version in its own package and points the runner at it through `DOTRIX_SRT`.

Which copy runs, in order: `DOTRIX_SRT` (a path to srt's `cli.js`, or to an `srt` executable), the
copy dotrix installed, then an `srt` already on PATH.

srt needs Node 22.12 or later, and per platform:
- macOS: nothing more (Seatbelt, built in).
- Linux: bubblewrap and socat.
- Windows (alpha in srt): a one-time setup per machine, `srt windows-install`, which asks for an
  administrator once (UAC) and creates the `srt-sandbox` account the tool runs as. `dotrix sandbox
  install` runs it; `check()` reads its state with srt's own `srt-win.exe status` (no elevation). The
  tool then starts with a fresh environment and its own profile, so the runner hands it what it needs
  (its key variables, where its sign-in lives) through a launcher (`windows_launcher`).
"""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

PACKAGE = "@anthropic-ai/sandbox-runtime"
VERSION = "0.0.79"  # pinned; the desktop app's package.json pins the same
MIN_NODE = (22, 12)
# What a sandboxed tool may reach: the model providers' APIs, and the package registries tests need.
ALLOWED_DOMAINS = [
    "api.anthropic.com", "api.openai.com", "generativelanguage.googleapis.com",
    "registry.npmjs.org", "pypi.org", "files.pythonhosted.org",
]
DENY_READ = ["~/.ssh", "~/.aws", "~/.config/gcloud", "~/.gnupg", "~/.netrc", "~/.docker"]


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


def package_dir() -> Path | None:
    """The srt package folder of the copy that runs (None: an `srt` from PATH, or none)."""
    chosen = os.environ.get("DOTRIX_SRT")
    cli = Path(chosen) if chosen else installed_cli()
    return cli.parent.parent if cli.suffix == ".js" and cli.is_file() else None


def srt_win() -> Path | None:
    """srt's Windows helper (`srt-win.exe`) in the copy that runs."""
    found = package_dir()
    if found is None:
        return None
    arch = "arm64" if platform.machine().lower() in ("arm64", "aarch64") else "x64"
    exe = found / "vendor" / "srt-win" / arch / "srt-win.exe"
    return exe if exe.is_file() else None


def windows_setup_missing() -> str | None:
    """What the one-time Windows setup lacks (None: done). Read with `srt-win.exe status`, which
    needs no administrator: the account, its stored credential, and the network filters."""
    exe = srt_win()
    if exe is None:
        return "srt's Windows helper (srt-win.exe): `dotrix sandbox install`"
    try:
        done = subprocess.run([str(exe), "status"], capture_output=True, text=True, timeout=60, check=False)
        status = json.loads(done.stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return "the one-time Windows setup (srt-win.exe status didn't answer): `dotrix sandbox install`"
    user, wfp = status.get("user") or {}, status.get("wfp") or {}
    exists = (user.get("user") or {}).get("exists") and user.get("cred_present")
    # Without an administrator the filters read as `cannot-read`; srt proves them itself when it starts.
    if not exists or wfp.get("state") not in ("installed", "cannot-read"):
        return "the one-time Windows setup (one administrator prompt): `dotrix sandbox install`"
    return None


def setup_windows() -> None:
    """Run srt's one-time Windows setup (`windows-install`): it asks for an administrator once (UAC)."""
    srt = command()
    if srt is None:
        raise RuntimeError("Install the sandbox runtime first: `dotrix sandbox install`")
    done = subprocess.run([*srt, "windows-install"], env={**os.environ, **env()}, check=False)
    if done.returncode == 2:
        raise RuntimeError("The Windows setup was cancelled at the administrator prompt; nothing changed")
    if done.returncode != 0:
        raise RuntimeError("srt's Windows setup failed (see above)")


def settings(tree: Path, *, home: Path | None = None, system: str | None = None) -> dict[str, object]:
    """srt's settings for one turn: writes only to the worktree, the coding tools' own state, and
    temporary files; no reads of credentials; network only to the model APIs and package registries."""
    home = home or Path.home()
    system = system or platform.system()
    tool_state = [home / ".claude", home / ".claude.json", home / ".local" / "share" / "opencode",
                  home / ".config" / "opencode", home / ".cache" / "opencode"]
    temporary: list[str] = []
    if system != "Windows":  # on Windows the tool has the sandbox account's own %TEMP%
        temporary = sorted({"/tmp", tempfile.gettempdir()} | ({"/private/tmp"} if system == "Darwin" else set()))
    return {
        "filesystem": {
            "denyRead": DENY_READ,
            "allowWrite": [str(tree), *(str(p) for p in tool_state), *temporary],
            "denyWrite": [],
        },
        "network": {"allowedDomains": ALLOWED_DOMAINS, "deniedDomains": []},
    }


# Host credentials are not part of the tool's environment. Keep the execution settings it needs
# and explicit provider/tool settings, on every platform and even when srt is unavailable.
EXECUTION_ENV = frozenset({
    "PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC", "PROGRAMDATA", "APPDATA", "LOCALAPPDATA",
    "HOME", "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "USER", "LOGNAME", "SHELL", "TMP", "TEMP", "TMPDIR",
    "LANG", "LANGUAGE", "LC_ALL", "LC_CTYPE", "TERM", "COLORTERM", "TZ",
    "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME",
    "SSL_CERT_FILE", "SSL_CERT_DIR", "NODE_EXTRA_CA_CERTS",
})
ANTHROPIC_ENV = frozenset({
    "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "ANTHROPIC_MODEL",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL", "ANTHROPIC_DEFAULT_SONNET_MODEL", "ANTHROPIC_DEFAULT_OPUS_MODEL",
})
OPENAI_ENV = frozenset({"OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_ORG_ID", "OPENAI_PROJECT_ID"})
TOOL_ENV = {
    "claude-code": ANTHROPIC_ENV | {
        "CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CONFIG_DIR", "CLAUDE_CODE_MAX_OUTPUT_TOKENS",
    },
    # Codex can be supplied through --tool codex --command even though it isn't auto-detected.
    "codex": OPENAI_ENV | {"CODEX_API_KEY", "CODEX_HOME"},
    "opencode": ANTHROPIC_ENV | OPENAI_ENV | {
        "GOOGLE_API_KEY", "GEMINI_API_KEY", "GOOGLE_GENERATIVE_AI_API_KEY", "GOOGLE_GEMINI_BASE_URL",
        "OPENCODE_CONFIG", "OPENCODE_CONFIG_DIR", "OPENCODE_CONFIG_CONTENT", "OPENCODE_DISABLE_AUTOUPDATE",
    },
}


def tool_environment(tool: str, environ: Mapping[str, str]) -> dict[str, str]:
    """An allowlist, rather than host inheritance or broad credential-name prefixes."""
    allowed = EXECUTION_ENV | TOOL_ENV[tool]
    return {key: value for key, value in environ.items() if key.upper() in allowed}


def windows_launcher(
    path: Path, argv: list[str], environ: dict[str, str], *, tool: str, home: Path | None = None,
) -> list[str]:
    """A batch file that sets the tool's environment and starts it, for the Windows sandbox: the
    tool's key variables, and where its sign-in and state live (the person's profile, not the
    sandbox account's). Deleted by the runner when the turn ends."""
    home = home or Path.home()
    forwarded = TOOL_ENV[tool] | {"XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME"}
    values = {k: v for k, v in tool_environment(tool, environ).items() if k.upper() in forwarded}
    if tool == "claude-code":
        values.setdefault("CLAUDE_CONFIG_DIR", str(home / ".claude"))
    values.setdefault("XDG_CONFIG_HOME", str(home / ".config"))
    values.setdefault("XDG_DATA_HOME", str(home / ".local" / "share"))
    values.setdefault("XDG_CACHE_HOME", str(home / ".cache"))

    def quoted(text: str) -> str:
        return '"' + text.replace("%", "%%").replace('"', '""') + '"'

    lines = ["@echo off"]
    lines += [f'set "{k}={v.replace("%", "%%")}"' for k, v in sorted(values.items()) if "\n" not in v and '"' not in v]
    lines += [" ".join(quoted(a) for a in argv), "exit /b %errorlevel%"]
    path.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8", newline="")
    return ["cmd.exe", "/d", "/c", str(path)]


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
    system = platform.system()
    if system == "Linux":
        for binary, package in (("bwrap", "bubblewrap"), ("socat", "socat")):
            if shutil.which(binary) is None:
                missing.append(f"{package} (e.g. `sudo apt-get install {package}`)")
    elif system == "Windows" and srt is not None and (why := windows_setup_missing()):
        missing.append(why)
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
