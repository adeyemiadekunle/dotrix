"""Build the dotrix CLI as a standalone program (no Python needed where it runs), for the desktop
app to bundle and start `dotrix runner` with: `python apps/cli/scripts/standalone.py` (`pnpm
--filter @dotrix/desktop bundle-cli`).

It installs the CLI with only its own dependencies (`uv export --package dotrix`, never the
backend's) into a scratch environment with PyInstaller, and writes a folder
(`apps/desktop/resources/dotrix/`, or `--out`) holding `dotrix` (`dotrix.exe` on Windows) and what
it loads. Built on each platform for that platform: PyInstaller doesn't cross-compile. The desktop
app finds it there (`apps/desktop/src/runner.ts`, `cliCommand`).
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
# Packages whose files beside the code (rules, templates, prompts, tokenizer data) the CLI reads.
COLLECT = ["dotrix_engine", "dotrix_cli", "deepagents", "tiktoken_ext", "markitdown", "magika"]


PYINSTALLER = "pyinstaller==6.22.3"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=ROOT / "apps" / "desktop" / "resources" / "dotrix")
    args = parser.parse_args()
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
        subprocess.run([uv, "pip", "install", "--quiet", "--python", str(python), "-r", str(requirements), PYINSTALLER,
                        str(ROOT / "packages" / "engine"), str(ROOT / "apps" / "cli")], cwd=ROOT, check=True)
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
