"""Build the dotrix CLI as a standalone program (no Python needed where it runs), for the desktop
app to bundle and start `dotrix runner` with: `python apps/cli/scripts/standalone.py` (`pnpm
--filter @dotrix/desktop bundle-cli`).

It installs the CLI with only its own dependencies (`uv export --package dotrix`, never the
backend's) into a scratch environment with PyInstaller, and writes a folder
(`apps/desktop/resources/dotrix/`, or `--out`) holding `dotrix` (`dotrix.exe` on Windows) and what
it loads. Built on each platform for that platform: PyInstaller doesn't cross-compile. The desktop
app finds it there (`apps/desktop/src/runner.ts`, `cliCommand`). With `--api-url`, that server is the
CLI's default (a release's), written into the build as `dotrix_cli/_build.py`; the source never has it.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[3]
# Packages whose files beside the code (rules, templates, prompts, tokenizer data) the CLI reads.
COLLECT = ["dotrix_engine", "dotrix_cli", "deepagents", "tiktoken_ext", "markitdown", "magika"]


PYINSTALLER = "pyinstaller==6.22.3"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=ROOT / "apps" / "desktop" / "resources" / "dotrix")
    parser.add_argument("--api-url", help="the server this build talks to by default, e.g. https://dotrix.example.com")
    args = parser.parse_args()
    if args.api_url:
        parts = urlsplit(args.api_url)
        if parts.scheme != "https" or not parts.netloc:
            sys.exit(f"--api-url must be an https:// address (got {args.api_url!r})")
    uv = shutil.which("uv")
    if uv is None:
        sys.exit("Building the CLI needs uv (https://docs.astral.sh/uv/)")

    with tempfile.TemporaryDirectory(prefix="dotrix-build-") as tmp:
        work = Path(tmp)
        venv = work / "venv"
        python = venv / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        requirements = work / "requirements.txt"
        subprocess.run([uv, "export", "--package", "dotrix", "--no-dev", "--no-hashes", "--no-emit-workspace",
                        "--frozen", "--output-file", str(requirements)], cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
        subprocess.run([uv, "venv", "--quiet", str(venv)], cwd=ROOT, check=True)
        cli = ROOT / "apps" / "cli"
        if args.api_url:  # a copy of the CLI with its default server, so the source stays as it is
            cli = work / "cli"
            shutil.copytree(ROOT / "apps" / "cli", cli, ignore=shutil.ignore_patterns("__pycache__", ".venv", "build"))
            origin = f"{urlsplit(args.api_url).scheme}://{urlsplit(args.api_url).netloc}"
            (cli / "src" / "dotrix_cli" / "_build.py").write_text(f'API_URL = "{origin}"\n')
        # --no-sources: the engine comes from the path given here (a copied CLI is outside the workspace).
        subprocess.run([uv, "pip", "install", "--quiet", "--no-sources", "--python", str(python), "-r", str(requirements),
                        PYINSTALLER, str(ROOT / "packages" / "engine"), str(cli)], cwd=ROOT, check=True)
        entry = work / "dotrix.py"
        entry.write_text("from dotrix_cli.cli import app\n\nif __name__ == '__main__':\n    app()\n")
        collect = [f"--collect-all={name}" for name in COLLECT]
        subprocess.run([str(python), "-m", "PyInstaller", str(entry), "--name", "dotrix", "--onedir", "--noconfirm",
                        "--clean", "--console", "--log-level", "WARN", "--distpath", str(work / "dist"),
                        "--workpath", str(work / "build"), "--specpath", tmp, *collect], cwd=tmp, check=True)
        if args.out.exists():
            shutil.rmtree(args.out)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(work / "dist" / "dotrix", args.out, symlinks=True)
    print(f"dotrix built into {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
