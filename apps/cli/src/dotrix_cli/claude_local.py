"""Native Claude shell in a Linux namespace with a host-owned Anthropic/browser relay.

The whole runtime is confined, including file tools, commands and descendants.
No saved hooks, grants, OAuth files or actual provider keys enter the namespace.
"""
from __future__ import annotations

import argparse
import asyncio
import functools
import json
import os
import shutil
import signal
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit


@functools.lru_cache(maxsize=1)
def available() -> bool:
    from .fx_native import available as namespaces_available

    return sys.platform == "linux" and namespaces_available()


def configured() -> bool:
    return available() and bool(os.environ.get("ANTHROPIC_API_KEY"))


def command(browser: bool = False) -> list[str]:
    # The namespace is the boundary. The temporary home has no saved grants,
    # providers, executable helpers, hooks, plugins, skills or MCP configuration.
    # Its subagents (`Agent`: Kai's workers, and its own general-purpose one) run in the same process and namespace,
    # each within `--tools` (checked on Claude Code 2.1.323).
    from dotrix_engine.coding_helpers import claude_agents, workers

    argv = ["-p", "--output-format", "stream-json", "--verbose", "--setting-sources", "",
            "--strict-mcp-config", "--disable-slash-commands", "--tools", "Read,Edit,Write,Glob,Grep,Bash,Agent",
            "--allowedTools", "Read,Edit,Write,Glob,Grep,Bash,Agent" + (",mcp__browser" if browser else ""),
            "--agents", claude_agents(workers()),
            "--permission-mode", "acceptEdits", "--settings", json.dumps({"disableAllHooks": True,
                "permissions": {"deny": ["WebFetch", "WebSearch", "Skill"]},
                "sandbox": {"enabled": False}})]
    if browser:
        argv += ["--mcp-config", json.dumps({"mcpServers": {"browser": {
            "type": "http", "url": "http://127.0.0.1:31820/browser"}}})]
    return argv


def connection(selected_model: str | None = None) -> tuple[str, str, str]:
    key = os.environ.get("ANTHROPIC_API_KEY")
    target = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com").rstrip('/').removesuffix('/v1')
    address = urlsplit(target)
    model = (selected_model.partition(":")[2] or selected_model) if selected_model else os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
    if (not key or not model or address.username or address.password or address.query or address.fragment
            or not address.hostname or (address.scheme != 'https' and not
                (address.scheme == 'http' and address.hostname in ('127.0.0.1', 'localhost')))):
        raise ValueError("Local commands require a custom API-key connection; use cloud coding for other sign-ins")
    return target, key, model


async def run(browser: Path | None = None, model: str | None = None) -> int:
    from .fx_native import launch

    def error(message):
        print(json.dumps({"type": "error", "message": message}), flush=True)

    binary = shutil.which("claude")
    if not binary or not available():
        error("Local command isolation is unavailable; install Linux Bubblewrap with working namespaces or use cloud coding")
        return 1
    try:
        upstream = connection(model)
        configured_browser = json.loads(browser.read_text())["mcpServers"]["browser"] if browser else None
    except (OSError, ValueError, KeyError, TypeError):
        error("Could not prepare the local model/browser connection; check your API-key setup or use cloud coding")
        return 1
    brief = sys.stdin.read()
    with tempfile.TemporaryDirectory(prefix="dotrix-claude-local-") as temporary:
        profile = Path(temporary)
        profile.chmod(0o700)
        (profile / '.claude').mkdir(mode=0o700)
        (profile / '.claude.json').write_text(json.dumps({'hasCompletedOnboarding': True, 'lastOnboardingVersion': '2.1.296'}))
        (profile / 'auth-source.json').write_text(json.dumps({'originals': {}}))
        (profile / 'command.json').write_text(json.dumps({'model': upstream[2], 'argv': command(browser is not None)}))
        cancelled = False
        previous = {}
        try:
            async with launch(profile, str(Path(binary).resolve()), Path.cwd().resolve(), configured_browser, anthropic=upstream) as (child, _, _):
                assert child.stdin and child.stdout
                def cancel(*args):
                    nonlocal cancelled
                    cancelled = True
                    if child.returncode is None:
                        child.send_signal(signal.SIGINT)
                previous = {sig: signal.signal(sig, cancel) for sig in (signal.SIGINT, signal.SIGTERM)}
                child.stdin.write(brief.encode())
                await child.stdin.drain()
                child.stdin.close()
                failed = False
                while line := await child.stdout.readline():
                    print(line.decode(), end="", flush=True)
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    if event.get("type") == "system" and (event.get("subtype") == "authentication_failed" or event.get("error") == "authentication_failed"):
                        failed = True
                        error("The model connection needs attention; check your local API key and try again")
                        child.terminate()
                        break
                try:
                    status = await asyncio.wait_for(child.wait(), timeout=3)
                except TimeoutError:
                    child.kill()
                    await child.wait()
                    status = 1
                return 1 if failed or cancelled else status
        except (OSError, ValueError, TimeoutError, RuntimeError):
            error("Could not start isolated local commands; use the tested coding runtime (2.1.296) and an API-key connection")
            return 1
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--browser-config", type=Path)
    parser.add_argument("--model")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(args.browser_config, args.model)))


if __name__ == "__main__":
    main()
