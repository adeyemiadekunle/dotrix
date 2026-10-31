"""dotrix's one version, kept the same in every package, and its changelog.

    python scripts/release.py check          # every package on one version, with a CHANGELOG section (CI)
    python scripts/release.py version        # print it
    python scripts/release.py notes [X.Y.Z]  # that version's CHANGELOG section (the GitHub release's text)
    python scripts/release.py bump X.Y.Z     # set every package to X.Y.Z and turn Unreleased into its section

Releases are cut on `stage` (bump, then a PR into stage); merging stage into main tags vX.Y.Z and
publishes the GitHub release (.github/workflows/release.yml). Standard library only.
"""
from __future__ import annotations

import datetime
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHANGELOG = ROOT / "CHANGELOG.md"
PACKAGE_JSONS = ["apps/web", "apps/desktop", "apps/ops", "packages/ui", "packages/api-client"]
PYPROJECTS = ["apps/backend", "apps/cli", "packages/engine"]
API_VERSION = ROOT / "apps/backend/src/dotrix_backend/main.py"  # API_VERSION = "X.Y.Z" (OpenAPI's info.version)
SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")
PY_VERSION = re.compile(r'^(version\s*=\s*")([^"]+)(")', re.M)
API = re.compile(r'^(API_VERSION\s*=\s*")([^"]+)(")', re.M)
UNRELEASED = "## [Unreleased]"


def versions() -> dict[str, str]:
    """Where each version is written, and what it says."""
    found: dict[str, str] = {}
    for folder in PACKAGE_JSONS:
        found[f"{folder}/package.json"] = json.loads((ROOT / folder / "package.json").read_text())["version"]
    for folder in PYPROJECTS:
        match = PY_VERSION.search((ROOT / folder / "pyproject.toml").read_text())
        found[f"{folder}/pyproject.toml"] = match.group(2) if match else "(none)"
    match = API.search(API_VERSION.read_text())
    found[str(API_VERSION.relative_to(ROOT))] = match.group(2) if match else "(none)"
    return found


def current() -> str:
    found = set(versions().values())
    if len(found) != 1:
        sys.exit("Packages disagree on the version:\n" + "\n".join(f"  {p}: {v}" for p, v in versions().items()))
    return found.pop()


def notes(version: str) -> str:
    """The text of `## [version]` in the changelog, without its heading."""
    text = CHANGELOG.read_text()
    match = re.search(rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|^\[[^\]]+\]: |\Z)", text, re.M | re.S)
    if not match:
        sys.exit(f"CHANGELOG.md has no section for {version}")
    return match.group(1).strip() + "\n"


def check() -> None:
    version = current()
    notes(version)
    if UNRELEASED not in CHANGELOG.read_text():
        sys.exit(f"CHANGELOG.md needs an {UNRELEASED} section at the top for changes since {version}")
    print(f"dotrix {version}: every package agrees, and CHANGELOG.md has its section")


def bump(version: str) -> None:
    if not SEMVER.match(version):
        sys.exit(f"{version} isn't a version like 1.2.3")
    old = current()
    if version == old:
        sys.exit(f"Already at {version}")
    text = CHANGELOG.read_text()
    head, sep, rest = text.partition(UNRELEASED + "\n")
    if not sep:
        sys.exit(f"CHANGELOG.md has no {UNRELEASED} section")
    body, _, tail = rest.partition("\n## [")
    if not body.strip():
        sys.exit(f"Nothing under {UNRELEASED} in CHANGELOG.md: write what changed first")
    today = datetime.date.today().isoformat()
    tail = ("\n## [" + tail) if tail else ""
    text = f"{head}{UNRELEASED}\n\n## [{version}] - {today}\n\n{body.strip()}\n{tail}"
    # The links at the bottom: Unreleased compares from the new version; the new version's release page.
    text = re.sub(r"^\[Unreleased\]: (\S+)/compare/v[^.\s]+\.[^.\s]+\.\S+?\.\.\.(\S+)$",
                  rf"[Unreleased]: \g<1>/compare/v{version}...\g<2>\n[{version}]: \g<1>/releases/tag/v{version}",
                  text, count=1, flags=re.M)
    CHANGELOG.write_text(text)
    for folder in PACKAGE_JSONS:
        path = ROOT / folder / "package.json"
        path.write_text(re.sub(r'("version":\s*")[^"]+(")', rf"\g<1>{version}\g<2>", path.read_text(), count=1))
    for folder in PYPROJECTS:
        path = ROOT / folder / "pyproject.toml"
        path.write_text(PY_VERSION.sub(rf"\g<1>{version}\g<3>", path.read_text(), count=1))
    API_VERSION.write_text(API.sub(rf"\g<1>{version}\g<3>", API_VERSION.read_text(), count=1))
    # uv.lock records the workspace packages' versions; CI installs with --locked.
    try:
        subprocess.run(["uv", "lock"], cwd=ROOT, check=True)
    except (OSError, subprocess.CalledProcessError):
        print("Run `uv lock` before committing (uv.lock records the packages' versions)")
    print(f"{old} -> {version}. Next: `pnpm openapi` (the API's version is in openapi.json), then a PR into stage.")


def main(argv: list[str]) -> None:
    match argv:
        case ["check"]:
            check()
        case ["version"]:
            print(current())
        case ["notes"]:
            sys.stdout.write(notes(current()))
        case ["notes", version]:
            sys.stdout.write(notes(version.removeprefix("v")))
        case ["bump", version]:
            bump(version.removeprefix("v"))
        case _:
            sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
