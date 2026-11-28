"""Load Codex's own sign-in and provider settings, then replace only its tool policy.

MCP table overrides merge: setting mcp_servers={} does not remove existing servers.
List configuration without starting servers, disable those names, and attach the
desktop browser under a fresh id. No token is put on the command line.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
from pathlib import Path


def run(browser: Path | None = None, helpers: int | None = None) -> int:
    from .runner import Tool

    binary = shutil.which("codex")
    if binary is None:
        print(json.dumps({"type": "error", "message": "The local coding tool is not installed"}), flush=True)
        return 1
    try:
        version = subprocess.run([binary, "--version"], stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=15, check=True)
        match = re.search(r"(\d+)\.(\d+)\.(\d+)", version.stdout)
        if match is None or tuple(map(int, match.groups())) < (0, 169, 0):
            raise ValueError("This tool is too old for the local policy")
        listed = subprocess.run([binary, "-c", "features.hooks=false", "-c", "features.plugins=false",
                                 "mcp", "list", "--json"], stdin=subprocess.DEVNULL, capture_output=True,
                                text=True, timeout=30, check=True)
        servers = json.loads(listed.stdout)
        names = tuple(server["name"] for server in servers)
        if not all(isinstance(name, str) for name in names):
            raise ValueError("Invalid server configuration")
        argv = Tool.named("codex", browser=browser, native=True, disabled_mcp=names,
                          **({"helpers": helpers} if helpers else {})).argv
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        print(json.dumps({"type": "error", "message": "Could not load the local coding configuration; update the tool and try again"}), flush=True)
        return 1
    if os.name != "nt":
        os.execvpe(binary, [binary, *argv[1:]], dict(os.environ))
    # The native process remains in the runner's process group; stdin has not been consumed.
    try:
        return subprocess.call([binary, *argv[1:]])
    except KeyboardInterrupt:
        return 130


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--browser-config", type=Path)
    parser.add_argument("--helpers", type=int, help="Its subagents at once (the turn's share of the runner's)")
    args = parser.parse_args()
    raise SystemExit(run(args.browser_config, args.helpers))


if __name__ == "__main__":
    main()
