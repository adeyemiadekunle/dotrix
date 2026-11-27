"""The standalone CLI's entry point (apps/cli/scripts/standalone.py). A frozen build has no Python interpreter to run
fx_bridge.py with, so native Code's macOS and Windows launchers start the bridge as `dotrix _bridge <args>`
(fx_native.bridge_argv), and this hands those arguments to fx_bridge.main as its own. Everything else is the CLI.
"""
from __future__ import annotations

import json
import sys

BRIDGE_COMMAND = "_bridge"


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == BRIDGE_COMMAND:
        from . import fx_bridge

        if sys.argv[2:] == ["--version"]:  # the release smoke check: the bridge is reachable in this build
            print(json.dumps({"bridge": True, "fx": fx_bridge.KAI_FX_VERSION, "claude": fx_bridge.CLAUDE_CODE_VERSION}))
            return
        del sys.argv[1]  # fx_bridge reads its channel, profile, and binary from sys.argv[1:]
        fx_bridge.main()
        return
    from .cli import app

    app()
